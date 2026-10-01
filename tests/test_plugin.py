"""Model plug-in path: switch Rules -> bundle LightGBM by config only."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.api import app as app_module
from src.api.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = "artifacts/bundles/dev-fixture-sim-lgbm"


@pytest.fixture(scope="module", autouse=True)
def dev_bundle():
    subprocess.run([sys.executable, "scripts/make_dev_bundle.py"], cwd=ROOT, check=True, capture_output=True)
    subprocess.run([sys.executable, "scripts/parity_check.py", "--bundle", BUNDLE, "--arm", "DEV_LGBM"],
                   cwd=ROOT, check=True, capture_output=True)


def _cfg(tmp_path, allow):
    cfg = yaml.safe_load((ROOT / "config" / "engine.yaml").read_text())
    cfg["active_model"] = {"kind": "bundle", "path": BUNDLE, "arm": "DEV_LGBM"}
    cfg["allow_bundle_statuses"] = allow
    p = tmp_path / "engine.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_dev_fixture_refused_by_default(tmp_path):
    rt = Runtime(engine_cfg_path=_cfg(tmp_path, ["completed"]), audit_path=str(tmp_path / "a.sqlite"))
    assert rt.model is None and "not in allowed" in rt.model_status["error"]


def test_bundle_model_switch_runs_scenario(tmp_path, monkeypatch):
    rt = Runtime(engine_cfg_path=_cfg(tmp_path, ["completed", "dev_fixture"]), audit_path=str(tmp_path / "a.sqlite"))
    assert rt.model.model_id == "DEV-LGBM"
    assert rt.model_status["parity"]["status"] == "passed"
    monkeypatch.setattr(app_module, "runtime", rt)
    rt.app = app_module.app
    with TestClient(app_module.app) as c:
        rt.app = app_module.app
        rid = c.post("/v1/runs", json={"scenario": "merchant_300"}).json()["run_id"]
        for _ in range(15):
            c.post(f"/v1/runs/{rid}/clock", json={"action": "step"})
        eng = c.get(f"/v1/runs/{rid}/views/simulator").json()
        p = eng["predictions"]["bank_a:E2-TX-0004"]
        assert p["model_id"] == "DEV-LGBM" and p["score_status"] == "computed"
        assert p["contributions"] and p["contributions"][0]["label"].startswith("SHAP")
        assert c.get("/v1/models").json()["active"]["model_id"] == "DEV-LGBM"


def test_results_hide_dev_fixture(tmp_path, monkeypatch):
    rt = Runtime(audit_path=str(tmp_path / "a.sqlite"))
    monkeypatch.setattr(app_module, "runtime", rt)
    with TestClient(app_module.app) as c:
        rt.app = app_module.app
        body = c.get("/v1/experiments").json()
        assert all(b["presentable"] for b in body["bundles"])
        assert body["template_arms"] and body["template_arms"][0]["status"] == "not_run"
        assert c.get("/v1/experiments/dev-fixture-sim-lgbm/results").status_code == 409
