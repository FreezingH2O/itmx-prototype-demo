"""LightGBM adapter: loads a Booster saved by the experiment (model.txt)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from src.models.base import ModelAdapter, ModelUnavailable


class LightGBMAdapter(ModelAdapter):
    def __init__(self, model_dir: Path, spec: dict[str, Any], source: dict[str, Any]):
        try:
            import lightgbm as lgb
        except Exception as exc:  # pragma: no cover
            raise ModelUnavailable(f"lightgbm import failed: {exc}") from exc
        path = model_dir / spec.get("model_file", "model.txt")
        if not path.exists():
            raise ModelUnavailable(f"model file not found: {path}")
        self.booster = lgb.Booster(model_file=str(path))
        self.features = list(spec.get("feature_names") or self.booster.feature_name())
        if self.features != self.booster.feature_name():
            raise ModelUnavailable("adapter.json feature_names differ from the booster's feature order")
        self.model_id = spec.get("model_id", model_dir.name)
        self.arm = spec.get("arm", model_dir.name)
        self.version = str(spec.get("version", "unknown"))
        self.task_id = spec["task_id"]
        self.feature_version = spec["feature_version"]
        self.score_semantics = spec.get(
            "score_semantics", "LightGBM output; ranking score, not calibrated probability")
        self.source = source

    def required_features(self):
        return self.features

    def _matrix(self, rows):
        return np.array([[np.nan if r.get(f) is None else r[f] for f in self.features] for r in rows], dtype=float)

    def score(self, rows):
        return [float(x) for x in self.booster.predict(self._matrix(rows))]

    def explain(self, row):
        contrib = self.booster.predict(self._matrix([row]), pred_contrib=True)[0][:-1]
        order = np.argsort(-np.abs(contrib))[:5]
        return [{"feature": self.features[i], "value": row.get(self.features[i]),
                 "contribution": round(float(contrib[i]), 6), "rule": None, "label": "SHAP (tree) contribution"}
                for i in order]
