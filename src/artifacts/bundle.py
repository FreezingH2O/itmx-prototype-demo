"""Load experiment result bundles produced by 05-model-experiments.

Expected layout (subset of 07-results-and-handoff.md):
  <bundle>/manifest.json            run_id, status, measurement_type, dataset, limitations
  <bundle>/feature_manifest.json    feature_version, feature_names
  <bundle>/models/<arm>/adapter.json  {"type": "lightgbm"|"rules"|"gnn", ...}
  <bundle>/results/<arm>.json       one file per arm, shape of templates/result.template.json
  <bundle>/comparisons.csv          optional paired deltas
  <bundle>/parity.json              written by scripts/parity_check.py
  <bundle>/figures/*                optional exported figures
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

PRESENTABLE_STATUSES = {"completed", "inconclusive"}
PRESENTABLE_MEASUREMENTS = {"external_synthetic_benchmark", "team_simulation", "measured_compute"}


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_bundle(path: Path) -> dict[str, Any]:
    manifest = _read_json(path / "manifest.json")
    if not manifest:
        raise FileNotFoundError(f"{path} has no manifest.json")
    for key in ("run_id", "status", "measurement_type"):
        if key not in manifest:
            raise ValueError(f"manifest.json missing {key!r}")
    results = []
    for f in sorted((path / "results").glob("*.json")) if (path / "results").exists() else []:
        r = _read_json(f)
        r["_file"] = f.name
        results.append(r)
    comparisons = []
    if (path / "comparisons.csv").exists():
        with (path / "comparisons.csv").open(encoding="utf-8") as f:
            comparisons = list(csv.DictReader(f))
    presentable = (manifest["status"] in PRESENTABLE_STATUSES
                   and manifest["measurement_type"] in PRESENTABLE_MEASUREMENTS)
    return {
        "id": path.name,
        "path": str(path),
        "manifest": manifest,
        "feature_manifest": _read_json(path / "feature_manifest.json"),
        "results": results,
        "comparisons": comparisons,
        "parity": _read_json(path / "parity.json"),
        "figures": sorted(p.name for p in (path / "figures").glob("*")) if (path / "figures").exists() else [],
        "failures": _read_json(path / "failures.json") or [],
        "presentable": presentable,
        "arms": sorted(p.name for p in (path / "models").iterdir() if p.is_dir()) if (path / "models").exists() else [],
    }


def list_bundles(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "manifest.json").exists():
            try:
                out.append(load_bundle(p))
            except Exception as exc:
                out.append({"id": p.name, "path": str(p), "error": str(exc), "presentable": False})
    return out


def template_rows(template_csv: Path) -> list[dict[str, str]]:
    if not template_csv.exists():
        return []
    with template_csv.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))
