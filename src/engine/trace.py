"""Forward tracing of a case from the reported account, using only events visible at as_of.

Exchange settlement accounts are hubs: the trace never walks through them by bank
transfers (that would connect unrelated customers). It crosses into the exchange only
through deposit links, and keeps the link status (verified / candidate / unresolved).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.contracts import Case
from src.store.state import EngineState


def trace_case(state: EngineState, case: Case, as_of: datetime, cfg: dict[str, Any]) -> dict[str, Any]:
    visible = [e for e in state.events.values() if e.available_at <= as_of]
    transfers = sorted([e for e in visible if e.event_type == "bank_transfer"], key=lambda e: e.occurred_at)
    signal = state.events[case.trigger_event_id]
    origin = case.origin_subject
    onward = timedelta(hours=cfg["onward_window_hours"])
    accounts: dict[str, dict[str, Any]] = {origin: {"hop": 0, "received": [], "role": "origin"}}
    customers: dict[str, dict[str, Any]] = {}
    path_events: list[str] = [signal.event_id]
    queue = [(origin, signal.occurred_at - timedelta(hours=cfg["lookback_hours"]), 0)]
    while queue:
        acct, since, hop = queue.pop(0)
        if hop >= cfg["max_hops"]:
            continue
        outs = [t for t in transfers if t.from_ref == acct and t.occurred_at >= since
                and (hop == 0 or t.occurred_at <= since + onward)]
        for t in outs:
            if t.event_id in path_events:
                continue
            path_events.append(t.event_id)
            if t.attributes.get("to_account_kind") == "exchange_settlement":
                for link in state.links.values():
                    if t.event_id in link.evidence_event_ids or t.event_id in link.candidates:
                        c = customers.setdefault(link.to_id, {"hop": hop + 1, "links": [], "via": []})
                        if link.link_id not in c["links"]:
                            c["links"].append(link.link_id)
                            c["via"].append(t.event_id)
                            path_events.extend(x for x in link.evidence_event_ids if x not in path_events)
                accounts.setdefault(t.to_ref, {"hop": hop + 1, "received": [], "role": "hub"})
                continue
            if t.to_ref == origin:
                continue
            node = accounts.setdefault(t.to_ref, {"hop": hop + 1, "received": [], "role": "receiver"})
            node["received"].append({"event_id": t.event_id, "amount_minor": t.amount_minor, "at": t.occurred_at})
            queue.append((t.to_ref, t.occurred_at, hop + 1))

    for acct, node in accounts.items():
        if node["role"] != "receiver":
            continue
        first = min(r["at"] for r in node["received"])
        outs = [t for t in transfers if t.from_ref == acct and first <= t.occurred_at <= first + onward]
        node["received_minor"] = sum(r["amount_minor"] for r in node["received"])
        node["onward_minor"] = sum(t.amount_minor or 0 for t in outs)
        node["onward_events"] = [t.event_id for t in outs]
        node["first_received_at"] = first
        node["minutes_to_first_onward"] = (
            (min(t.occurred_at for t in outs) - first).total_seconds() / 60 if outs else None)

    withdrawals: dict[str, dict[str, Any]] = {}
    for e in visible:
        if e.event_type == "withdrawal_request" and e.from_ref in customers:
            wid = f"wd:exchange:{e.attributes['withdrawal_id']}"
            withdrawals[wid] = {"event_id": e.event_id, "customer": e.from_ref, "destination": e.to_ref,
                                "asset": e.asset, "amount_minor": e.amount_minor,
                                "requested_at": e.occurred_at,
                                "controllable_until": datetime.fromisoformat(e.attributes["controllable_until"]),
                                "state": "pending"}
            path_events.append(e.event_id)
    for e in sorted(visible, key=lambda e: e.available_at):
        if e.event_type == "withdrawal_state":
            wid = f"wd:exchange:{e.attributes['withdrawal_id']}"
            if wid in withdrawals:
                withdrawals[wid]["state"] = e.attributes["state"]
                withdrawals[wid]["state_event"] = e.event_id

    # Destination history known before the request (no use of the withdrawal's own chain tx).
    for w in withdrawals.values():
        hist = []
        for e in visible:
            if (e.event_type == "chain_transfer" and e.from_ref == w["destination"]
                    and e.available_at <= w["requested_at"]):
                ent = state.entities.get(e.to_ref)
                labels = [l for l in (ent.attributes.get("labels", []) if ent else [])
                          if datetime.fromisoformat(l["known_at"]) <= w["requested_at"]]
                if labels:
                    hist.append({"event_id": e.event_id, "to": e.to_ref, "labels": labels,
                                 "amount_minor": e.amount_minor, "occurred_at": e.occurred_at})
        w["destination_history"] = hist

    scope_entities = [a for a in accounts] + list(customers) + list(withdrawals) + [
        w["destination"] for w in withdrawals.values()]
    return {"origin": origin, "signal": signal, "accounts": accounts, "customers": customers,
            "withdrawals": withdrawals, "scope_entities": scope_entities, "scope_events": path_events}
