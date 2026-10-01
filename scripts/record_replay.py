"""Record a live engine run (scenario + scripted demo decisions) for offline replay.

The recording stores the run state after each step. Replay mode serves these stored
states and labels itself "RECORDED replay"; it performs no inference.

Usage (from 03-solution/): python scripts/record_replay.py [--scenario merchant_300]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from src.api import app as app_module  # noqa: E402
from src.sim import scenarios  # noqa: E402


def main(scenario: str) -> Path:
    rt = app_module.runtime
    scn = scenarios.build(scenario)
    merchant = scn["merchant_account_id"]
    with TestClient(app_module.app) as c:
        rt.app = app_module.app
        rid = c.post("/v1/runs", json={"scenario": scenario}).json()["run_id"]
        run = rt.get(rid)
        frames = []

        def snap():
            st = rt.get(rid).model_dump(mode="json")
            st["sim"]["api_log"] = st["sim"]["api_log"][-60:]
            frames.append({"sim_time": st["sim"]["clock"]["now"], "state": st})

        def view(role):
            return c.get(f"/v1/runs/{rid}/views/{role}").json()

        def decide(org, rec, action, **scope):
            r = c.post(f"/v1/runs/{rid}/decisions", headers={"X-Sim-Role": org}, json={
                "recommendation_id": rec["recommendation_id"], "actor_org": org, "actor_id": f"{org}-officer-1",
                "action": action, "target_scope": scope, "reason": "scripted demo decision",
                "expected_state_version": rec["subject_state"]["state_version"], "idempotency_key": uuid.uuid4().hex})
            r.raise_for_status()

        def act(a):
            if a["action"] == "restrict_amount":
                rec = next(r for r in view("bank_b")["recommendations"]
                           if r["subject_id"] == merchant and r["action_type"] == "RECOMMEND_RESTRICTION_REVIEW")
                decide("bank_b", rec, "restrict_amount", amount_minor=rec["target_scope"]["amount_minor"])
            elif a["action"] == "hold_withdrawal":
                rec = next((r for r in view("exchange")["recommendations"]
                            if r["subject_id"] == a["subject"] and r["action_type"] == "RECOMMEND_RESTRICTION_REVIEW"), None)
                if rec:
                    decide("exchange", rec, "hold_withdrawal")
            elif a["action"] == "submit_evidence":
                rs = view(f"merchant:{merchant}")["restrictions"][0]
                c.post(f"/v1/runs/{rid}/cases/{rs['case_id']}/evidence", headers={"X-Sim-Role": f"merchant:{merchant}"},
                       json={"restriction_id": rs["restriction_id"], "fixture_ref": a["fixture"],
                             "idempotency_key": uuid.uuid4().hex}).raise_for_status()
            elif a["action"] == "release_restriction":
                rec = next(r for r in view("bank_b")["recommendations"]
                           if r["subject_id"] == merchant and r["action_type"] == "RECOMMEND_RELEASE_REVIEW")
                decide("bank_b", rec, "release_restriction", restriction_id=rec["target_scope"]["restriction_id"])

        snap()
        script = sorted(scn["demo_script"], key=lambda a: a["at"])
        while True:
            nxt = rt._next_due(run)
            if script and (nxt is None or script[0]["at"] <= nxt):
                a = script.pop(0)
                c.post(f"/v1/runs/{rid}/clock", json={"action": "seek", "to": a["at"].isoformat()})
                act(a)
            elif nxt is not None:
                c.post(f"/v1/runs/{rid}/clock", json={"action": "step"})
            else:
                c.post(f"/v1/runs/{rid}/clock", json={"action": "seek", "to": run.sim.clock.end.isoformat()})
                snap()
                break
            run = rt.get(rid)
            snap()
    out = ROOT / rt.engine_cfg["recordings_dir"] / f"{scenario}_demo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "meta": {"scenario": scenario, "recorded_at": datetime.now(timezone.utc).isoformat(),
                 "source_run_id": rid, "model": rt.model_info(),
                 "note": "Recorded from a live engine run with scripted demo decisions. Replay performs no inference."},
        "frames": frames}, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {out} ({len(frames)} frames, {out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="merchant_300")
    main(ap.parse_args().scenario)
