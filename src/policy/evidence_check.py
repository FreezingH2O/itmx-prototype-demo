"""Consistency check of a merchant's evidence against the restricted transaction.

This checks that the document agrees with the transaction record. It does not prove the
document is genuine or that the merchant is innocent; a human reviewer decides.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.contracts import Event

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "fixtures" / "evidence"


def list_fixtures() -> list[dict[str, Any]]:
    out = []
    for p in sorted(FIXTURES.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"fixture_ref": p.stem, "title": d.get("title"), "type": d.get("type")})
    return out


def load_fixture(ref: str) -> tuple[dict[str, Any], str]:
    p = FIXTURES / f"{ref}.json"
    if not p.exists() or p.parent != FIXTURES:
        raise FileNotFoundError(ref)
    raw = p.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def check(fixture: dict[str, Any], tx: Event, cfg: dict[str, Any]) -> dict[str, Any]:
    issues, matched = [], []
    amount_minor = round(float(fixture.get("amount_thb", "0")) * 100)
    if cfg.get("amount_must_match", True):
        (matched if amount_minor == tx.amount_minor else issues).append(
            f"amount {fixture.get('amount_thb')} THB vs transaction {tx.amount_minor / 100:.2f} THB")
    try:
        paid_at = datetime.fromisoformat(fixture["paid_at"])
        diff = abs((paid_at - tx.occurred_at).total_seconds()) / 60
        (matched if diff <= cfg.get("max_time_diff_minutes", 10) else issues).append(
            f"payment time differs by {diff:.0f} min")
    except Exception:
        issues.append("payment time missing or unreadable")
    hint = str(fixture.get("payer_hint", ""))
    (matched if hint and tx.from_ref.endswith(hint.lstrip("•")) else issues).append(
        f"payer hint {hint or '(none)'}")
    for field in ("order_id", "items"):
        if not fixture.get(field):
            issues.append(f"missing {field}")
    return {"consistent": not issues, "matched": matched, "issues": issues,
            "note": "Consistency with the transaction record only; not proof of authenticity or innocence."}
