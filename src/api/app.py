"""Engine API (FastAPI). Run: uvicorn src.api.app:app --port 8000 (from 03-solution/)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from src.api import projections
from src.api.runtime import ROOT, ReadOnlyRun, Runtime
from src.artifacts.bundle import list_bundles, load_bundle, template_rows
from src.contracts import (
    SCHEMA_VERSION,
    AssessmentRequest,
    Decision,
    DecisionIn,
    EventIn,
    EvidenceSubmission,
    EvidenceSubmissionIn,
    RunCreate,
)
from src.engine import core
from src.engine.graph import build_graph
from src.policy import evidence_check
from src.sim import scenarios
from src.sim.institutions import SimRejected, apply_decision, receive_evidence

runtime = Runtime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.app = app
    runtime.start()
    yield


app = FastAPI(title="Bank x Crypto Risk Engine API (synthetic PoC)", version=SCHEMA_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
runtime.app = app


def _run(rid: str):
    try:
        return runtime.get(rid)
    except KeyError:
        raise HTTPException(404, f"run {rid} not found")


def _writable(run) -> None:
    try:
        runtime.ensure_writable(run)
    except ReadOnlyRun as exc:
        raise HTTPException(409, str(exc))


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str))


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def run_summary(run) -> dict[str, Any]:
    clock = run.sim.clock
    return {"run_id": run.run_id, "scenario": run.scenario, "mode": run.mode, "recording": run.recording,
            "epoch": run.epoch, "version": run.version,
            "clock": {"start": clock.start, "now": clock.now, "end": clock.end, "playing": clock.playing,
                      "speed": clock.speed},
            "case_ids": list(run.engine.cases), "merchant_account_id": run.sim.merchant_account_id,
            "model": run.model_info, "faults": run.faults, "notices": run.sim.notices[-5:],
            "pending_deliveries": sum(1 for d in run.sim.deliveries if not d.delivered)}


# ---------------------------------------------------------------- meta
@app.get("/v1/health")
def health():
    return {"ok": True, "schema_version": SCHEMA_VERSION, "model": runtime.model_info()}


@app.get("/v1/scenarios")
def list_scenarios():
    recs = ROOT / runtime.engine_cfg["recordings_dir"]
    return [{"id": k, "description": v, "recording_available": (recs / f"{k}_demo.json").exists()}
            for k, v in scenarios.SCENARIOS.items()]


@app.get("/v1/models")
def models():
    return {"active": runtime.model_info(), "config": runtime.engine_cfg["active_model"],
            "policy_version": runtime.policy["policy_version"],
            "score_priority_threshold": runtime.policy.get("score_priority_threshold")}


@app.get("/v1/evidence-fixtures")
def fixtures():
    return evidence_check.list_fixtures()


@app.get("/v1/metrics/latency")
def latency():
    xs = sorted(x for c in runtime.ctx.values() for x in c.latencies_ms)
    if not xs:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "scope": "assessment handler, this process"}
    return {"n": len(xs), "p50_ms": round(statistics.median(xs), 3),
            "p95_ms": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 3),
            "scope": "assessment handler time in this process (excludes network and data delay)"}


# ---------------------------------------------------------------- runs & clock
@app.post("/v1/runs")
async def create_run(body: RunCreate):
    try:
        run = await runtime.create_run(body.scenario, body.mode, body.speed, body.recording)
    except KeyError as exc:
        raise HTTPException(422, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return run_summary(run)


@app.get("/v1/runs/{rid}")
def get_run(rid: str):
    return run_summary(_run(rid))


class ClockIn(BaseModel):
    action: str = Field(pattern="^(play|pause|step|reset|speed|seek)$")
    speed: Optional[float] = Field(default=None, gt=0, le=600)
    to: Optional[datetime] = None  # seek: forward-only, live runs


@app.post("/v1/runs/{rid}/clock")
async def clock(rid: str, body: ClockIn):
    run = _run(rid)
    if body.action == "play":
        run.sim.clock.playing = run.sim.clock.now < run.sim.clock.end
    elif body.action == "pause":
        run.sim.clock.playing = False
    elif body.action == "step":
        run.sim.clock.playing = False
        await runtime.step(run)
    elif body.action == "reset":
        run = await runtime.reset(run)
    elif body.action == "speed" and body.speed:
        run.sim.clock.speed = body.speed
    elif body.action == "seek":
        _writable(run)
        if body.to is None or body.to < run.sim.clock.now:
            raise HTTPException(422, "seek needs a 'to' time at or after the current sim time")
        run.sim.clock.playing = False
        await runtime.advance(run, body.to)
    run = runtime.get(rid)
    runtime.touch(run)
    return run_summary(run)


@app.get("/v1/runs/{rid}/stream")
async def stream(rid: str, request: Request):
    run = _run(rid)
    q: asyncio.Queue = asyncio.Queue()
    runtime.subscribers.setdefault(rid, set()).add(q)

    async def gen():
        try:
            yield f"data: {json.dumps({'run_id': rid, 'version': run.version, 'hello': True})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    while not q.empty():  # coalesce bursts
                        msg = q.get_nowait()
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            runtime.subscribers.get(rid, set()).discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class FaultsIn(BaseModel):
    model_unavailable: bool


@app.post("/v1/runs/{rid}/faults")
def set_faults(rid: str, body: FaultsIn):
    run = _run(rid)
    _writable(run)
    run.faults["model_unavailable"] = body.model_unavailable
    runtime.ctx[rid].model_unavailable = body.model_unavailable
    runtime.sim_audit(run, "presenter", "fault", "model_unavailable", body.model_dump())
    runtime.touch(run)
    return run.faults


# ---------------------------------------------------------------- engine API
class EventsIn(BaseModel):
    events: list[dict[str, Any]] = Field(min_length=1, max_length=500)


@app.post("/v1/runs/{rid}/events")
async def post_events(rid: str, body: EventsIn, x_sim_client: str = Header(default="external")):
    run = _run(rid)
    _writable(run)
    t0 = time.perf_counter()
    async with runtime.lock(rid):
        merged: list[Any] = [None] * len(body.events)
        valid, slots = [], []
        for i, raw in enumerate(body.events):
            try:
                ev = EventIn.model_validate(raw)
            except ValidationError as exc:
                merged[i] = {"source_event_id": raw.get("source_event_id"), "event_id": None,
                             "status": "rejected", "detail": exc.errors(include_url=False)[0]["msg"]}
                continue
            if ev.source_org != x_sim_client:
                merged[i] = {"source_event_id": ev.source_event_id, "event_id": None, "status": "rejected",
                             "detail": f"client {x_sim_client!r} may not submit events for {ev.source_org!r}"}
                continue
            valid.append(ev)
            slots.append(i)
        for i, r in zip(slots, core.ingest(run.engine, valid, run.sim.clock.now, runtime.ctx[rid]) if valid else []):
            merged[i] = r
        resp = {"run_id": rid, "results": merged}
        code = 409 if len(merged) == 1 and merged[0]["status"] == "conflict" else 200
        runtime.log_api(run, x_sim_client, "POST", f"/v1/runs/{rid}/events", code,
                        {"events": body.events if len(body.events) <= 3 else f"{len(body.events)} events"},
                        resp, t0)
        runtime.touch(run)
    return JSONResponse(_jsonable(resp), status_code=code)


@app.post("/v1/runs/{rid}/assessments")
async def post_assessment(rid: str, body: AssessmentRequest, x_sim_client: str = Header(default="external")):
    run = _run(rid)
    _writable(run)
    t0 = time.perf_counter()
    async with runtime.lock(rid):
        inst = x_sim_client if x_sim_client in projections.INSTITUTIONS else None
        try:
            a = core.assess_subject(run.engine, body.subject_id, run.sim.clock.now, runtime.ctx[rid], inst)
        except core.EngineUnavailable as exc:
            resp = {"detail": str(exc), "status": "pending", "existing_controls_apply": True}
            runtime.log_api(run, x_sim_client, "POST", f"/v1/runs/{rid}/assessments", 503, body.model_dump(), resp, t0)
            runtime.touch(run)
            return JSONResponse(resp, status_code=503)
        except KeyError:
            raise HTTPException(404, f"unknown subject {body.subject_id}")
        recs = [projections._clean_rec(run.engine.recommendations[r]) for r in a.recommendation_ids]
        resp = {"assessment": a.model_dump(mode="json"), "recommendations": recs}
        runtime.log_api(run, x_sim_client, "POST", f"/v1/runs/{rid}/assessments", 200, body.model_dump(),
                        {"assessment_id": a.assessment_id, "risk_score": a.risk_score, "score_status": a.score_status,
                         "case_id": a.case_id, "recommendations": [{"id": r["recommendation_id"],
                                                                    "action_type": r["action_type"]} for r in recs]}, t0)
        runtime.touch(run)
    return resp


@app.get("/v1/runs/{rid}/graph")
def graph(rid: str, as_of: Optional[datetime] = None):
    run = _run(rid)
    return _jsonable(build_graph(run.engine, as_of or run.sim.clock.now, run.sim.clock.start))


def _role(x_sim_role: Optional[str], role: Optional[str]) -> str:
    r = x_sim_role or role
    if not r:
        raise HTTPException(403, "role required (X-Sim-Role header or role query)")
    return r


@app.get("/v1/runs/{rid}/views/{role}")
def view(rid: str, role: str):
    run = _run(rid)
    if role in projections.INSTITUTIONS:
        return _jsonable(projections.institution_view(run, role))
    if role.startswith("merchant:"):
        acct = role.split(":", 1)[1]
        if acct not in run.sim.accounts or run.sim.accounts[acct].holder_kind != "merchant":
            raise HTTPException(403, "unknown merchant account")
        return _jsonable(projections.merchant_view(run, acct))
    if role == "simulator":
        return _jsonable(projections.engine_view(run))
    raise HTTPException(403, f"unknown role {role}")


@app.get("/v1/runs/{rid}/cases/{case_id}")
def get_case(rid: str, case_id: str, role: Optional[str] = None, x_sim_role: Optional[str] = Header(default=None)):
    run = _run(rid)
    r = _role(x_sim_role, role)
    case = run.engine.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    if r == "simulator":
        a = run.engine.assessments.get(case.latest_assessment_id) if case.latest_assessment_id else None
        return _jsonable({"case": case.model_dump(mode="json"), "assessment": a.model_dump(mode="json") if a else None})
    if r in projections.INSTITUTIONS:
        v = projections.institution_view(run, r)
        return _jsonable({"case_id": case_id, "recommendations": [x for x in v["recommendations"] if x["case_id"] == case_id],
                          "decisions": [d for d in v["decisions"] if d["case_id"] == case_id]})
    if r.startswith("merchant:"):
        acct = r.split(":", 1)[1]
        mv = projections.merchant_view(run, acct)
        rs = [x for x in mv["restrictions"] if x["case_id"] == case_id]
        if not rs:
            raise HTTPException(403, "this case has no restriction on your account")
        return _jsonable({"case_id": case_id, "restrictions": rs, "ledger": mv["ledger"]})
    raise HTTPException(403, f"unknown role {r}")


@app.get("/v1/runs/{rid}/cases/{case_id}/timeline")
def get_timeline(rid: str, case_id: str):
    run = _run(rid)
    if case_id not in run.engine.cases:
        raise HTTPException(404, "case not found")
    return _jsonable(projections.timeline(run))


@app.get("/v1/runs/{rid}/audit")
def get_audit(rid: str, after: int = 0, limit: int = 200):
    run = _run(rid)
    if run.mode == "recorded":
        return {"note": "recorded replay: use the timeline; the audit log belongs to the recording run", "items": []}
    return {"items": runtime.audit.query(rid, run.epoch, after, min(limit, 1000))}


@app.post("/v1/runs/{rid}/decisions")
async def post_decision(rid: str, body: DecisionIn, x_sim_role: Optional[str] = Header(default=None)):
    run = _run(rid)
    _writable(run)
    t0 = time.perf_counter()
    if x_sim_role != body.actor_org:
        raise HTTPException(403, "X-Sim-Role must match actor_org")
    async with runtime.lock(rid):
        eng = run.engine
        idem = eng.idempotency.get(f"decision:{body.idempotency_key}")
        if idem:
            if idem["hash"] != _hash(body.model_dump(mode="json")):
                raise HTTPException(409, "idempotency key reused with a different payload")
            return JSONResponse(idem["body"], status_code=idem["code"])
        rec = eng.recommendations.get(body.recommendation_id)
        if rec is None:
            raise HTTPException(404, "recommendation not found")
        if rec.institution != body.actor_org:
            raise HTTPException(403, "recommendation belongs to another institution")
        if rec.status == "superseded":
            raise HTTPException(409, "recommendation superseded; refresh the case")
        now = run.sim.clock.now
        did = eng.next_id("DEC")
        follow = []
        try:
            detail, rid_restr, follow = apply_decision(run.sim, body, rec, now, rec.case_id, did)
            outcome, code = "acknowledged", 200
        except SimRejected as exc:
            if exc.code in (403, 404, 422):
                raise HTTPException(exc.code, exc.detail)
            detail, rid_restr, outcome, code = exc.detail, None, "rejected", exc.code
        dec = Decision(**body.model_dump(), decision_id=did, case_id=rec.case_id, recorded_at=now,
                       outcome=outcome, outcome_detail=detail, restriction_id=rid_restr)
        if rid_restr and "restriction_id" not in dec.target_scope:
            dec.target_scope = {**dec.target_scope, "restriction_id": rid_restr,
                                "account_id": rec.subject_id}
        dec.target_scope.setdefault("account_id", rec.subject_id)
        eng.decisions[did] = dec
        runtime.ctx[rid].audit("decision", did, dec.model_dump(mode="json"))
        if outcome == "acknowledged" and body.action != "no_action":
            rec.status = "acknowledged"
        case = eng.cases[rec.case_id]
        core.assess_case(eng, case, now, runtime.ctx[rid])
        run.sim.deliveries.extend(follow)
        resp = {"decision": dec.model_dump(mode="json")}
        eng.idempotency[f"decision:{body.idempotency_key}"] = {"hash": _hash(body.model_dump(mode="json")),
                                                                "code": code, "body": _jsonable(resp)}
        runtime.log_api(run, body.actor_org, "POST", f"/v1/runs/{rid}/decisions", code,
                        body.model_dump(mode="json"), {"outcome": outcome, "detail": detail}, t0)
        runtime.touch(run)
    if follow:
        await runtime.advance(run, run.sim.clock.now)
    return JSONResponse(_jsonable(resp), status_code=code)


@app.post("/v1/runs/{rid}/cases/{case_id}/evidence")
async def post_evidence(rid: str, case_id: str, body: EvidenceSubmissionIn,
                        x_sim_role: Optional[str] = Header(default=None)):
    run = _run(rid)
    _writable(run)
    t0 = time.perf_counter()
    if not x_sim_role or not x_sim_role.startswith("merchant:"):
        raise HTTPException(403, "only the merchant app may submit evidence")
    acct = x_sim_role.split(":", 1)[1]
    async with runtime.lock(rid):
        eng, sim = run.engine, run.sim
        key = f"evidence:{body.idempotency_key}"
        if key in eng.idempotency:
            idem = eng.idempotency[key]
            if idem["hash"] != _hash(body.model_dump()):
                raise HTTPException(409, "idempotency key reused with a different payload")
            return JSONResponse(idem["body"], status_code=idem["code"])
        r = sim.restrictions.get(body.restriction_id)
        if r is None or r.account_id != acct or r.case_id != case_id:
            raise HTTPException(403, "restriction not found on your account for this case")
        if r.status != "active":
            raise HTTPException(409, f"restriction already {r.status}")
        try:
            fixture, fhash = evidence_check.load_fixture(body.fixture_ref)
        except FileNotFoundError:
            raise HTTPException(422, "unknown evidence fixture")
        dec = eng.decisions[r.decision_id]
        rec = eng.recommendations[dec.recommendation_id]
        tx = eng.events[rec.target_scope["related_event_ids"][0]]
        consistency = evidence_check.check(fixture, tx, runtime.policy["evidence_check"])
        sub = EvidenceSubmission(submission_id=eng.next_id("EVD"), case_id=case_id, account_id=acct,
                                 restriction_id=r.restriction_id, fixture_ref=body.fixture_ref, fixture_hash=fhash,
                                 submitted_at=sim.clock.now, consistency=consistency,
                                 idempotency_key=body.idempotency_key)
        eng.evidence_submissions[sub.submission_id] = sub
        receive_evidence(sim, r.restriction_id, sim.clock.now, sub.submission_id)
        runtime.ctx[rid].audit("evidence_submission", sub.submission_id, sub.model_dump(mode="json"))
        core.assess_case(eng, eng.cases[case_id], sim.clock.now, runtime.ctx[rid])
        resp = {"submission_id": sub.submission_id, "review_state": "review_pending",
                "note": "Evidence received. A reviewer decides; submission alone does not release funds."}
        eng.idempotency[key] = {"hash": _hash(body.model_dump()), "code": 200, "body": resp}
        runtime.log_api(run, x_sim_role, "POST", f"/v1/runs/{rid}/cases/{case_id}/evidence", 200,
                        body.model_dump(), resp, t0)
        runtime.touch(run)
    return resp


# ---------------------------------------------------------------- experiment results
def _bundles_dir() -> Path:
    return ROOT / runtime.engine_cfg["results"]["bundles_dir"]


@app.get("/v1/experiments")
def experiments(include_dev: bool = False):
    show_dev = include_dev or runtime.engine_cfg["results"].get("include_dev_fixtures", False)
    out = []
    for b in list_bundles(_bundles_dir()):
        if not b.get("presentable") and not show_dev:
            continue
        m = b.get("manifest", {})
        out.append({"id": b["id"], "run_id": m.get("run_id"), "status": m.get("status"),
                    "measurement_type": m.get("measurement_type"), "presentable": b.get("presentable"),
                    "error": b.get("error")})
    tpl = ROOT / runtime.engine_cfg["results"]["template_csv"]
    return {"bundles": out, "template_arms": template_rows(tpl.resolve())}


@app.get("/v1/experiments/{bid}/results")
def experiment_results(bid: str, include_dev: bool = False):
    path = _bundles_dir() / bid
    if not (path / "manifest.json").exists() or path.resolve().parent != _bundles_dir().resolve():
        raise HTTPException(404, "bundle not found")
    b = load_bundle(path)
    if not b["presentable"] and not include_dev:
        raise HTTPException(409, f"bundle status {b['manifest']['status']!r} is not presentable as a result")
    return _jsonable(b)


@app.get("/v1/experiments/{bid}/figures/{name}")
def experiment_figure(bid: str, name: str):
    p = (_bundles_dir() / bid / "figures" / name).resolve()
    if p.parent != (_bundles_dir() / bid / "figures").resolve() or not p.exists():
        raise HTTPException(404, "figure not found")
    return FileResponse(p)
