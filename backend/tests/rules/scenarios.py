"""Explicit server-state examples; no model, files, or labelled case fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from covenia_b.domain.types import AccountabilityState, PreparedAction, Scope


def make_state(
    *,
    evidence_status: str = "VALID",
    issue_type: str = "PACKAGE_DAMAGE",
    prohibited_actions: tuple[str, ...] = (),
) -> AccountabilityState:
    return AccountabilityState.model_validate(
        {
            "case_id": "synthetic-rule-case",
            "case_status": "READY_FOR_BRAND",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": evidence_status,
            "current_scope": {
                "order_id": "synthetic-order",
                "sku_id": "synthetic-sku",
                "fulfillment_item_id": "synthetic-item",
                "issue_type": issue_type,
            },
            "active_commitments": [],
            "prohibited_actions": list(prohibited_actions),
            "experience_gap_diagnosis": {
                "consumer_expression": "synthetic service progress request",
                "traceable_service_facts": [
                    {
                        "fact_type": "EVIDENCE_SUBMITTED",
                        "statement": "synthetic server evidence fact",
                        "source_ids": ["synthetic-session"],
                    }
                ],
                "deterioration_cause": "waiting for service progress",
                "latent_need": "an auditable update",
                "responsibility_judgment": {
                    "consumer_input_complete": True,
                    "accountable_side": "BRAND",
                },
                "action_impacts": ["CHECK_EXISTING_FULFILLMENT"],
                "reply_strategy": "check the existing fulfillment",
            },
            "open_obligation": None,
            "service_progress_receipt": None,
            "experience_risk": "MEDIUM",
            "audit_trail": [],
        }
    )


def make_action(state: AccountabilityState, action_type: str = "ASK_EVIDENCE") -> PreparedAction:
    return PreparedAction.model_validate(
        {
            "action_id": "synthetic-action",
            "action_type": action_type,
            "requested_scope": state.current_scope.model_dump()
            if action_type == "ASK_EVIDENCE"
            else None,
            "requires_human_approval": False,
        }
    )


@dataclass(frozen=True)
class Scenario:
    name: str
    evidence_status: str
    issue_type: str
    action_type: str
    prohibitions: tuple[str, ...]
    expected: tuple[str, str, int]
    suppressed: tuple[str, ...] = ()
    changed_sku: bool = False

    def inputs(self) -> tuple[AccountabilityState, PreparedAction]:
        state = make_state(
            evidence_status=self.evidence_status,
            issue_type=self.issue_type,
            prohibited_actions=self.prohibitions,
        )
        action = make_action(state, self.action_type)
        if self.changed_sku:
            scope = Scope.model_validate({**state.current_scope.model_dump(), "sku_id": "gift-sku"})
            action = PreparedAction.model_validate(
                {**action.model_dump(), "requested_scope": scope}
            )
        return state, action


SCENARIOS = (
    Scenario(
        "A13",
        "VALID",
        "PACKAGE_DAMAGE",
        "CLOSE_CASE",
        ("CLOSE_BEFORE_RESOLUTION",),
        ("INTERVENE", "P0_PROHIBITED_ACTION", 400),
    ),
    Scenario(
        "A14",
        "VALID",
        "ADVERSE_REACTION",
        "ASK_EVIDENCE",
        ("ASK_SAME_EVIDENCE",),
        ("HUMAN_REVIEW", "H1", 350),
        ("E1",),
    ),
    Scenario(
        "A15",
        "VALID",
        "PACKAGE_DAMAGE",
        "CHECK_REPLACEMENT_PROGRESS",
        (),
        ("ALLOW", "E0_NO_RULE_MATCHED", 0),
    ),
    Scenario(
        "A20",
        "VALID",
        "PACKAGE_DAMAGE",
        "ASK_EVIDENCE",
        ("ASK_SAME_EVIDENCE",),
        ("INTERVENE", "E1", 300),
    ),
    Scenario(
        "A21",
        "VALID",
        "PACKAGE_DAMAGE",
        "ASK_EVIDENCE",
        ("ASK_SAME_EVIDENCE",),
        ("INTERVENE", "E1", 300),
    ),
    Scenario(
        "A29",
        "VALID",
        "PACKAGE_DAMAGE",
        "SHIFT_FOLLOW_UP_TO_CONSUMER",
        ("SHIFT_FOLLOW_UP_TO_CONSUMER",),
        ("INTERVENE", "P0_PROHIBITED_ACTION", 400),
    ),
    Scenario(
        "A30",
        "VALID",
        "ADVERSE_REACTION",
        "CLOSE_CASE",
        ("CLOSE_BEFORE_RESOLUTION",),
        ("INTERVENE", "P0_PROHIBITED_ACTION", 400),
        ("H1",),
    ),
    Scenario(
        "repeat-explanation",
        "VALID",
        "PACKAGE_DAMAGE",
        "REPEAT_EXPLANATION_REQUEST",
        ("ASK_REPEAT_EXPLANATION",),
        ("INTERVENE", "P0_PROHIBITED_ACTION", 400),
    ),
    Scenario(
        "scope-change",
        "MISMATCHED",
        "PACKAGE_DAMAGE",
        "ASK_EVIDENCE",
        (),
        ("ALLOW", "E2", 100),
        changed_sku=True,
    ),
    Scenario(
        "uncertain-evidence",
        "NEED_HUMAN_REVIEW",
        "PACKAGE_DAMAGE",
        "ASK_EVIDENCE",
        (),
        ("HUMAN_REVIEW", "H1", 350),
    ),
    Scenario(
        "H1-suppresses-E2",
        "MISMATCHED",
        "ADVERSE_REACTION",
        "ASK_EVIDENCE",
        (),
        ("HUMAN_REVIEW", "H1", 350),
        ("E2",),
        changed_sku=True,
    ),
)
