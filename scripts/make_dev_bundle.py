"""Create a DEV FIXTURE bundle to test the plug-in path (LightGBM load + parity + switch).

NOT AN EXPERIMENT RESULT. The model is trained on random synthetic feature rows with a toy
label. Status is "dev_fixture" so the engine refuses it unless allow_bundle_statuses
includes dev_fixture, and the Results page never presents it as a result.

Usage (from 03-solution/):  python scripts/make_dev_bundle.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.features import sim_local  # noqa: E402
from src.sim import scenarios  # noqa: E402
from scripts._events import load_events  # noqa: E402

OUT = ROOT / "artifacts" / "bundles" / "dev-fixture-sim-lgbm"
ARM = "DEV_LGBM"


def main() -> None:
    rng = np.random.default_rng(7)
    n = 4000
    X = pd.DataFrame({
        "amount_thb": rng.lognormal(6, 1.5, n), "is_qr": rng.integers(0, 2, n).astype(float),
        "src_account_age_hours": rng.uniform(1, 2000, n), "src_in_sum_24h_thb": rng.lognormal(7, 2, n),
        "src_out_count_1h": rng.poisson(1, n).astype(float), "src_out_sum_1h_thb": rng.lognormal(6, 2, n),
        "pass_through_ratio_24h": rng.uniform(0, 1.2, n), "minutes_since_src_last_inbound": rng.uniform(0, 2000, n),
        "src_unique_out_counterparties_1h": rng.integers(1, 6, n).astype(float),
        "dst_unique_payers_30d": rng.integers(0, 40, n).astype(float),
        "dst_in_count_30d": rng.integers(0, 60, n).astype(float),
        "dst_is_exchange_settlement": rng.integers(0, 2, n).astype(float),
    })[sim_local.FEATURE_NAMES]
    toy = (X.pass_through_ratio_24h > 0.8) & (X.minutes_since_src_last_inbound < 60)
    y = (toy | (rng.uniform(size=n) < 0.02)).astype(int)
    model = lgb.train({"objective": "binary", "num_leaves": 15, "learning_rate": 0.1, "verbose": -1,
                       "seed": 17, "deterministic": True}, lgb.Dataset(X, y), num_boost_round=60)

    mdir = OUT / "models" / ARM
    mdir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(mdir / "model.txt"))
    (mdir / "adapter.json").write_text(json.dumps({
        "type": "lightgbm", "model_file": "model.txt", "model_id": "DEV-LGBM", "arm": ARM, "version": "dev-1",
        "task_id": "dev_fixture_not_a_task", "feature_version": sim_local.FEATURE_VERSION,
        "feature_names": sim_local.FEATURE_NAMES,
        "score_semantics": "DEV FIXTURE output on random data; meaningless as risk"}, indent=2))
    (OUT / "manifest.json").write_text(json.dumps({
        "schema_version": "0.1", "run_id": "dev-fixture-0001", "status": "dev_fixture",
        "measurement_type": "dev_fixture", "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {"id": "random_feature_rows", "note": "not IBM, not a benchmark"},
        "limitations": ["Plumbing test only. Never present as a result."]}, indent=2))
    (OUT / "feature_manifest.json").write_text(json.dumps({
        "feature_version": sim_local.FEATURE_VERSION, "feature_names": sim_local.FEATURE_NAMES}, indent=2))

    # Parity sample: scenario events + the scores this script expects for bank transfers.
    scn = scenarios.build("merchant_300")
    evs = scn["history"] + [d["event"] for d in scn["deliveries"]]
    psd = OUT / "parity_sample"
    psd.mkdir(exist_ok=True)
    (psd / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs), encoding="utf-8")
    events = load_events(psd / "events.jsonl")
    targets = [e for e in events if e.event_type == "bank_transfer" and e.occurred_at >= scenarios.DAY0]
    rows = pd.DataFrame([sim_local.build(events, t) for t in targets])[sim_local.FEATURE_NAMES].astype(float)
    preds = pd.DataFrame({"event_id": [t.event_id for t in targets], "score": model.predict(rows)})
    (OUT / "predictions").mkdir(exist_ok=True)
    preds.to_parquet(OUT / "predictions" / f"{ARM}.parquet", index=False)
    print(f"wrote dev fixture bundle to {OUT} ({len(preds)} parity targets)")


if __name__ == "__main__":
    main()
