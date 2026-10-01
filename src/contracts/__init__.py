"""Pydantic contracts shared by engine, simulator and API (schema v0.1).

Money is always integer minor units plus an asset id. Never floats for ledger math.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "0.1"
ASSET_SCALE = {"THB": 2, "USDT": 6}

EventType = Literal[
    "bank_transfer",
    "exchange_deposit",
    "exchange_trade",
    "withdrawal_request",
    "withdrawal_state",
    "chain_transfer",
    "external_signal",
    "address_label",
]

LinkStatus = Literal["verified", "candidate", "unresolved", "requested"]

RecommendationType = Literal[
    "EXISTING_CONTROLS_ONLY",
    "REVIEW_PRIORITY",
    "REQUEST_INFORMATION",
    "INSUFFICIENT_EVIDENCE",
    "RECOMMEND_RESTRICTION_REVIEW",
    "RECOMMEND_RELEASE_REVIEW",
]

DecisionAction = Literal[
    "acknowledge",
    "restrict_amount",
    "release_restriction",
    "retain_restriction",
    "request_information",
    "hold_withdrawal",
    "release_withdrawal",
    "no_action",
]


class EventIn(BaseModel):
    """An event as a simulated institution submits it to the engine."""

    source_org: str
    source_event_id: str
    event_type: EventType
    occurred_at: datetime
    available_at: datetime
    asset: Optional[str] = None
    amount_minor: Optional[int] = Field(default=None, ge=0)
    from_ref: Optional[str] = None
    to_ref: Optional[str] = None
    reference_id: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "EventIn":
        if self.occurred_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("timestamps must carry an explicit timezone")
        if self.available_at < self.occurred_at:
            raise ValueError("available_at must be >= occurred_at")
        if self.amount_minor is not None and self.asset not in ASSET_SCALE:
            raise ValueError(f"unknown asset {self.asset!r}; allowed {sorted(ASSET_SCALE)}")
        return self


class Event(EventIn):
    event_id: str
    payload_hash: str
    ingest_seq: int
    ingested_sim_time: datetime


class Entity(BaseModel):
    entity_id: str
    entity_type: Literal["bank_account", "exchange_customer", "chain_address"]
    institution: Optional[str] = None
    display: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    first_known_at: datetime


class Link(BaseModel):
    link_id: str
    relation: str
    from_id: str
    to_id: str
    status: LinkStatus
    method: str
    evidence_event_ids: list[str]
    known_at: datetime
    candidates: list[str] = Field(default_factory=list)
    note: Optional[str] = None


class Prediction(BaseModel):
    event_id: str
    as_of: datetime
    task_id: str
    model_id: str
    model_version: str
    feature_version: str
    score: Optional[float]
    score_semantics: str
    score_status: Literal["computed", "out_of_scope", "unavailable"]
    features: dict[str, Optional[float]] = Field(default_factory=dict)
    contributions: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    kind: str
    text: str
    refs: list[str] = Field(default_factory=list)
    known_at: Optional[datetime] = None


class Recommendation(BaseModel):
    recommendation_id: str
    assessment_id: str
    case_id: str
    institution: str
    subject_id: str
    action_type: RecommendationType
    target_scope: dict[str, Any] = Field(default_factory=dict)
    priority: Optional[str] = None
    rationale: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    policy_version: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    status: Literal["delivered", "acknowledged", "superseded", "expired"] = "delivered"
    authority_to_act: bool = False


class Assessment(BaseModel):
    assessment_id: str
    case_id: Optional[str]
    subject_id: str
    as_of: datetime
    task_id: str
    model: dict[str, Any]
    risk_score: Optional[float]
    score_status: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    context_benign: list[EvidenceItem] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)
    policy_version: str


class Case(BaseModel):
    case_id: str
    opened_at: datetime
    trigger_event_id: str
    origin_subject: str
    scope_entities: list[str] = Field(default_factory=list)
    scope_events: list[str] = Field(default_factory=list)
    status: Literal["open", "closed"] = "open"
    latest_assessment_id: Optional[str] = None


class AssessmentRequest(BaseModel):
    subject_id: str
    as_of: Optional[datetime] = None


class DecisionIn(BaseModel):
    recommendation_id: str
    actor_org: str
    actor_id: str
    action: DecisionAction
    target_scope: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3)
    expected_state_version: int
    idempotency_key: str = Field(min_length=8)


class Decision(DecisionIn):
    decision_id: str
    case_id: str
    recorded_at: datetime
    outcome: Literal["acknowledged", "rejected"]
    outcome_detail: str
    restriction_id: Optional[str] = None


class EvidenceSubmissionIn(BaseModel):
    restriction_id: str
    fixture_ref: str
    idempotency_key: str = Field(min_length=8)


class EvidenceSubmission(BaseModel):
    submission_id: str
    case_id: str
    account_id: str
    restriction_id: str
    fixture_ref: str
    fixture_hash: str
    submitted_at: datetime
    review_state: Literal["review_pending", "reviewed"] = "review_pending"
    consistency: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class Restriction(BaseModel):
    restriction_id: str
    account_id: str
    institution: str
    asset: str
    amount_minor: int
    status: Literal["active", "released"] = "active"
    review_state: Literal[
        "restricted", "review_pending", "more_info_requested", "retained", "released"
    ] = "restricted"
    reason_category: str
    decision_id: str
    case_id: str
    created_at: datetime
    updated_at: datetime
    history: list[dict[str, Any]] = Field(default_factory=list)


class RunCreate(BaseModel):
    scenario: str = "merchant_300"
    mode: Literal["live", "recorded"] = "live"
    recording: Optional[str] = None
    speed: float = Field(default=30.0, gt=0, le=600)
