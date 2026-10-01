"""Authored synthetic scenarios. All names, accounts and addresses are fictional.

merchant_300      : base storyboard (E1-E8). Value conserves:
                    50,000 -> 16,000 + 16,000 + 300 + 17,700 remaining.
missing_reference : both exchange deposits arrive without a bank reference (equal amounts),
                    so links stay unverified (candidate or unresolved) and no restriction is recommended.
late_broadcast    : the withdrawal is broadcast before the report arrives.

Ground truth roles live in TRUTH and are for evaluators only; the engine never imports it.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

TZ = timezone(timedelta(hours=7))
DAY0 = datetime(2026, 10, 1, 9, 55, tzinfo=TZ)

VICTIM = "acct:bank_a:A-0042"
M1 = "acct:bank_a:A-1001"
M2 = "acct:bank_b:B-2001"
M3 = "acct:bank_b:B-2002"
MERCHANT = "acct:bank_b:B-3001"
SETTLEMENT = "acct:bank_b:B-9000"
X1 = "xcust:exchange:X-501"
X2 = "xcust:exchange:X-502"
DEST = "addr:tron:TSYNdest0000000000000000000000001"
FLAGGED = "addr:tron:TSYNflag0000000000000000000000009"
OTHER = "addr:tron:TSYNsrc00000000000000000000000005"

TRUTH = {  # evaluator-only
    VICTIM: "victim", M1: "mule", M2: "mule", M3: "mule", MERCHANT: "benign_merchant",
    X1: "mule_exchange_customer", X2: "mule_exchange_customer",
}

SCENARIOS = {
    "merchant_300": "Merchant receives 300 THB from a reported account; the rest moves to an exchange.",
    "missing_reference": "Same flow, but exchange deposits carry no bank reference (links not verified).",
    "late_broadcast": "Same flow, but the withdrawal is broadcast before the report arrives.",
}

RATE_THB_PER_USDT = "35.20"


def T(minutes: float = 0, seconds: float = 0, days: float = 0) -> datetime:
    return DAY0 + timedelta(minutes=minutes, seconds=seconds, days=days)


def _ev(source_org: str, sid: str, etype: str, occurred: datetime, delay_s: float = 3, **kw: Any) -> dict:
    return {"source_org": source_org, "source_event_id": sid, "event_type": etype,
            "occurred_at": occurred.isoformat(), "available_at": (occurred + timedelta(seconds=delay_s)).isoformat(),
            **kw}


def _transfer(org: str, sid: str, at: datetime, frm: str, to: str, thb_minor: int, fmt: str = "transfer",
              ref: str | None = None, to_kind: str | None = None, delay_s: float = 3) -> dict:
    attrs = {"payment_format": fmt}
    if to_kind:
        attrs["to_account_kind"] = to_kind
    return _ev(org, sid, "bank_transfer", at, delay_s, asset="THB", amount_minor=thb_minor,
               from_ref=frm, to_ref=to, reference_id=ref, attributes=attrs)


def _usdt_for(thb_minor: int) -> tuple[int, int, int]:
    gross = (thb_minor * 1_000_000) // 3520  # THB minor / (35.20 * 100) * 1e6
    fee = gross // 1000                       # 0.10% fee in USDT
    return gross, fee, gross - fee


def history() -> list[dict]:
    """Permitted history available before the run starts (context only)."""
    rng = random.Random(17)
    out: list[dict] = []
    payers = [f"acct:bank_a:A-5{n:03d}" for n in range(16)] + [f"acct:bank_b:B-5{n:03d}" for n in range(12)]
    for i in range(45):
        at = T(days=-30 + i * 0.66, minutes=rng.randint(0, 600))
        amt = rng.choice([60, 80, 120, 150, 180, 200, 240, 250, 300, 350, 420, 480, 550, 650]) * 100
        payer = payers[rng.randrange(len(payers))]
        org = payer.split(":")[1]
        out.append(_transfer(org, f"H-SALE-{i:03d}", at, payer, MERCHANT, amt, "qr"))
    out.append(_transfer("bank_a", "H-M1-001", T(days=-3), "acct:bank_a:A-7001", M1, 10000))
    out.append(_transfer("bank_a", "H-M1-002", T(days=-2), "acct:bank_a:A-7001", M1, 5000))
    out.append(_transfer("bank_b", "H-M2-001", T(days=-4), "acct:bank_b:B-7002", M2, 5000))
    out.append(_transfer("bank_b", "H-M3-001", T(days=-4, minutes=30), "acct:bank_b:B-7002", M3, 5000))
    out.append(_transfer("bank_a", "H-V-001", T(days=-5), "acct:bank_a:A-7100", VICTIM, 4500000))
    out.append(_ev("chain", "H-LBL-001", "address_label", T(days=-10), 60, to_ref=FLAGGED,
                   attributes={"category": "scam_linked", "source": "simulated_chain_label_feed"}))
    out.append(_ev("chain", "H-TX-001", "chain_transfer", T(days=-7), 30, asset="USDT", amount_minor=2_000_000_000,
                   from_ref=OTHER, to_ref=DEST, attributes={"tx_hash": "synthetic-tx-h001", "chain": "tron",
                                                            "confirmed": True}))
    out.append(_ev("chain", "H-TX-002", "chain_transfer", T(days=-6), 30, asset="USDT", amount_minor=1_200_000_000,
                   from_ref=DEST, to_ref=FLAGGED, attributes={"tx_hash": "synthetic-tx-h002", "chain": "tron",
                                                              "confirmed": True}))
    return out


def build(name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; options {sorted(SCENARIOS)}")
    with_refs = name != "missing_reference"
    late = name == "late_broadcast"
    g1, f1, n1 = _usdt_for(1600000)
    g2, f2, n2 = _usdt_for(1600000)
    wd_amount = 454_000_000
    wd_at = T(minutes=21) if late else T(minutes=27)
    controllable = wd_at + (timedelta(minutes=2) if late else timedelta(minutes=18))

    live = [
        ("bank_a", _transfer("bank_a", "E1-TX-0001", T(minutes=5), VICTIM, M1, 5000000)),
        ("bank_a", _transfer("bank_a", "E2-TX-0002", T(minutes=9), M1, M2, 1600000, ref="ITMX-0002")),
        ("bank_a", _transfer("bank_a", "E2-TX-0003", T(minutes=9, seconds=40), M1, M3, 1600000, ref="ITMX-0003")),
        ("bank_a", _transfer("bank_a", "E2-TX-0004", T(minutes=11, seconds=10), M1, MERCHANT, 30000, "qr",
                             ref="ITMX-0004")),
        ("bank_b", _transfer("bank_b", "E3-TX-0005", T(minutes=17), M2, SETTLEMENT, 1600000,
                             ref="DEP-77120" if with_refs else None, to_kind="exchange_settlement")),
        ("exchange", _ev("exchange", "E3-DEP-501", "exchange_deposit", T(minutes=17, seconds=30), 15,
                         asset="THB", amount_minor=1600000, to_ref=X1,
                         reference_id="DEP-77120" if with_refs else None,
                         attributes={"credited_from": SETTLEMENT})),
        ("bank_b", _transfer("bank_b", "E3-TX-0006", T(minutes=18, seconds=10), M3, SETTLEMENT, 1600000,
                             ref="DEP-77121" if with_refs else None, to_kind="exchange_settlement")),
        ("exchange", _ev("exchange", "E3-DEP-502", "exchange_deposit", T(minutes=18, seconds=40), 15,
                         asset="THB", amount_minor=1600000, to_ref=X2,
                         reference_id="DEP-77121" if with_refs else None,
                         attributes={"credited_from": SETTLEMENT})),
        ("exchange", _ev("exchange", "E3-TRD-501", "exchange_trade", T(minutes=20), 5, from_ref=X1,
                         attributes={"sell_asset": "THB", "sell_minor": 1600000, "buy_asset": "USDT",
                                     "buy_gross_minor": g1, "fee_asset": "USDT", "fee_minor": f1,
                                     "buy_net_minor": n1, "rate_thb_per_usdt": RATE_THB_PER_USDT})),
        ("exchange", _ev("exchange", "E3-TRD-502", "exchange_trade", T(minutes=20, seconds=30), 5, from_ref=X2,
                         attributes={"sell_asset": "THB", "sell_minor": 1600000, "buy_asset": "USDT",
                                     "buy_gross_minor": g2, "fee_asset": "USDT", "fee_minor": f2,
                                     "buy_net_minor": n2, "rate_thb_per_usdt": RATE_THB_PER_USDT})),
        ("signals", _ev("signals", "E4-SIG-0001", "external_signal", T(minutes=23), 120, to_ref=M1,
                        attributes={"category": "victim_report", "source": "simulated_report_source"})),
        ("exchange", _ev("exchange", "E5-WD-901", "withdrawal_request", wd_at, 2, asset="USDT",
                         amount_minor=wd_amount, from_ref=X1, to_ref=DEST,
                         attributes={"withdrawal_id": "W-901", "chain": "tron",
                                     "controllable_until": controllable.isoformat()})),
    ]
    deliveries = [{"client": c, "event": e, "due": e["available_at"]} for c, e in live]
    deliveries.sort(key=lambda d: d["due"])
    return {
        "name": name,
        "description": SCENARIOS[name],
        "start": DAY0,
        "end": T(minutes=50),
        "history": history(),
        "deliveries": deliveries,
        "accounts": [
            {"account_id": VICTIM, "institution": "bank_a", "display": "Bank A •0042", "holder_kind": "person",
             "holder_name": "Customer A-0042 (synthetic)", "balance_minor": 8000000},
            {"account_id": M1, "institution": "bank_a", "display": "Bank A •1001", "holder_kind": "person",
             "holder_name": "Customer A-1001 (synthetic)", "balance_minor": 15000},
            {"account_id": M2, "institution": "bank_b", "display": "Bank B •2001", "holder_kind": "person",
             "holder_name": "Customer B-2001 (synthetic)", "balance_minor": 5000},
            {"account_id": M3, "institution": "bank_b", "display": "Bank B •2002", "holder_kind": "person",
             "holder_name": "Customer B-2002 (synthetic)", "balance_minor": 5000},
            {"account_id": MERCHANT, "institution": "bank_b", "display": "Bank B •3001", "holder_kind": "merchant",
             "holder_name": "ร้านป้ามะลิ ข้าวมันไก่ (synthetic)", "balance_minor": 1000000},
            {"account_id": SETTLEMENT, "institution": "bank_b", "display": "Bank B •9000",
             "holder_kind": "exchange_settlement", "holder_name": "Exchange settlement account (synthetic)",
             "balance_minor": 50000000},
        ],
        "customers": [
            {"customer_id": X1, "display": "Exchange customer X-501", "balances": {"THB": 0, "USDT": 0}},
            {"customer_id": X2, "display": "Exchange customer X-502", "balances": {"THB": 0, "USDT": 0}},
        ],
        "merchant_account_id": MERCHANT,
        "demo_script": [
            {"at": T(minutes=28), "actor": "bank_b", "action": "restrict_amount", "subject": MERCHANT},
            {"at": T(minutes=29), "actor": "exchange", "action": "hold_withdrawal", "subject": "wd:exchange:W-901"},
            {"at": T(minutes=31), "actor": "merchant", "action": "submit_evidence", "fixture": "sale_receipt_300"},
            {"at": T(minutes=34), "actor": "bank_b", "action": "release_restriction", "subject": MERCHANT},
        ],
    }
