"""Run manager: shared clock, simulated clients and SSE fan-out.

Simulated clients call the Engine API through the ASGI interface (in-process HTTP),
so every client request goes through the same routing and validation as an external call.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from src.engine.core import EngineContext
from src.models.base import ModelUnavailable
from src.models.registry import load_model
from src.sim import scenarios
from src.sim.institutions import apply_event, auto_progress, new_sim
from src.store.audit import AuditLog
from src.store.state import ApiLogEntry, ClientLogEntry, Delivery, EngineState, RunState

ROOT = Path(__file__).resolve().parents[2]
TICK_SECONDS = 0.25


class ReadOnlyRun(Exception):
    pass


class Runtime:
    def __init__(self, engine_cfg_path: Path = ROOT / "config" / "engine.yaml",
                 policy_cfg_path: Path = ROOT / "config" / "policy.yaml", audit_path: Optional[str] = None):
        self.engine_cfg = yaml.safe_load(engine_cfg_path.read_text(encoding="utf-8"))
        self.policy = yaml.safe_load(policy_cfg_path.read_text(encoding="utf-8"))
        self.audit = AuditLog(audit_path or (ROOT / self.engine_cfg["audit_db"]))
        self.model, self.model_status = None, {}
        try:
            self.model, self.model_status = load_model(self.engine_cfg)
        except (ModelUnavailable, FileNotFoundError, KeyError, ValueError) as exc:
            self.model_status = {"kind": "error", "error": str(exc),
                                 "live_label": "Model failed to load: existing controls only"}
        self.runs: dict[str, RunState] = {}
        self.ctx: dict[str, EngineContext] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.frames: dict[str, list[dict[str, Any]]] = {}
        self.frame_index: dict[str, int] = {}
        self.app = None
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------ helpers
    def model_info(self) -> dict[str, Any]:
        info = self.model.info() if self.model else {}
        return {**info, "status": self.model_status}

    def lock(self, rid: str) -> asyncio.Lock:
        return self.locks.setdefault(rid, asyncio.Lock())

    def get(self, rid: str) -> RunState:
        if rid not in self.runs:
            raise KeyError(rid)
        return self.runs[rid]

    def ensure_writable(self, run: RunState) -> None:
        if run.mode == "recorded":
            raise ReadOnlyRun("recorded replay is read-only")

    def make_ctx(self, run: RunState) -> EngineContext:
        def audit(kind: str, ref: str, body: Any) -> None:
            self.audit.append(run.run_id, run.epoch, run.version, run.sim.clock.now, "engine", kind, ref, body)
        return EngineContext(model=self.model, model_status=self.model_status, policy=self.policy, audit=audit,
                             model_unavailable=run.faults.get("model_unavailable", False))

    def sim_audit(self, run: RunState, actor: str, kind: str, ref: str, body: Any) -> None:
        self.audit.append(run.run_id, run.epoch, run.version, run.sim.clock.now, actor, kind, ref, body)

    def touch(self, run: RunState) -> None:
        run.version += 1
        msg = {"run_id": run.run_id, "version": run.version, "epoch": run.epoch,
               "sim_time": run.sim.clock.now.isoformat(), "playing": run.sim.clock.playing, "mode": run.mode}
        for q in list(self.subscribers.get(run.run_id, ())):
            q.put_nowait(msg)

    def log_api(self, run: RunState, client: str, method: str, path: str, code: int, req: Any, resp: Any,
                t0: float) -> None:
        run.sim.api_log.append(ApiLogEntry(
            seq=len(run.sim.api_log) + 1, sim_time=run.sim.clock.now, client=client, method=method, path=path,
            status_code=code, request=req, response=resp, latency_ms=round((time.perf_counter() - t0) * 1000, 2)))
        run.sim.api_log = run.sim.api_log[-300:]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://engine.local",
                                 timeout=10.0)

    # ------------------------------------------------------------ runs
    async def create_run(self, scenario: str, mode: str, speed: float, recording: Optional[str],
                         run_id: Optional[str] = None, epoch: int = 1) -> RunState:
        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"
        if mode == "recorded":
            return self._load_recording(rid, recording or f"{scenario}_demo", speed)
        scn = scenarios.build(scenario)
        run = RunState(run_id=rid, scenario=scenario, mode="live", epoch=epoch,
                       created_at=datetime.now(timezone.utc), engine=EngineState(),
                       sim=new_sim(scn, speed), model_info=self.model_info())
        self.runs[rid] = run
        self.ctx[rid] = self.make_ctx(run)
        self.sim_audit(run, "simulator", "run_created", rid, {"scenario": scenario, "speed": speed})
        by_org: dict[str, list[dict]] = {}
        for ev in scn["history"]:
            by_org.setdefault(ev["source_org"], []).append(ev)
        async with self.client() as c:
            for org, evs in by_org.items():
                await c.post(f"/v1/runs/{rid}/events", json={"events": evs}, headers={"X-Sim-Client": org})
        run.sim.client_log.append(ClientLogEntry(
            seq=1, sim_time=run.sim.clock.now, client="simulator", summary=f"initial sync of {len(scn['history'])} "
            "historical events (context only, before demo start)", status="sent"))
        self.touch(run)
        return run

    async def reset(self, run: RunState) -> RunState:
        if run.mode == "recorded":
            self.frame_index[run.run_id] = 0
            return self._apply_frame(run.run_id, 0, playing=False)
        return await self.create_run(run.scenario, "live", run.sim.clock.speed, None, run.run_id, run.epoch + 1)

    # ------------------------------------------------------------ clock
    def _next_due(self, run: RunState) -> Optional[datetime]:
        dues = [d.due for d in run.sim.deliveries if not d.delivered]
        dues += [w.controllable_until for w in run.sim.withdrawals.values() if w.state == "pending"]
        return min(dues) if dues else None

    async def advance(self, run: RunState, target: datetime) -> None:
        sim = run.sim
        while True:
            nxt = self._next_due(run)
            if nxt is None or nxt > target:
                break
            sim.clock.now = max(sim.clock.now, nxt)
            sim.deliveries.extend(auto_progress(sim, sim.clock.now))
            for d in sorted([d for d in sim.deliveries if not d.delivered and d.due <= sim.clock.now],
                            key=lambda d: d.due):
                await self.deliver(run, d)
        sim.clock.now = max(sim.clock.now, min(target, sim.clock.end))
        self.touch(run)

    async def step(self, run: RunState) -> None:
        if run.mode == "recorded":
            idx = min(self.frame_index[run.run_id] + 1, len(self.frames[run.run_id]) - 1)
            self._apply_frame(run.run_id, idx, playing=False)
            return
        nxt = self._next_due(run)
        await self.advance(run, nxt if nxt else run.sim.clock.end)

    async def deliver(self, run: RunState, d: Delivery) -> None:
        d.delivered = True
        sim = run.sim
        try:
            apply_event(sim, d.event)
        except ValueError as exc:
            sim.notices.append({"at": sim.clock.now.isoformat(), "level": "error", "text": str(exc)})
        self.sim_audit(run, d.client, "sim_event_booked", d.event["source_event_id"], d.event)
        entry = ClientLogEntry(seq=len(sim.client_log) + 1, sim_time=sim.clock.now, client=d.client,
                               summary=_summary(d.event), status="sending")
        sim.client_log.append(entry)
        async with self.client() as c:
            r = await c.post(f"/v1/runs/{run.run_id}/events", json={"events": [d.event]},
                             headers={"X-Sim-Client": d.client})
            if r.status_code != 200:
                entry.status = f"rejected ({r.status_code})"
                return
            item = r.json()["results"][0]
            entry.event_id = item["event_id"]
            entry.status = "sent" if item["status"] == "accepted" else item["status"]
            etype = d.event["event_type"]
            if item["status"] != "accepted" or etype not in ("bank_transfer", "withdrawal_request"):
                return
            subject = (item["event_id"] if etype == "bank_transfer"
                       else f"wd:exchange:{d.event['attributes']['withdrawal_id']}")
            entry.subject_id = subject
            a = await c.post(f"/v1/runs/{run.run_id}/assessments", json={"subject_id": subject},
                             headers={"X-Sim-Client": d.client})
            if a.status_code == 503:
                entry.status = "engine unavailable: existing controls apply"
            elif a.status_code == 200:
                body = a.json()
                entry.assessment_id = body["assessment"]["assessment_id"]
                entry.recommendation_ids = [x["recommendation_id"] for x in body["recommendations"]]
                entry.status = "recommendation received" if entry.recommendation_ids else "assessed"
            else:
                entry.status = f"assessment error ({a.status_code})"

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            for rid, run in list(self.runs.items()):
                if not run.sim.clock.playing:
                    continue
                try:
                    if run.mode == "recorded":
                        self._play_recorded(run)
                        continue
                    target = run.sim.clock.now + timedelta(seconds=TICK_SECONDS * run.sim.clock.speed)
                    if target >= run.sim.clock.end:
                        run.sim.clock.playing = False
                    await self.advance(run, target)
                except Exception as exc:  # keep the loop alive; surface the error
                    run.sim.clock.playing = False
                    run.sim.notices.append({"at": run.sim.clock.now.isoformat(), "level": "error",
                                            "text": f"clock error: {exc}"})
                    self.touch(run)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop())

    # ------------------------------------------------------------ recorded replay
    def _load_recording(self, rid: str, name: str, speed: float) -> RunState:
        path = ROOT / self.engine_cfg["recordings_dir"] / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"recording {name!r} not found; run scripts/record_replay.py first")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.frames[rid] = data["frames"]
        self.frame_index[rid] = 0
        run = self._apply_frame(rid, 0, playing=False, speed=speed, recording=name)
        return run

    def _apply_frame(self, rid: str, idx: int, playing: bool, speed: Optional[float] = None,
                     recording: Optional[str] = None) -> RunState:
        prev = self.runs.get(rid)
        frame = self.frames[rid][idx]
        run = RunState.model_validate(frame["state"])
        run.run_id, run.mode = rid, "recorded"
        run.recording = recording or (prev.recording if prev else None)
        run.version = (prev.version if prev else 0)
        run.sim.clock.playing = playing
        if speed or prev:
            run.sim.clock.speed = speed or prev.sim.clock.speed
        self.runs[rid] = run
        self.frame_index[rid] = idx
        self.touch(run)
        return run

    def _play_recorded(self, run: RunState) -> None:
        rid = run.run_id
        frames = self.frames[rid]
        target = run.sim.clock.now + timedelta(seconds=TICK_SECONDS * run.sim.clock.speed)
        idx = self.frame_index[rid]
        while idx + 1 < len(frames) and datetime.fromisoformat(frames[idx + 1]["sim_time"]) <= target:
            idx += 1
        if idx != self.frame_index[rid]:
            self._apply_frame(rid, idx, playing=True)
            run = self.runs[rid]
        run.sim.clock.now = min(max(run.sim.clock.now, target), run.sim.clock.end)
        if idx + 1 >= len(frames) and run.sim.clock.now >= run.sim.clock.end:
            run.sim.clock.playing = False
        self.touch(run)


def _summary(ev: dict[str, Any]) -> str:
    t = ev["event_type"]
    amt = ev.get("amount_minor")
    if t == "bank_transfer":
        return f"transfer {amt / 100:,.2f} THB {ev['from_ref'].split(':')[-1]} -> {ev['to_ref'].split(':')[-1]}"
    if t == "exchange_deposit":
        return f"deposit credit {amt / 100:,.2f} THB to {ev['to_ref'].split(':')[-1]}"
    if t == "exchange_trade":
        a = ev["attributes"]
        return f"trade {a['sell_minor'] / 100:,.2f} THB -> {a['buy_net_minor'] / 1e6:,.6f} USDT ({ev['from_ref'].split(':')[-1]})"
    if t == "withdrawal_request":
        return f"withdrawal request {ev['attributes']['withdrawal_id']} {amt / 1e6:,.2f} USDT"
    if t == "withdrawal_state":
        return f"withdrawal {ev['attributes']['withdrawal_id']} {ev['attributes']['state']}"
    if t == "chain_transfer":
        return f"chain transfer {amt / 1e6:,.2f} USDT"
    if t == "external_signal":
        return f"{ev['attributes']['category']} on {ev['to_ref'].split(':')[-1]}"
    return t
