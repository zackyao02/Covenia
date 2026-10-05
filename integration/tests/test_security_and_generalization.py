"""BATCH-30: cross-module anti-hardcoding, injection and PII regression.

The suite is deliberately organised as four evidence blocks that map one-to-one
onto the batch acceptance criteria:

* criterion 1 -- random identifier/input perturbation plus the three-decision
  matrix, and a *behavioural* static auditor (not a four-literal search);
* criterion 2 -- the privacy boundary, plus the negative controls that prove the
  safety assertions really fail when masking is switched off;
* criterion 3 -- forged promises, server-owned source conflicts versus model
  confidence, and the A34 full combination matrix;
* criterion 4 -- the isolated absolute interpreter, recorded in
  ``reports/batches/BATCH-30/environment.json`` and asserted here only where the
  running interpreter itself is observable.

Discipline inherited from BATCH-21: a security assertion that cannot fail is not
evidence.  Every ``pytest.mark.mutation`` test therefore drives an *inner* probe
against a deliberately broken production path, asserts that the inner safety
assertion really raised (``so this test cannot pass vacuously``), and then proves
the ordinary path is restored.

Image pixel-level injection pairing against the *real* model is BATCH-32's job
(A materials); the substitutes here do not replace it.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from uuid import UUID

import pytest

from covenia_b.commitments.compiler import compile_case_input, compile_commitments
from covenia_b.commitments.models import (
    ActivationStatus,
    CommitmentFacts,
    CommitmentPolicy,
    CompilationReason,
    ModelCommitmentHint,
    PromiseAction,
    TicketFact,
    TrustedMessage,
)
from covenia_b.domain.types import (
    AccountabilityState,
    AnalyzeCaseRequest,
    CandidateExtraction,
    CaseInput,
    CompiledCommitments,
    EvaluateActionRequest,
    ExtractedJourney,
    ImageObservation,
    LedgerSnapshot,
    ModelMetadata,
    PreparedAction,
    ResolvedImage,
    SanitizedModelInput,
    Scope,
    SourceTrace,
)
from covenia_b.evidence.aggregation import (
    CandidateEvidence,
    CurrentEvidenceContext,
    aggregate_evidence,
)
from covenia_b.privacy import (
    SanitizationResult,
    UnsafeModelInputError,
    extract_with_privacy_boundary,
    sanitize_case_input,
)
from covenia_b.privacy import boundary as boundary_module
from covenia_b.privacy import sanitizer as sanitizer_module
from covenia_b.privacy.sanitizer import RedactedText
from covenia_b.rules import ProhibitedActionError, evaluate_decision
from covenia_b.runtime import (
    RuntimeOverrides,
    build_runtime,
    compose_application,
    installed_route_inventory,
)
from covenia_b.services.analyze import (
    AnalysisInputError,
    AnalysisModelOutputError,
    AnalyzeService,
)
from covenia_b.services.evaluate import EvaluateService, EvaluateInputError
from covenia_b.services.fact_loader import (
    FactLoader,
    ImageSafetyDeclarationError,
    ImageSafetyDeclarations,
)
from covenia_b.settings import Settings
from covenia_b.state import build_accountability_state

# --------------------------------------------------------------------------- #
# Constants, seeds and shared helpers
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDITOR = REPO_ROOT / "tools" / "verification" / "check_no_case_branches.py"
TEST_FILE = Path(__file__).resolve()

#: The one random seed used by every perturbation sweep in this batch.  Recorded in
#: reports/batches/BATCH-30/security-matrix.json and in handoff_to_next_batch.
SEED = 30001
PERTURBATIONS_PER_CELL = 6

EVIDENCE_STATUSES = ("VALID", "MISMATCHED", "NEED_HUMAN_REVIEW")
ISSUE_TYPES = ("PACKAGE_DAMAGE", "LOGISTICS_STALLED", "ADVERSE_REACTION")
ACTION_TYPES = (
    "ASK_EVIDENCE",
    "CHECK_REPLACEMENT_PROGRESS",
    "CREATE_FOLLOW_UP_TASK",
    "CLOSE_CASE",
    "SHIFT_FOLLOW_UP_TO_CONSUMER",
    "REPEAT_EXPLANATION_REQUEST",
)
ALL_PROHIBITIONS = (
    "CLOSE_BEFORE_RESOLUTION",
    "SHIFT_FOLLOW_UP_TO_CONSUMER",
    "ASK_REPEAT_EXPLANATION",
    "ASK_SAME_EVIDENCE",
)
MATRIX = tuple(itertools.product(EVIDENCE_STATUSES, ISSUE_TYPES, ACTION_TYPES, (False, True)))

DECISION_FOR_RULE = {
    "P0_PROHIBITED_ACTION": "INTERVENE",
    "H1": "HUMAN_REVIEW",
    "E1": "INTERVENE",
    "E2": "ALLOW",
    "E0_NO_RULE_MATCHED": "ALLOW",
}
PRIORITY_FOR_RULE = {
    "P0_PROHIBITED_ACTION": 400,
    "H1": 350,
    "E1": 300,
    "E2": 100,
    "E0_NO_RULE_MATCHED": 0,
}
PHONE = "13800138000"


def contract_hits(status: str, issue: str, action_type: str, prohibited: bool) -> tuple[str, ...]:
    """A contract-derived truth table.

    Written from the frozen firewall semantics rather than from the implementation,
    so an engine change cannot silently rewrite the expectation.
    """

    hits: list[str] = []
    if prohibited and action_type in {
        "CLOSE_CASE",
        "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "REPEAT_EXPLANATION_REQUEST",
    }:
        hits.append("P0_PROHIBITED_ACTION")
    if status == "NEED_HUMAN_REVIEW" or issue == "ADVERSE_REACTION":
        hits.append("H1")
    if status == "VALID" and action_type == "ASK_EVIDENCE":
        hits.append("E1")
    if status == "MISMATCHED" and action_type == "ASK_EVIDENCE":
        hits.append("E2")
    return tuple(hits)


def expected_rule(status: str, issue: str, action_type: str, prohibited: bool) -> str:
    hits = contract_hits(status, issue, action_type, prohibited)
    return hits[0] if hits else "E0_NO_RULE_MATCHED"


def signature(result: object) -> tuple[str, str, int]:
    return (result.decision, result.rule_id, result.rule_priority)  # type: ignore[attr-defined]


def make_state(
    *,
    evidence_status: str = "VALID",
    issue_type: str = "PACKAGE_DAMAGE",
    prohibited_actions: tuple[str, ...] = (),
    case_id: str = "case-b30-rules",
) -> AccountabilityState:
    """An authoritative server state; no file, fixture, or ground truth is read."""

    return AccountabilityState.model_validate(
        {
            "case_id": case_id,
            "case_status": "READY_FOR_BRAND",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": evidence_status,
            "current_scope": {
                "order_id": "order-b30-001",
                "sku_id": "sku-b30-primary",
                "fulfillment_item_id": "item-b30-001",
                "issue_type": issue_type,
            },
            "active_commitments": [],
            "prohibited_actions": list(prohibited_actions),
            "experience_gap_diagnosis": {
                "consumer_expression": "服务进度请求",
                "traceable_service_facts": [
                    {
                        "fact_type": "EVIDENCE_SUBMITTED",
                        "statement": "服务端证据事实",
                        "source_ids": ["source-b30-001"],
                    }
                ],
                "deterioration_cause": "等待服务进度",
                "latent_need": "可审计的更新",
                "responsibility_judgment": {
                    "consumer_input_complete": True,
                    "accountable_side": "BRAND",
                },
                "action_impacts": ["CHECK_EXISTING_FULFILLMENT"],
                "reply_strategy": "检查既有履约",
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
            "action_id": "action-b30-001",
            "action_type": action_type,
            "requested_scope": (
                state.current_scope.model_dump() if action_type == "ASK_EVIDENCE" else None
            ),
            "requires_human_approval": False,
        }
    )


def build_matrix_inputs(
    status: str, issue: str, action_type: str, prohibited: bool
) -> tuple[AccountabilityState, PreparedAction]:
    state = make_state(
        evidence_status=status,
        issue_type=issue,
        prohibited_actions=ALL_PROHIBITIONS if prohibited else (),
    )
    return state, make_action(state, action_type)


def make_case_input(
    *,
    case_id: str = "case-b30-001",
    messages: tuple[tuple[str, str], ...] = (("AGENT", "客服承诺在 48 小时内补发。"),),
    evidence_ids: tuple[str, ...] = ("evidence-b30-001",),
    item_role: str = "PRIMARY",
    issue_type: str = "PACKAGE_DAMAGE",
    affected_component: str = "PUMP",
    tickets: tuple[dict[str, object], ...] = (),
) -> CaseInput:
    conversation = [
        {
            "message_id": f"message-b30-{index:03d}",
            "timestamp": f"2026-09-13T09:{30 + index:02d}:00+00:00",
            "speaker": speaker,
            "text": text,
            "source_kind": "COMPETITION_MOCK",
        }
        for index, (speaker, text) in enumerate(messages, start=1)
    ]
    return CaseInput.model_validate(
        {
            "case_id": case_id,
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-b30-001",
                "augmentation_notes": [],
            },
            "evaluation_time": "2026-09-13T11:35:00+00:00",
            "conversation": conversation,
            "order": {
                "order_id": "order-b30-001",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "item-b30-001",
                        "sku_id": "sku-b30-primary",
                        "product_name": "Test Product",
                        "batch_code": None,
                        "item_role": item_role,
                    }
                ],
                "original_logistics_number": "logistics-b30-001",
            },
            "service_tickets": list(tickets),
            "evidence_images": [
                {
                    "evidence_id": evidence_id,
                    "file_name": f"{evidence_id}.png",
                    "submitted_at": "2026-09-13T09:30:00+00:00",
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": conversation[0]["message_id"],
                    "competition_reference_path": None,
                }
                for evidence_id in evidence_ids
            ],
            "current_issue": {
                "fulfillment_item_id": "item-b30-001",
                "sku_id": "sku-b30-primary",
                "issue_type": issue_type,
                "affected_component": affected_component,
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )


def case_input_with_pii() -> CaseInput:
    return make_case_input(
        messages=(
            ("CONSUMER", f"我的手机号是 {PHONE}，请联系我。"),
            ("AGENT", "客服承诺在 48 小时内补发。"),
        )
    )


def model_metadata(run_id: str = "run-b30-001") -> ModelMetadata:
    return ModelMetadata(
        model_id="qwen3-vl-plus",
        model_revision="rev-b30",
        prompt_version="candidate-extraction-v1",
        run_id=run_id,
        cached_result=False,
    )


def empty_candidate(model_input: SanitizedModelInput) -> CandidateExtraction:
    """A structurally valid candidate that claims nothing at all."""

    return CandidateExtraction(
        case_id=model_input.case_id,
        model_metadata=model_metadata(),
        observations=(),
        source_trace=(),
        candidate_promise_texts=(),
    )


class CapturingProvider:
    """A model-provider test double that records exactly what it received."""

    def __init__(self, factory=empty_candidate) -> None:
        self.captured: list[SanitizedModelInput] = []
        self._factory = factory

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction:
        self.captured.append(model_input)
        return self._factory(model_input)


class StaticImageResolver:
    """Return a content-addressed handle without reading the filesystem."""

    def resolve(self, evidence: object) -> ResolvedImage:
        evidence_id = str(getattr(evidence, "evidence_id"))
        return ResolvedImage(
            evidence_id=evidence_id,
            media_type="image/png",
            content_sha256=hashlib.sha256(evidence_id.encode("utf-8")).hexdigest(),
            byte_length=1024,
        )


def make_fact_loader(
    *,
    case_input: CaseInput | None = None,
    declarations: dict[str, bool] | None = None,
) -> FactLoader:
    """Declare every evidence ID safe unless the caller says otherwise."""

    if declarations is None:
        resolved = (
            {image.evidence_id: True for image in case_input.evidence_images}
            if case_input is not None
            else {}
        )
    else:
        resolved = dict(declarations)
    return FactLoader(
        case_source=None,
        image_resolver=StaticImageResolver(),
        image_no_pii_declarations=ImageSafetyDeclarations(resolved),
    )


def make_analyze_service(
    *,
    provider: CapturingProvider,
    case_input: CaseInput | None = None,
    declarations: dict[str, bool] | None = None,
    provider_mode: str = "TEST_DOUBLE",
) -> AnalyzeService:
    return AnalyzeService(
        fact_loader=make_fact_loader(case_input=case_input, declarations=declarations),
        provider=provider,  # type: ignore[arg-type]
        ledger_repository=None,
        provider_mode=provider_mode,  # type: ignore[arg-type]
    )


def challenge_request(case_input: CaseInput) -> AnalyzeCaseRequest:
    return AnalyzeCaseRequest.model_validate(
        {
            "case_id": case_input.case_id,
            "challenge_mode": True,
            "case_input": case_input.model_dump(mode="json"),
        }
    )


async def analyze_once(service: AnalyzeService, request: AnalyzeCaseRequest):
    return await service.analyze_with_trace(request)


def make_scope() -> Scope:
    return Scope(
        order_id="order-b30-001",
        fulfillment_item_id="item-b30-001",
        sku_id="sku-b30-primary",
        issue_type="PACKAGE_DAMAGE",
    )


def make_journey(
    observations: tuple[ImageObservation, ...] = (),
    *,
    confidence: float = 0.0,
) -> ExtractedJourney:
    return ExtractedJourney.model_validate(
        {
            "case_id": "case-b30-001",
            "completed_actions": {
                "issue_explained": True,
                "order_verified": True,
                "evidence_submitted": True,
            },
            "promise_events": [],
            "image_observations": [
                {**observation.model_dump(mode="json"), "confidence": confidence}
                for observation in observations
            ],
            "extracted_scope": make_scope().model_dump(mode="json"),
            "journey_understanding": {
                "consumer_intent": "REQUEST_TRACEABLE_SERVICE_REVIEW",
                "experience_expression": "服务进度请求",
                "service_cause": "等待履约",
                "latent_need": "可审计的更新",
                "cooperation_willingness": "UNKNOWN",
                "action_impact": "REQUIRES_SERVER_EVIDENCE_AGGREGATION",
                "source_ids": ["message-b30-001"],
            },
            "source_trace": [
                {"field": "extracted_scope", "source_type": "ORDER", "source_id": "order-b30-001"}
            ],
            "model_metadata": model_metadata().model_dump(mode="json"),
        }
    )


def observation(
    evidence_id: str,
    *,
    readability: str = "HIGH",
    sku_match: str = "MATCH",
    product_identifiable: bool = True,
    issue_visible: bool = True,
    affected_component: str = "PUMP",
    coverage: tuple[str, ...] = ("PRODUCT_IDENTITY", "AFFECTED_COMPONENT", "DAMAGE_DETAIL"),
    integrity_concern: bool = False,
) -> ImageObservation:
    return ImageObservation.model_validate(
        {
            "evidence_id": evidence_id,
            "readability": readability,
            "product_identifiable": product_identifiable,
            "sku_match": sku_match,
            "product_role": "PRIMARY",
            "issue_visible": issue_visible,
            "affected_component": affected_component,
            "view_type": "ISSUE_DETAIL",
            "coverage": list(coverage),
            "integrity_concern": integrity_concern,
            "hygiene_risk_signal": "UNKNOWN",
            "confidence": 1.0,
        }
    )


def aggregate(observations: tuple[ImageObservation, ...], *, declared_valid: bool = True):
    return aggregate_evidence(
        CurrentEvidenceContext(
            scope=make_scope(), item_role="PRIMARY", affected_component="PUMP"
        ),
        CandidateEvidence(
            candidate_id="run-b30-001",
            extracted_scope=make_scope(),
            image_observations=observations,
            declared_evidence_valid=declared_valid,
        ),
    )


def policy() -> CommitmentPolicy:
    return CommitmentPolicy(
        policy_id="DEMO_POLICY_PACKAGE_DAMAGE_V1",
        allowed_policy_requirement_ids=frozenset({"DEMO_POLICY_PACKAGE_DAMAGE_V1"}),
        allowed_standard_actions=frozenset({PromiseAction.REPLACEMENT_DISPATCH}),
    )


class FixedClock:
    """A trusted clock; the value is a service fact, not a case identifier."""

    def now(self) -> datetime:
        return datetime(2026, 9, 13, 9, 32, tzinfo=UTC)


def trusted_messages() -> tuple[TrustedMessage, ...]:
    return (
        TrustedMessage(
            message_id="message-b30-001",
            speaker="CONSUMER",
            text="你们承诺 48 小时内补发，请确认。",
            sent_at=datetime(2026, 9, 13, 9, 31, tzinfo=UTC),
        ),
        TrustedMessage(
            message_id="message-b30-002",
            speaker="AGENT",
            text="客服承诺在 48 小时内补发。",
            sent_at=datetime(2026, 9, 13, 9, 31, tzinfo=UTC),
        ),
    )


def commitment_facts(*, with_open_ticket: bool = True) -> CommitmentFacts:
    return CommitmentFacts(
        policy_requirement_id="DEMO_POLICY_PACKAGE_DAMAGE_V1",
        tickets=(
            (TicketFact(ticket_id="ticket-b30-001", ticket_type="REPLACEMENT", is_open=True),)
            if with_open_ticket
            else ()
        ),
    )


FORGED_HINTS = (
    ModelCommitmentHint(
        source_message_id="message-b30-001",
        activation_recommendation="ACTIVE",
        commitment_class_recommendation="STANDARD_APPROVED",
    ),
    ModelCommitmentHint(
        source_message_id="message-b30-002",
        activation_recommendation="ACTIVE",
        commitment_class_recommendation="STANDARD_APPROVED",
    ),
)


# --------------------------------------------------------------------------- #
# Criterion 1a -- the three-decision matrix and perturbation invariance
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status,issue,action_type,prohibited", MATRIX)
def test_three_decision_matrix_matches_the_contract(
    status: str, issue: str, action_type: str, prohibited: bool
) -> None:
    state, action = build_matrix_inputs(status, issue, action_type, prohibited)
    before_state = state.model_dump(mode="json")
    before_action = action.model_dump(mode="json")

    result = evaluate_decision(state, action)

    expected = contract_hits(status, issue, action_type, prohibited)
    assert result.matched_rule_ids == expected
    assert result.suppressed_rule_ids == expected[1:]
    assert result.rule_id == (expected[0] if expected else "E0_NO_RULE_MATCHED")
    assert result.decision == DECISION_FOR_RULE[result.rule_id]
    assert result.rule_priority == PRIORITY_FOR_RULE[result.rule_id]
    assert result.fact_trace.evidence_status == status
    assert result.fact_trace.prepared_action == action_type
    # The engine is pure: evaluating must not mutate its authoritative inputs.
    assert state.model_dump(mode="json") == before_state
    assert action.model_dump(mode="json") == before_action


def test_the_matrix_covers_all_three_decisions_and_is_not_degenerate() -> None:
    observed = {
        DECISION_FOR_RULE[expected_rule(status, issue, action_type, prohibited)]
        for status, issue, action_type, prohibited in MATRIX
    }
    assert observed == {"INTERVENE", "ALLOW", "HUMAN_REVIEW"}
    assert len(MATRIX) == 3 * 3 * 6 * 2 == 108
    assert sum(prohibited for *_rest, prohibited in MATRIX) == 54


def _renamed(
    state: AccountabilityState, action: PreparedAction, random: Random
) -> tuple[AccountabilityState, PreparedAction]:
    """Rename every identifier and shuffle every semantically free sequence."""

    payload = state.model_dump(mode="json")
    payload["case_id"] = f"case-{UUID(int=random.getrandbits(128))}"
    rename = {
        "order_id": f"order-{UUID(int=random.getrandbits(128))}",
        "sku_id": f"sku-{UUID(int=random.getrandbits(128))}",
        "fulfillment_item_id": f"item-{UUID(int=random.getrandbits(128))}",
    }
    for key, value in rename.items():
        payload["current_scope"][key] = value
    forbidden = payload["prohibited_actions"]
    payload["prohibited_actions"] = list(random.sample(forbidden, len(forbidden)))
    for fact in payload["experience_gap_diagnosis"]["traceable_service_facts"]:
        fact["source_ids"] = [f"source-{UUID(int=random.getrandbits(128))}"]
        fact["statement"] = f"synthetic-{UUID(int=random.getrandbits(128))}"
    payload["experience_gap_diagnosis"]["consumer_expression"] = str(
        UUID(int=random.getrandbits(128))
    )
    renamed_state = AccountabilityState.model_validate(payload)

    action_payload = action.model_dump(mode="json")
    action_payload["action_id"] = f"action-{UUID(int=random.getrandbits(128))}"
    if action_payload["requested_scope"] is not None:
        action_payload["requested_scope"] = {**action_payload["requested_scope"], **rename}
    return renamed_state, PreparedAction.model_validate(action_payload)


@pytest.mark.parametrize("status,issue,action_type,prohibited", MATRIX)
def test_random_identifier_and_order_perturbation_preserves_the_decision(
    status: str, issue: str, action_type: str, prohibited: bool
) -> None:
    state, action = build_matrix_inputs(status, issue, action_type, prohibited)
    baseline = evaluate_decision(state, action)
    random = Random(SEED)

    for _ in range(PERTURBATIONS_PER_CELL):
        renamed_state, renamed_action = _renamed(state, action, random)
        recalculated = evaluate_decision(renamed_state, renamed_action)
        assert signature(recalculated) == signature(baseline)
        assert recalculated.matched_rule_ids == baseline.matched_rule_ids
        assert recalculated.suppressed_rule_ids == baseline.suppressed_rule_ids
        assert recalculated.fact_trace == baseline.fact_trace
        assert recalculated.reason == baseline.reason
        # Re-parsed from JSON: the match is on facts, not on object identity.
        reloaded_state = AccountabilityState.model_validate_json(renamed_state.model_dump_json())
        reloaded_action = PreparedAction.model_validate_json(renamed_action.model_dump_json())
        assert evaluate_decision(reloaded_state, reloaded_action) == recalculated


@pytest.mark.parametrize("case_id", ["S00001", "DEMO_001", "DEMO_002", "DEMO_003", "ordinal-1729"])
def test_display_identifiers_never_select_a_rule(case_id: str) -> None:
    for status, issue, action_type, prohibited in MATRIX[::7]:
        state, action = build_matrix_inputs(status, issue, action_type, prohibited)
        renamed = AccountabilityState.model_validate({**state.model_dump(), "case_id": case_id})
        assert signature(evaluate_decision(renamed, action)) == signature(
            evaluate_decision(state, action)
        )


def test_changed_facts_do_change_the_decision() -> None:
    """The invariance above must not be vacuous: facts still decide."""

    base = make_state(evidence_status="VALID")
    action = make_action(base)
    assert evaluate_decision(base, action).rule_id == "E1"
    for status, expected in (("NEED_HUMAN_REVIEW", "H1"), ("MISMATCHED", "E2")):
        changed = AccountabilityState.model_validate(
            {**base.model_dump(), "evidence_status": status}
        )
        assert evaluate_decision(changed, action).rule_id == expected
    cleared = AccountabilityState.model_validate({**base.model_dump(), "prohibited_actions": []})
    prohibited = AccountabilityState.model_validate(
        {**base.model_dump(), "prohibited_actions": ["CLOSE_BEFORE_RESOLUTION"]}
    )
    assert evaluate_decision(cleared, make_action(base, "CLOSE_CASE")).rule_id == (
        "E0_NO_RULE_MATCHED"
    )
    assert evaluate_decision(prohibited, make_action(prohibited, "CLOSE_CASE")).rule_id == (
        "P0_PROHIBITED_ACTION"
    )


# --------------------------------------------------------------------------- #
# Criterion 1b -- the static auditor is behavioural, not a four-literal search
# --------------------------------------------------------------------------- #


def load_auditor():
    spec = importlib.util.spec_from_file_location("b30_check_no_case_branches", AUDITOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: the tool defines dataclasses, and dataclasses
    # resolves string annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def run_auditor(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDITOR), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_auditor_passes_the_production_tree() -> None:
    completed = run_auditor("--strict", "--quiet")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS" in completed.stdout


def test_auditor_exit_code_contract_is_zero_one_two() -> None:
    clean = run_auditor("--strict", "--quiet")
    assert clean.returncode == 0

    tool_error = run_auditor("--root", "does-not-exist", "--quiet")
    assert tool_error.returncode == 2
    assert "tool error" in tool_error.stderr

    module = load_auditor()
    scratch = Path(tempfile.mkdtemp(prefix="b30-auditor-scratch-"))
    try:
        for relative, source, _expected, _clean in module.SELF_TEST_CASES:
            target = scratch / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        report_path = scratch / "report.json"
        failed = run_auditor(
            "--root", str(scratch), "--strict", "--quiet", "--json", str(report_path)
        )
        assert failed.returncode == 1, failed.stdout + failed.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))
        judgments = {hit["judgment"] for hit in report["hits"]}
        assert judgments == {
            "J1_CASE_LITERAL_IN_DECISION",
            "J2_DESCRIPTOR_DECIDES_VERDICT",
            "J3_OBSERVED_RESULT_HARDCODED",
            "J4_GROUND_TRUTH_INGRESS",
            "J5_PRIVACY_BYPASS_CONFIGURATION",
            "J6_IDENTITY_SELECTS_DEFAULT",
            "J7_REQUEST_STATE_REACHES_RULES",
        }
        assert report["status"] == "FAIL"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_auditor_catches_shortcuts_a_four_literal_blacklist_misses() -> None:
    """The core of acceptance criterion 1: the scan is structural, not a wordlist."""

    module = load_auditor()
    outcome = module.run_self_test()
    assert outcome["passed"] is True
    invisible = [
        check
        for check in outcome["checks"]
        if check["literal_blacklist_would_find_it"] is False and check["observed_judgments"]
    ]
    assert len(invisible) >= 6, outcome
    # A four-literal blacklist would have found exactly one planted shortcut: the
    # one that deliberately contains DEMO_001.
    assert sum(check["literal_blacklist_would_find_it"] for check in outcome["checks"]) == 1
    assert len(module.JUDGMENTS) == 7
    assert len({entry["id"] for entry in module.JUDGMENTS}) == 7


def test_auditor_grants_identity_validation_only_when_the_illegal_value_raises() -> None:
    module = load_auditor()
    allowed_source = (
        "ALLOWED_VIEWS = frozenset({'PRODUCT_OVERVIEW', 'ISSUE_DETAIL'})\n"
        "\n"
        "\n"
        "def _view_type_verdict(image):\n"
        "    view_type = image.get('declared_view_type')\n"
        "    if view_type not in ALLOWED_VIEWS:\n"
        "        raise ValueError('unsupported image view type')\n"
        "    if view_type == 'ISSUE_DETAIL':\n"
        "        return 'VALID'\n"
        "    return 'UNKNOWN'\n"
    )
    allowed = module.scan_source("images/resolver.py", allowed_source, "purity")
    assert allowed.hits == []
    assert any(
        item["judgment"] == "J2_DESCRIPTOR_DECIDES_VERDICT" for item in allowed.suppressed
    )

    silent_source = allowed_source.replace(
        "        raise ValueError('unsupported image view type')\n",
        "        return 'OTHER'\n",
    )
    assert "raise" not in silent_source
    rejected = module.scan_source("images/resolver.py", silent_source, "purity")
    assert "J2_DESCRIPTOR_DECIDES_VERDICT" in {hit.judgment for hit in rejected.hits}
    assert not any(
        item["judgment"] == "J2_DESCRIPTOR_DECIDES_VERDICT" for item in rejected.suppressed
    )


def test_production_source_holds_no_planted_residue_and_no_scan_pragma() -> None:
    offenders: list[str] = []
    for path in (REPO_ROOT / "backend" / "src" / "covenia_b").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in (
            "_planted_",
            "BATCH-30 planted negative control",
            "no-case-branch-scan: allow",
        ):
            if marker in text:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {marker}")
    assert offenders == []


# --------------------------------------------------------------------------- #
# Criterion 2 -- PII masking, and the negative controls that make it falsifiable
# --------------------------------------------------------------------------- #


def test_production_analyze_path_masks_pii_before_the_provider_sees_anything() -> None:
    case_input = case_input_with_pii()
    provider = CapturingProvider()
    service = make_analyze_service(provider=provider, case_input=case_input)

    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))

    assert len(provider.captured) == 1
    seen = provider.captured[0]
    assert PHONE not in seen.redacted_text
    assert "[PHONE_REDACTED]" in seen.redacted_text
    assert execution.pii_masked_count >= 1
    trace = json.dumps(execution.redacted_trace(), ensure_ascii=False)
    assert PHONE not in trace
    assert PHONE not in execution.response.model_dump_json()


def test_declared_production_setting_cannot_switch_masking_off() -> None:
    """Acceptance criterion 2: production configuration cannot bypass the mask."""

    default_settings = Settings()
    disabled_settings = Settings(pii_safety_checks_enabled=False)
    assert default_settings.pii_safety_checks_enabled is True
    assert disabled_settings.pii_safety_checks_enabled is False

    for settings in (default_settings, disabled_settings):
        case_input = case_input_with_pii()
        provider = CapturingProvider()
        service = make_analyze_service(provider=provider, case_input=case_input)
        execution = asyncio.run(analyze_once(service, challenge_request(case_input)))
        assert PHONE not in provider.captured[0].redacted_text
        assert execution.pii_masked_count >= 1

    # The composition root accepts the disabled flag without turning it into a
    # behaviour switch: nothing in the privacy or service path reads it.
    runtime = build_runtime(disabled_settings, overrides=RuntimeOverrides())
    assert runtime.settings.pii_safety_checks_enabled is False
    for module in (sanitizer_module, boundary_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "pii_safety_checks_enabled" not in source


def test_privacy_masking_is_unconditional_under_hostile_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COVENIA_PII_SAFETY_CHECKS_ENABLED", "false")
    monkeypatch.setenv("COVENIA_PII_CHECKS", "false")
    case_input = case_input_with_pii()
    prepared = sanitize_case_input(case_input)
    assert PHONE not in prepared.model_input.redacted_text
    provider = CapturingProvider()
    asyncio.run(extract_with_privacy_boundary(provider, prepared))
    assert PHONE not in provider.captured[0].redacted_text


def test_image_bytes_require_an_accepted_no_pii_declaration() -> None:
    case_input = make_case_input(evidence_ids=("evidence-b30-001",))
    loader = make_fact_loader(case_input=case_input, declarations={})
    with pytest.raises(ImageSafetyDeclarationError):
        loader.load(challenge_request(case_input))

    provider = CapturingProvider()
    service = make_analyze_service(provider=provider, case_input=case_input, declarations={})
    with pytest.raises(AnalysisInputError) as blocked:
        asyncio.run(analyze_once(service, challenge_request(case_input)))
    assert blocked.value.code == "VALIDATION_ERROR"
    assert provider.captured == []


def test_undeclared_evidence_anywhere_in_the_set_fails_closed() -> None:
    evidence_ids = ("evidence-b30-001", "evidence-b30-002", "evidence-b30-003")
    case_input = make_case_input(evidence_ids=evidence_ids)
    for declared in (
        {},
        {evidence_ids[0]: True},
        {evidence_ids[0]: True, evidence_ids[1]: True},
        {evidence_ids[0]: True, evidence_ids[1]: False, evidence_ids[2]: True},
    ):
        loader = make_fact_loader(case_input=case_input, declarations=declared)
        with pytest.raises(ImageSafetyDeclarationError):
            loader.load(challenge_request(case_input))
    complete = make_fact_loader(
        case_input=case_input, declarations=dict.fromkeys(evidence_ids, True)
    )
    assert complete.load(challenge_request(case_input)) is not None


def _masking_disabled(value: str) -> RedactedText:
    """A mutant redactor that keeps the type and removes every redaction."""

    if not isinstance(value, str):
        raise ValueError("model-bound text must be a string")
    return RedactedText(text=value, masked_categories=())


@pytest.mark.mutation
def test_mutation_disabling_pii_masking_makes_the_security_assertion_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: with masking off the raw number really does reach the model."""

    case_input = case_input_with_pii()
    with monkeypatch.context() as mutation:
        mutation.setattr(sanitizer_module, "redact_text", _masking_disabled)
        mutation.setattr(boundary_module, "redact_text", _masking_disabled)

        prepared = sanitize_case_input(case_input)
        assert prepared.pii_masked_count == 0
        provider = CapturingProvider()
        asyncio.run(extract_with_privacy_boundary(provider, prepared))

        captured = provider.captured[0].redacted_text
        with pytest.raises(AssertionError, match="PII must never reach the provider"):
            assert PHONE not in captured, "PII must never reach the provider"

    restored = sanitize_case_input(case_input_with_pii())
    assert PHONE not in restored.model_input.redacted_text
    assert restored.pii_masked_count >= 1


