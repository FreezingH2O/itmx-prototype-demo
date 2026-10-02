"""Role-scoped views. Each simulated client sees only what its role may see.

The `simulator` role is the presenter's privileged overview and is labelled as such.
"""
from __future__ import annotations

from typing import Any, Optional

from src.engine.graph import pick_case
from src.policy.evidence_check import list_fixtures
from src.sim.institutions import ledger
from src.store.state import RunState

FEED_LIMIT = 200   # most recent client-log rows per institution view


def is_institution(role: Optional[str]) -> bool:
    return bool(role) and (role == "exchange" or role.startswith("bank_"))


def institutions(run: RunState) -> list[str]:
    """Institutions in this run: the banks that hold simulated accounts, then the exchange."""
    return sorted({a.institution for a in run.sim.accounts.values()}) + ["exchange"]


def display_name(org: str) -> str:
    return "Exchange" if org == "exchange" else org.replace("_", " ").title()


def responsible(org: str) -> str:
    return f"{display_name(org)} review team (simulated)"


def _clean_rec(r) -> dict[str, Any]:
    d = r.model_dump(mode="json")
    d["target_scope"] = {k: v for k, v in d["target_scope"].items() if k != "_key"}
    return d


def _subject_state(run: RunState, subject: str) -> dict[str, Any]:
    sim = run.sim
    if subject in sim.accounts:
        return {"kind": "account", **ledger(sim, subject)}
    if subject in sim.withdrawals:
        w = sim.withdrawals[subject]
        return {"kind": "withdrawal", "state": w.state, "state_version": w.version,
                "controllable_until": w.controllable_until.isoformat(), "amount_minor": w.amount_minor,
                "asset": w.asset}
    if subject in sim.customers:
        c = sim.customers[subject]
        return {"kind": "customer", "balances": c.balances, "state_version": c.version}
    return {"kind": "unknown"}


EVIDENCE_LIMIT = 25   # per recommendation in large scenarios


def _rec_evidence(run: RunState, r, large: bool) -> list:
    ev = _assessment_evidence(run, r.assessment_id)
    if not large:
        return ev
    # A network case's pack covers every account; keep the items about this recommendation.
    refs = set(r.evidence_refs) | {r.subject_id}
    return [e for e in ev if refs.intersection(e.refs)][:EVIDENCE_LIMIT]


def institution_view(run: RunState, org: str, large: bool = False) -> dict[str, Any]:
    eng, sim = run.engine, run.sim
    recs = [r for r in eng.recommendations.values() if r.institution == org
            and not (large and r.status == "superseded")]
    rec_out = []
    for r in sorted(recs, key=lambda r: r.created_at):
        d = _clean_rec(r)
        d["subject_display"] = eng.entities[r.subject_id].display if r.subject_id in eng.entities else r.subject_id
        d["subject_state"] = _subject_state(run, r.subject_id)
        d["evidence"] = [e.model_dump(mode="json") for e in _rec_evidence(run, r, large)]
        d["decisions"] = [x.model_dump(mode="json") for x in eng.decisions.values()
                          if x.recommendation_id == r.recommendation_id]
        rec_out.append(d)
    own_accounts = [a for a in sim.accounts.values() if a.institution == org]
    restrictions = [r for r in sim.restrictions.values() if r.institution == org]
    review_queue = []
    for r in restrictions:
        subs = [s.model_dump(mode="json") for s in eng.evidence_submissions.values()
                if s.restriction_id == r.restriction_id]
        review_queue.append({**r.model_dump(mode="json"), "submissions": subs,
                             "ledger": ledger(sim, r.account_id)})
    return {
        "role": org, "as_of": sim.clock.now,
        "feed": [e.model_dump(mode="json") for e in sim.client_log if e.client == org][-FEED_LIMIT:],
        "recommendations": rec_out,
        "decisions": [d.model_dump(mode="json") for d in eng.decisions.values() if d.actor_org == org],
        "accounts": [{**a.model_dump(mode="json"), "ledger": ledger(sim, a.account_id)} for a in own_accounts],
        "withdrawals": [w.model_dump(mode="json") for w in sim.withdrawals.values()] if org == "exchange" else [],
        "customers": [c.model_dump(mode="json") for c in sim.customers.values()] if org == "exchange" else [],
        "review_queue": review_queue,
        "api_log": [x.model_dump(mode="json") for x in sim.api_log if x.client == org][-40:],
    }


