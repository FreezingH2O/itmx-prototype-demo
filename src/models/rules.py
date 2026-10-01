"""R0 rules adapter. The default config is hand-set for the demo, not fitted.

A fitted R0 from the experiment can replace it via models/<arm>/rules.json in a bundle.
"""
from __future__ import annotations

import operator
from typing import Any, Optional

from src.models.base import ModelAdapter

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}


class RulesAdapter(ModelAdapter):
    def __init__(self, config: dict[str, Any], source: dict[str, Any]):
        self.model_id = config.get("model_id", "R0-demo")
        self.arm = config.get("arm", "R0")
        self.version = str(config.get("version", "0"))
        self.task_id = config.get("task_id", "sim_transaction_risk_demo")
        self.feature_version = config["feature_version"]
        self.score_semantics = config.get(
            "score_semantics", "sum of fired rule weights in [0,1]; ranking score, not a probability")
        self.components = config["components"]
        self.source = source

    def required_features(self) -> list[str]:
        return sorted({c["feature"] for c in self.components})

    def _fired(self, row: dict[str, Optional[float]]) -> list[dict[str, Any]]:
        out = []
        for c in self.components:
            v = row.get(c["feature"])
            if v is not None and _OPS[c["op"]](v, c["value"]):
                out.append({"feature": c["feature"], "value": v, "contribution": c["weight"],
                            "rule": f'{c["feature"]} {c["op"]} {c["value"]}', "label": c.get("label")})
        return out

    def score(self, rows):
        return [min(1.0, round(sum(f["contribution"] for f in self._fired(r)), 6)) for r in rows]

    def explain(self, row):
        return self._fired(row)
