from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime
from typing import Any

from .jev_client import ask_jev, setting, typesafe_configured
from .privacy import mask_model_text
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
_CACHE_TIMES: dict[str, float] = {}
ALLOWED_ACTIONS = {"CHECK_REPLACEMENT", "HUMAN_ESCALATION", "CONTINUE_TROUBLESHOOTING", "REQUEST_EVIDENCE"}


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
        "messages": case_input.get("conversation", []),
        "deadline": deadline,
        "questions": jev_questions(),
        "model": setting("TYPESAFE_MODEL_VERSION", "jev-latest"),
        "configured": typesafe_configured(),
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


def _valid_probability(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def _valid_answers(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    for question in ("emotion_worsening", "needs_human"):
        answer = _answer(raw, question)
        if answer.get("type") != "noul" or not _valid_probability(answer.get("noul")):
            return False
    answer = _answer(raw, "next_action")
    distribution = answer.get("probabilities")
    if answer.get("type") != "choice" or answer.get("choice") not in ALLOWED_ACTIONS or not isinstance(distribution, dict):
        return False
    return (set(distribution) == ALLOWED_ACTIONS
            and all(_valid_probability(p) for p in distribution.values())
            and abs(sum(distribution.values()) - 1) < 0.01
            and distribution[answer["choice"]] >= max(distribution.values()) - 1e-6)


def _deterministic_signals(state: dict[str, Any], case_input: dict[str, Any], deadline: dict[str, Any]) -> dict[str, Any]:
    conversation_count = len(case_input.get("conversation", []))
    evidence_status = state.get("evidence_status", "UNKNOWN")
    has_open_obligation = bool(state.get("open_obligation") or state.get("active_commitments"))
    promise_overdue = deadline.get("status") in {"OVERDUE", "ESCALATED"} or state.get("case_status") == "AT_RISK"
    repeated_contact = any(
        any(cue in message.get("text", "") for cue in ("上次", "再次联系", "又来问", "问过", "第三次", "第二次"))
        for message in case_input.get("conversation", [])
        if str(message.get("speaker", "")).upper() in {"CONSUMER", "CUSTOMER"}
    )
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
    consumer_messages = [
        message for message in case_input.get("conversation", [])
        if str(message.get("speaker", "")).upper() in {"CONSUMER", "CUSTOMER"}
    ]
    masked_messages = []
    pii_count = 0

    def mask_customer_text(message: dict[str, Any] | None) -> str | None:
        nonlocal pii_count
        if not message:
            return None
        masked, count = mask_model_text(message.get("text"))
        pii_count += count
        return masked

    for message in messages:
        masked, count = mask_model_text(message.get("text"))
        pii_count += count
        masked_messages.append({"speaker": message.get("speaker"), "text": masked, "timestamp": message.get("timestamp")})
    return {
        "case_id": case_id,
        "customer_state_version": _state_version(case_id, state, case_input, deadline),
        "case_status": state.get("case_status"),
        "evidence_status": state.get("evidence_status"),
        "experience_risk": state.get("experience_risk"),
        "current_scope": {key: state.get("current_scope", {}).get(key) for key in ("sku_id", "issue_type")},
        "deadline": deadline,
        "deterministic_signals": signals,
        "recent_messages": masked_messages,
        "consumer_emotion_comparison": {
            "previous_consumer_message": mask_customer_text(consumer_messages[-2]) if len(consumer_messages) >= 2 else None,
            "latest_consumer_message": mask_customer_text(consumer_messages[-1]) if consumer_messages else None,
        },
        "pii_masked_count": pii_count,
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
    ttl = 300 if _CACHE.get(version, {}).get("status") == "READY" else 15
    if version in _CACHE and time.monotonic() - _CACHE_TIMES.get(version, 0) < ttl:
        return _CACHE[version]

    signals = _deterministic_signals(state, case_input, deadline)
    jev_state = _jev_state(case_id, state, case_input, deadline, signals)
    questions = jev_questions()
    transport = ask_jev(jev_state, questions)
    if transport.get("ok") and not _valid_answers(transport.get("raw")):
        transport = {**transport, "ok": False, "error": {"code": "TYPESAFE_OUTPUT_INVALID", "message": "The typed provider answers are incomplete or invalid."}}
    raw = transport.get("raw") if transport.get("ok") else None

    emotion_answer = _answer(raw, "emotion_worsening")
    human_answer = _answer(raw, "needs_human")
    action_answer = _answer(raw, "next_action")

    emotion_probability = _probability(emotion_answer, "YES") if transport.get("ok") else None
    consumer_messages = [item for item in case_input.get("conversation", []) if str(item.get("speaker", "")).upper() in {"CONSUMER", "CUSTOMER"}]
    emotion_trend = "UNKNOWN"
    if emotion_probability is not None and len(consumer_messages) >= 2:
        if emotion_probability >= EMOTION_WORSENING_THRESHOLD:
            emotion_trend = "WORSENING"
        elif emotion_probability <= 1 - EMOTION_WORSENING_THRESHOLD:
            emotion_trend = "STABLE"
    emotion_worsening = emotion_trend == "WORSENING"

    human_probability = _probability(human_answer, "YES") if transport.get("ok") else None
    needs_human = signals["needs_human_by_rule"] or (human_probability is not None and human_probability >= NEEDS_HUMAN_THRESHOLD)

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
        next_action_probability = provider_action_probability if transport.get("ok") else None

    # Advisory never recommends re-asking valid evidence or bypassing safety review.
    if signals["needs_human_by_rule"]:
        next_action = "HUMAN_ESCALATION"
    elif next_action == "REQUEST_EVIDENCE" and signals["evidence_status"] == "VALID":
        next_action = fallback_action
    action_from_model = bool(transport.get("ok") and next_action == provider_action and provider_action_probability >= NEXT_ACTION_THRESHOLD and not signals["needs_human_by_rule"])

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
        "pii_masked_count": jev_state["pii_masked_count"],
        "thresholds_validated": False,
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
            "trend": emotion_trend,
            "probability": round(emotion_probability, 4) if emotion_probability is not None else None,
            "threshold": EMOTION_WORSENING_THRESHOLD,
            "source": source,
        },
        "human_escalation": {
            "required": needs_human,
            "probability": round(human_probability, 4) if human_probability is not None else None,
            "threshold": NEEDS_HUMAN_THRESHOLD,
            "source": "RULE" if signals["needs_human_by_rule"] else source,
        },
        "next_best_action": {
            "recommended": next_action,
            "probability": round(next_action_probability, 4) if action_from_model and next_action_probability is not None else None,
            "threshold": NEXT_ACTION_THRESHOLD,
            "source": "JEV" if action_from_model else "RULE_FALLBACK",
        },
        "deterministic_signals": signals,
        "audit": audit,
    }
    _CACHE[version] = advisory
    _CACHE_TIMES[version] = time.monotonic()
    return advisory
