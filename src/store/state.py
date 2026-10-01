"""Run state. Engine state and simulator state are separate objects.

Engine code receives only EngineState; simulated institutions own SimState.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from src.contracts import (
    Assessment,
    Case,
    Decision,
    Entity,
    Event,
    EvidenceSubmission,
    Link,
    Prediction,
    Recommendation,
    Restriction,
)


class EngineState(BaseModel):
    events: dict[str, Event] = Field(default_factory=dict)
    entities: dict[str, Entity] = Field(default_factory=dict)
    links: dict[str, Link] = Field(default_factory=dict)
    predictions: dict[str, Prediction] = Field(default_factory=dict)
    cases: dict[str, Case] = Field(default_factory=dict)
    assessments: dict[str, Assessment] = Field(default_factory=dict)
    recommendations: dict[str, Recommendation] = Field(default_factory=dict)
    decisions: dict[str, Decision] = Field(default_factory=dict)
    evidence_submissions: dict[str, EvidenceSubmission] = Field(default_factory=dict)
    idempotency: dict[str, dict[str, Any]] = Field(default_factory=dict)
    case_content_hash: dict[str, str] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)
    ingest_seq: int = 0

    def next_id(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}-{n:04d}"


class BankAccount(BaseModel):
    account_id: str
    institution: str
    display: str
    holder_kind: Literal["person", "merchant", "exchange_settlement"]
    holder_name: str
    balance_minor: int
    asset: str = "THB"
    version: int = 1


class ExchangeCustomer(BaseModel):
    customer_id: str
    display: str
    balances: dict[str, int] = Field(default_factory=dict)
    version: int = 1


class Withdrawal(BaseModel):
    withdrawal_id: str
    customer_id: str
    asset: str
    amount_minor: int
    destination: str
    chain: str
    requested_at: datetime
    controllable_until: datetime
    state: Literal["pending", "held_for_review", "broadcast"] = "pending"
    tx_hash: Optional[str] = None
    version: int = 1


class Delivery(BaseModel):
    """A scenario item that a simulated client delivers to the engine at `due`."""

    due: datetime
    client: str
    event: dict[str, Any]
    delivered: bool = False


class ClientLogEntry(BaseModel):
    seq: int
    sim_time: datetime
    client: str
    event_id: Optional[str] = None
    subject_id: Optional[str] = None
    summary: str
    status: str
    assessment_id: Optional[str] = None
    recommendation_ids: list[str] = Field(default_factory=list)


class ApiLogEntry(BaseModel):
    seq: int
    sim_time: datetime
    client: str
    method: str
    path: str
    status_code: int
    request: Any = None
    response: Any = None
    latency_ms: float


class Clock(BaseModel):
    start: datetime
    now: datetime
    end: datetime
    playing: bool = False
    speed: float = 30.0


class SimState(BaseModel):
    clock: Clock
    accounts: dict[str, BankAccount] = Field(default_factory=dict)
    customers: dict[str, ExchangeCustomer] = Field(default_factory=dict)
    withdrawals: dict[str, Withdrawal] = Field(default_factory=dict)
    restrictions: dict[str, Restriction] = Field(default_factory=dict)
    deliveries: list[Delivery] = Field(default_factory=list)
    client_log: list[ClientLogEntry] = Field(default_factory=list)
    api_log: list[ApiLogEntry] = Field(default_factory=list)
    notices: list[dict[str, Any]] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)
    merchant_account_id: str
    case_hint: Optional[str] = None

    def next_id(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}-{n:04d}"


class RunState(BaseModel):
    run_id: str
    scenario: str
    mode: Literal["live", "recorded"]
    epoch: int = 1
    version: int = 0
    created_at: datetime
    faults: dict[str, bool] = Field(default_factory=lambda: {"model_unavailable": False})
    engine: EngineState
    sim: SimState
    model_info: dict[str, Any] = Field(default_factory=dict)
    recording: Optional[str] = None
