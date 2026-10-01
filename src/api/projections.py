"""Role-scoped views. Each simulated client sees only what its role may see.

The `simulator` role is the presenter's privileged overview and is labelled as such.
"""
from __future__ import annotations

from typing import Any

from src.policy.evidence_check import list_fixtures
from src.sim.institutions import ledger
from src.store.state import RunState

INSTITUTIONS = ("bank_a", "bank_b", "exchange")
RESPONSIBLE = {"bank_a": "Bank A review team (simulated)", "bank_b": "Bank B review team (simulated)"}


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


def institution_view(run: RunState, org: str) -> dict[str, Any]:
    eng, sim = run.engine, run.sim
    recs = [r for r in eng.recommendations.values() if r.institution == org]
    rec_out = []
    for r in sorted(recs, key=lambda r: r.created_at):
        d = _clean_rec(r)
        d["subject_display"] = eng.entities[r.subject_id].display if r.subject_id in eng.entities else r.subject_id
        d["subject_state"] = _subject_state(run, r.subject_id)
        d["evidence"] = [e.model_dump(mode="json") for e in _assessment_evidence(run, r.assessment_id)]
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
        "feed": [e.model_dump(mode="json") for e in sim.client_log if e.client == org],
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
            "reason_category": r.reason_category, "responsible": RESPONSIBLE.get(r.institution, r.institution),
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


def engine_view(run: RunState) -> dict[str, Any]:
    eng = run.engine
    cases = []
    for c in eng.cases.values():
        a = eng.assessments.get(c.latest_assessment_id) if c.latest_assessment_id else None
        cases.append({**c.model_dump(mode="json"), "assessment": a.model_dump(mode="json") if a else None})
    return {
        "role": "simulator (presenter overview, privileged)", "as_of": run.sim.clock.now,
        "model_info": run.model_info, "faults": run.faults, "cases": cases,
        "recommendations": [_clean_rec(r) for r in sorted(eng.recommendations.values(), key=lambda r: r.created_at)],
        "decisions": [d.model_dump(mode="json") for d in eng.decisions.values()],
        "links": [l.model_dump(mode="json") for l in eng.links.values()],
        "predictions": {k: v.model_dump(mode="json") for k, v in eng.predictions.items()
                        if eng.events[k].occurred_at >= run.sim.clock.start},
        "evidence_submissions": [s.model_dump(mode="json") for s in eng.evidence_submissions.values()],
        "counts": {"events": len(eng.events), "entities": len(eng.entities), "links": len(eng.links),
                   "assessments": len(eng.assessments)},
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
