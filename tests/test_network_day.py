"""Network Day (scale scenario): data consistency, network-case merging, multi-bank views,
and the featured merchant's restrict -> evidence -> release cycle at a bank other than A/B."""
from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timedelta

import pytest

from src.policy import evidence_check
from src.sim import network_day
from tests.test_engine_flow import client, decide, recs  # noqa: F401  (fixture + helpers)

# Shortly after the first report on the featured merchant's payer, so its payment is traced.
SEEK_TO = (network_day.featured_report_at() + timedelta(minutes=15)).isoformat()


def test_generated_ledgers_never_go_negative():
    """Replaying deliveries in due order, as the simulator books them, keeps every balance valid."""
    s = network_day.build()
    bal = {a["account_id"]: a["balance_minor"] for a in s["accounts"]}
    cust = {c["customer_id"]: {"THB": 0, "USDT": 0} for c in s["customers"]}
    for d in sorted(s["deliveries"], key=lambda d: datetime.fromisoformat(d["due"])):
        e = d["event"]
        t = e["event_type"]
        if t == "bank_transfer":
            bal[e["from_ref"]] -= e["amount_minor"]
            bal[e["to_ref"]] += e["amount_minor"]
            assert bal[e["from_ref"]] >= 0, e
        elif t == "exchange_deposit":
            cust[e["to_ref"]]["THB"] += e["amount_minor"]
        elif t == "exchange_trade":
            a = e["attributes"]
            assert cust[e["from_ref"]]["THB"] >= a["sell_minor"], e
            cust[e["from_ref"]]["THB"] -= a["sell_minor"]
            cust[e["from_ref"]]["USDT"] += a["buy_net_minor"]
        elif t == "withdrawal_request":
            assert cust[e["from_ref"]]["USDT"] >= e["amount_minor"], e
            cust[e["from_ref"]]["USDT"] -= e["amount_minor"]


def test_bought_mule_accounts_respect_face_scan_limits():
    s = network_day.build()
    truth = network_day.TRUTH()
    per_day = Counter()
    for d in s["deliveries"]:
        e = d["event"]
        if e["event_type"] == "bank_transfer" and truth[e["from_ref"]] == "mule_l1_bought":
            assert e["amount_minor"] < network_day.FACE_SCAN_TX_MINOR
            per_day[e["from_ref"]] += e["amount_minor"]
    assert max(per_day.values()) <= network_day.FACE_SCAN_DAY_MINOR


def test_featured_fixture_matches_the_payment():
    fixture, _ = evidence_check.load_fixture("sale_receipt_network_day")
    from src.contracts import Event
    e = network_day.featured_payment()
    tx = Event(**e, event_id="x", payload_hash="x", ingest_seq=0, ingested_sim_time=datetime.fromisoformat(e["occurred_at"]))
    assert evidence_check.check(fixture, tx, {"amount_must_match": True, "max_time_diff_minutes": 10})["consistent"]


@pytest.fixture()
def network_run(client):  # noqa: F811
    r = client.post("/v1/runs", json={"scenario": "network_day", "speed": 600})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    s = client.post(f"/v1/runs/{rid}/clock", json={"action": "seek", "to": SEEK_TO}).json()
    return client, rid, s


def test_reports_join_one_network_case(network_run):
    client, rid, s = network_run
    assert s["large"] and len(s["institutions"]) == 6
    assert not [n for n in s["notices"] if n["level"] == "error"]
    view = client.get(f"/v1/runs/{rid}/views/simulator").json()
    net = view["network"]
    assert net["reported_accounts"] >= 5 and len(net["institutions"]) >= 3
    # One recommendation per (institution, subject, action), not one per report.
    active = [r for r in view["recommendations"] if r["status"] != "superseded"]
    keys = Counter((r["institution"], r["subject_id"], r["action_type"]) for r in active)
    assert max(keys.values()) == 1
    # Whole network, every node tagged for grouping; only case accounts and payments into reported ones.
    g = client.get(f"/v1/runs/{rid}/graph").json()
    assert g["mode"] == "network" and len(g["focus_options"]) == net["reported_accounts"]
    assert all(n["stage"] in g["stages"] for n in g["nodes"])
    case = next(c for c in view["cases"] if c["case_id"] == net["case_id"])
    scope = set(case["scope_events"])
    reported = {o["id"] for o in g["focus_options"]}
    for e in g["edges"]:
        if e["kind"] in ("transfer", "deposit"):
            assert e["target"] in reported or set(e["evidence_event_ids"]) <= scope
    one = client.get(f"/v1/runs/{rid}/graph", params={"focus": g["focus_options"][0]["id"]}).json()
    assert one["mode"] == "focus" and len(one["nodes"]) < len(g["nodes"])


def test_graph_waits_for_a_report(client):  # noqa: F811
    """Before any report the large graph draws nothing (it used to draw every live transfer)."""
    rid = client.post("/v1/runs", json={"scenario": "network_day", "speed": 600}).json()["run_id"]
    client.post(f"/v1/runs/{rid}/clock", json={"action": "seek", "to": "2026-10-01T09:00:00+07:00"})
    g = client.get(f"/v1/runs/{rid}/graph").json()
    assert g["mode"] == "waiting" and g["nodes"] == [] and g["waiting"]["transfers"] > 100


def test_merchant_release_cycle_at_bank_e(network_run):
    client, rid, s = network_run
    m_id = s["merchant_account_id"]
    org = m_id.split(":")[1]
    assert org not in ("bank_a", "bank_b")
    rec = next(r for r in recs(client, rid, org)
               if r["subject_id"] == m_id and r["action_type"] == "RECOMMEND_RESTRICTION_REVIEW")
    amount = rec["target_scope"]["amount_minor"]
    assert amount == network_day.featured_payment()["amount_minor"]   # traced amount only
    assert decide(client, rid, rec, "restrict_amount", org, amount_minor=amount).status_code == 200

    role = {"X-Sim-Role": f"merchant:{m_id}"}
    mv = client.get(f"/v1/runs/{rid}/views/merchant:{m_id}").json()
    assert mv["ledger"]["restricted_minor"] == amount
    rs = mv["restrictions"][0]
    ev = client.post(f"/v1/runs/{rid}/cases/{rs['case_id']}/evidence", headers=role,
                     json={"restriction_id": rs["restriction_id"], "fixture_ref": "sale_receipt_network_day",
                           "idempotency_key": uuid.uuid4().hex})
    assert ev.status_code == 200, ev.text
    rel = next(r for r in recs(client, rid, org)
               if r["subject_id"] == m_id and r["action_type"] == "RECOMMEND_RELEASE_REVIEW")
    r = decide(client, rid, rel, "release_restriction", org, restriction_id=rs["restriction_id"])
    assert r.status_code == 200, r.text
    mv = client.get(f"/v1/runs/{rid}/views/merchant:{m_id}").json()
    assert mv["ledger"]["restricted_minor"] == 0 and mv["restrictions"][0]["review_state"] == "released"
    assert json.dumps(mv).count("score") == 0
