"""ModelAdapter: the single interface every model (Rules / LightGBM / GNN) implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class ModelUnavailable(RuntimeError):
    pass


class ModelAdapter(ABC):
    model_id: str
    arm: str
    version: str
    task_id: str
    feature_version: str
    score_semantics: str
    source: dict[str, Any]

    @abstractmethod
    def required_features(self) -> list[str]: ...

    @abstractmethod
    def score(self, rows: list[dict[str, Optional[float]]]) -> list[float]: ...

    def explain(self, row: dict[str, Optional[float]]) -> list[dict[str, Any]]:
        return []

    def info(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "arm": self.arm, "version": self.version,
            "task_id": self.task_id, "feature_version": self.feature_version,
            "score_semantics": self.score_semantics, "source": self.source,
        }
