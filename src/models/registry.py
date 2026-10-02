"""Pick the active model from config/engine.yaml. UI reads model identity from the API."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.artifacts.bundle import load_bundle
from src.features.registry import get_builder
from src.models.base import ModelAdapter, ModelUnavailable
from src.models.gnn import GNNAdapter
from src.models.lightgbm_adapter import LightGBMAdapter
from src.models.rules import RulesAdapter

ROOT = Path(__file__).resolve().parents[2]


def load_model(cfg: dict[str, Any]) -> tuple[ModelAdapter, dict[str, Any]]:
    """Returns (adapter, status). Status says whether live inference may be claimed."""
    active = cfg["active_model"]
    if active["kind"] == "rules":
        adapter = RulesAdapter(cfg["rules"], source={"kind": "config", "file": "config/engine.yaml"})
        status = {"kind": "rules", "live_label": "LIVE inference (hand-set demo rules)",
                  "parity": {"status": "not_applicable"}, "bundle_status": None}
    elif active["kind"] == "bundle":
        bdir = (ROOT / active["path"]).resolve()
        bundle = load_bundle(bdir)
        man = bundle["manifest"]
        allowed = set(cfg.get("allow_bundle_statuses", ["completed", "inconclusive"]))
        if man["status"] not in allowed:
            raise ModelUnavailable(f"bundle status {man['status']!r} not in allowed {sorted(allowed)}")
        arm = active["arm"]
        mdir = bdir / "models" / arm
        spec = __import__("json").loads((mdir / "adapter.json").read_text(encoding="utf-8"))
        spec.setdefault("arm", arm)
        source = {"kind": "bundle", "bundle_id": bundle["id"], "run_id": man["run_id"],
                  "status": man["status"], "measurement_type": man["measurement_type"]}
        if spec["type"] == "lightgbm":
            adapter = LightGBMAdapter(mdir, spec, source)
        elif spec["type"] == "rules":
            spec.setdefault("feature_version", (bundle["feature_manifest"] or {}).get("feature_version"))
            adapter = RulesAdapter(spec, source)
        elif spec["type"] == "gnn":
            adapter = GNNAdapter(mdir, spec, source)
        else:
            raise ModelUnavailable(f"unknown adapter type {spec['type']!r}")
        parity = bundle["parity"] or {"status": "not_run"}
        live_ok = parity.get("status") == "passed" and parity.get("arm") == arm
        status = {"kind": "bundle", "bundle_status": man["status"], "parity": parity,
                  "live_label": "LIVE inference" if live_ok else "Model loaded; parity not passed (not claimable as live result model)"}
    else:
        raise ModelUnavailable(f"unknown active_model.kind {active['kind']!r}")
    _, names = get_builder(adapter.feature_version)
    missing = [f for f in adapter.required_features() if f not in names]
    if missing:
        raise ModelUnavailable(f"feature builder {adapter.feature_version!r} lacks {missing}")
    return adapter, status
