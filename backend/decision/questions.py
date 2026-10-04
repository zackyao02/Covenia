from __future__ import annotations

from typing import Any


def jev_questions() -> list[dict[str, Any]]:
    """Typed-choice questions owned by Covenia, not by the provider."""

    return [
        {
            "id": "emotion_worsening",
            "type": "noul",
            "instructions": "Compare `consumer_emotion_comparison.previous_consumer_message` with `consumer_emotion_comparison.latest_consumer_message`. Is the latest consumer message explicitly more frustrated, urgent, or distrustful than the previous consumer message? Judge only the consumer's wording. Ignore agent messages, risk scores, repeat contact, evidence status, and overdue promises. If either message is missing or the wording does not show a clear change, answer false.",
            "criteria": {
                "true": "The latest consumer message clearly increases expressed frustration, urgency, or distrust compared with the previous consumer message.",
                "false": "There is no clear increase: the consumer is stable, calmer, missing a comparison message, or asking a routine follow-up.",
            },
        },
        {
            "id": "needs_human",
            "type": "noul",
            "instructions": "Does this case require human review before the next customer-facing action?",
            "criteria": {
                "true": "Human review is needed because of safety, adverse reaction, unclear evidence, conflict, or escalation risk.",
                "false": "The next action can be handled by normal service workflow or deterministic rules.",
            },
        },
        {
            "id": "next_action",
            "type": "choice",
            "instructions": "Choose the safest next best action for the current customer state.",
            "criteria": {
                "CHECK_REPLACEMENT": "Check replacement, reshipment, or fulfillment progress and proactively update the customer.",
                "HUMAN_ESCALATION": "Escalate to human review before sending the next customer-facing answer.",
                "CONTINUE_TROUBLESHOOTING": "Continue normal service handling without escalation.",
                "REQUEST_EVIDENCE": "Ask only for missing evidence that is necessary for the current issue scope.",
            },
        },
    ]
