"""Transport-free analysis orchestration for a single authoritative fact chain.

The service intentionally accepts only frozen ports and domain DTOs.  It does
not create HTTP envelopes, choose a model endpoint, or publish a decision.  A
later HTTP batch can translate ``AnalysisServiceError`` while preserving the
request ID and the exact failure class recorded here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from covenia_b.commitments.compiler import compile_case_input
from covenia_b.commitments.models import (
    CommitmentCompilation,
    CommitmentPolicy,
    PromiseAction,
)
from covenia_b.domain.time import format_rfc3339_timestamp
from covenia_b.domain.types import (
    AccountabilityState,
    AnalyzeCaseRequest,
    AnalyzeCaseResponse,
    CandidateExtraction,
    CompiledCommitment,
    CompiledCommitments,
    ExtractedJourney,
    ImageObservation,
    LedgerSnapshot,
    PromiseEvent,
    RuntimeMetrics,
    Scope,
    SourceTrace,
)
from covenia_b.evidence.aggregation import (
    CandidateEvidence,
    CurrentEvidenceContext,
    EvidenceAggregation,
    aggregate_evidence,
)
from covenia_b.model.extraction import CandidateSchemaError, validate_candidate_schema
from covenia_b.model.source_validation import (
    SourceValidationError,
    SourceValidationSummary,
    validate_candidate_sources,
)
from covenia_b.ports.contracts import LedgerRepository, MetricsSink, ModelProvider
from covenia_b.ports.errors import (
    LedgerConflict,
    LedgerUnavailable,
    MetricsUnavailable,
    ModelOutputInvalid,
    ModelUnavailable,
)
from covenia_b.privacy import UnsafeModelInputError, extract_with_privacy_boundary, redact_text
from covenia_b.state import (
    ApprovedResolution,
    FulfillmentProgress,
    PersistedLedger,
    build_accountability_state,
)

from .fact_loader import FactLoader, FactLoadingError, LoadedAnalysisFacts

ProviderMode = Literal["LIVE", "TEST_DOUBLE"]

_DEFAULT_POLICY = CommitmentPolicy(
    policy_id="DEMO_POLICY_PACKAGE_DAMAGE_V1",
    allowed_policy_requirement_ids=frozenset({"DEMO_POLICY_PACKAGE_DAMAGE_V1"}),
    allowed_standard_actions=frozenset({PromiseAction.REPLACEMENT_DISPATCH}),
)


class AnalysisServiceError(RuntimeError):
    """Stable, transport-neutral failure with the request context retained."""

    code: Literal[
        "VALIDATION_ERROR", "MODEL_UNAVAILABLE", "MODEL_OUTPUT_INVALID", "INTERNAL_ERROR"
    ]
    retryable: bool

    def __init__(
        self,
        message: str,
        *,
        request_id: str,
        runtime_metrics: RuntimeMetrics,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.runtime_metrics = runtime_metrics
        self.retryable = retryable


class AnalysisInputError(AnalysisServiceError):
    code = "VALIDATION_ERROR"


class AnalysisModelUnavailable(AnalysisServiceError):
    code = "MODEL_UNAVAILABLE"


class AnalysisModelOutputError(AnalysisServiceError):
    code = "MODEL_OUTPUT_INVALID"


class AnalysisInfrastructureError(AnalysisServiceError):
    code = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class AnalysisExecution:
    """Response plus safe orchestration facts for an adapter or implementation trace."""

    response: AnalyzeCaseResponse
    request_id: str
    provider_mode: ProviderMode
    used_persisted_state: bool
    persisted: bool
    source_summary: SourceValidationSummary
    pii_masked_count: int
    provider_image_binding_verified: bool

    def redacted_trace(self) -> dict[str, object]:
        """Return source-free implementation evidence; no prompt, PII, or image bytes."""

        return {
            "case_id": self.response.extracted_journey.case_id,
            "request_id": self.request_id,
            "provider_mode": self.provider_mode,
            "used_persisted_state": self.used_persisted_state,
            "persisted": self.persisted,
            "pii_masked_count": self.pii_masked_count,
            "provider_image_binding_verified": self.provider_image_binding_verified,
            "source_validation": {
                "trusted_source_count": self.source_summary.trusted_source_count,
                "traced_field_count": self.source_summary.traced_field_count,
                "agent_quote_count": self.source_summary.agent_quote_count,
                "image_observation_count": self.source_summary.image_observation_count,
            },
            "runtime_metrics": self.response.runtime_metrics.model_dump(mode="json"),
            "case_status": self.response.accountability_state.case_status,
            "evidence_status": self.response.accountability_state.evidence_status,
        }


@dataclass(frozen=True, slots=True)
class _EvaluationClock:
    """Use the server-bound analysis time for deterministic commitment compilation."""

    instant: datetime

    def now(self) -> datetime:
        return self.instant


class AnalyzeService:
    """Orchestrate facts → safe candidate → server facts → accountability state."""

    def __init__(
        self,
        *,
        fact_loader: FactLoader,
        provider: ModelProvider,
        ledger_repository: LedgerRepository | None,
        commitment_policy: CommitmentPolicy = _DEFAULT_POLICY,
        metrics_sink: MetricsSink | None = None,
        provider_mode: ProviderMode = "TEST_DOUBLE",
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if provider_mode not in {"LIVE", "TEST_DOUBLE"}:
            raise ValueError("provider_mode must be LIVE or TEST_DOUBLE")
        self._fact_loader = fact_loader
        self._provider = provider
        self._ledger_repository = ledger_repository
        self._commitment_policy = commitment_policy
        self._metrics_sink = metrics_sink
        self._provider_mode = provider_mode
        self._request_id_factory = request_id_factory or (lambda: f"analyze-{uuid4().hex}")

    async def analyze(
        self,
        request: AnalyzeCaseRequest,
        *,
        request_id: str | None = None,
    ) -> AnalyzeCaseResponse:
        """Return only the frozen response projection for a later transport adapter."""

        return (await self.analyze_with_trace(request, request_id=request_id)).response

    async def analyze_with_trace(
        self,
        request: AnalyzeCaseRequest,
        *,
        request_id: str | None = None,
    ) -> AnalysisExecution:
        """Run one analysis without allowing model output to own any state transition."""

        correlation_id = self._request_id(request_id)
        zero_metrics = _zero_metrics()
        try:
            loaded = self._fact_loader.load(request)
            if self._provider_mode == "LIVE" and not loaded.provider_image_binding_verified:
                raise FactLoadingError("live provider requires verified image-to-bytes binding")

            candidate, metrics = await self._extract_candidate(loaded)
            source_summary = self._validate_candidate(candidate, loaded)
            compilation = _compile_from_server_facts(
                loaded.case_input,
                policy=self._commitment_policy,
            )
            journey = _enrich_extracted_journey(
                case_input=loaded.case_input,
                candidate=candidate,
                compilation=compilation,
            )
            evidence = _aggregate_server_evidence(loaded.case_input, journey, candidate)
            prior = self._load_prior_snapshot(loaded, correlation_id, metrics)
            state = build_accountability_state(
                case_input=loaded.case_input,
                journey=journey,
                evidence=evidence,
                compilation=compilation,
                request_id=correlation_id,
                persisted=_persisted_ledger_from_snapshot(prior),
                actor="ANALYZE_SERVICE",
            )
            metrics = self._record_or_read_metrics(metrics)
            saved_state, did_persist = self._persist_state(
                loaded=loaded,
                prior=prior,
                state=state,
                compilation=compilation,
                request_id=correlation_id,
                metrics=metrics,
            )
            response = AnalyzeCaseResponse(
                extracted_journey=journey,
                accountability_state=saved_state,
                model_metadata=journey.model_metadata,
                runtime_metrics=metrics,
            )
            response.to_contract()
            return AnalysisExecution(
                response=response,
                request_id=correlation_id,
                provider_mode=self._provider_mode,
                used_persisted_state=prior is not None,
                persisted=did_persist,
                source_summary=source_summary,
                pii_masked_count=loaded.sanitization.pii_masked_count,
                provider_image_binding_verified=loaded.provider_image_binding_verified,
            )
        except FactLoadingError as error:
            raise AnalysisInputError(
                "analysis input could not be safely loaded",
                request_id=correlation_id,
                runtime_metrics=zero_metrics,
                retryable=False,
            ) from error
        except UnsafeModelInputError as error:
            raise AnalysisInputError(
                "analysis input failed the privacy boundary",
                request_id=correlation_id,
                runtime_metrics=zero_metrics,
                retryable=False,
            ) from error
        except ModelUnavailable as error:
            raise AnalysisModelUnavailable(
                "model provider is unavailable",
                request_id=correlation_id,
                runtime_metrics=_failure_metrics(self._provider_mode),
                retryable=getattr(error, "retryable", True),
            ) from error
        except (ModelOutputInvalid, CandidateSchemaError, SourceValidationError) as error:
            raise AnalysisModelOutputError(
                "model output could not be accepted",
                request_id=correlation_id,
                runtime_metrics=_failure_metrics(self._provider_mode),
                retryable=False,
            ) from error
        except (LedgerConflict, LedgerUnavailable, MetricsUnavailable) as error:
            raise AnalysisInfrastructureError(
                "analysis infrastructure is unavailable",
                request_id=correlation_id,
                runtime_metrics=zero_metrics,
                retryable=True,
            ) from error
        except AnalysisServiceError:
            raise
        except Exception as error:
            raise AnalysisInfrastructureError(
                "analysis could not complete safely",
                request_id=correlation_id,
                runtime_metrics=zero_metrics,
                retryable=False,
            ) from error

    async def _extract_candidate(
        self,
        loaded: LoadedAnalysisFacts,
    ) -> tuple[CandidateExtraction, RuntimeMetrics]:
        started_ns = perf_counter_ns()
        candidate = await extract_with_privacy_boundary(self._provider, loaded.sanitization)
        elapsed_ms = max(0, (perf_counter_ns() - started_ns) // 1_000_000)
        if self._provider_mode == "TEST_DOUBLE" or candidate.model_metadata.cached_result:
            elapsed_ms = 0
        return candidate, RuntimeMetrics(
            input_tokens=0,
            output_tokens=0,
            inference_latency_ms=elapsed_ms,
            rule_substitution_count=0,
        )

    @staticmethod
    def _validate_candidate(
        candidate: CandidateExtraction,
        loaded: LoadedAnalysisFacts,
    ) -> SourceValidationSummary:
        validated = validate_candidate_schema(candidate, loaded.sanitization.model_input)
        return validate_candidate_sources(validated, loaded.sanitization.model_input)

    def _load_prior_snapshot(
        self,
        loaded: LoadedAnalysisFacts,
        request_id: str,
        metrics: RuntimeMetrics,
    ) -> LedgerSnapshot | None:
        if loaded.challenge_mode:
            return None
        if self._ledger_repository is None:
            raise AnalysisInfrastructureError(
                "normal analysis requires a ledger repository",
                request_id=request_id,
                runtime_metrics=metrics,
                retryable=True,
            )
        prior = self._ledger_repository.load(loaded.case_input.case_id)
        if prior is not None and prior.case_id != loaded.case_input.case_id:
            raise LedgerUnavailable("ledger returned a snapshot for another case")
        return prior

    def _record_or_read_metrics(self, measured: RuntimeMetrics) -> RuntimeMetrics:
        if self._metrics_sink is None:
            return measured
        existing = getattr(self._metrics_sink, "runtime_metrics", None)
        if isinstance(existing, RuntimeMetrics):
            return existing
        self._metrics_sink.record(endpoint="analyze", metrics=measured)
        return measured

    def _persist_state(
        self,
        *,
        loaded: LoadedAnalysisFacts,
        prior: LedgerSnapshot | None,
        state: AccountabilityState,
        compilation: CommitmentCompilation,
        request_id: str,
        metrics: RuntimeMetrics,
    ) -> tuple[AccountabilityState, bool]:
        if loaded.challenge_mode:
            return state, False
        if self._ledger_repository is None:
            raise AnalysisInfrastructureError(
                "normal analysis requires a ledger repository",
                request_id=request_id,
                runtime_metrics=metrics,
                retryable=True,
            )
        snapshot = LedgerSnapshot(
            case_id=loaded.case_input.case_id,
            version=0 if prior is None else prior.version,
            event_high_watermark=None if prior is None else prior.event_high_watermark,
            accountability_state=state,
            compiled_commitments=_compiled_commitments(compilation),
        )
        saved = self._ledger_repository.save(
            snapshot,
            expected_version=None if prior is None else prior.version,
        )
        if saved.accountability_state is None:
            raise LedgerUnavailable("ledger discarded the analyzed accountability state")
        return saved.accountability_state, True

    def _request_id(self, requested: str | None) -> str:
        value = self._request_id_factory() if requested is None else requested
        if not isinstance(value, str) or not value.strip():
            raise ValueError("request_id must be a non-empty string")
        return value


def _compile_from_server_facts(
    case_input: object,
    *,
    policy: CommitmentPolicy,
) -> CommitmentCompilation:
    if not hasattr(case_input, "evaluation_time"):
        raise ValueError("case input lacks an evaluation time")
    evaluation_time = _parse_timestamp(case_input.evaluation_time)
    return compile_case_input(case_input, policy, _EvaluationClock(evaluation_time))


def _enrich_extracted_journey(
    *,
    case_input: object,
    candidate: CandidateExtraction,
    compilation: CommitmentCompilation,
) -> ExtractedJourney:
    if not hasattr(case_input, "current_issue") or not hasattr(case_input, "order"):
        raise ValueError("case input lacks source facts")
    scope = _scope_from_case(case_input)
    observations = _server_image_observations(case_input)
    promise_events = _server_promise_events(case_input, compilation)
    source_trace = _source_trace(
        case_input=case_input,
        candidate=candidate,
        image_observations=observations,
        promise_events=promise_events,
    )
    fallback_source_id = case_input.conversation[0].message_id
    return ExtractedJourney(
        case_id=case_input.case_id,
        completed_actions={
            "issue_explained": any(
                message.speaker == "CONSUMER" and bool(message.text.strip())
                for message in case_input.conversation
            ),
            "order_verified": True,
            "evidence_submitted": bool(case_input.evidence_images),
        },
        promise_events=list(promise_events),
        image_observations=list(observations),
        extracted_scope=scope,
        journey_understanding={
            "consumer_intent": "REQUEST_TRACEABLE_SERVICE_REVIEW",
            "experience_expression": "MODEL_CANDIDATE_REMAINS_UNTRUSTED",
            "service_cause": "SERVER_FACTS_REQUIRE_EVIDENCE_AGGREGATION",
            "latent_need": "TRACEABLE_STATUS_UPDATE",
            "cooperation_willingness": "UNKNOWN",
            "action_impact": "REQUIRES_SERVER_EVIDENCE_AGGREGATION",
            "source_ids": [fallback_source_id],
        },
        source_trace=list(source_trace),
        model_metadata=candidate.model_metadata,
    )


def _scope_from_case(case_input: object) -> Scope:
    current = case_input.current_issue
    return Scope(
        order_id=case_input.order.order_id,
        fulfillment_item_id=current.fulfillment_item_id,
        sku_id=current.sku_id,
        issue_type=current.issue_type,
    )


def _server_image_observations(case_input: object) -> tuple[ImageObservation, ...]:
    """Keep image content claims unknown until a later approved observation mapping exists."""

    return tuple(
        ImageObservation(
            evidence_id=image.evidence_id,
            readability="UNKNOWN",
            product_identifiable=False,
            sku_match="UNKNOWN",
            product_role="UNKNOWN",
            issue_visible=False,
            affected_component="UNKNOWN",
            view_type=image.declared_view_type,
            coverage=[],
            integrity_concern=False,
            hygiene_risk_signal="UNKNOWN",
            confidence=0.0,
        )
        for image in case_input.evidence_images
    )


def _server_promise_events(
    case_input: object,
    compilation: CommitmentCompilation,
) -> tuple[PromiseEvent, ...]:
    messages = {message.message_id: message for message in case_input.conversation}
    events: list[PromiseEvent] = []
    for promise in compilation.promises:
        message = messages.get(promise.source_message_id)
        if message is None:
            raise ValueError("compiled commitment has no source message")
        events.append(
            PromiseEvent(
                raw_text=redact_text(promise.raw_text).text,
                promise_type=promise.action.value,
                commitment_class=promise.commitment_class.value,
                activation_recommendation=promise.activation_status.value,
                conditions=[reason.value for reason in promise.reasons],
                committed_at=message.timestamp,
                deadline=_format_optional_timestamp(promise.deadline),
                confidence=1.0,
                source_ids=[promise.source_message_id],
            )
        )
    return tuple(events)


def _source_trace(
    *,
    case_input: object,
    candidate: CandidateExtraction,
    image_observations: tuple[ImageObservation, ...],
    promise_events: tuple[PromiseEvent, ...],
) -> tuple[SourceTrace, ...]:
    entries: dict[tuple[str, str, str], SourceTrace] = {
        (trace.field, trace.source_type, trace.source_id): trace for trace in candidate.source_trace
    }

    def add(field: str, source_type: str, source_id: str) -> None:
        trace = SourceTrace(field=field, source_type=source_type, source_id=source_id)
        entries[(trace.field, trace.source_type, trace.source_id)] = trace

    add("completed_actions.order_verified", "ORDER", case_input.order.order_id)
    add("extracted_scope", "ORDER", case_input.order.order_id)
    first_message = case_input.conversation[0]
    add("journey_understanding", "CHAT", first_message.message_id)
    for index, image in enumerate(image_observations):
        add(f"image_observations[{index}]", "IMAGE", image.evidence_id)
    for index, event in enumerate(promise_events):
        add(f"promise_events[{index}]", "CHAT", event.source_ids[0])
    return tuple(entries[key] for key in sorted(entries))


def _aggregate_server_evidence(
    case_input: object,
    journey: ExtractedJourney,
    candidate: CandidateExtraction,
) -> EvidenceAggregation:
    item = next(
        (
            value
            for value in case_input.order.items
            if value.fulfillment_item_id == case_input.current_issue.fulfillment_item_id
            and value.sku_id == case_input.current_issue.sku_id
        ),
        None,
    )
    if item is None:
        raise ValueError("current issue has no matching order item")
    return aggregate_evidence(
        CurrentEvidenceContext(
            scope=_scope_from_case(case_input),
            item_role=item.item_role,
            affected_component=case_input.current_issue.affected_component,
        ),
        CandidateEvidence(
            candidate_id=candidate.model_metadata.run_id,
            extracted_scope=journey.extracted_scope,
            image_observations=tuple(journey.image_observations),
        ),
    )


def _compiled_commitments(compilation: CommitmentCompilation) -> CompiledCommitments:
    return CompiledCommitments(
        commitments=tuple(
            CompiledCommitment(
                source_promise_text=promise.raw_text,
                commitment_class=promise.commitment_class.value,
                activation_status=promise.activation_status.value,
                deadline=_format_optional_timestamp(promise.deadline),
                next_check_at=_format_optional_timestamp(promise.next_check_at),
            )
            for promise in compilation.promises
        ),
        compiled_from_evidence=True,
    )


def _persisted_ledger_from_snapshot(snapshot: LedgerSnapshot | None) -> PersistedLedger | None:
    if snapshot is None:
        return None
    state = snapshot.accountability_state
    if state is None:
        return PersistedLedger(initialized=True)

    obligation = state.open_obligation
    receipt = state.service_progress_receipt
    latest_update = (
        _parse_timestamp(receipt.latest_update_at)
        if receipt is not None
        else _latest_audit_time(state)
    )
    approved: ApprovedResolution | None = None
    fulfillment: FulfillmentProgress | None = None
    if obligation is not None:
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for item in state.active_commitments
                    for source_id in item.source_ids
                }
            )
        ) or ("persisted-accountability",)
        first = state.active_commitments[0] if state.active_commitments else None
        approved = ApprovedResolution(
            deadline=_parse_timestamp(obligation.deadline),
            next_check_at=_parse_timestamp(obligation.next_check_at),
            executor=obligation.executor,
            recovery_if_missed=(
                receipt.recovery_if_missed
                if receipt is not None
                else "品牌将主动催办并通知新的处理时间"
            ),
            raw_text=(
                first.raw_text
                if first is not None
                else "Persisted responsibility projection"
            ),
            promise_type=(first.promise_type if first is not None else "REPLACEMENT_DISPATCH"),
            source_ids=source_ids,
        )
        fulfillment = FulfillmentProgress(
            milestone=obligation.milestone,
            status=obligation.status,
            event_at=latest_update or _parse_timestamp(obligation.deadline),
            executor=obligation.executor,
            receipt_id=None if receipt is None else receipt.receipt_id,
        )
    return PersistedLedger(
        initialized=True,
        approved_resolution=approved,
        fulfillment_progress=fulfillment,
        prior_commitments=tuple(state.active_commitments),
        audit_trail=tuple(state.audit_trail),
        latest_update_at=latest_update,
        receipt_id=None if receipt is None else receipt.receipt_id,
        explanation_received=state.evidence_status == "VALID",
    )


def _latest_audit_time(state: AccountabilityState) -> datetime | None:
    if not state.audit_trail:
        return None
    return max((_parse_timestamp(entry.at) for entry in state.audit_trail), default=None)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("analysis time must be timezone-aware")
    return parsed


def _format_optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else format_rfc3339_timestamp(value)


def _zero_metrics() -> RuntimeMetrics:
    return RuntimeMetrics(
        input_tokens=0,
        output_tokens=0,
        inference_latency_ms=0,
        rule_substitution_count=0,
    )


def _failure_metrics(provider_mode: ProviderMode) -> RuntimeMetrics:
    del provider_mode
    return _zero_metrics()
