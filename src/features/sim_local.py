"""Feature set `sim-local-v0`: local + light graph features for one bank transfer.

Leakage rule: history = events whose available_at is strictly before the target's
available_at. The target's own attributes are used directly. Labels, scenario truth
and pattern IDs never enter this module.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Optional

from src.contracts import Event

FEATURE_VERSION = "sim-local-v0"
FEATURE_NAMES = [
    "amount_thb",
    "is_qr",
    "src_account_age_hours",
    "src_in_sum_24h_thb",
    "src_out_count_1h",
    "src_out_sum_1h_thb",
    "pass_through_ratio_24h",
    "minutes_since_src_last_inbound",
    "src_unique_out_counterparties_1h",
    "dst_unique_payers_30d",
    "dst_in_count_30d",
    "dst_is_exchange_settlement",
]


def _thb(minor: Optional[int]) -> float:
    return (minor or 0) / 100.0


def visible_history(events: Iterable[Event], target: Event) -> list[Event]:
    return [e for e in events if e.available_at < target.available_at and e.event_id != target.event_id]


def build(events: Iterable[Event], target: Event) -> dict[str, Optional[float]]:
    if target.event_type != "bank_transfer":
        raise ValueError("sim-local-v0 only covers bank_transfer events")
    hist = [e for e in visible_history(events, target) if e.event_type == "bank_transfer"]
    t = target.occurred_at
    src, dst = target.from_ref, target.to_ref

    src_seen = [e.occurred_at for e in hist if src in (e.from_ref, e.to_ref)]
    src_in = [e for e in hist if e.to_ref == src]
    src_out = [e for e in hist if e.from_ref == src]
    in_24h = [e for e in src_in if t - timedelta(hours=24) <= e.occurred_at <= t]
    out_1h = [e for e in src_out if t - timedelta(hours=1) <= e.occurred_at <= t]
    out_24h = [e for e in src_out if t - timedelta(hours=24) <= e.occurred_at <= t]
    in_sum_24h = sum(e.amount_minor or 0 for e in in_24h)
    out_sum_24h = sum(e.amount_minor or 0 for e in out_24h) + (target.amount_minor or 0)
    last_in = max((e.occurred_at for e in src_in if e.occurred_at <= t), default=None)
    dst_in_30d = [e for e in hist if e.to_ref == dst and t - timedelta(days=30) <= e.occurred_at <= t]

    return {
        "amount_thb": _thb(target.amount_minor),
        "is_qr": 1.0 if target.attributes.get("payment_format") == "qr" else 0.0,
        "src_account_age_hours": ((t - min(src_seen)).total_seconds() / 3600.0) if src_seen else None,
        "src_in_sum_24h_thb": _thb(in_sum_24h),
        "src_out_count_1h": float(len(out_1h)),
        "src_out_sum_1h_thb": _thb(sum(e.amount_minor or 0 for e in out_1h)),
        "pass_through_ratio_24h": (out_sum_24h / in_sum_24h) if in_sum_24h else None,
        "minutes_since_src_last_inbound": ((t - last_in).total_seconds() / 60.0) if last_in else None,
        "src_unique_out_counterparties_1h": float(len({e.to_ref for e in out_1h} | {dst})),
        "dst_unique_payers_30d": float(len({e.from_ref for e in dst_in_30d})),
        "dst_in_count_30d": float(len(dst_in_30d)),
        "dst_is_exchange_settlement": 1.0 if target.attributes.get("to_account_kind") == "exchange_settlement" else 0.0,
    }
