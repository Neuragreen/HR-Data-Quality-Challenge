"""Deterministic, standard-library-only HR reconciliation components.

Raw observations are retained separately from semantic values. Identity scores are
evidence scores, not calibrated probabilities or permission to change a source.
"""

from .models import MatchResult, Snapshot

__all__ = ["Snapshot", "MatchResult"]
