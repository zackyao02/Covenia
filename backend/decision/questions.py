from __future__ import annotations

from typing import Any


def jev_questions() -> list[dict[str, Any]]:
    """Typed-choice questions owned by Covenia, not by the provider."""

    return [
        {
            "id": "emotion_worsening",
            "type": "noul",
            "instructions": "Does the consumer's emotion appear to be worsening compared with the start of this service interaction?",
            "criteria": {
                "true": "The consumer shows increasing frustration, urgency, distrust, or repeated effort.",
                "false": "The consumer is stable, calmer, or only asking a routine status question.",
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
