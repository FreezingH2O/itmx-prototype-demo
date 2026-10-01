"""GNN adapter slot (G2). Not implemented yet.

To plug in the notebook03 GNN: install torch + torch_geometric in the env, rebuild the
bounded temporal subgraph for each target exactly as notebook03 does (same fanout, same
target/reverse-edge masking, train-fitted normalization), load weights, and return edge
scores. Until then the registry refuses to load a GNN arm instead of faking scores.
"""
from __future__ import annotations

from src.models.base import ModelUnavailable


class GNNAdapter:
    def __init__(self, *args, **kwargs):
        raise ModelUnavailable(
            "GNN adapter is a slot only. Use the LightGBM/G1 arm for live inference, or implement "
            "src/models/gnn.py following PLUGIN.md.")
