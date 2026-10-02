"""Engine pipeline: validate -> dedupe -> append -> link -> features -> score -> case -> assessment.

Engine code reads and writes EngineState only. It never sees simulator ledgers or
scenario ground truth.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from src.contracts import (
    Assessment,
    Case,
    Entity,
    Event,
    EventIn,
    EvidenceItem,
    Prediction,
    Recommendation,
)
from src.engine import trace as tracing
from src.features import sim_local
from src.features.registry import get_builder
from src.linking.linker import relink
from src.models.base import ModelAdapter
from src.policy import recommend
from src.store.state import EngineState

INSTITUTION_NAMES = {"bank_a": "Bank A", "bank_b": "Bank B", "exchange": "Exchange"}


class EngineUnavailable(RuntimeError):
    pass


@dataclass
class EngineContext:
    model: Optional[ModelAdapter]
    model_status: dict[str, Any]
    policy: dict[str, Any]
    audit: Callable[[str, str, Any], None]
    model_unavailable: bool = False
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def model_ready(self) -> bool:
        return self.model is not None and not self.model_unavailable


def payload_hash(item: EventIn) -> str:
    raw = json.dumps(item.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- entities

def _display(ref: str) -> tuple[str, Optional[str], str]:
    kind, inst, local = ref.split(":", 2)
    if kind == "acct":
        return "bank_account", inst, f"{INSTITUTION_NAMES.get(inst, inst)} •{local.split('-')[-1]}"
    if kind == "xcust":
        return "exchange_customer", inst, f"Exchange customer {local}"
    if kind == "addr":
        return "chain_address", inst, f"{inst.upper()} {local[:6]}…{local[-4:]}"
    raise ValueError(f"unknown entity namespace in {ref!r}")


def _upsert_entity(state: EngineState, ref: Optional[str], known_at: datetime, **attrs: Any) -> None:
    if not ref:
        return
    ent = state.entities.get(ref)
    if ent is None:
        etype, inst, disp = _display(ref)
        ent = Entity(entity_id=ref, entity_type=etype, institution=inst, display=disp, first_known_at=known_at)
        state.entities[ref] = ent
    elif known_at < ent.first_known_at:
        ent.first_known_at = known_at
    for k, v in attrs.items():
        if isinstance(v, dict) and k in ("label", "signal"):
            ent.attributes.setdefault(k + "s", [])
            if v not in ent.attributes[k + "s"]:
                ent.attributes[k + "s"].append(v)
        else:
            ent.attributes[k] = v


def _register_entities(state: EngineState, e: Event) -> None:
    t = e.available_at
    if e.event_type == "bank_transfer":
        _upsert_entity(state, e.from_ref, t)
        kind = e.attributes.get("to_account_kind")
        if kind == "exchange_settlement":
            _upsert_entity(state, e.to_ref, t, account_kind=kind, hub=True)
        else:
            _upsert_entity(state, e.to_ref, t)
    elif e.event_type in ("exchange_deposit", "exchange_trade"):
        _upsert_entity(state, e.to_ref or e.from_ref, t)
    elif e.event_type == "withdrawal_request":
        _upsert_entity(state, e.from_ref, t)
        _upsert_entity(state, e.to_ref, t)
    elif e.event_type == "chain_transfer":
        _upsert_entity(state, e.from_ref, t)
        _upsert_entity(state, e.to_ref, t)
    elif e.event_type == "address_label":
        _upsert_entity(state, e.to_ref, t, label={**e.attributes, "known_at": e.available_at.isoformat(),
                                                   "event_id": e.event_id})
    elif e.event_type == "external_signal":
        _upsert_entity(state, e.to_ref, t, signal={**e.attributes, "known_at": e.available_at.isoformat(),
                                                    "event_id": e.event_id})


# ---------------------------------------------------------------- scoring

def score_event(state: EngineState, e: Event, ctx: EngineContext) -> Optional[Prediction]:
    if e.event_type != "bank_transfer":
        return None
    if not ctx.model_ready:
        pred = Prediction(event_id=e.event_id, as_of=e.available_at, task_id="unavailable", model_id="unavailable",
                          model_version="-", feature_version="-", score=None, score_semantics="model unavailable",
                          score_status="unavailable")
    else:
        m = ctx.model
        builder, _ = get_builder(m.feature_version)
        # sim-local features only read transfers of the sender or receiver; other builders get every event.
        events = (state.ix().touching(e.from_ref, e.to_ref) if m.feature_version == sim_local.FEATURE_VERSION
                  else state.events.values())
        row = builder(events, e)
        score = m.score([row])[0]
        pred = Prediction(event_id=e.event_id, as_of=e.available_at, task_id=m.task_id, model_id=m.model_id,
                          model_version=m.version, feature_version=m.feature_version, score=score,
                          score_semantics=m.score_semantics, score_status="computed", features=row,
                          contributions=m.explain(row))
    state.predictions[e.event_id] = pred
    ctx.audit("prediction", e.event_id, pred.model_dump(mode="json"))
    return pred


# ---------------------------------------------------------------- ingest

def ingest(state: EngineState, items: list[EventIn], now: datetime, ctx: EngineContext) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    new_events: list[Event] = []
    for item in items:
        eid = f"{item.source_org}:{item.source_event_id}"
        h = payload_hash(item)
        if eid in state.events:
            same = state.events[eid].payload_hash == h
            results.append({"source_event_id": item.source_event_id, "event_id": eid,
                            "status": "duplicate" if same else "conflict",
                            "detail": None if same else "same source_event_id with a different payload"})
            continue
        if item.available_at > now:
            results.append({"source_event_id": item.source_event_id, "event_id": None, "status": "rejected",
                            "detail": "available_at is later than the engine clock"})
            continue
        state.ingest_seq += 1
        ev = Event(**item.model_dump(), event_id=eid, payload_hash=h, ingest_seq=state.ingest_seq,
                   ingested_sim_time=now)
        state.add_event(ev)
        _register_entities(state, ev)
        ctx.audit("event", eid, ev.model_dump(mode="json"))
        new_events.append(ev)
        results.append({"source_event_id": item.source_event_id, "event_id": eid, "status": "accepted",
                        "detail": None})
    for ev in new_events:
        score_event(state, ev, ctx)
    touched = {r for ev in new_events for r in (ev.from_ref, ev.to_ref) if r}
    for link in relink(state, now):
        ctx.audit("link", link.link_id, link.model_dump(mode="json"))
        touched.update(x for x in (link.from_id, link.to_id) if x)
    for ev in new_events:
        if ev.event_type == "external_signal" and ev.to_ref and ev.to_ref.startswith("acct:"):
            open_case(state, ev, now, ctx)
    if new_events:
        # Events without parties (withdrawal state) or that relabel entities may change any case.
        everything = any(ev.event_type in GLOBAL_EVENT_TYPES for ev in new_events)
        reassess_open_cases(state, now, ctx, None if everything else touched)
        merge_cases(state, now, ctx)
    return results


GLOBAL_EVENT_TYPES = {"withdrawal_state", "address_label"}
RELAY_SHARE = 0.8   # a receiver that sent on at least this share of what it got is a pass-through


# ---------------------------------------------------------------- cases

def open_case(state: EngineState, signal: Event, now: datetime, ctx: EngineContext) -> Case:
    """A report on an account already reached by an open case joins that case; otherwise a new case."""
    open_cases = [c for c in state.cases.values() if c.status == "open"]
    case = next((c for c in open_cases if signal.to_ref in c.origins()), None) or next(
        (c for c in open_cases if signal.to_ref in c.scope_entities), None)
    if case is None:
        case = Case(case_id=state.next_id("CASE"), opened_at=now, trigger_event_id=signal.event_id,
                    origin_subject=signal.to_ref, origin_subjects=[signal.to_ref],
                    trigger_event_ids=[signal.event_id])
        state.cases[case.case_id] = case
    else:
        case.origin_subjects = case.origins() + ([signal.to_ref] if signal.to_ref not in case.origins() else [])
        case.trigger_event_ids = case.triggers() + [signal.event_id]
    ctx.audit("case", case.case_id, case.model_dump(mode="json"))
    return case


def live_case(state: EngineState, case_id: str) -> Case:
    """The open case a (possibly merged) case id now belongs to."""
    case = state.cases[case_id]
    while case.merged_into:
        case = state.cases[case.merged_into]
    return case


def merge_cases(state: EngineState, now: datetime, ctx: EngineContext) -> list[Case]:
    """Merge open cases that share a reported account, a pass-through account or an exchange customer.

    Sharing an end receiver (a shop paid by two unrelated networks) is not enough to merge.
    """
    survivors: list[Case] = []
    while True:
        open_cases = sorted((c for c in state.cases.values() if c.status == "open"),
                            key=lambda c: (c.opened_at, c.case_id))
        pair = None
        for i, a in enumerate(open_cases):
            key_a, scope_a = set(a.relay_entities) | set(a.origins()), set(a.scope_entities)
            for b in open_cases[i + 1:]:
                key_b = set(b.relay_entities) | set(b.origins())
                if key_a & key_b or scope_a.intersection(b.origins()) or set(b.scope_entities).intersection(a.origins()):
                    pair = (a, b)
                    break
            if pair:
                break
        if pair is None:
            return survivors
        a, b = pair
        a.origin_subjects = a.origins() + [o for o in b.origins() if o not in a.origins()]
        a.trigger_event_ids = a.triggers() + [t for t in b.triggers() if t not in a.triggers()]
        a.merged_case_ids = a.merged_case_ids + [b.case_id] + b.merged_case_ids
        b.status, b.merged_into = "closed", a.case_id
        ctx.audit("case", b.case_id, b.model_dump(mode="json"))
        assess_case(state, a, now, ctx, force=True)
        ctx.audit("case", a.case_id, a.model_dump(mode="json"))
        survivors.append(a)


def reassess_open_cases(state: EngineState, now: datetime, ctx: EngineContext,
                        touched: Optional[set[str]] = None) -> list[Assessment]:
    """Reassess open cases. With `touched`, only cases that are new or include a touched entity."""
    out = []
    for case in list(state.cases.values()):
        if touched is not None and case.latest_assessment_id is not None and not (
                case.origin_subject in touched or touched.intersection(case.scope_entities)):
            continue
        if case.status == "open":
            a = assess_case(state, case, now, ctx)
            if a:
                out.append(a)
    return out


def _rec_key(case_id: str, p: dict[str, Any]) -> str:
    # Case id is not part of the key: after a merge, the same advice from either case is one recommendation.
    sig = json.dumps({"i": p["institution"], "s": p["subject_id"], "a": p["action_type"],
                      "t": p["target_scope"]}, sort_keys=True, default=str)
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


def assess_case(state: EngineState, case: Case, now: datetime, ctx: EngineContext,
                force: bool = False) -> Optional[Assessment]:
    tr = tracing.trace_case(state, case, now, ctx.policy["trace"])
    proposal = recommend.build(state, case, tr, now, ctx.policy, ctx.model)
    content = json.dumps({"p": proposal["recommendations"], "e": [x.model_dump(mode="json") for x in proposal["evidence"]],
                          "m": proposal["missing_inputs"]}, sort_keys=True, default=str)
    h = hashlib.sha256(content.encode()).hexdigest()
    case.scope_entities = tr["scope_entities"]
    case.scope_events = tr["scope_events"]
    case.relay_entities = [a for a, n in tr["accounts"].items() if n["role"] == "receiver" and n["received_minor"]
                           and n["onward_minor"] >= RELAY_SHARE * n["received_minor"]] + [
        c for c, v in tr["customers"].items() if any(state.links[l].status == "verified" for l in v["links"])]
    if not force and state.case_content_hash.get(case.case_id) == h:
        return None
    state.case_content_hash[case.case_id] = h

    aid = state.next_id("ASMT")
    rec_ids: list[str] = []
    active_keys: set[str] = set()
    family = case.family()
    rank = {"acknowledged": 0, "delivered": 1}
    by_key: dict[str, Recommendation] = {}   # one recommendation per key; prefer acted-on, then oldest
    for r in state.recommendations.values():
        if r.case_id in family:
            k = r.target_scope.get("_key")
            cur = by_key.get(k)
            if cur is None or rank.get(r.status, 2) < rank.get(cur.status, 2):
                by_key[k] = r
    for p in proposal["recommendations"]:
        key = _rec_key(case.case_id, p)
        active_keys.add(key)
        existing = by_key.get(key)
        if existing and existing.status in ("delivered", "acknowledged"):
            rec_ids.append(existing.recommendation_id)
            continue
        rec = Recommendation(
            recommendation_id=state.next_id("REC"), assessment_id=aid, case_id=case.case_id,
            institution=p["institution"], subject_id=p["subject_id"], action_type=p["action_type"],
            target_scope={**p["target_scope"], "_key": key}, priority=p.get("priority"),
            rationale=p.get("rationale", []), evidence_refs=p.get("evidence_refs", []),
            policy_version=ctx.policy["policy_version"], created_at=now, expires_at=p.get("expires_at"))
        state.recommendations[rec.recommendation_id] = rec
        by_key[key] = rec
        ctx.audit("recommendation", rec.recommendation_id, rec.model_dump(mode="json"))
        rec_ids.append(rec.recommendation_id)
    # Supersede delivered (not yet decided) recommendations the new assessment no longer makes.
    for r in state.recommendations.values():
        if r.case_id in family and r.status == "delivered" and (
                r.target_scope.get("_key") not in active_keys or by_key.get(r.target_scope.get("_key")) is not r):
            r.status = "superseded"
            ctx.audit("recommendation", r.recommendation_id, r.model_dump(mode="json"))

    m = ctx.model
    a = Assessment(
        assessment_id=aid, case_id=case.case_id, subject_id=case.case_id, as_of=now,
        task_id=m.task_id if m else "unavailable",
        model=(m.info() | {"status": ctx.model_status}) if m else {"status": "unavailable"},
        risk_score=None, score_status="case_level_no_single_score",
        evidence=proposal["evidence"], context_benign=proposal["context_benign"],
        missing_inputs=proposal["missing_inputs"], uncertainty=proposal["uncertainty"],
        recommendation_ids=rec_ids, policy_version=ctx.policy["policy_version"])
    state.assessments[aid] = a
    case.latest_assessment_id = aid
    ctx.audit("assessment", aid, a.model_dump(mode="json"))
    return a


# ---------------------------------------------------------------- subject assessment API

def assess_subject(state: EngineState, subject_id: str, now: datetime, ctx: EngineContext,
                   institution: Optional[str]) -> Assessment:
    if not ctx.model_ready:
        raise EngineUnavailable("model unavailable; existing institution controls apply")
    t0 = time.perf_counter()
    open_cases = [c for c in state.cases.values() if c.status == "open"]
    case = next((c for c in open_cases if subject_id in c.scope_events or subject_id in c.scope_entities), None)
    evidence: list[EvidenceItem] = []
    risk, status, task = None, "out_of_scope", ctx.model.task_id
    ev = state.events.get(subject_id)
    if ev is not None and ev.event_type == "bank_transfer":
        pred = state.predictions.get(subject_id)
        if pred is None or pred.score_status != "computed":
            pred = score_event(state, ev, ctx)
        risk, status = pred.score, pred.score_status
        for c in pred.contributions:
            evidence.append(EvidenceItem(kind="model_contribution",
                                         text=f"{c.get('label') or c['feature']}: {c['value']} (contribution {c['contribution']})",
                                         refs=[subject_id]))
    elif ev is None and not subject_id.startswith("wd:") and subject_id not in state.entities:
        raise KeyError(subject_id)
    rec_ids: list[str] = []
    if case:
        if case.latest_assessment_id is None:
            assess_case(state, case, now, ctx, force=True)
        family = case.family()
        rec_ids = [r.recommendation_id for r in state.recommendations.values()
                   if r.case_id in family and r.status in ("delivered", "acknowledged")
                   and (institution is None or r.institution == institution)]
        evidence.append(EvidenceItem(kind="case", text=f"Part of {case.case_id}", refs=[case.case_id]))
    else:
        evidence.append(EvidenceItem(kind="policy", text="No recommendation from this layer: existing controls only"))
    a = Assessment(assessment_id=state.next_id("ASMT"), case_id=case.case_id if case else None,
                   subject_id=subject_id, as_of=now, task_id=task,
                   model=ctx.model.info() | {"status": ctx.model_status}, risk_score=risk, score_status=status,
                   evidence=evidence, recommendation_ids=rec_ids, policy_version=ctx.policy["policy_version"])
    state.assessments[a.assessment_id] = a
    ctx.audit("assessment", a.assessment_id, a.model_dump(mode="json"))
    ctx.latencies_ms.append((time.perf_counter() - t0) * 1000)
    return a
