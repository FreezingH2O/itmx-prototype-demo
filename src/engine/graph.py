"""Graph view of what the engine knows at as_of. Nodes appear only once available."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.store.state import EngineState

LANE_ORDER = ["bank_a", "bank_b", "exchange", "chain"]


def _lane(entity_id: str) -> str:
    kind, inst, _ = entity_id.split(":", 2)
    if kind == "addr":
        return "chain"
    if kind == "xcust":
        return "exchange"
    return inst


def _amount(asset: str | None, minor: int | None) -> str:
    if minor is None:
        return ""
    if asset == "USDT":
        return f"{minor / 1_000_000:,.2f} USDT"
    return f"{minor / 100:,.2f} THB"


def build_graph(state: EngineState, as_of: datetime, since: datetime) -> dict[str, Any]:
    case = next(iter(state.cases.values()), None)
    scope_events = set(case.scope_events) if case else set()
    scope_entities = set(case.scope_entities) if case else set()
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def add_node(eid: str) -> None:
        if eid:
            node_ids.add(eid)

    for e in sorted(state.events.values(), key=lambda e: e.available_at):
        if e.available_at > as_of:
            continue
        live = e.occurred_at >= since or e.event_id in scope_events
        if e.event_type == "bank_transfer" and live:
            p = state.predictions.get(e.event_id)
            edges.append({
                "id": e.event_id, "source": e.from_ref, "target": e.to_ref, "kind": "transfer",
                "status": "observed", "label": _amount(e.asset, e.amount_minor),
                "amount_minor": e.amount_minor, "asset": e.asset, "reference_id": e.reference_id,
                "occurred_at": e.occurred_at, "available_at": e.available_at,
                "payment_format": e.attributes.get("payment_format"),
                "score": p.score if p else None, "score_status": p.score_status if p else None,
                "model_id": p.model_id if p else None, "in_case": e.event_id in scope_events,
                "evidence_event_ids": [e.event_id], "method": f"reported by {e.source_org}"})
            add_node(e.from_ref)
            add_node(e.to_ref)
        elif e.event_type == "withdrawal_request" and live:
            state_ev = next((x for x in state.events.values() if x.event_type == "withdrawal_state"
                             and x.attributes.get("withdrawal_id") == e.attributes["withdrawal_id"]
                             and x.available_at <= as_of), None)
            edges.append({
                "id": e.event_id, "source": e.from_ref, "target": e.to_ref, "kind": "withdrawal",
                "status": "broadcast" if state_ev else "requested",
                "label": f"{e.attributes['withdrawal_id']} {_amount(e.asset, e.amount_minor)}",
                "amount_minor": e.amount_minor, "asset": e.asset, "occurred_at": e.occurred_at,
                "available_at": e.available_at, "in_case": e.event_id in scope_events,
                "evidence_event_ids": [e.event_id] + ([state_ev.event_id] if state_ev else []),
                "method": "requested destination (intended, not proof of ownership)",
                "controllable_until": e.attributes.get("controllable_until")})
            add_node(e.from_ref)
            add_node(e.to_ref)

    for link in state.links.values():
        if link.known_at > as_of:
            continue
        sources = [link.from_id] if link.from_id else [
            state.events[c].from_ref for c in link.candidates if c in state.events]
        for i, src in enumerate(sources or [""]):
            if not src:
                continue
            edges.append({
                "id": f"{link.link_id}#{i}", "source": src, "target": link.to_id, "kind": "deposit_link",
                "status": link.status, "label": link.status, "occurred_at": link.known_at,
                "available_at": link.known_at, "in_case": link.to_id in scope_entities,
                "evidence_event_ids": link.evidence_event_ids, "method": link.method, "note": link.note,
                "reference_id": next((state.events[x].reference_id for x in link.evidence_event_ids
                                      if x in state.events and state.events[x].reference_id), None)})
            add_node(src)
            add_node(link.to_id)

    dests = {e["target"] for e in edges if e["kind"] == "withdrawal"}
    for e in state.events.values():
        if e.event_type == "chain_transfer" and e.available_at <= as_of and (
                e.from_ref in dests or e.to_ref in dests):
            edges.append({
                "id": e.event_id, "source": e.from_ref, "target": e.to_ref, "kind": "chain",
                "status": "observed", "label": _amount(e.asset, e.amount_minor), "amount_minor": e.amount_minor,
                "asset": e.asset, "occurred_at": e.occurred_at, "available_at": e.available_at,
                "in_case": e.to_ref in scope_entities or e.from_ref in scope_entities,
                "evidence_event_ids": [e.event_id], "method": "confirmed chain transfer (simulated)"})
            add_node(e.from_ref)
            add_node(e.to_ref)

    nodes = []
    for nid in node_ids:
        ent = state.entities.get(nid)
        if ent is None:
            continue
        signals = [s for s in ent.attributes.get("signals", []) if datetime.fromisoformat(s["known_at"]) <= as_of]
        labels = [l for l in ent.attributes.get("labels", []) if datetime.fromisoformat(l["known_at"]) <= as_of]
        nodes.append({"id": nid, "label": ent.display, "kind": ent.entity_type, "lane": _lane(nid),
                      "hub": bool(ent.attributes.get("hub")), "signals": signals, "labels": labels,
                      "in_case": nid in scope_entities, "first_known_at": ent.first_known_at})
    return {"as_of": as_of, "case_id": case.case_id if case else None, "lanes": LANE_ORDER,
            "nodes": sorted(nodes, key=lambda n: (LANE_ORDER.index(n["lane"]), n["first_known_at"])),
            "edges": edges}
