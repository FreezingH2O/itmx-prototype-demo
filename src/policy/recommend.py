"""Policy: turn a traced case into scoped recommendations (demo-policy-v1).

Rules of this layer:
- Recommendations are advice to one institution about its own subject; never commands.
- Restriction scope is the traced amount only, never the whole account.
- The model score is evidence and may raise review priority; it never decides a
  merchant's restriction or release. Release review comes only from submitted evidence.
- Unverified links produce requests for information, not restriction recommendations.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from src.contracts import Case, EvidenceItem
from src.models.base import ModelAdapter
from src.store.state import EngineState


def _thb(minor: Optional[int]) -> str:
    return f"{(minor or 0) / 100:,.2f} THB"


def _usdt(minor: Optional[int]) -> str:
    return f"{(minor or 0) / 1_000_000:,.6f} USDT"


def _amount(asset: Optional[str], minor: Optional[int]) -> str:
    return _usdt(minor) if asset == "USDT" else _thb(minor)


def _quantile(values: list[int], q: float) -> Optional[int]:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def receiving_context(state: EngineState, account: str, before, cfg: dict[str, Any]) -> dict[str, Any]:
    ix = state.ix()
    hist = [e for e in ix.in_by.get(account, ())
            if e.available_at < before and before - timedelta(days=30) <= e.occurred_at < before]
    amounts = [e.amount_minor or 0 for e in hist]
    payers = {e.from_ref for e in hist}
    seen = [e.occurred_at for e in ix.touching(account) if e.available_at < before]
    return {
        "count_30d": len(hist), "unique_payers_30d": len(payers),
        "p10_minor": _quantile(amounts, 0.1), "typical_high_minor": _quantile(amounts, cfg["typical_quantile"]),
        "established": len(payers) >= cfg["min_unique_payers_30d"],
        "first_seen": min(seen) if seen else None,
    }


def _score_text(state: EngineState, event_id: str) -> Optional[str]:
    p = state.predictions.get(event_id)
    if not p or p.score_status != "computed":
        return None
    return f"Risk score {p.score:.2f} ({p.score_semantics})"


def _high_by_score(state: EngineState, event_ids: list[str], threshold: Optional[float]) -> bool:
    if threshold is None:
        return False
    return any((p := state.predictions.get(e)) and p.score is not None and p.score >= threshold for e in event_ids)


def build(state: EngineState, case: Case, tr: dict[str, Any], now, policy: dict[str, Any],
          model: Optional[ModelAdapter]) -> dict[str, Any]:
    evidence: list[EvidenceItem] = []
    context: list[EvidenceItem] = []
    missing: list[str] = []
    uncertainty: list[str] = []
    recs: list[dict[str, Any]] = []
    thr = policy.get("score_priority_threshold")
    for sig in tr["signals"]:
        evidence.append(EvidenceItem(
            kind="external_signal",
            text=f"{sig.attributes.get('category', 'signal')} on {state.entities[sig.to_ref].display} "
                 f"from {sig.attributes.get('source', 'unknown source')} (assertion, not adjudication)",
            refs=[sig.event_id], known_at=sig.available_at))
    for origin in tr["origins"]:
        recs.append({
            "institution": origin.split(":")[1], "subject_id": origin, "action_type": "EXISTING_CONTROLS_ONLY",
            "target_scope": {"account_id": origin}, "priority": None,
            "rationale": ["Reported account is handled under the institution's existing process.",
                          "Evidence pack attached for the downstream flow."],
            "evidence_refs": [s.event_id for s in tr["signals"] if s.to_ref == origin]})

    # ---- downstream bank accounts
    for acct, node in tr["accounts"].items():
        if node["role"] != "receiver":
            continue
        inst = acct.split(":")[1]
        disp = state.entities[acct].display
        received_ids = [r["event_id"] for r in node["received"]]
        for r in node["received"]:
            s = _score_text(state, r["event_id"])
            evidence.append(EvidenceItem(
                kind="traced_transfer",
                text=f"{state.entities[state.events[r['event_id']].from_ref].display} -> {disp}: "
                     f"{_thb(r['amount_minor'])}" + (f"; {s}" if s else ""),
                refs=[r["event_id"]], known_at=state.events[r["event_id"]].available_at))
        remaining = max(0, node["received_minor"] - node["onward_minor"])
        ctx = receiving_context(state, acct, node["first_received_at"], policy["merchant_context"])
        if remaining == 0:
            mins = node["minutes_to_first_onward"]
            recs.append({
                "institution": inst, "subject_id": acct, "action_type": "REVIEW_PRIORITY",
                "target_scope": {"account_id": acct},
                "priority": "high" if (mins is not None and mins <= 30) or _high_by_score(state, node["onward_events"], thr) else "standard",
                "rationale": [f"Received {_thb(node['received_minor'])} from the case path and sent "
                              f"{_thb(node['onward_minor'])} onward" + (f" within {mins:.0f} min." if mins is not None else "."),
                              "No traced amount remains in this account; review, not restriction."],
                "evidence_refs": received_ids + node["onward_events"]})
            continue
        rationale = [f"Received {_thb(node['received_minor'])} traced from the reported account; "
                     f"{_thb(remaining)} not sent onward.",
                     "Scope is the traced amount only, not the whole account."]
        if ctx["established"]:
            typical = ctx["typical_high_minor"]
            in_range = typical is not None and node["received_minor"] <= typical
            context.append(EvidenceItem(
                kind="receiving_pattern",
                text=f"{disp}: {ctx['count_30d']} incoming payments from {ctx['unique_payers_30d']} payers in 30 days"
                     + (f"; this amount is within its typical range (≤ {_thb(typical)})." if in_range else "."),
                refs=received_ids))
            rationale.append("Established receiving pattern is context for the reviewer, not a verdict.")
            if not any(s.account_id == acct and s.consistency.get("consistent")
                       for s in state.evidence_submissions.values()):
                missing.append(f"sale_evidence_for:{received_ids[0]}")
        else:
            uncertainty.append(f"{disp}: little receiving history; missing history is uncertainty, not risk.")
        recs.append({
            "institution": inst, "subject_id": acct, "action_type": "RECOMMEND_RESTRICTION_REVIEW",
            "target_scope": {"account_id": acct, "asset": "THB", "amount_minor": remaining,
                             "related_event_ids": received_ids},
            "priority": "high" if _high_by_score(state, received_ids, thr) else "standard",
            "rationale": rationale + (["Ask the account holder for sale evidence."] if ctx["established"] else []),
            "evidence_refs": received_ids})

    # ---- exchange customers reached through deposit links
    for cust, c in tr["customers"].items():
        links = [state.links[l] for l in c["links"]]
        verified = [l for l in links if l.status == "verified"]
        for l in links:
            evidence.append(EvidenceItem(
                kind=f"link_{l.status}",
                text=f"{l.relation} ({l.status}) to {state.entities[cust].display}: {l.method}"
                     + (f"; {l.note}" if l.note else ""),
                refs=l.evidence_event_ids, known_at=l.known_at))
        cust_withdrawals = {k: w for k, w in tr["withdrawals"].items() if w["customer"] == cust}
        if not verified:
            for l in links:
                missing.append(f"verified_deposit_reference:{l.evidence_event_ids[-1]}")
            uncertainty.append(f"{state.entities[cust].display}: deposit link not verified; no restriction recommended.")
            recs.append({
                "institution": "exchange", "subject_id": cust, "action_type": "REQUEST_INFORMATION",
                "target_scope": {"customer_id": cust, "requested": "bank reference for deposit credit"},
                "priority": "standard",
                "rationale": ["Deposit could not be tied to a case transfer by reference.",
                              "Equal amounts and timing are leads only."],
                "evidence_refs": [e for l in links for e in l.evidence_event_ids]})
            continue
        if not cust_withdrawals:
            recs.append({
                "institution": "exchange", "subject_id": cust, "action_type": "REVIEW_PRIORITY",
                "target_scope": {"customer_id": cust}, "priority": "standard",
                "rationale": ["Verified deposit from the case path; no withdrawal request seen yet."],
                "evidence_refs": [e for l in verified for e in l.evidence_event_ids]})
        for wid, w in cust_withdrawals.items():
            for h in w["destination_history"]:
                for lab in h["labels"]:
                    evidence.append(EvidenceItem(
                        kind="destination_history",
                        text=f"Requested destination sent {_usdt(h['amount_minor'])} to an address labelled "
                             f"'{lab.get('category')}' by {lab.get('source')} (label known before request)",
                        refs=[h["event_id"], lab.get("event_id", "")], known_at=h["occurred_at"]))
            refs = [w["event_id"]] + [e for l in verified for e in l.evidence_event_ids]
            if w["state"] == "broadcast":
                recs.append({
                    "institution": "exchange", "subject_id": wid, "action_type": "REVIEW_PRIORITY",
                    "target_scope": {"withdrawal_id": wid}, "priority": "high",
                    "rationale": ["Withdrawal already broadcast; it cannot be stopped by this recommendation.",
                                  "Use for investigation and referral only."],
                    "evidence_refs": refs})
            elif now < w["controllable_until"]:
                recs.append({
                    "institution": "exchange", "subject_id": wid, "action_type": "RECOMMEND_RESTRICTION_REVIEW",
                    "target_scope": {"withdrawal_id": wid, "asset": w["asset"], "amount_minor": w["amount_minor"]},
                    "priority": "high" if w["destination_history"] else "standard",
                    "rationale": [f"Withdrawal of {_amount(w['asset'], w['amount_minor'])} by a customer whose deposit "
                                  "is verified-linked to the case path.",
                                  "Review before the control deadline; scope is this request only."],
                    "evidence_refs": refs, "expires_at": w["controllable_until"]})
            else:
                uncertainty.append(f"{wid}: past the simulated control deadline; state not yet confirmed.")

    # ---- restrictions with submitted evidence -> release review or more information
    family = case.family()
    for d in state.decisions.values():
        if d.case_id not in family or d.action != "restrict_amount" or d.outcome != "acknowledged":
            continue
        rid = d.restriction_id
        reviews = [x for x in state.decisions.values()
                   if x.target_scope.get("restriction_id") == rid and x.outcome == "acknowledged"
                   and x.action in ("release_restriction", "retain_restriction", "request_information")]
        if any(x.action in ("release_restriction", "retain_restriction") for x in reviews):
            continue
        last_review = max((x.recorded_at for x in reviews), default=None)
        subs = [s for s in state.evidence_submissions.values()
                if s.restriction_id == rid and (last_review is None or s.submitted_at > last_review)]
        if not subs:
            continue
        s = max(subs, key=lambda s: s.submitted_at)
        inst = d.actor_org
        if s.consistency.get("consistent"):
            recs.append({
                "institution": inst, "subject_id": d.target_scope["account_id"],
                "action_type": "RECOMMEND_RELEASE_REVIEW",
                "target_scope": {"restriction_id": rid, "account_id": d.target_scope["account_id"],
                                 "submission_id": s.submission_id},
                "priority": "standard",
                "rationale": ["Submitted sale evidence is consistent with the restricted transaction "
                              "(amount, time, payer).",
                              "Consistency is not proof; the reviewer decides."],
                "evidence_refs": [s.submission_id]})
            context.append(EvidenceItem(kind="evidence_consistency",
                                        text="Merchant evidence consistent: " + "; ".join(s.consistency.get("matched", [])),
                                        refs=[s.submission_id], known_at=s.submitted_at))
        else:
            recs.append({
                "institution": inst, "subject_id": d.target_scope["account_id"],
                "action_type": "REQUEST_INFORMATION",
                "target_scope": {"restriction_id": rid, "account_id": d.target_scope["account_id"],
                                 "submission_id": s.submission_id},
                "priority": "standard",
                "rationale": ["Submitted evidence does not match the transaction: "
                              + "; ".join(s.consistency.get("issues", [])),
                              "Keep the restriction under review; ask for clarification."],
                "evidence_refs": [s.submission_id]})
            missing.append(f"consistent_evidence_for:{rid}")

    if model is None:
        uncertainty.append("Model unavailable: scores missing; recommendations rely on links and rules.")
    return {"evidence": evidence, "context_benign": context, "missing_inputs": sorted(set(missing)),
            "uncertainty": uncertainty, "recommendations": recs}
