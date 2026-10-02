"""Graph view of what the engine knows at as_of. Nodes appear only once available."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from src.contracts import Case
from src.engine.trace import trace_case
from src.store.state import EngineState


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


def pick_case(state: EngineState, case_id: Optional[str] = None, largest: bool = False) -> Optional[Case]:
    open_cases = [c for c in state.cases.values() if c.status == "open"]
    if case_id and case_id in state.cases:
        return state.cases[case_id]
    if largest and open_cases:
        return max(open_cases, key=lambda c: (len(c.origins()), len(c.scope_entities)))
    return open_cases[0] if open_cases else next(iter(state.cases.values()), None)


def _focus_trace(state: EngineState, case: Case, focus: str, as_of: datetime, cfg: dict[str, Any]) -> dict[str, Any]:
    """Trace from one reported account of a network case (display only; not stored)."""
    trig = [t for t in case.triggers() if state.events[t].to_ref == focus] or [case.trigger_event_id]
    one = Case(case_id=case.case_id, opened_at=case.opened_at, trigger_event_id=trig[0], origin_subject=focus,
               origin_subjects=[focus], trigger_event_ids=trig)
    return trace_case(state, one, as_of, cfg)


def build_graph(state: EngineState, as_of: datetime, since: datetime, case_id: Optional[str] = None) -> dict[str, Any]:
    """Small scenarios: every live transfer plus the case path. Large runs use build_network_graph."""
    case = pick_case(state, case_id)
    scope_events = set(case.scope_events) if case else set()
    scope_entities = set(case.scope_entities) if case else set()

    def shown(e) -> bool:
        return e.occurred_at >= since or e.event_id in scope_events

    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def add_node(eid: str) -> None:
        if eid:
            node_ids.add(eid)

    for e in sorted(state.events.values(), key=lambda e: e.available_at):
        if e.available_at > as_of:
            continue
        live = shown(e)
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
                "evidence_event_ids": [e.event_id], "method": f"reported by {e.source_org}", "count": 1})
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

    lane_order = sorted({_lane(n) for n in node_ids if _lane(n) not in ("exchange", "chain")}) + ["exchange", "chain"]
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
    return {"as_of": as_of, "case_id": case.case_id if case else None, "lanes": lane_order,
            "nodes": sorted(nodes, key=lambda n: (lane_order.index(n["lane"]), n["first_known_at"])),
            "edges": edges}


# ---------------------------------------------------------------- large runs

# Columns of the network graph, left to right. Bank receivers are split by hop and by behaviour.
STAGES = ["source", "reported", "hop1", "hop2", "hop3", "settlement", "customer", "withdrawal", "chain"]
PASS_THROUGH = 0.8   # sent on at least this share of what it received


def _wd_status(state: EngineState) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in sorted(state.decisions.values(), key=lambda d: d.recorded_at):
        rec = state.recommendations.get(d.recommendation_id)
        if rec and rec.subject_id.startswith("wd:") and d.outcome == "acknowledged":
            if d.action == "hold_withdrawal":
                out[rec.subject_id] = "held"
            elif d.action == "release_withdrawal":
                out[rec.subject_id] = "released"
    return out


def build_network_graph(state: EngineState, as_of: datetime, since: datetime, trace_cfg: dict[str, Any],
                        case_id: Optional[str] = None, focus: Optional[str] = None) -> dict[str, Any]:
    """Large runs: the whole network case (or the flow from one reported account, `focus`), with each node
    tagged by stage and behaviour so the UI can group it. Never draws transfers outside a case."""
    case = pick_case(state, case_id, largest=True)
    if case is None:
        seen = [e for sent in state.ix().out_by.values() for e in sent
                if since <= e.occurred_at and e.available_at <= as_of]
        return {"as_of": as_of, "case_id": None, "mode": "waiting", "nodes": [], "edges": [], "stages": STAGES,
                "waiting": {"transfers": len(seen),
                            "scored": sum(1 for e in seen if e.event_id in state.predictions)}}
    origins = case.origins()
    focus = focus if focus in origins else None
    tr = _focus_trace(state, case, focus, as_of, trace_cfg) if focus else trace_case(state, case, as_of, trace_cfg)
    ix = state.ix()
    nodes: dict[str, dict[str, Any]] = {}

    def node(ref: str, **kw: Any) -> None:
        if ref in nodes:
            nodes[ref].update({k: v for k, v in kw.items() if k != "stage"})
            return
        ent = state.entities.get(ref)
        nodes[ref] = {
            "id": ref, "label": ent.display if ent else ref, "kind": ent.entity_type if ent else "unknown",
            "institution": ent.institution if ent else None, "hub": bool(ent and ent.attributes.get("hub")),
            "first_known_at": ent.first_known_at if ent else as_of, "in_case": True,
            "signals": [x for x in (ent.attributes.get("signals", []) if ent else [])
                        if datetime.fromisoformat(x["known_at"]) <= as_of],
            "labels": [x for x in (ent.attributes.get("labels", []) if ent else [])
                       if datetime.fromisoformat(x["known_at"]) <= as_of],
            "behaviour": None, "hop": None, "received_minor": None, "onward_minor": None, "remaining_minor": None,
            **kw}

    for acct, n in tr["accounts"].items():
        if n["role"] == "hub":
            continue   # drawn only if some deposit into it is not linked to a customer
        if n["role"] == "origin":
            node(acct, stage="reported", hop=0, behaviour="reported")
            continue
        rec, on = n.get("received_minor", 0), n.get("onward_minor", 0)
        node(acct, stage=f"hop{min(n['hop'], 3)}", hop=n["hop"], received_minor=rec, onward_minor=on,
             remaining_minor=max(0, rec - on),
             behaviour="pass_through" if rec and on >= PASS_THROUGH * rec else "holding")
    for cust in tr["customers"]:
        node(cust, stage="customer")

    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def edge(kind: str, src: str, dst: str, e, **kw: Any) -> None:
        key = (kind, src, dst)
        p = state.predictions.get(e.event_id) if kind in ("transfer", "deposit") else None
        f = edges.get(key)
        if f is None:
            edges[key] = {"id": e.event_id, "source": src, "target": dst, "kind": kind, "status": "observed",
                          "amount_minor": e.amount_minor or 0, "asset": e.asset, "count": 1,
                          "occurred_at": e.occurred_at, "last_at": e.occurred_at, "available_at": e.available_at,
                          "evidence_event_ids": [e.event_id], "reference_id": e.reference_id,
                          "score": p.score if p else None, "score_status": p.score_status if p else None,
                          "model_id": p.model_id if p else None, "method": f"reported by {e.source_org}", **kw}
            return
        f["count"] += 1
        f["amount_minor"] += e.amount_minor or 0
        f["last_at"] = max(f["last_at"], e.occurred_at)
        f["evidence_event_ids"].append(e.event_id)
        if p and p.score is not None and (f["score"] is None or p.score > f["score"]):
            f["score"], f["score_status"], f["model_id"] = p.score, p.score_status, p.model_id

    link_of: dict[str, Any] = {}
    for link in state.links.values():
        if link.known_at <= as_of:
            for x in link.evidence_event_ids + link.candidates:
                link_of.setdefault(x, link)
    shown = list(tr["scope_events"])
    for o in tr["origins"]:   # payments into reported accounts (victims and other sources)
        shown += [e.event_id for e in ix.in_by.get(o, ()) if e.occurred_at >= since and e.available_at <= as_of]
    for eid in dict.fromkeys(shown):
        e = state.events.get(eid)
        if e is None or e.event_type != "bank_transfer" or e.available_at > as_of:
            continue
        if e.from_ref not in nodes:
            node(e.from_ref, stage="source")
        if e.attributes.get("to_account_kind") == "exchange_settlement":
            link = link_of.get(e.event_id)
            if link and link.to_id:
                node(link.to_id, stage="customer")
                edge("deposit", e.from_ref, link.to_id, e, status=link.status, method=link.method)
            else:
                node(e.to_ref, stage="settlement", hub=True)
                edge("transfer", e.from_ref, e.to_ref, e, status="unresolved", method="no verified deposit link")
            continue
        if e.to_ref not in nodes:
            node(e.to_ref, stage="hop3")
        edge("transfer", e.from_ref, e.to_ref, e)

    held = _wd_status(state)
    for wid, w in tr["withdrawals"].items():
        ev = state.events[w["event_id"]]
        status = "broadcast" if w["state"] == "broadcast" else held.get(wid, "requested")
        node(wid, stage="withdrawal", kind="withdrawal", label=f"Withdrawal {wid.split(':')[-1]}",
             first_known_at=ev.available_at, status=status, amount_minor=w["amount_minor"],
             controllable_until=w["controllable_until"])
        node(w["destination"], stage="chain")
        edge("withdrawal", w["customer"], wid, ev, status=status, controllable_until=w["controllable_until"],
             method="withdrawal request")
        edge("broadcast", wid, w["destination"], ev, status=status,
             method="requested destination (intended, not proof of ownership)")
        for h in w["destination_history"]:
            node(h["to"], stage="chain")
            edge("chain", w["destination"], h["to"], state.events[h["event_id"]],
                 method="earlier chain transfer from the destination (known before the request)")

    reports: dict[str, int] = {}
    for t in case.triggers():
        reports[state.events[t].to_ref] = reports.get(state.events[t].to_ref, 0) + 1
    for o, n in reports.items():
        if o in nodes:
            nodes[o]["reports"] = n
    return {"as_of": as_of, "case_id": case.case_id, "mode": "focus" if focus else "network", "stages": STAGES,
            "focus": focus, "nodes": sorted(nodes.values(), key=lambda n: (STAGES.index(n["stage"]), n["first_known_at"])),
            "edges": list(edges.values()),
            "focus_options": [{"id": o, "label": state.entities[o].display, "reports": reports.get(o, 0)}
                              for o in origins if o in state.entities]}
