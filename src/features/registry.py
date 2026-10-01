"""Feature builder registry keyed by feature_version.

PLUG-IN POINT: when the experiment bundle declares a feature_version (in
feature_manifest.json), register a builder for it here that reproduces the notebook's
features exactly. The parity check then verifies the engine matches saved predictions.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from src.contracts import Event
from src.features import sim_local

Builder = Callable[[Iterable[Event], Event], dict[str, Optional[float]]]

BUILDERS: dict[str, tuple[Builder, list[str]]] = {
    sim_local.FEATURE_VERSION: (sim_local.build, sim_local.FEATURE_NAMES),
}


def get_builder(feature_version: str) -> tuple[Builder, list[str]]:
    if feature_version not in BUILDERS:
        raise KeyError(
            f"No feature builder registered for {feature_version!r}. "
            "Implement it in src/features/ and register it in src/features/registry.py."
        )
    return BUILDERS[feature_version]
