"""Parity gate: engine features + adapter must reproduce the experiment's saved predictions.

Bundle must contain:
  parity_sample/events.jsonl      EventIn-shaped events (history + targets), engine schema
  predictions/<arm>.parquet       columns: event_id, score  (event_id = "<source_org>:<source_event_id>")
Writes parity.json into the bundle. The UI shows "LIVE inference" for a bundle model only
after this passes for the active arm.

Usage: python scripts/parity_check.py --bundle artifacts/bundles/<id> --arm G1 [--tol 1e-6]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.features.registry import get_builder  # noqa: E402
from src.models.lightgbm_adapter import LightGBMAdapter  # noqa: E402
from src.models.rules import RulesAdapter  # noqa: E402
from scripts._events import load_events  # noqa: E402


def run(bundle: Path, arm: str, tol: float) -> dict:
    spec = json.loads((bundle / "models" / arm / "adapter.json").read_text(encoding="utf-8"))
    src = {"kind": "bundle", "bundle_id": bundle.name}
    if spec["type"] == "lightgbm":
        adapter = LightGBMAdapter(bundle / "models" / arm, spec, src)
    elif spec["type"] == "rules":
        adapter = RulesAdapter(spec, src)
    else:
        raise SystemExit(f"parity for adapter type {spec['type']!r} not implemented")
    builder, _ = get_builder(adapter.feature_version)
    events = load_events(bundle / "parity_sample" / "events.jsonl")
    by_id = {e.event_id: e for e in events}
    expected = pd.read_parquet(bundle / "predictions" / f"{arm}.parquet")
    diffs, missing = [], []
    for eid, exp in zip(expected["event_id"], expected["score"]):
        if eid not in by_id:
            missing.append(eid)
            continue
        got = adapter.score([builder(events, by_id[eid])])[0]
        diffs.append(abs(got - float(exp)))
    result = {"status": "passed" if diffs and not missing and max(diffs) <= tol else "failed", "arm": arm,
              "n_checked": len(diffs), "n_missing_events": len(missing), "max_abs_diff": max(diffs) if diffs else None,
              "tolerance": tol, "feature_version": adapter.feature_version,
              "checked_at": datetime.now(timezone.utc).isoformat()}
    (bundle / "parity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--tol", type=float, default=1e-6)
    a = ap.parse_args()
    r = run((ROOT / a.bundle).resolve(), a.arm, a.tol)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["status"] == "passed" else 1)