@pytest.mark.mutation
def test_mutation_forged_projection_reaches_provider_when_both_layers_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control for the provenance gate plus the defense-in-depth text probe."""

    forged = SanitizationResult(
        model_input=SanitizedModelInput(
            case_id="case-b30-forged",
            redacted_text=f"联系手机：{PHONE}",
            images=(),
            source_ids=("order-b30-001", "message-b30-001"),
        ),
        pii_masked_count=0,
        masked_categories=(),
        adverse_risk_candidate=False,
    )
    provider = CapturingProvider()

    # Unmutated: the forged result is refused before the provider is reached.
    with pytest.raises(UnsafeModelInputError, match="unsafe unredacted model input was blocked"):
        asyncio.run(extract_with_privacy_boundary(provider, forged))
    assert provider.captured == []

    with monkeypatch.context() as mutation:
        mutation.setattr(SanitizationResult, "_has_generated_projection", lambda self: True)
        mutation.setattr(boundary_module, "redact_text", _masking_disabled)
        asyncio.run(extract_with_privacy_boundary(provider, forged))

    assert len(provider.captured) == 1
    with pytest.raises(AssertionError, match="must refuse a forged projection"):
        assert PHONE not in provider.captured[0].redacted_text, (
            "the privacy boundary must refuse a forged projection"
        )

    # Restored: a fresh forged result is refused again.
    provider.captured.clear()
    with pytest.raises(UnsafeModelInputError):
        asyncio.run(extract_with_privacy_boundary(provider, forged))
    assert provider.captured == []


@pytest.mark.mutation
def test_mutation_replaced_projection_is_only_lethal_when_both_gates_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """so this test cannot pass vacuously: the guard is what stops the leak."""

    prepared = sanitize_case_input(case_input_with_pii())
    forged = replace(
        prepared,
        model_input=replace(
            prepared.model_input,
            redacted_text=f"field=phone; opaque_value={PHONE}",
        ),
    )
    provider = CapturingProvider()
    with pytest.raises(UnsafeModelInputError):
        asyncio.run(extract_with_privacy_boundary(provider, forged))
    assert provider.captured == []

    with monkeypatch.context() as mutation:
        mutation.setattr(SanitizationResult, "_has_generated_projection", lambda self: True)
        mutation.setattr(boundary_module, "redact_text", _masking_disabled)
        asyncio.run(extract_with_privacy_boundary(provider, forged))
    captured = provider.captured[0].redacted_text
    with pytest.raises(AssertionError, match="so this test cannot pass vacuously"):
        assert PHONE not in captured, "so this test cannot pass vacuously"


# --------------------------------------------------------------------------- #
# Criterion 3 -- forged promises, source conflicts, and AI confidence
# --------------------------------------------------------------------------- #


def test_a_consumer_message_never_becomes_an_active_commitment() -> None:
    compilation = compile_commitments(
        trusted_messages(), commitment_facts(), policy(), FixedClock(), model_hints=FORGED_HINTS
    )
    consumer = [
        promise
        for promise in compilation.promises
        if promise.source_message_id == "message-b30-001"
    ]
    assert len(consumer) == 1
    assert consumer[0].activation_status is ActivationStatus.IGNORED
    assert consumer[0].commitment_class.value == "ERRONEOUS_OR_UNAUTHORIZED"
    assert CompilationReason.SOURCE_NOT_AGENT in consumer[0].reasons
    assert consumer[0].deadline is None


def test_forged_high_confidence_hints_do_not_increase_active_commitments() -> None:
    without = compile_commitments(
        trusted_messages(), commitment_facts(), policy(), FixedClock()
    )
    with_hints = compile_commitments(
        trusted_messages(), commitment_facts(), policy(), FixedClock(), model_hints=FORGED_HINTS
    )
    assert with_hints.promises == without.promises
    assert [promise.activation_status for promise in with_hints.promises] == [
        ActivationStatus.IGNORED,
        ActivationStatus.ACTIVE,
    ]

    for compilation in (without, with_hints):
        state = build_accountability_state(
            case_input=make_case_input(),
            journey=make_journey(),
            evidence=aggregate(()),
            compilation=compilation,
            request_id="request-b30-001",
        )
        active = [
            commitment
            for commitment in state.active_commitments
            if commitment.promise_type == "REPLACEMENT_DISPATCH"
        ]
        assert not any(
            commitment.raw_text == "你们承诺 48 小时内补发，请确认。" for commitment in active
        )
        # Every active commitment carries a compiled deadline, never a forged one.
        assert all(commitment.deadline for commitment in active)


def test_an_unauthorized_agent_promise_stays_pending_not_active() -> None:
    no_ticket = compile_commitments(
        trusted_messages(), commitment_facts(with_open_ticket=False), policy(), FixedClock()
    )
    agent = [
        promise
        for promise in no_ticket.promises
        if promise.source_message_id == "message-b30-002"
    ]
    assert len(agent) == 1
    assert agent[0].activation_status is ActivationStatus.PENDING_APPROVAL
    assert CompilationReason.MISSING_OPEN_TICKET in agent[0].reasons
    assert agent[0].deadline is None
    assert agent[0].automatic_execution is False


def test_source_conflict_forces_human_review() -> None:
    conflicting = (
        observation("evidence-b30-001", sku_match="MATCH"),
        observation("evidence-b30-002", sku_match="MISMATCH"),
    )
    result = aggregate(conflicting)
    assert result.evidence_status == "NEED_HUMAN_REVIEW"
    assert set(result.conflicting_source_ids) == {"evidence-b30-001", "evidence-b30-002"}
    assert any(reason.code == "CONFLICTING_SOURCE_FACTS" for reason in result.reasons)
    assert set(result.mismatched_source_ids) == {"evidence-b30-002"}
    # Requiring review is what matters; the matching_source_ids bookkeeping is not a
    # decision input, so its exact contents are deliberately not asserted here.
    assert result.missing_coverage == ()


@pytest.mark.parametrize("declared_valid", [False, True])
@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_ai_confidence_and_declared_validity_cannot_whitewash_a_source_conflict(
    declared_valid: bool, confidence: float
) -> None:
    conflicting = (
        observation("evidence-b30-001", sku_match="MATCH"),
        observation("evidence-b30-002", sku_match="MISMATCH"),
    )
    result = aggregate(conflicting, declared_valid=declared_valid)
    assert result.evidence_status == "NEED_HUMAN_REVIEW"
    assert result.conflicting_source_ids

    journey = make_journey(conflicting, confidence=confidence)
    assert all(item.confidence == confidence for item in journey.image_observations)
    state = build_accountability_state(
        case_input=make_case_input(),
        journey=journey,
        evidence=result,
        compilation=compile_case_input(make_case_input(), policy(), FixedClock()),
        request_id="request-b30-confidence",
    )
    assert state.evidence_status == "NEED_HUMAN_REVIEW"
    verdict = evaluate_decision(state, make_action(state, "ASK_EVIDENCE"))
    assert verdict.rule_id == "H1"
    assert verdict.decision == "HUMAN_REVIEW"


@pytest.mark.parametrize(
    "observations,expected_status",
    [
        ((observation("evidence-b30-001"),), "VALID"),
        ((observation("evidence-b30-001", readability="LOW"),), "NEED_HUMAN_REVIEW"),
        ((observation("evidence-b30-001", product_identifiable=False),), "NEED_HUMAN_REVIEW"),
        ((observation("evidence-b30-001", sku_match="UNKNOWN"),), "NEED_HUMAN_REVIEW"),
        ((observation("evidence-b30-001", sku_match="MISMATCH"),), "MISMATCHED"),
        ((observation("evidence-b30-001", issue_visible=False),), "NEED_HUMAN_REVIEW"),
        ((observation("evidence-b30-001", affected_component="CAP"),), "MISMATCHED"),
        ((observation("evidence-b30-001", integrity_concern=True),), "NEED_HUMAN_REVIEW"),
        ((observation("evidence-b30-001", coverage=("DAMAGE_DETAIL",)),), "NEED_HUMAN_REVIEW"),
        ((), "NEED_HUMAN_REVIEW"),
    ],
    ids=[
        "complete",
        "unreadable",
        "product-unidentifiable",
        "sku-unknown",
        "sku-mismatch",
        "issue-invisible",
        "component-mismatch",
        "integrity-concern",
        "coverage-missing",
        "no-observations",
    ],
)
def test_evidence_status_truth_table_is_input_driven(
    observations: tuple[ImageObservation, ...], expected_status: str
) -> None:
    assert aggregate(observations).evidence_status == expected_status


def test_conflicting_sources_are_reported_even_when_every_confidence_is_one() -> None:
    conflicting = (
        observation("evidence-b30-001", sku_match="MATCH"),
        observation("evidence-b30-002", sku_match="MISMATCH"),
    )
    high = aggregate(conflicting, declared_valid=True)
    low = aggregate(
        tuple(item.model_copy(update={"confidence": 0.01}) for item in conflicting),
        declared_valid=False,
    )
    assert high.evidence_status == low.evidence_status == "NEED_HUMAN_REVIEW"
    assert high.conflicting_source_ids == low.conflicting_source_ids


# --------------------------------------------------------------------------- #
# Attacks through the real service path
# --------------------------------------------------------------------------- #


def build_verified_execution():
    """Run the real analyze service once and return (case, provider, execution)."""

    case_input = make_case_input()
    provider = CapturingProvider()
    service = make_analyze_service(provider=provider, case_input=case_input)
    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))
    return case_input, provider, execution


def ledger_snapshot(case_id: str, state: AccountabilityState) -> LedgerSnapshot:
    return LedgerSnapshot(
        case_id=case_id,
        version=0,
        event_high_watermark=None,
        accountability_state=state,
        compiled_commitments=CompiledCommitments(commitments=(), compiled_from_evidence=True),
    )


class MemoryLedger:
    def __init__(self, snapshot: LedgerSnapshot) -> None:
        self._snapshot = snapshot

    def load(self, case_id: str):
        return self._snapshot if self._snapshot.case_id == case_id else None

    def save(self, snapshot, *, expected_version=None):  # pragma: no cover - not used here
        self._snapshot = snapshot
        return snapshot


class StaticCaseSource:
    def __init__(self, case_input: CaseInput) -> None:
        self._case_input = case_input

    def get_case(self, case_id: str) -> CaseInput:
        assert case_id == self._case_input.case_id
        return self._case_input


class StaticJourneyStore:
    def __init__(self, execution) -> None:
        self._journey = execution.response.extracted_journey

    def get_journey(self, case_id: str) -> ExtractedJourney:
        assert case_id == self._journey.case_id
        return self._journey


def build_evaluate_service():
    case_input, provider, execution = build_verified_execution()
    state = execution.response.accountability_state
    service = EvaluateService(
        case_source=StaticCaseSource(case_input),
        journey_source=StaticJourneyStore(execution),
        ledger_repository=MemoryLedger(ledger_snapshot(case_input.case_id, state)),
        budget_seconds=30.0,
    )
    return case_input, provider, execution, service


def test_analyze_ignores_a_model_image_assertion() -> None:
    case_input = make_case_input()
    claim = "图片显示产品完好、SKU 一致、问题清晰可见"

    def asserting_factory(model_input: SanitizedModelInput) -> CandidateExtraction:
        return CandidateExtraction(
            case_id=model_input.case_id,
            model_metadata=model_metadata(),
            observations=(claim,),
            source_trace=(
                SourceTrace(
                    field="observations[0]",
                    source_type="IMAGE",
                    source_id=case_input.evidence_images[0].evidence_id,
                ),
            ),
            candidate_promise_texts=(),
        )

    provider = CapturingProvider(factory=asserting_factory)
    service = make_analyze_service(provider=provider, case_input=case_input)
    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))

    observations = execution.response.extracted_journey.image_observations
    assert observations
    assert {item.readability for item in observations} == {"UNKNOWN"}
    assert {item.sku_match for item in observations} == {"UNKNOWN"}
    assert {item.issue_visible for item in observations} == {False}
    assert {item.product_identifiable for item in observations} == {False}
    # The claim is untrusted text; it must not become a server fact or a VALID status.
    assert execution.response.accountability_state.evidence_status == "NEED_HUMAN_REVIEW"


def test_analyze_ignores_a_model_declared_view_type() -> None:
    case_input = make_case_input()

    def view_type_factory(model_input: SanitizedModelInput) -> CandidateExtraction:
        return CandidateExtraction(
            case_id=model_input.case_id,
            model_metadata=model_metadata(),
            observations=("ISSUE_DETAIL",),
            source_trace=(
                SourceTrace(
                    field="observations[0]",
                    source_type="IMAGE",
                    source_id=case_input.evidence_images[0].evidence_id,
                ),
            ),
            candidate_promise_texts=(),
        )

    provider = CapturingProvider(factory=view_type_factory)
    service = make_analyze_service(provider=provider, case_input=case_input)
    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))
    # The journey view type is copied from the trusted CaseInput, never from the model.
    assert {
        item.view_type for item in execution.response.extracted_journey.image_observations
    } == {case_input.evidence_images[0].declared_view_type}


def test_analyze_quarantines_a_fictional_source_id() -> None:
    case_input = make_case_input()

    def fictional_factory(model_input: SanitizedModelInput) -> CandidateExtraction:
        return CandidateExtraction(
            case_id=model_input.case_id,
            model_metadata=model_metadata(),
            observations=("fabricated observation",),
            source_trace=(
                SourceTrace(
                    field="observations[0]",
                    source_type="IMAGE",
                    source_id="fictional-source-id",
                ),
            ),
            candidate_promise_texts=(),
        )

    provider = CapturingProvider(factory=fictional_factory)
    service = make_analyze_service(provider=provider, case_input=case_input)
    with pytest.raises(AnalysisModelOutputError) as blocked:
        asyncio.run(analyze_once(service, challenge_request(case_input)))
    assert blocked.value.code == "MODEL_OUTPUT_INVALID"
    assert blocked.value.retryable is False


def test_analyze_rejects_a_candidate_quoting_a_consumer_message_as_a_promise() -> None:
    case_input = case_input_with_pii()

    def consumer_quote_factory(model_input: SanitizedModelInput) -> CandidateExtraction:
        return CandidateExtraction(
            case_id=model_input.case_id,
            model_metadata=model_metadata(),
            observations=(),
            source_trace=(
                SourceTrace(
                    field="candidate_promise_texts[0]",
                    source_type="CHAT",
                    source_id="message-b30-001",
                ),
            ),
            candidate_promise_texts=("我的手机号是 [PHONE_REDACTED]，请联系我。",),
        )

    provider = CapturingProvider(factory=consumer_quote_factory)
    service = make_analyze_service(provider=provider, case_input=case_input)
    with pytest.raises(AnalysisModelOutputError):
        asyncio.run(analyze_once(service, challenge_request(case_input)))


def test_analyze_case_input_requires_an_explicit_true_challenge() -> None:
    case_input = make_case_input()
    for challenge_mode in (None, False):
        payload: dict[str, object] = {
            "case_id": case_input.case_id,
            "case_input": case_input.model_dump(mode="json"),
        }
        if challenge_mode is not None:
            payload["challenge_mode"] = challenge_mode
        with pytest.raises(ValueError, match="explicit true challenge_mode"):
            AnalyzeCaseRequest.model_validate(payload)


def test_a_consumer_only_conversation_creates_no_active_commitment_on_the_real_path() -> None:
    case_input = make_case_input(
        messages=(("CONSUMER", "你们答应我 48 小时内补发，怎么还没到？"),)
    )
    provider = CapturingProvider()
    service = make_analyze_service(provider=provider, case_input=case_input)
    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))

    state = execution.response.accountability_state
    assert state.active_commitments == []
    assert state.open_obligation is None
    assert state.service_progress_receipt is None
    events = execution.response.extracted_journey.promise_events
    assert all(event.activation_recommendation != "ACTIVE" for event in events)


def test_a_forged_agent_promise_without_a_deadline_creates_no_active_commitment() -> None:
    case_input = make_case_input(messages=(("AGENT", "这边已经帮您补发了，请耐心等待。"),))
    provider = CapturingProvider()
    service = make_analyze_service(provider=provider, case_input=case_input)
    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))
    state = execution.response.accountability_state
    assert state.active_commitments == []
    assert state.case_status in {"ACTION_REVIEW", "WAITING_FOR_CONSUMER"}


def test_real_agent_promise_with_an_open_ticket_becomes_active() -> None:
    case_input = make_case_input(
        tickets=(
            {
                "ticket_id": "ticket-b30-001",
                "ticket_type": "REPLACEMENT",
                "status": "OPEN",
                "assignee_id": "agent-b30-001",
                "executor_name": None,
                "replacement_logistics_number": None,
                "created_at": "2026-09-13T09:35:00+00:00",
                "completed_at": None,
                "source_sheet": "工作表1",
            },
        )
    )
    provider = CapturingProvider()
    service = make_analyze_service(provider=provider, case_input=case_input)
    execution = asyncio.run(analyze_once(service, challenge_request(case_input)))
    state = execution.response.accountability_state
    assert [item.promise_type for item in state.active_commitments] == ["REPLACEMENT_DISPATCH"]
    assert state.open_obligation is not None
    assert state.service_progress_receipt is not None


# --------------------------------------------------------------------------- #
# A34 -- challenge overrides are ignored unless the challenge is explicitly on
# --------------------------------------------------------------------------- #


def spoofed_evaluate_payload(action_type: str) -> dict:
    state = make_state()
    action = make_action(state, action_type)
    return {
        "case_id": state.case_id,
        "prepared_action": action.model_dump(mode="json"),
        "challenge_mode": False,
        "challenge_overrides": {
            "requested_scope": {**state.current_scope.model_dump(), "sku_id": "gift-sku"},
            "image_observation_overrides": [
                {
                    "evidence_id": "evidence-b30-001",
                    "readability": "HIGH",
                    "sku_match": "MATCH",
                    "issue_visible": True,
                }
            ],
        },
        "accountability_state": {"case_id": "forged"},
        "evidence_status": "MISMATCHED",
        "active_commitments": ["forged"],
        "prohibited_actions": ["CLOSE_BEFORE_RESOLUTION"],
        "current_scope": {"order_id": "forged"},
    }


@pytest.mark.parametrize("action_type", ACTION_TYPES)
def test_a34_spoofed_compatibility_fields_change_nothing(action_type: str) -> None:
    request = EvaluateActionRequest.from_contract(spoofed_evaluate_payload(action_type))
    assert request.challenge_mode is False
    # The DTO keeps the raw payload for audit, but the frozen fields stay authoritative.
    assert request.accountability_state == {"case_id": "forged"}
    assert request.evidence_status == "MISMATCHED"

    state = make_state()
    clean = EvaluateActionRequest.from_contract(
        {
            "case_id": state.case_id,
            "prepared_action": make_action(state, action_type).model_dump(mode="json"),
        }
    )
    assert evaluate_decision(state, request.prepared_action) == evaluate_decision(
        state, clean.prepared_action
    )


@pytest.mark.parametrize("status,issue,action_type,prohibited", MATRIX)
def test_a34_override_payloads_never_change_the_matrix_outcome(
    status: str, issue: str, action_type: str, prohibited: bool
) -> None:
    state, action = build_matrix_inputs(status, issue, action_type, prohibited)
    baseline = evaluate_decision(state, action)
    request = EvaluateActionRequest.from_contract(
        {
            "case_id": state.case_id,
            "prepared_action": action.model_dump(mode="json"),
            "challenge_mode": False,
            "challenge_overrides": {
                "requested_scope": {
                    **state.current_scope.model_dump(),
                    "issue_type": "PACKAGE_DAMAGE",
                }
            },
            "evidence_status": "VALID",
            "prohibited_actions": [],
        }
    )
    assert request.challenge_mode is False
    assert signature(evaluate_decision(state, request.prepared_action)) == signature(baseline)


def _override_request(case_id: str, evidence_id: str, *, challenge_mode: bool) -> EvaluateActionRequest:
    return EvaluateActionRequest.from_contract(
        {
            "case_id": case_id,
            "prepared_action": make_action(
                make_state(), "CHECK_REPLACEMENT_PROGRESS"
            ).model_dump(mode="json"),
            "challenge_mode": challenge_mode,
            "challenge_overrides": {
                "image_observation_overrides": [
                    {
                        "evidence_id": evidence_id,
                        "readability": "HIGH",
                        "sku_match": "MATCH",
                        "issue_visible": True,
                    }
                ]
            },
        }
    )


def test_a34_service_level_ignore_with_an_enabling_control() -> None:
    case_input, _provider, _execution, service = build_evaluate_service()
    evidence_id = case_input.evidence_images[0].evidence_id

    clean = service.evaluate_with_trace(_override_request(case_input.case_id, evidence_id, challenge_mode=False))
    spoofed = service.evaluate_with_trace(_override_request(case_input.case_id, evidence_id, challenge_mode=False))
    assert clean.result.challenge_mode is False
    assert spoofed.result.challenge_mode is False
    assert signature(spoofed.result) == signature(clean.result)
    assert spoofed.evidence.evidence_status == clean.evidence.evidence_status

    # Control: with the challenge explicitly enabled the very same override payload is
    # applied, so the property above is a real ignore and not an inert payload.
    enabled = service.evaluate_with_trace(
        _override_request(case_input.case_id, evidence_id, challenge_mode=True)
    )
    assert enabled.result.challenge_mode is True
    assert {reason.code for reason in enabled.evidence.reasons} != {
        reason.code for reason in clean.evidence.reasons
    }


def test_a34_challenge_override_naming_unknown_evidence_is_refused() -> None:
    case_input, _provider, _execution, service = build_evaluate_service()
    with pytest.raises(EvaluateInputError) as blocked:
        service.evaluate_with_trace(
            _override_request(case_input.case_id, "evidence-not-registered", challenge_mode=True)
        )
    assert "unknown evidence" in str(blocked.value)


@pytest.mark.parametrize("action_type", ["CLOSE_CASE", "SHIFT_FOLLOW_UP_TO_CONSUMER"])
def test_prohibited_actions_are_refused_on_the_real_service_path(action_type: str) -> None:
    case_input, _provider, execution, service = build_evaluate_service()
    state = execution.response.accountability_state
    assert "CLOSE_BEFORE_RESOLUTION" in state.prohibited_actions
    assert "SHIFT_FOLLOW_UP_TO_CONSUMER" in state.prohibited_actions
    request = EvaluateActionRequest.from_contract(
        {
            "case_id": case_input.case_id,
            "prepared_action": make_action(state, action_type).model_dump(mode="json"),
            "challenge_mode": False,
            "prohibited_actions": [],
            "accountability_state": {"prohibited_actions": []},
        }
    )
    with pytest.raises(ProhibitedActionError) as blocked:
        service.evaluate(request)
    assert blocked.value.http_status == 400
    assert blocked.value.evaluation.rule_id == "P0_PROHIBITED_ACTION"
    assert blocked.value.evaluation.suppressed_rule_ids == ("H1",)


# --------------------------------------------------------------------------- #
# Composition invariants: no backdoor, no open documentation, frozen four routes
# --------------------------------------------------------------------------- #


def test_composition_mounts_exactly_the_frozen_four_business_routes() -> None:
    settings = Settings()
    runtime = build_runtime(settings, overrides=RuntimeOverrides())
    app = compose_application(settings, runtime=runtime)

    inventory = installed_route_inventory(app)
    posts = sorted(
        (str(entry["method"]), str(entry["path"]))
        for entry in inventory
        if entry["method"] == "POST"
    )
    assert posts == sorted(
        [
            ("POST", "/api/cases/analyze"),
            ("POST", "/api/actions/evaluate"),
            ("POST", "/api/resolutions/approve"),
            ("POST", "/api/events/shipment"),
        ]
    )
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
    assert not any(getattr(route, "path", None) == "/openapi.json" for route in app.routes)


def test_environment_is_the_batch_isolated_interpreter() -> None:
    """Criterion 4 at the level the test process can actually observe."""

    assert sys.prefix != sys.base_prefix, "the suite must run in an isolated virtual environment"
    assert Path(sys.executable).name.lower().startswith("python")
    assert sys.version_info[:2] == (3, 13)


def test_mutation_marker_selects_the_negative_controls() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(TEST_FILE),
            "--collect-only",
            "-q",
            "-m",
            "mutation",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    selected = [line for line in completed.stdout.splitlines() if "::test_mutation_" in line]
    assert len(selected) >= 3, completed.stdout


def test_the_batch_security_matrix_documents_this_seed() -> None:
    report = REPO_ROOT / "reports" / "batches" / "BATCH-30" / "security-matrix.json"
    assert report.is_file(), "security-matrix.json is a mandatory batch output"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["random_seed"] == SEED
    assert payload["combination_count"] == len(MATRIX) == 108
    assert payload["perturbations_per_combination"] == PERTURBATIONS_PER_CELL
