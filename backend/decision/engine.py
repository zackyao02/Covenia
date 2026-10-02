from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .jev_client import ask_jev, typesafe_configured
from .policy import (
    EMOTION_WORSENING_THRESHOLD,
    NEEDS_HUMAN_THRESHOLD,
    NEXT_ACTION_THRESHOLD,
    clamp_probability,
    fallback_next_action,
)
from .questions import jev_questions


_CACHE: dict[str, dict[str, Any]] = {}
AUDIT_LOG: list[dict[str, Any]] = []


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _state_version(case_id: str, state: dict[str, Any], case_input: dict[str, Any], deadline: dict[str, Any]) -> str:
    relevant = {
        "case_id": case_id,
        "case_status": state.get("case_status"),
        "evidence_status": state.get("evidence_status"),
        "experience_risk": state.get("experience_risk"),
        "current_scope": state.get("current_scope"),
        "active_commitments": state.get("active_commitments", []),
        "open_obligation": state.get("open_obligation"),
        "conversation_count": len(case_input.get("conversation", [])),
        "latest_message": (case_input.get("conversation") or [{}])[-1].get("message_id"),
        "deadline": deadline,
    }
    return hashlib.sha1(_canonical(relevant).encode("utf-8")).hexdigest()[:12]


def _answer(raw: dict[str, Any] | None, question_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    answers = raw.get("answers", raw)
    if not isinstance(answers, dict):
        return {}
    value = answers.get(question_id, {})
    return value if isinstance(value, dict) else {"value": value}


def _probability(answer: dict[str, Any], yes_choice: str = "YES") -> float:
    for key in ("probability", "noul", "score", "confidence"):
        if key in answer:
            return clamp_probability(answer[key])
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict):
        return clamp_probability(probabilities.get(yes_choice))
    return 0.0


def _choice(answer: dict[str, Any], default: str) -> tuple[str, float]:
    raw_choice = answer.get("choice") or answer.get("label") or answer.get("value") or default
    choice = str(raw_choice)
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict):
        return choice, clamp_probability(probabilities.get(choice), default=0.0)
    return choice, _probability(answer, yes_choice=choice)


def _deterministic_signals(state: dict[str, Any], case_input: dict[str, Any], deadline: dict[str, Any]) -> dict[str, Any]:
    conversation_count = len(case_input.get("conversation", []))
    evidence_status = state.get("evidence_status", "UNKNOWN")
    has_open_obligation = bool(state.get("open_obligation") or state.get("active_commitments"))
    promise_overdue = deadline.get("status") in {"OVERDUE", "ESCALATED"} or state.get("case_status") == "AT_RISK"
    repeated_contact = conversation_count >= 3
    needs_human_by_rule = evidence_status == "NEED_HUMAN_REVIEW" or state.get("current_scope", {}).get("issue_type") == "ADVERSE_REACTION"
    return {
        "promise_overdue": promise_overdue,
        "repeated_contact": repeated_contact,
        "conversation_count": conversation_count,
        "evidence_status": evidence_status,
        "has_open_obligation": has_open_obligation,
        "needs_human_by_rule": needs_human_by_rule,
    }


def _jev_state(
    case_id: str,
    state: dict[str, Any],
    case_input: dict[str, Any],
    deadline: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, Any]:
    messages = case_input.get("conversation", [])[-6:]
    return {
        "case_id": case_id,
        "customer_state_version": _state_version(case_id, state, case_input, deadline),
        "case_status": state.get("case_status"),
        "evidence_status": state.get("evidence_status"),
        "experience_risk": state.get("experience_risk"),
        "current_scope": state.get("current_scope"),
        "deadline": deadline,
        "deterministic_signals": signals,
        "recent_messages": [
            {
                "speaker": message.get("speaker"),
                "text": message.get("text"),
                "timestamp": message.get("timestamp"),
            }
            for message in messages
        ],
    }


