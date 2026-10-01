"""Simulated institution systems: bank ledgers, restrictions, exchange ledger, withdrawals.

These play the role of the member institutions' own systems. A decision changes money
state only here, and only after an authorised simulated officer records it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from src.contracts import DecisionIn, Recommendation, Restriction
from src.store.state import BankAccount, Delivery, ExchangeCustomer, SimState, Withdrawal


class SimRejected(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def ledger(sim: SimState, account_id: str) -> dict[str, Any]:
    a = sim.accounts[account_id]
    active = [r for r in sim.restrictions.values() if r.account_id == account_id and r.status == "active"]
    restricted = min(a.balance_minor, sum(r.amount_minor for r in active))
    return {"account_id": account_id, "asset": a.asset, "total_minor": a.balance_minor,
            "restricted_minor": restricted, "available_minor": a.balance_minor - restricted,
            "state_version": a.version, "as_of": sim.clock.now.isoformat()}


def apply_event(sim: SimState, ev: dict[str, Any]) -> None:
    """Institution books its own event (before reporting it to the engine)."""
    t = ev["event_type"]
    if t == "bank_transfer":
        frm, to, amt = sim.accounts.get(ev["from_ref"]), sim.accounts.get(ev["to_ref"]), ev["amount_minor"]
        if frm is None or to is None:
            raise ValueError(f"scenario transfer between unknown accounts {ev['from_ref']} -> {ev['to_ref']}")
        if ledger(sim, frm.account_id)["available_minor"] < amt:
            raise ValueError(f"insufficient available balance in {frm.account_id}")
        frm.balance_minor -= amt
        to.balance_minor += amt
        frm.version += 1
        to.version += 1
    elif t == "exchange_deposit":
        c = sim.customers[ev["to_ref"]]
        c.balances["THB"] = c.balances.get("THB", 0) + ev["amount_minor"]
        c.version += 1
    elif t == "exchange_trade":
        a = ev["attributes"]
        c = sim.customers[ev["from_ref"]]
        if c.balances.get(a["sell_asset"], 0) < a["sell_minor"]:
            raise ValueError("trade exceeds balance")
        c.balances[a["sell_asset"]] -= a["sell_minor"]
        c.balances[a["buy_asset"]] = c.balances.get(a["buy_asset"], 0) + a["buy_net_minor"]
        c.version += 1
    elif t == "withdrawal_request":
        a = ev["attributes"]
        c = sim.customers[ev["from_ref"]]
        if c.balances.get(ev["asset"], 0) < ev["amount_minor"]:
            raise ValueError("withdrawal exceeds balance")
        wid = f"wd:exchange:{a['withdrawal_id']}"
        sim.withdrawals[wid] = Withdrawal(
            withdrawal_id=wid, customer_id=ev["from_ref"], asset=ev["asset"], amount_minor=ev["amount_minor"],
            destination=ev["to_ref"], chain=a["chain"], requested_at=datetime.fromisoformat(ev["occurred_at"]),
            controllable_until=datetime.fromisoformat(a["controllable_until"]))


def _broadcast(sim: SimState, w: Withdrawal, now: datetime) -> list[Delivery]:
    c = sim.customers[w.customer_id]
    c.balances[w.asset] -= w.amount_minor
    c.version += 1
    w.state = "broadcast"
    w.tx_hash = f"synthetic-tx-{w.withdrawal_id.split(':')[-1].lower()}"
    w.version += 1
    local = w.withdrawal_id.split(":")[-1]
    iso = now.isoformat()
    return [
        Delivery(due=now, client="exchange", event={
            "source_org": "exchange", "source_event_id": f"{local}-STATE-broadcast", "event_type": "withdrawal_state",
            "occurred_at": iso, "available_at": iso,
            "attributes": {"withdrawal_id": local, "state": "broadcast", "tx_hash": w.tx_hash}}),
        Delivery(due=now, client="chain", event={
            "source_org": "chain", "source_event_id": f"{w.tx_hash}", "event_type": "chain_transfer",
            "occurred_at": iso, "available_at": iso, "asset": w.asset, "amount_minor": w.amount_minor,
            "from_ref": "addr:tron:TSYNexchangehot000000000000000001", "to_ref": w.destination,
            "attributes": {"tx_hash": w.tx_hash, "chain": w.chain, "confirmed": True,
                           "withdrawal_id": local}}),
    ]


def auto_progress(sim: SimState, now: datetime) -> list[Delivery]:
    """Exchange broadcasts pending withdrawals once the control deadline passes."""
    out: list[Delivery] = []
    for w in sim.withdrawals.values():
        if w.state == "pending" and now >= w.controllable_until:
            out.extend(_broadcast(sim, w, w.controllable_until))
    return out


def apply_decision(sim: SimState, d: DecisionIn, rec: Recommendation, now: datetime,
                   case_id: str, decision_id: str) -> tuple[str, Optional[str], list[Delivery]]:
    """Returns (detail, restriction_id, follow-up deliveries). Raises SimRejected."""
    subject = rec.subject_id
    if d.action in ("acknowledge", "no_action"):
        return "acknowledged without state change", None, []

    if subject.startswith("wd:"):
        w = sim.withdrawals.get(subject)
        if w is None:
            raise SimRejected(404, "withdrawal unknown to the exchange system")
        if d.expected_state_version != w.version:
            raise SimRejected(409, f"stale state: withdrawal version is {w.version}")
        if d.action == "hold_withdrawal":
            if w.state != "pending" or now >= w.controllable_until:
                raise SimRejected(409, f"not controllable: withdrawal is {w.state}; deadline "
                                       f"{w.controllable_until.isoformat()}")
            w.state = "held_for_review"
            w.version += 1
            return "withdrawal held for review", None, []
        if d.action == "release_withdrawal":
            if w.state != "held_for_review":
                raise SimRejected(409, f"withdrawal is {w.state}, not held")
            return "withdrawal released and broadcast", None, _broadcast(sim, w, now)
        raise SimRejected(422, f"action {d.action} does not apply to a withdrawal")

    acct = sim.accounts.get(subject)
    if acct is None:
        raise SimRejected(404, "account unknown to the bank system")
    if acct.institution != d.actor_org:
        raise SimRejected(403, "account belongs to another institution")
    if d.expected_state_version != acct.version:
        raise SimRejected(409, f"stale state: account version is {acct.version}")

    if d.action == "restrict_amount":
        amount = int(d.target_scope.get("amount_minor", rec.target_scope.get("amount_minor", 0)))
        cap = rec.target_scope.get("amount_minor")
        if amount <= 0 or cap is None or amount > cap:
            raise SimRejected(422, "restriction must be > 0 and within the recommended traced amount")
        if amount > ledger(sim, acct.account_id)["available_minor"]:
            raise SimRejected(409, "amount exceeds available balance")
        rid = sim.next_id("RST")
        sim.restrictions[rid] = Restriction(
            restriction_id=rid, account_id=acct.account_id, institution=acct.institution, asset=acct.asset,
            amount_minor=amount, reason_category="incoming payment linked to a reported transfer is under review",
            decision_id=decision_id, case_id=case_id, created_at=now, updated_at=now,
            history=[{"at": now.isoformat(), "state": "restricted", "decision_id": decision_id}])
        acct.version += 1
        return f"restricted {amount / 100:,.2f} THB only", rid, []

    rid = d.target_scope.get("restriction_id") or rec.target_scope.get("restriction_id")
    r = sim.restrictions.get(rid or "")
    if r is None or r.account_id != acct.account_id:
        raise SimRejected(422, "restriction_id missing or not on this account")
    if r.status != "active":
        raise SimRejected(409, f"restriction already {r.status}")
    mapping = {"release_restriction": "released", "retain_restriction": "retained",
               "request_information": "more_info_requested"}
    if d.action not in mapping:
        raise SimRejected(422, f"action {d.action} does not apply to an account")
    r.review_state = mapping[d.action]
    if d.action == "release_restriction":
        r.status = "released"
    r.updated_at = now
    r.history.append({"at": now.isoformat(), "state": r.review_state, "decision_id": decision_id})
    acct.version += 1
    return f"restriction {rid} -> {r.review_state} (only this restriction)", rid, []


def receive_evidence(sim: SimState, restriction_id: str, now: datetime, submission_id: str) -> None:
    r = sim.restrictions[restriction_id]
    if r.status != "active":
        raise SimRejected(409, f"restriction already {r.status}")
    r.review_state = "review_pending"
    r.updated_at = now
    r.history.append({"at": now.isoformat(), "state": "review_pending", "submission_id": submission_id})
    sim.accounts[r.account_id].version += 1


def new_sim(scn: dict[str, Any], speed: float) -> SimState:
    from src.store.state import Clock
    sim = SimState(clock=Clock(start=scn["start"], now=scn["start"], end=scn["end"], speed=speed),
                   merchant_account_id=scn["merchant_account_id"])
    for a in scn["accounts"]:
        sim.accounts[a["account_id"]] = BankAccount(**a)
    for c in scn["customers"]:
        sim.customers[c["customer_id"]] = ExchangeCustomer(**c)
    sim.deliveries = [Delivery(due=datetime.fromisoformat(d["due"]), client=d["client"], event=d["event"])
                      for d in scn["deliveries"]]
    return sim
