"""Covenia decision layer.

This package keeps TypeSafe/JEV integration behind a stable Covenia schema so
BC core APIs and React cards do not consume provider-specific responses.
"""

from .engine import decision_advisory_for

__all__ = ["decision_advisory_for"]
