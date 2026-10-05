"""Authoritative, read-only evaluation of a prepared action.

The request contributes an action and an opt-in challenge only.  Case facts,
the verified extraction, and the current ledger snapshot remain server-owned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from covenia_b.commitments.compiler import compile_case_input
from covenia_b.commitments.models import CommitmentPolicy, PromiseAction
from covenia_b.domain.types import (
    CaseInput,
    ChallengeOverrides,
    EvaluateActionRequest,
    ExtractedJourney,
    RuntimeMetrics,
    Scope,
)
from covenia_b.evidence.aggregation import (
    CandidateEvidence,
    CurrentEvidenceContext,
    EvidenceAggregation,
    aggregate_evidence,
)
from covenia_b.ports.contracts import CaseSource, LedgerRepository, MetricsSink
from covenia_b.ports.errors import CaseNotFound, LedgerUnavailable, MetricsUnavailable
from covenia_b.resolutions.planner import ResolutionPlanningError, plan_resolution
from covenia_b.rules import ProhibitedActionError, evaluate_decision
from covenia_b.state import build_accountability_state

from .analyze import _EvaluationClock, _persisted_ledger_from_snapshot

_DEFAULT_POLICY = CommitmentPolicy(
    policy_id="DEMO_POLICY_PACKAGE_DAMAGE_V1",
    allowed_policy_requirement_ids=frozenset({"DEMO_POLICY_PACKAGE_DAMAGE_V1"}),
    allowed_standard_actions=frozenset({PromiseAction.REPLACEMENT_DISPATCH}),
)


class VerifiedJourneySource(Protocol):
    """Return the server-validated extraction retained for an analysed case."""

    def get_journey(self, case_id: str) -> ExtractedJourney: ...


class EvaluateServiceError(RuntimeError):
    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, *, request_id: str) -> None:
        super().__init__(message)
        self.request_id = request_id


class EvaluateInputError(EvaluateServiceError):
    code = "VALIDATION_ERROR"


class EvaluateNotAnalyzed(EvaluateInputError):
    """The endpoint never invents facts when analysis has not completed."""


class EvaluateBudgetExceeded(EvaluateServiceError):
    retryable = True


class EvaluateInfrastructureError(EvaluateServiceError):
    retryable = True


@dataclass(frozen=True, slots=True)
class EvaluateExecution:
    result: object
    request_id: str
    evidence: EvidenceAggregation


class EvaluateService:
    """Rebuild a non-persisted decision snapshot from authoritative facts."""

    def __init__(
        self,
        *,
        case_source: CaseSource,
        journey_source: VerifiedJourneySource,
        ledger_repository: LedgerRepository,
        metrics_sink: MetricsSink | None = None,
        commitment_policy: CommitmentPolicy = _DEFAULT_POLICY,
        request_id_factory: Callable[[], str] | None = None,
        budget_seconds: float = 10.0,
    ) -> None:
        if budget_seconds <= 0:
            raise ValueError("budget_seconds must be positive")
        self._case_source = case_source
        self._journey_source = journey_source
        self._ledger_repository = ledger_repository
        self._metrics_sink = metrics_sink
        self._commitment_policy = commitment_policy
        self._request_id_factory = request_id_factory or (lambda: f"evaluate-{uuid4().hex}")
        self._budget_seconds = budget_seconds

    def evaluate(self, request: EvaluateActionRequest, *, request_id: str | None = None):
        return self.evaluate_with_trace(request, request_id=request_id).result

    def evaluate_with_trace(
        self, request: EvaluateActionRequest, *, request_id: str | None = None
    ) -> EvaluateExecution:
        correlation_id = self._request_id(request_id)
        started = perf_counter()
        try:
            if not isinstance(request, EvaluateActionRequest):
                raise EvaluateInputError(
                    "evaluate requires a valid action request", request_id=correlation_id
                )
            case = self._load_case(request, correlation_id)
            self._within_budget(started, correlation_id)
            snapshot = self._ledger_repository.load(case.case_id)
            if snapshot is None or snapshot.accountability_state is None:
                raise EvaluateNotAnalyzed(
                    "case must be analysed before an action can be evaluated",
                    request_id=correlation_id,
                )
            journey = self._load_verified_journey(case, correlation_id)
            journey = self._apply_challenge(journey, request, correlation_id)
            evidence = _aggregate(case, journey)
            compilation = compile_case_input(
                case,
                self._commitment_policy,
                _EvaluationClock(_parse_time(case.evaluation_time)),
            )
            rebuilt = build_accountability_state(
                case_input=case,
                journey=journey,
                evidence=evidence,
                compilation=compilation,
                persisted=_persisted_ledger_from_snapshot(snapshot),
                request_id=correlation_id,
                actor="EVALUATE_SERVICE",
            )
            evaluation = evaluate_decision(
                rebuilt,
                request.prepared_action,
                challenge_mode=request.challenge_mode,
                evidence=evidence,
            )
            self._within_budget(started, correlation_id)
            evaluation.require_permitted_action()
            resolution = plan_resolution(
                evaluation,
                request.prepared_action,
                case,
                compilation,
                evidence=evidence,
            )
            metrics = RuntimeMetrics(
                input_tokens=0,
                output_tokens=0,
                inference_latency_ms=int((perf_counter() - started) * 1000),
                rule_substitution_count=0,
            )
            if self._metrics_sink is not None:
                self._metrics_sink.record(endpoint="evaluate", metrics=metrics)
            result = evaluation.to_decision_result(
                resolution_path=resolution, runtime_metrics=metrics
            )
            result.to_contract()
            return EvaluateExecution(result=result, request_id=correlation_id, evidence=evidence)
        except ProhibitedActionError:
            raise
        except EvaluateServiceError:
            raise
        except (CaseNotFound, LedgerUnavailable, MetricsUnavailable) as error:
            raise EvaluateInfrastructureError(
                "authoritative evaluation facts are unavailable", request_id=correlation_id
            ) from error
        except (ResolutionPlanningError, TypeError, ValueError) as error:
            raise EvaluateInputError(
                "authoritative facts cannot produce a legal evaluation", request_id=correlation_id
            ) from error

    def _load_case(self, request: EvaluateActionRequest, request_id: str) -> CaseInput:
        try:
            case = self._case_source.get_case(request.case_id)
        except (CaseNotFound, ValueError) as error:
            raise EvaluateInputError("case was not found", request_id=request_id) from error
        if not isinstance(case, CaseInput) or case.case_id != request.case_id:
            raise EvaluateInputError("case source returned an invalid case", request_id=request_id)
        if request.evaluation_time is not None:
            case = case.model_copy(update={"evaluation_time": request.evaluation_time})
        return case

    def _load_verified_journey(self, case: CaseInput, request_id: str) -> ExtractedJourney:
        try:
            journey = self._journey_source.get_journey(case.case_id)
        except (CaseNotFound, ValueError) as error:
            raise EvaluateNotAnalyzed(
                "verified extraction is unavailable", request_id=request_id
            ) from error
        if not isinstance(journey, ExtractedJourney) or journey.case_id != case.case_id:
            raise EvaluateNotAnalyzed(
                "verified extraction does not bind to this case", request_id=request_id
            )
        return journey

    @staticmethod
    def _apply_challenge(
        journey: ExtractedJourney,
        request: EvaluateActionRequest,
        request_id: str,
    ) -> ExtractedJourney:
        if not request.challenge_mode or request.challenge_overrides is None:
            return journey
        overrides = ChallengeOverrides.model_validate(request.challenge_overrides)
        if overrides.image_observation_overrides is None:
            return journey
        by_id = {observation.evidence_id: observation for observation in journey.image_observations}
        if len(by_id) != len(journey.image_observations):
            raise EvaluateInputError(
                "verified extraction contains duplicate evidence", request_id=request_id
            )
        for override in overrides.image_observation_overrides:
            prior = by_id.get(override.evidence_id)
            if prior is None:
                raise EvaluateInputError(
                    "challenge override names unknown evidence", request_id=request_id
                )
            updates: dict[str, object] = {"readability": override.readability}
            if override.sku_match is not None:
                updates["sku_match"] = override.sku_match
            if override.issue_visible is not None:
                updates["issue_visible"] = override.issue_visible
            by_id[override.evidence_id] = prior.model_copy(update=updates)
        return journey.model_copy(
            update={
                "image_observations": [
                    by_id[item.evidence_id] for item in journey.image_observations
                ]
            }
        )

    def _within_budget(self, started: float, request_id: str) -> None:
        if perf_counter() - started > self._budget_seconds:
            raise EvaluateBudgetExceeded(
                "evaluate exceeded its 10 second budget", request_id=request_id
            )

    def _request_id(self, requested: str | None) -> str:
        value = self._request_id_factory() if requested is None else requested
        if not isinstance(value, str) or not value.strip():
            raise ValueError("request_id must be a non-empty string")
        return value


def _aggregate(case: CaseInput, journey: ExtractedJourney) -> EvidenceAggregation:
    item = next(
        (
            candidate
            for candidate in case.order.items
            if candidate.fulfillment_item_id == case.current_issue.fulfillment_item_id
            and candidate.sku_id == case.current_issue.sku_id
        ),
        None,
    )
    if item is None:
        raise ValueError("current issue has no matching order item")
    return aggregate_evidence(
        CurrentEvidenceContext(
            scope=Scope(
                order_id=case.order.order_id,
                fulfillment_item_id=case.current_issue.fulfillment_item_id,
                sku_id=case.current_issue.sku_id,
                issue_type=case.current_issue.issue_type,
            ),
            item_role=item.item_role,
            affected_component=case.current_issue.affected_component,
        ),
        CandidateEvidence(
            candidate_id=journey.model_metadata.run_id,
            extracted_scope=journey.extracted_scope,
            image_observations=tuple(journey.image_observations),
        ),
    )


def _parse_time(value: str):
    from datetime import datetime

    parsed = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("evaluation time must be timezone-aware")
    return parsed
