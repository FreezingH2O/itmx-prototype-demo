"""Helpers to turn EventIn-shaped JSON into engine Event objects for offline checks."""
from __future__ import annotations

import json
from pathlib import Path

from src.contracts import Event, EventIn
from src.engine.core import payload_hash


def load_events(path: Path) -> list[Event]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        item = EventIn.model_validate(json.loads(line))
        out.append(Event(**item.model_dump(), event_id=f"{item.source_org}:{item.source_event_id}",
                         payload_hash=payload_hash(item), ingest_seq=i + 1, ingested_sim_time=item.available_at))
    return out
