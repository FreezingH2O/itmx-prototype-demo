"""End-to-end and failure tests for the engine API + simulator (plan section 8)."""
from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import app as app_module
from src.api.runtime import Runtime
from src.contracts import EventIn
from src.features import sim_local
from src.sim import scenarios

ROOT = Path(__file__).resolve().parents[1]
MERCHANT = scenarios.MERCHANT


@pytest.fixture()
def client(tmp_path, monkeypatch):
    rt = Runtime(audit_path=str(tmp_path / "audit.sqlite"))
    monkeypatch.setattr(app_module, "runtime", rt)
    rt.app = app_module.app
    with TestClient(app_module.app) as c:
        rt.app = app_module.app
        yield c


def new_run(c, scenario="merchant_300"):
    r = c.post("/v1/runs", json={"scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def step_until(c, rid, n=40, until_case=False):
    s = None
    for _ in range(n):
        s = c.post(f"/v1/runs/{rid}/clock", json={"action": "step"}).json()
        if until_case and s["case_ids"]:
            break
        if not until_case and s["pending_deliveries"] == 0:
            break
    return s


def recs(c, rid, org):
    return c.get(f"/v1/runs/{rid}/views/{org}").json()["recommendations"]


def merchant(c, rid):
    return c.get(f"/v1/runs/{rid}/views/merchant:{MERCHANT}").json()


def decide(c, rid, rec, action, org, key=None, **scope):
    body = {"recommendation_id": rec["recommendation_id"], "actor_org": org, "actor_id": f"{org}-officer-1",
            "action": action, "target_scope": scope, "reason": "demo decision",
            "expected_state_version": rec["subject_state"]["state_version"],
            "idempotency_key": key or uuid.uuid4().hex}
    return c.post(f"/v1/runs/{rid}/decisions", json=body, headers={"X-Sim-Role": org})


def merchant_rec(c, rid, action="RECOMMEND_RESTRICTION_REVIEW"):
    return next(r for r in recs(c, rid, "bank_b") if r["subject_id"] == MERCHANT and r["action_type"] == action)


# ------------------------------------------------------------------ main story
def test_merchant_story_full_cycle(client):
    rid = new_run(client)
    step_until(client, rid)
    rec = merchant_rec(client, rid)
    assert rec["target_scope"]["amount_minor"] == 30000  # traced amount only
    assert merchant(client, rid)["ledger"]["restricted_minor"] == 0  # recommendation alone changes nothing

    r = decide(client, rid, rec, "restrict_amount", "bank_b", amount_minor=30000)
    assert r.status_code == 200, r.text
    m = merchant(client, rid)
    assert (m["ledger"]["total_minor"], m["ledger"]["restricted_minor"], m["ledger"]["available_minor"]) == (
        1030000, 30000, 1000000)
    restriction = m["restrictions"][0]
    assert "score" not in str(m).lower()  # merchant view exposes no internal scores

    ev = client.post(f"/v1/runs/{rid}/cases/{restriction['case_id']}/evidence",
                     json={"restriction_id": restriction["restriction_id"], "fixture_ref": "sale_receipt_300",
                           "idempotency_key": uuid.uuid4().hex},
                     headers={"X-Sim-Role": f"merchant:{MERCHANT}"})
    assert ev.status_code == 200, ev.text
    m = merchant(client, rid)
    assert m["restrictions"][0]["review_state"] == "review_pending"
    assert m["ledger"]["available_minor"] == 1000000  # evidence does not auto-release

    rel = merchant_rec(client, rid, "RECOMMEND_RELEASE_REVIEW")
    r = decide(client, rid, rel, "release_restriction", "bank_b", restriction_id=restriction["restriction_id"])
    assert r.status_code == 200, r.text
    m = merchant(client, rid)
    assert m["ledger"]["available_minor"] == 1030000 and m["restrictions"][0]["review_state"] == "released"


def test_conflicting_evidence_requests_information(client):
    rid = new_run(client)
    step_until(client, rid)
    decide(client, rid, merchant_rec(client, rid), "restrict_amount", "bank_b", amount_minor=30000)
    rs = merchant(client, rid)["restrictions"][0]
    client.post(f"/v1/runs/{rid}/cases/{rs['case_id']}/evidence",
                json={"restriction_id": rs["restriction_id"], "fixture_ref": "sale_receipt_mismatch",
                      "idempotency_key": uuid.uuid4().hex}, headers={"X-Sim-Role": f"merchant:{MERCHANT}"})
    types = {r["action_type"] for r in recs(client, rid, "bank_b") if r["subject_id"] == MERCHANT}
    assert "REQUEST_INFORMATION" in types and "RECOMMEND_RELEASE_REVIEW" not in types
    assert merchant(client, rid)["ledger"]["restricted_minor"] == 30000


# ------------------------------------------------------------------ idempotency (T01, T05)
def test_duplicate_event_and_conflict(client):
    rid = new_run(client)
    step_until(client, rid, n=1)
    ev = scenarios.build("merchant_300")["deliveries"][0]["event"]
    r = client.post(f"/v1/runs/{rid}/events", json={"events": [ev]}, headers={"X-Sim-Client": "bank_a"})
    assert r.json()["results"][0]["status"] == "duplicate"
    bad = {**ev, "amount_minor": ev["amount_minor"] + 1}
    r = client.post(f"/v1/runs/{rid}/events", json={"events": [bad]}, headers={"X-Sim-Client": "bank_a"})
    assert r.status_code == 409


def test_duplicate_decision_does_not_double_restrict(client):
    rid = new_run(client)
    step_until(client, rid)
    rec = merchant_rec(client, rid)
    key = uuid.uuid4().hex
    a = decide(client, rid, rec, "restrict_amount", "bank_b", key=key, amount_minor=30000)
    b = decide(client, rid, rec, "restrict_amount", "bank_b", key=key, amount_minor=30000)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert merchant(client, rid)["ledger"]["restricted_minor"] == 30000
    # A new click with stale state version is rejected, not applied twice
    c2 = decide(client, rid, rec, "restrict_amount", "bank_b", amount_minor=30000)
    assert c2.status_code == 409
    assert merchant(client, rid)["ledger"]["restricted_minor"] == 30000


def test_restriction_capped_to_traced_amount(client):
    rid = new_run(client)
    step_until(client, rid)
    r = decide(client, rid, merchant_rec(client, rid), "restrict_amount", "bank_b", amount_minor=1030000)
    assert r.status_code == 422


# ------------------------------------------------------------------ links (T02, T06)
def test_missing_reference_stays_unresolved(client):
    rid = new_run(client, "missing_reference")
    step_until(client, rid)
    eng = client.get(f"/v1/runs/{rid}/views/simulator").json()
    statuses = {l["status"] for l in eng["links"]}
    assert "verified" not in statuses and "unresolved" in statuses  # equal amounts are leads only
    ex = recs(client, rid, "exchange")
    assert {r["action_type"] for r in ex} == {"REQUEST_INFORMATION"}
    assert not any(r["subject_id"].startswith("wd:") for r in ex)


def test_settlement_hub_not_traversed(client):
    rid = new_run(client)
    step_until(client, rid)
    case = client.get(f"/v1/runs/{rid}/views/simulator").json()["cases"][0]
    # Only customers reached through verified deposit links, not every settlement-account customer
    assert set(e for e in case["scope_entities"] if e.startswith("xcust:")) == {scenarios.X1, scenarios.X2}
    assert not any(r["subject_id"] == scenarios.SETTLEMENT for r in recs(client, rid, "bank_b"))


# ------------------------------------------------------------------ broadcast (T04)
def test_late_broadcast_cannot_be_held(client):
    rid = new_run(client, "late_broadcast")
    step_until(client, rid)
    ex = recs(client, rid, "exchange")
    wd = [r for r in ex if r["subject_id"] == "wd:exchange:W-901"]
    assert wd and all(r["action_type"] == "REVIEW_PRIORITY" for r in wd)
    r = decide(client, rid, wd[0], "hold_withdrawal", "exchange")
    assert r.status_code == 409 and r.json()["decision"]["outcome"] == "rejected"


def test_hold_after_deadline_rejected(client):
    rid = new_run(client)
    step_until(client, rid)
    rec = next(r for r in recs(client, rid, "exchange") if r["subject_id"] == "wd:exchange:W-901")
    client.post(f"/v1/runs/{rid}/clock", json={"action": "step"})  # deadline passes -> broadcast
    rec = next(r for r in recs(client, rid, "exchange") if r["recommendation_id"] == rec["recommendation_id"])
    r = decide(client, rid, rec, "hold_withdrawal", "exchange")
    assert r.status_code == 409


# ------------------------------------------------------------------ failures (T13, T14)
def test_model_unavailable_returns_pending_not_allow(client):
    rid = new_run(client)
    client.post(f"/v1/runs/{rid}/faults", json={"model_unavailable": True})
    step_until(client, rid, n=1)
    feed = client.get(f"/v1/runs/{rid}/views/bank_a").json()["feed"]
    assert feed[-1]["status"] == "engine unavailable: existing controls apply"
    r = client.post(f"/v1/runs/{rid}/assessments", json={"subject_id": feed[-1]["subject_id"]})
    assert r.status_code == 503 and r.json()["status"] == "pending"


def test_role_scope_enforced(client):
    rid = new_run(client)
    step_until(client, rid)
    rec = merchant_rec(client, rid)
    r = decide(client, rid, rec, "restrict_amount", "bank_a", amount_minor=30000)
    assert r.status_code == 403
    r = client.post(f"/v1/runs/{rid}/events", json={"events": [scenarios.build("merchant_300")["deliveries"][0]["event"]]},
                    headers={"X-Sim-Client": "bank_b"})
    assert r.json()["results"][0]["status"] == "rejected"
    case_id = rec["case_id"]
    assert client.get(f"/v1/runs/{rid}/cases/{case_id}", params={"role": f"merchant:{MERCHANT}"}).status_code == 403


# ------------------------------------------------------------------ ledger & leakage (T03, T17, T18)
def test_ledger_conserves_value(client):
    rid = new_run(client)
    step_until(client, rid)
    run = app_module.runtime.get(rid)
    scn = scenarios.build("merchant_300")
    start_total = sum(a["balance_minor"] for a in scn["accounts"])
    assert sum(a.balance_minor for a in run.sim.accounts.values()) == start_total
    x1 = run.sim.customers[scenarios.X1].balances
    assert x1["THB"] == 0 and x1["USDT"] == scenarios._usdt_for(1600000)[2]
    assert run.sim.accounts[scenarios.M1].balance_minor == 15000 + 5000000 - 1600000 * 2 - 30000


def test_features_ignore_future_events(client):
    rid = new_run(client)
    step_until(client, rid)
    eng = app_module.runtime.get(rid).engine
    target = eng.events["bank_a:E2-TX-0002"]
    full = sim_local.build(eng.events.values(), target)
    past_only = sim_local.build([e for e in eng.events.values() if e.available_at < target.available_at], target)
    assert full == past_only
    assert eng.predictions[target.event_id].features == full


def test_engine_never_imports_truth():
    for p in (ROOT / "src").rglob("*.py"):
        if "sim" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert "TRUTH" not in names, f"{p} references scenario truth"


def test_event_validation():
    with pytest.raises(ValueError):
        EventIn(source_org="bank_a", source_event_id="x", event_type="bank_transfer",
                occurred_at="2026-10-01T10:00:00+07:00", available_at="2026-10-01T09:59:00+07:00",
                asset="THB", amount_minor=1)
    with pytest.raises(ValueError):
        EventIn(source_org="bank_a", source_event_id="x", event_type="bank_transfer",
                occurred_at="2026-10-01T10:00:00", available_at="2026-10-01T10:00:00", asset="THB", amount_minor=1)


def test_reset_clears_state(client):
    rid = new_run(client)
    step_until(client, rid)
    decide(client, rid, merchant_rec(client, rid), "restrict_amount", "bank_b", amount_minor=30000)
    s = client.post(f"/v1/runs/{rid}/clock", json={"action": "reset"}).json()
    assert s["epoch"] == 2 and s["case_ids"] == []
    assert merchant(client, rid)["ledger"]["restricted_minor"] == 0


def test_recorded_replay_is_read_only(client):
    if not (ROOT / "artifacts" / "recordings" / "merchant_300_demo.json").exists():
        pytest.skip("run scripts/record_replay.py first")
    r = client.post("/v1/runs", json={"scenario": "merchant_300", "mode": "recorded"})
    assert r.status_code == 200 and r.json()["mode"] == "recorded"
    rid = r.json()["run_id"]
    for _ in range(30):
        client.post(f"/v1/runs/{rid}/clock", json={"action": "step"})
    m = merchant(client, rid)
    assert m["restrictions"] and m["restrictions"][0]["review_state"] == "released"
    ev = scenarios.build("merchant_300")["deliveries"][0]["event"]
    assert client.post(f"/v1/runs/{rid}/events", json={"events": [ev]},
                       headers={"X-Sim-Client": "bank_a"}).status_code == 409
