from __future__ import annotations

EMOTION_WORSENING_THRESHOLD = 0.70
NEEDS_HUMAN_THRESHOLD = 0.65
NEXT_ACTION_THRESHOLD = 0.60


def clamp_probability(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def risk_level_from_score(score: int) -> str:
    if score >= 120:
        return "CRITICAL"
    if score >= 92:
        return "HIGH"
    if score >= 64:
        return "MEDIUM"
    return "LOW"


def fallback_next_action(*, needs_human: bool, has_open_obligation: bool, evidence_status: str) -> str:
    if needs_human:
        return "HUMAN_ESCALATION"
    if evidence_status in {"MISMATCHED", "NEED_HUMAN_REVIEW"}:
        return "REQUEST_EVIDENCE"
    if has_open_obligation:
        return "CHECK_REPLACEMENT"
    return "CONTINUE_TROUBLESHOOTING"