def decision_advisory_for(
    case_id: str,
    state: dict[str, Any],
    case_input: dict[str, Any],
    deadline: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    """Return optional JEV-backed advisory without changing BC core rules."""

    version = _state_version(case_id, state, case_input, deadline)
    if version in _CACHE:
        return _CACHE[version]

    signals = _deterministic_signals(state, case_input, deadline)
    jev_state = _jev_state(case_id, state, case_input, deadline, signals)
    questions = jev_questions()
    transport = ask_jev(jev_state, questions)
    raw = transport.get("raw") if transport.get("ok") else None

    emotion_answer = _answer(raw, "emotion_worsening")
    human_answer = _answer(raw, "needs_human")
    action_answer = _answer(raw, "next_action")

    fallback_emotion_probability = 0.74 if signals["repeated_contact"] and signals["has_open_obligation"] else 0.42
    emotion_probability = _probability(emotion_answer, "YES") if transport.get("ok") else fallback_emotion_probability
    emotion_worsening = emotion_probability >= EMOTION_WORSENING_THRESHOLD

    fallback_human_probability = 0.82 if signals["needs_human_by_rule"] else 0.34
    human_probability = _probability(human_answer, "YES") if transport.get("ok") else fallback_human_probability
    needs_human = signals["needs_human_by_rule"] or human_probability >= NEEDS_HUMAN_THRESHOLD

    fallback_action = fallback_next_action(
        needs_human=needs_human,
        has_open_obligation=signals["has_open_obligation"],
        evidence_status=signals["evidence_status"],
    )
    provider_action, provider_action_probability = _choice(action_answer, fallback_action)
    if transport.get("ok") and provider_action_probability >= NEXT_ACTION_THRESHOLD:
        next_action = provider_action
        next_action_probability = provider_action_probability
    else:
        next_action = fallback_action
        next_action_probability = provider_action_probability if transport.get("ok") else 0.0

    source = "JEV" if transport.get("ok") else "RULE_FALLBACK"
    assessment_id = f"JEV_{case_id}_{version}"
    jev_call = {
        "configured": typesafe_configured(),
        "attempted": bool(transport.get("attempted") or transport.get("ok")),
        "succeeded": bool(transport.get("ok")),
        "fallback_used": not bool(transport.get("ok")),
        "error_code": (transport.get("error") or {}).get("code"),
    }
    audit = {
        "assessment_id": assessment_id,
        "case_id": case_id,
        "customer_state_version": version,
        "source": source,
        "jev_call": jev_call,
        "model_version": transport.get("model_version"),
        "questions": [question["id"] for question in questions],
        "thresholds": {
            "emotion_worsening": EMOTION_WORSENING_THRESHOLD,
            "needs_human": NEEDS_HUMAN_THRESHOLD,
            "next_action": NEXT_ACTION_THRESHOLD,
        },
        "final_decision": {
            "emotion_worsening": emotion_worsening,
            "needs_human": needs_human,
            "next_action": next_action,
        },
        "provider_error": transport.get("error"),
        "latency_ms": transport.get("latency_ms", 0),
        "created_at": now,
    }
    AUDIT_LOG.append(audit)

    advisory = {
        "assessment_id": assessment_id,
        "customer_state_version": version,
        "source": source,
        "status": "READY" if transport.get("ok") else "FALLBACK",
        "configured": typesafe_configured(),
        "jev_call": jev_call,
        "emotion": {
            "trend": "WORSENING" if emotion_worsening else "STABLE",
            "probability": round(emotion_probability, 4),
            "threshold": EMOTION_WORSENING_THRESHOLD,
            "source": source,
        },
        "human_escalation": {
            "required": needs_human,
            "probability": round(human_probability, 4),
            "threshold": NEEDS_HUMAN_THRESHOLD,
            "source": "RULE" if signals["needs_human_by_rule"] else source,
        },
        "next_best_action": {
            "recommended": next_action,
            "probability": round(next_action_probability, 4),
            "threshold": NEXT_ACTION_THRESHOLD,
            "source": source if transport.get("ok") and provider_action_probability >= NEXT_ACTION_THRESHOLD else "RULE_FALLBACK",
        },
        "deterministic_signals": signals,
        "audit": audit,
    }
    _CACHE[version] = advisory
    return advisory