def _assessment_evidence(run: RunState, assessment_id: str):
    a = run.engine.assessments.get(assessment_id)
    return (a.evidence + a.context_benign) if a else []


def merchant_view(run: RunState, account_id: str) -> dict[str, Any]:
    eng, sim = run.engine, run.sim
    acct = sim.accounts[account_id]
    restrictions = [r for r in sim.restrictions.values() if r.account_id == account_id]
    out = []
    for r in restrictions:
        dec = eng.decisions.get(r.decision_id)
        rec = eng.recommendations.get(dec.recommendation_id) if dec else None
        tx_id = (rec.target_scope.get("related_event_ids") or [None])[0] if rec else None
        tx = eng.events.get(tx_id) if tx_id else None
        subs = [s for s in eng.evidence_submissions.values() if s.restriction_id == r.restriction_id]
        out.append({
            "restriction_id": r.restriction_id, "case_id": r.case_id, "amount_minor": r.amount_minor,
            "asset": r.asset, "status": r.status, "review_state": r.review_state,
            "reason_category": r.reason_category, "responsible": responsible(r.institution),
            "history": r.history, "created_at": r.created_at, "updated_at": r.updated_at,
            "related_transaction": {"amount_minor": tx.amount_minor, "occurred_at": tx.occurred_at,
                                    "payer_hint": "•" + tx.from_ref.split("-")[-1],
                                    "payment_format": tx.attributes.get("payment_format")} if tx else None,
            "submissions": [{"submission_id": s.submission_id, "fixture_ref": s.fixture_ref,
                             "submitted_at": s.submitted_at, "review_state": s.review_state} for s in subs],
            "next_step": _next_step(r.review_state),
        })
    recent = [e for e in eng.events.values() if e.event_type == "bank_transfer" and e.to_ref == account_id
              and e.occurred_at >= sim.clock.start]
    return {
        "role": f"merchant:{account_id}", "as_of": sim.clock.now, "holder_name": acct.holder_name,
        "display": acct.display, "ledger": ledger(sim, account_id), "restrictions": out,
        "incoming": [{"event_id": e.event_id, "amount_minor": e.amount_minor, "occurred_at": e.occurred_at,
                      "payer_hint": "•" + e.from_ref.split("-")[-1],
                      "payment_format": e.attributes.get("payment_format")} for e in recent],
        "fixtures": list_fixtures(),
    }


def _next_step(state: str) -> str:
    return {
        "restricted": "Send sale evidence for this payment. Only this amount is on hold; the rest of your balance is usable.",
        "review_pending": "Your evidence was received. A bank reviewer will decide; sending a receipt does not release funds automatically.",
        "more_info_requested": "The reviewer needs more information. Check the evidence and send it again.",
        "retained": "The reviewer kept this hold. Contact the bank for the next steps of the formal process.",
        "released": "The hold on this amount was released by the bank reviewer.",
    }.get(state, "")


