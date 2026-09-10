"""
Global session domain entities — pure Python, no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalDimScore:
    """Decoded per-key score data from the global session hash."""
    key: str
    pos: float = 0.0
    neg: float = 0.0
    conf: float = 0.0
    cnt: int = 0
    last_ts: int = 0


@dataclass(frozen=True)
class InfluenceWeights:
    """
    The three additive influence fractions that sum to 1.0.
    Computed by the aggregator per dimension per feed request.
    """
    persistent: float       # minimum 0.54
    global_session: float   # maximum 0.15
    module_session: float   # maximum 0.31
