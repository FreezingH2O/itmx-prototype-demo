"""Map a simulated bank transfer to IBM AML-Data transaction columns.

PLUG-IN NOTE: an IBM-trained model never saw THB or PromptPay/QR. Scoring simulated
transfers with it is out of distribution. These mappings are explicit assumptions that
must be agreed before an IBM bundle is used for live scoring (see PLUGIN.md).
"""
from __future__ import annotations

from src.contracts import Event

IBM_COLUMNS = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
    "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency", "Payment Format",
]

# Assumptions, not facts. Change only with a recorded decision.
CURRENCY_ASSUMPTION = {"THB": None}  # IBM has no Thai Baht; None means "no faithful mapping"
PAYMENT_FORMAT_ASSUMPTION = {"transfer": "ACH", "qr": None}


def _parts(ref: str) -> tuple[str, str]:
    _, inst, acct = ref.split(":", 2)
    return inst, acct


def to_ibm_row(e: Event) -> dict:
    if e.event_type != "bank_transfer":
        raise ValueError("only bank_transfer maps to IBM rows")
    fb, fa = _parts(e.from_ref)
    tb, ta = _parts(e.to_ref)
    amount = f"{(e.amount_minor or 0) / 100:.2f}"
    return {
        "Timestamp": e.occurred_at.strftime("%Y/%m/%d %H:%M"),
        "From Bank": fb, "Account": fa, "To Bank": tb, "Account.1": ta,
        "Amount Received": amount, "Receiving Currency": CURRENCY_ASSUMPTION.get(e.asset),
        "Amount Paid": amount, "Payment Currency": CURRENCY_ASSUMPTION.get(e.asset),
        "Payment Format": PAYMENT_FORMAT_ASSUMPTION.get(e.attributes.get("payment_format")),
        "_unmapped": [k for k, v in {
            "currency": CURRENCY_ASSUMPTION.get(e.asset),
            "payment_format": PAYMENT_FORMAT_ASSUMPTION.get(e.attributes.get("payment_format")),
        }.items() if v is None],
    }