def engine_view(run: RunState, case_id: Optional[str] = None, large: bool = False) -> dict[str, Any]:
    """Selected case first (with its assessment); other open cases follow as summaries."""
    eng = run.engine
    sel = pick_case(eng, case_id, largest=large)
    cases = []
    for c in sorted(eng.cases.values(), key=lambda c: c is not sel):
        if c.status != "open" and c is not sel:
            continue
        a = eng.assessments.get(c.latest_assessment_id) if c is sel and c.latest_assessment_id else None
        cases.append({**c.model_dump(mode="json", exclude={"scope_events"} if c is not sel else None),
                      "assessment": a.model_dump(mode="json") if a else None,
                      "origin_displays": [eng.entities[o].display for o in c.origins() if o in eng.entities]})
    live = {k for k, e in eng.events.items() if e.occurred_at >= run.sim.clock.start}
    if large and sel:  # only what the graph can show: the case path and payments into reported accounts
        origins = set(sel.origins())
        live = set(sel.scope_events) | {k for k in live if eng.events[k].to_ref in origins}
    return {
        "role": "simulator (presenter overview, privileged)", "as_of": run.sim.clock.now,
        "model_info": run.model_info, "faults": run.faults, "cases": cases,
        "network": network_summary(run, sel),
        "recommendations": [_clean_rec(r) for r in sorted(eng.recommendations.values(), key=lambda r: r.created_at)
                            if not (large and r.status == "superseded")],
        "decisions": [d.model_dump(mode="json") for d in eng.decisions.values()],
        "links": [l.model_dump(mode="json") for l in eng.links.values()],
        "predictions": {k: v.model_dump(mode="json") for k, v in eng.predictions.items() if k in live},
        "evidence_submissions": [s.model_dump(mode="json") for s in eng.evidence_submissions.values()],
        "counts": {"events": len(eng.events), "entities": len(eng.entities), "links": len(eng.links),
                   "assessments": len(eng.assessments)},
    }


def network_summary(run: RunState, case) -> dict[str, Any]:
    """Counts for the presenter: how big the selected case is and how much officer work it creates."""
    eng, sim = run.engine, run.sim
    fam = case.family() if case else set()
    recs = [r for r in eng.recommendations.values() if r.case_id in fam and r.status != "superseded"]
    # Same rule as the Institutions page: undecided advice, excluding notes and unstoppable withdrawals.
    waiting = [r for r in recs if r.status == "delivered" and r.action_type != "EXISTING_CONTROLS_ONLY"
               and not (r.subject_id in sim.withdrawals and sim.withdrawals[r.subject_id].state == "broadcast")]
    scope = case.scope_entities if case else []
    held = [r for r in sim.restrictions.values() if r.case_id in fam and r.status == "active"]
    return {
        "open_cases": sum(1 for c in eng.cases.values() if c.status == "open"),
        "case_id": case.case_id if case else None,
        "reports": len(case.triggers()) if case else 0,
        "reported_accounts": len(case.origins()) if case else 0,
        "bank_accounts": sum(1 for x in scope if x.startswith("acct:") and x not in {
            a for a, v in sim.accounts.items() if v.holder_kind == "exchange_settlement"}),
        "exchange_customers": sum(1 for x in scope if x.startswith("xcust:")),
        "withdrawals": sum(1 for x in scope if x.startswith("wd:")),
        "institutions": sorted({x.split(":")[1] for x in scope if x.startswith("acct:")}),
        "recommendations": len(recs),
        "awaiting_officer": len(waiting),
        "held_minor": sum(r.amount_minor for r in held),
        "holds": len(held),
    }


def timeline(run: RunState) -> list[dict[str, Any]]:
    eng = run.engine
    items: list[dict[str, Any]] = []
    for e in eng.events.values():
        if e.occurred_at >= run.sim.clock.start:
            items.append({"at": e.available_at, "kind": "event", "ref": e.event_id,
                          "text": f"{e.source_org} sent {e.event_type}"})
    for l in eng.links.values():
        items.append({"at": l.known_at, "kind": "link", "ref": l.link_id, "text": f"{l.relation}: {l.status}"})
    for c in eng.cases.values():
        items.append({"at": c.opened_at, "kind": "case", "ref": c.case_id, "text": f"case opened from {c.trigger_event_id}"})
    for r in eng.recommendations.values():
        items.append({"at": r.created_at, "kind": "recommendation", "ref": r.recommendation_id,
                      "text": f"{r.action_type} -> {r.institution} ({r.status})"})
    for d in eng.decisions.values():
        items.append({"at": d.recorded_at, "kind": "decision", "ref": d.decision_id,
                      "text": f"{d.actor_org} {d.action}: {d.outcome} ({d.outcome_detail})"})
    for s in eng.evidence_submissions.values():
        items.append({"at": s.submitted_at, "kind": "evidence", "ref": s.submission_id,
                      "text": f"merchant evidence {s.fixture_ref}: review pending"})
    return sorted(items, key=lambda x: (x["at"], x["kind"]))
