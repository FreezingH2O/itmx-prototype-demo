"""Link bank transfers into exchange settlement accounts with exchange deposit credits.

verified   : shared bank reference + equal amount + transfer into a settlement account
candidate  : no reference, exactly one equal-amount transfer in the window (lead only)
unresolved : no reference and zero or several candidates, or reference conflicts
Same amount/time alone is never treated as verified identity.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.contracts import Event, Link
from src.store.state import EngineState

CANDIDATE_WINDOW = timedelta(minutes=60)


def _settlement_transfers(state: EngineState, as_of: datetime) -> list[Event]:
    return [e for e in state.ix().settlement_in if e.available_at <= as_of]


def relink(state: EngineState, as_of: datetime) -> list[Link]:
    """Recompute deposit links visible at as_of. Returns links whose status changed."""
    changed: list[Link] = []
    transfers = _settlement_transfers(state, as_of)
    deposits = [e for e in state.ix().by_type.get("exchange_deposit", ()) if e.available_at <= as_of]
    verified_transfer_ids = set()
    proposals: dict[str, Link] = {}
    for d in sorted(deposits, key=lambda e: e.ingest_seq):
        link_id = f"link:deposit:{d.event_id}"
        if d.reference_id:
            matches = [t for t in transfers if t.reference_id == d.reference_id]
            if len(matches) == 1 and matches[0].amount_minor == d.amount_minor and matches[0].asset == d.asset:
                t = matches[0]
                verified_transfer_ids.add(t.event_id)
                proposals[link_id] = Link(
                    link_id=link_id, relation="transfer_credited_as_deposit", from_id=t.from_ref, to_id=d.to_ref,
                    status="verified", method="shared bank reference + equal amount",
                    evidence_event_ids=[t.event_id, d.event_id], known_at=max(t.available_at, d.available_at))
            else:
                note = ("reference not yet seen on bank side" if not matches
                        else "reference matches but amount/asset differs" if len(matches) == 1
                        else "reference appears on several transfers")
                proposals[link_id] = Link(
                    link_id=link_id, relation="transfer_credited_as_deposit", from_id="", to_id=d.to_ref,
                    status="unresolved", method="reference check", evidence_event_ids=[d.event_id],
                    known_at=d.available_at, candidates=[t.event_id for t in matches], note=note)
    for d in sorted(deposits, key=lambda e: e.ingest_seq):
        link_id = f"link:deposit:{d.event_id}"
        if d.reference_id:
            continue
        cands = [t for t in transfers
                 if t.event_id not in verified_transfer_ids and t.amount_minor == d.amount_minor
                 and t.asset == d.asset and d.occurred_at - CANDIDATE_WINDOW <= t.occurred_at <= d.occurred_at]
        if len(cands) == 1:
            proposals[link_id] = Link(
                link_id=link_id, relation="candidate_related_event", from_id=cands[0].from_ref, to_id=d.to_ref,
                status="candidate", method="equal amount within 60 min, no reference (lead only)",
                evidence_event_ids=[cands[0].event_id, d.event_id], known_at=d.available_at,
                candidates=[cands[0].event_id], note="no bank reference on deposit")
        else:
            proposals[link_id] = Link(
                link_id=link_id, relation="candidate_related_event", from_id="", to_id=d.to_ref,
                status="unresolved", method="equal amount within 60 min, no reference",
                evidence_event_ids=[d.event_id], known_at=d.available_at,
                candidates=[t.event_id for t in cands],
                note=f"{len(cands)} equal-amount transfers; cannot pick one without a reference")
    for link_id, new in proposals.items():
        old = state.links.get(link_id)
        if old is None or old.model_dump(exclude={"known_at"}) != new.model_dump(exclude={"known_at"}):
            state.links[link_id] = new
            changed.append(new)
    return changed
