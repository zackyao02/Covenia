"""The single deterministic firewall entry point for server-owned facts."""

from covenia_b.rules.engine import (
    RULE_VERSION,
    ProhibitedActionError,
    RuleEvaluation,
    evaluate_decision,
)

__all__ = ["RULE_VERSION", "ProhibitedActionError", "RuleEvaluation", "evaluate_decision"]
