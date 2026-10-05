"""The single composition root for the Covenia backend.

Every process-owned adapter and both transport seams are assembled here once.
The four business routers are the already-reviewed BATCH-21/22/24/26 factories;
this module never re-implements a rule, a route body, or an error mapping.  It
only decides which concrete repository, clock, model provider, image resolver,
cache policy, metrics sink and verified-journey seam those factories receive.

Resource acquisition is deliberately deferred: importing the composition root
performs no I/O, and a broken local input is reported as a typed port error
(never as a fabricated result) the first time a request needs it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from covenia_b.api.analyze import (
    ANALYZE_PATH,
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    create_analyze_router,
)
from covenia_b.api.approve import install_approve_router
from covenia_b.api.base import REQUEST_ID_HEADER, install_api_seams
from covenia_b.api.evaluate import create_evaluate_router
from covenia_b.api.shipment import install_shipment_router
from covenia_b.domain.types import (
    AnalyzeCaseRequest,
    AnalyzeCaseResponse,
    CandidateExtraction,
    EvidenceImage,
    ExtractedJourney,
    LedgerSnapshot,
    ResolvedImage,
    RuntimeMetrics,
)
from covenia_b.images import ManifestImageResolver, ProviderImageInput, ResolvedEvidence
from covenia_b.importing.case_assembler import CaseAssembler
from covenia_b.model.adapters.qwen_http import QwenHttpConfig, QwenHttpProvider
from covenia_b.model.prompts.candidate_extraction import (
    CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
    PROMPT_VERSION,
    prompt_manifest,
)
from covenia_b.ports.clock import DemoClock, SystemClock
from covenia_b.ports.contracts import (
    Clock,
    ImageResolver,
    LedgerRepository,
    MetricsSink,
    ModelProvider,
)
from covenia_b.ports.errors import (
    CaseNotFound,
    ImageUnavailable,
    LedgerUnavailable,
    MetricsUnavailable,
    ModelUnavailable,
)
from covenia_b.services.analyze import AnalyzeService
from covenia_b.services.approve import ApprovalService
from covenia_b.services.evaluate import EvaluateService
from covenia_b.services.fact_loader import (
    AssemblerCaseSource,
    FactLoader,
    ImageSafetyDeclarationError,
    ImageSafetyDeclarations,
)
from covenia_b.services.shipment import ShipmentEventService
from covenia_b.settings import Settings, get_settings
from covenia_b.storage import SQLiteLedgerRepository
from covenia_b.storage.models import Mutation, TransactionResult

REQUEST_LOGGER = logging.getLogger("covenia_b.request")

# The frozen four-endpoint contract of ``docs/05-api-and-ui.md`` section 1.  The
# composition root declares it and verifies the mounted application against it,
# so a router that drifts (or a fifth business route) fails composition loudly.
EVALUATE_PREFIX = "/api/actions"
EVALUATE_SUFFIX = "/evaluate"
EXPECTED_BUSINESS_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", ANALYZE_PATH),
    ("POST", f"{EVALUATE_PREFIX}{EVALUATE_SUFFIX}"),
    ("POST", "/api/resolutions/approve"),
    ("POST", "/api/events/shipment"),
)

T = TypeVar("T")

_BOUND_IMAGE_LIMIT = 64
"""Registered evidence IDs are few; the bound keeps a challenge payload from growing memory."""


class RuntimeConfigurationError(RuntimeError):
    """A composition decision cannot be represented safely by the frozen ports."""


# --------------------------------------------------------------------------- #
# Lazy, failure-honest adapters
# --------------------------------------------------------------------------- #


class _LazyResource(Generic[T]):
    """Build one process-owned resource on first use; never cache a failure.

    A build failure is re-raised as the caller's typed port error, so an
    unavailable local input becomes a documented transport error instead of a
    fabricated success.  A later request retries the build, which lets an
    operator repair a file without restarting the process.
    """

    def __init__(self, build: Callable[[], T], *, unavailable: Callable[[str], Exception]) -> None:
        self._build = build
        self._unavailable = unavailable
        self._lock = threading.Lock()
        self._instance: T | None = None

    def get(self) -> T:
        instance = self._instance
        if instance is not None:
            return instance
        with self._lock:
            if self._instance is None:
                try:
                    built = self._build()
                except Exception as error:  # noqa: BLE001 - re-raised as a typed port error
                    raise self._unavailable(str(error)) from error
                self._instance = built
            return cast(T, self._instance)


class LazyCaseSource:
    """Defer the workbook/catalog read until a request actually needs a case."""

    def __init__(self, build: Callable[[], Any]) -> None:
        self._resource: _LazyResource[Any] = _LazyResource(
            build,
            unavailable=lambda reason: CaseNotFound(
                f"the configured case source is unavailable: {reason}"
            ),
        )

    def get_case(self, case_id: str) -> Any:
        return self._resource.get().get_case(case_id)


class BoundImageResolver:
    """Resolve declared evidence and retain provider-safe bytes for the model seam.

    ``FactLoader`` reaches the resolver through ``resolve_details``; the frozen
    Qwen adapter receives an ``ImagePayloadLoader`` keyed by ``ResolvedImage``.
    This adapter is that binding: it records the exact verified payload next to
    its handle so the provider can only send bytes the resolver already probed.
    """

    def __init__(self, build: Callable[[], ManifestImageResolver]) -> None:
        self._resource: _LazyResource[ManifestImageResolver] = _LazyResource(
            build,
            unavailable=lambda reason: ImageUnavailable(
                f"the configured image manifest is unavailable: {reason}"
            ),
        )
        self._bound: OrderedDict[str, ProviderImageInput] = OrderedDict()
        self._lock = threading.Lock()

    def resolve(self, evidence: EvidenceImage) -> ResolvedImage:
        return self.resolve_details(evidence).handle

    def resolve_details(self, evidence: EvidenceImage) -> ResolvedEvidence:
        details = self._resource.get().resolve_details(evidence)
        with self._lock:
            self._bound.pop(details.handle.evidence_id, None)
            self._bound[details.handle.evidence_id] = details.provider_image
            while len(self._bound) > _BOUND_IMAGE_LIMIT:
                self._bound.popitem(last=False)
        return details

    def provider_image(self, handle: ResolvedImage) -> ProviderImageInput:
        with self._lock:
            image = self._bound.get(handle.evidence_id)
        if image is None:
            raise ImageUnavailable("verified image bytes are unavailable for this handle")
        return image


class LazyImageDeclarations(Mapping[str, bool]):
    """Load the accepted no-PII declaration manifest on first access only."""

    def __init__(self, manifest_path: Path) -> None:
        self._manifest_path = manifest_path
        self._declarations: ImageSafetyDeclarations | None = None
        self._lock = threading.Lock()

    def _load(self) -> ImageSafetyDeclarations:
        if self._declarations is None:
            with self._lock:
                if self._declarations is None:
                    self._declarations = ImageSafetyDeclarations.from_accepted_manifest(
                        self._manifest_path
                    )
        return self._declarations

    def __getitem__(self, key: str) -> bool:
        try:
            return self._load().by_evidence_id[key]
        except KeyError as error:
            raise ImageSafetyDeclarationError("image is not declared safe") from error

    def __iter__(self) -> Iterator[str]:
        return iter(self._load().by_evidence_id)

    def __len__(self) -> int:
        return len(self._load().by_evidence_id)


class LazyLedgerRepository:
    """Create the SQLite ledger on first use; report unavailability as a port error."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._resource: _LazyResource[SQLiteLedgerRepository] = _LazyResource(
            self._build,
            unavailable=lambda reason: LedgerUnavailable(
                f"the local ledger is unavailable: {reason}"
            ),
        )

    @property
    def db_path(self) -> Path:
        return self._path

    def _build(self) -> SQLiteLedgerRepository:
        absolute = self._path if self._path.is_absolute() else (Path.cwd() / self._path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        return SQLiteLedgerRepository(absolute)

    def load(self, case_id: str) -> LedgerSnapshot | None:
        return self._resource.get().load(case_id)

    def save(self, snapshot: LedgerSnapshot, *, expected_version: int | None) -> LedgerSnapshot:
        return self._resource.get().save(snapshot, expected_version=expected_version)

    def execute(
        self,
        *,
        case_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, Any],
        mutate: Callable[[LedgerSnapshot | None], Mutation],
        event: Any = None,
        expected_version: int | None = None,
    ) -> TransactionResult:
        return self._resource.get().execute(
            case_id=case_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_body=request_body,
            mutate=mutate,
            event=event,
            expected_version=expected_version,
        )


class UnconfiguredModelProvider:
    """The explicit model blocker: it refuses instead of producing a placeholder.

    The model deployment is an external gate.  Until an operator registers one,
    the process answers ``MODEL_UNAVAILABLE`` and the CLI preflight names the
    exact missing settings; no cached or synthetic candidate is ever returned.
    """

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing

    async def extract(self, model_input: Any) -> CandidateExtraction:
        del model_input
        names = ", ".join(self.missing) or "model deployment"
        raise ModelUnavailable(f"the model provider is not configured ({names})")


# --------------------------------------------------------------------------- #
# Process-owned seams
# --------------------------------------------------------------------------- #


class VerifiedJourneyStore:
    """Retain the server-validated extraction that ``POST .../analyze`` produced.

    The frozen ledger stores accountability facts, not the verified extraction,
    and BATCH-22 requires a ``VerifiedJourneySource``.  This process-owned store
    is that seam.  It is intentionally in memory: after a restart the store is
    empty and ``evaluate`` answers the frozen "must be analysed" error rather
    than inventing an extraction it cannot prove.
    """

    def __init__(self) -> None:
        self._journeys: dict[str, ExtractedJourney] = {}
        self._lock = threading.Lock()

    def record(self, journey: ExtractedJourney) -> None:
        if not isinstance(journey, ExtractedJourney):
            raise RuntimeConfigurationError("only a verified extraction may be recorded")
        with self._lock:
            self._journeys[journey.case_id] = journey

    def get_journey(self, case_id: str) -> ExtractedJourney:
        with self._lock:
            journey = self._journeys.get(case_id)
        if journey is None:
            raise CaseNotFound("no verified extraction is retained for this case")
        return journey

    def __len__(self) -> int:
        with self._lock:
            return len(self._journeys)


class RecordingAnalyzeService:
    """Bind the analyze transport seam to the verified-journey store.

    This wrapper adds no rule: it awaits the reviewed BATCH-19 service and, only
    after a successful projection, retains the journey that the evaluate seam
    must later rebuild facts from.
    """

    def __init__(self, service: AnalyzeService, journeys: VerifiedJourneyStore) -> None:
        self._service = service
        self._journeys = journeys

    async def analyze(
        self,
        request: AnalyzeCaseRequest,
        *,
        request_id: str | None = None,
    ) -> AnalyzeCaseResponse:
        response = await self._service.analyze(request, request_id=request_id)
        self._journeys.record(response.extracted_journey)
        return response


class ComposedMetricsSink:
    """Aggregate safe per-endpoint metrics; no prompt, PII, image, or case content."""

    def __init__(self) -> None:
        self._totals: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()

    def record(self, *, endpoint: str, metrics: RuntimeMetrics) -> None:
        if endpoint not in {"analyze", "evaluate", "approve", "shipment"}:
            raise MetricsUnavailable("unknown endpoint name")
        with self._lock:
            totals = self._totals.setdefault(
                endpoint,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "inference_latency_ms": 0,
                    "rule_substitution_count": 0,
                },
            )
            totals["calls"] += 1
            for field in (
                "input_tokens",
                "output_tokens",
                "inference_latency_ms",
                "rule_substitution_count",
            ):
                totals[field] += int(getattr(metrics, field))

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {endpoint: dict(totals) for endpoint, totals in sorted(self._totals.items())}


class RequestTraceMiddleware:
    """Log one redacted JSON line per request, keyed by the assigned request ID.

    The line carries no body, header, prompt, image, or case content.  It is
    added outside the BATCH-02 transport seam, so ``request.state.request_id``
    (or the response header it publishes) is already the single ID attached to
    the response envelope.
    """

    def __init__(self, app: Any, *, log_path: Path) -> None:
        self.app = app
        self.log_path = log_path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        status_holder: dict[str, Any] = {}

        async def send_wrapper(message: Any) -> None:
            if message.get("type") == "http.response.start":
                status_holder["status"] = message.get("status")
                headers = message.setdefault("headers", [])
                for name, value in headers:
                    if name.lower() == REQUEST_ID_HEADER.lower().encode():
                        status_holder["request_id"] = value.decode("latin-1")
                        break
            await send(message)

        await self.app(scope, receive, send_wrapper)
        request_id = status_holder.get("request_id")
        if request_id is None:
            return
        self._write(
            {
                "at": datetime.now().astimezone().isoformat(),
                "request_id": request_id,
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status_holder.get("status"),
            }
        )

    def _write(self, record: dict[str, Any]) -> None:
        REQUEST_LOGGER.info(
            "request_id=%s method=%s path=%s status=%s",
            record["request_id"],
            record["method"],
            record["path"],
            record["status"],
        )
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
                handle.write("\n")
        except OSError:  # request logging must never break a served request
            REQUEST_LOGGER.warning("request trace log is not writable: %s", self.log_path)


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RuntimeOverrides:
    """Explicit seams a test or an operator may substitute for the real adapter."""

    case_source: Any | None = None
    image_resolver: ImageResolver | None = None
    model_provider: ModelProvider | None = None
    ledger_repository: LedgerRepository | None = None
    clock: Clock | None = None
    metrics_sink: MetricsSink | None = None
    journeys: VerifiedJourneyStore | None = None
    provider_mode: str = "LIVE"
    analysis_timeout_seconds: float | None = None
    evaluate_budget_seconds: float | None = None


class Runtime:
    """One immutable bundle of process-owned adapters and the four services."""

    __slots__ = (
        "settings",
        "clock",
        "repository",
        "metrics",
        "model_provider",
        "image_resolver",
        "case_source",
        "journeys",
        "analyze_service",
        "evaluate_service",
        "approval_service",
        "shipment_service",
        "analysis_timeout_seconds",
        "notices",
    )

    def __init__(
        self,
        *,
        settings: Settings,
        clock: Clock,
        repository: Any,
        metrics: MetricsSink,
        model_provider: ModelProvider,
        image_resolver: ImageResolver,
        case_source: Any,
        journeys: VerifiedJourneyStore,
        analyze_service: RecordingAnalyzeService,
        evaluate_service: EvaluateService,
        approval_service: ApprovalService,
        shipment_service: ShipmentEventService,
        analysis_timeout_seconds: float,
        notices: tuple[str, ...],
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.repository = repository
        self.metrics = metrics
        self.model_provider = model_provider
        self.image_resolver = image_resolver
        self.case_source = case_source
        self.journeys = journeys
        self.analyze_service = analyze_service
        self.evaluate_service = evaluate_service
        self.approval_service = approval_service
        self.shipment_service = shipment_service
        self.analysis_timeout_seconds = analysis_timeout_seconds
        self.notices = notices


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (Path.cwd() / path)


def _build_clock(settings: Settings) -> Clock:
    if settings.demo_clock == "system":
        return SystemClock()
    try:
        instant = datetime.fromisoformat(
            settings.demo_clock[:-1] + "+00:00"
            if settings.demo_clock.endswith("Z")
            else settings.demo_clock
        )
    except ValueError as error:
        raise RuntimeConfigurationError(
            "COVENIA_DEMO_CLOCK must be 'system' or an RFC 3339 instant"
        ) from error
    return DemoClock(instant)


def _build_case_source(settings: Settings) -> LazyCaseSource:
    def build() -> AssemblerCaseSource:
        assembler = CaseAssembler.from_paths(
            _resolve(settings.workbook_path),
            _resolve(settings.demo_cases_path),
            _resolve(settings.case_manifest_path),
        )
        return AssemblerCaseSource(assembler=assembler)

    return LazyCaseSource(build)


def _build_image_resolver(settings: Settings) -> BoundImageResolver:
    def build() -> ManifestImageResolver:
        return ManifestImageResolver.from_manifest_file(
            manifest_path=_resolve(settings.image_manifest_path),
            evidence_root=_resolve(settings.image_evidence_root),
        )

    return BoundImageResolver(build)


def missing_model_settings(settings: Settings) -> tuple[str, ...]:
    """Return the registered-deployment settings that are still empty."""

    required = {
        "model_deployment_id": settings.model_deployment_id,
        "model_endpoint": settings.model_endpoint,
        "model_revision": settings.model_revision,
    }
    return tuple(name for name, value in sorted(required.items()) if not str(value).strip())


def _build_model_provider(
    settings: Settings,
    images: BoundImageResolver,
    *,
    model_provider: ModelProvider | None,
) -> ModelProvider:
    if model_provider is not None:
        return model_provider
    missing = missing_model_settings(settings)
    if missing:
        return UnconfiguredModelProvider(missing)
    manifest = prompt_manifest()
    if settings.model_prompt_version != manifest["prompt_version"]:
        raise RuntimeConfigurationError(
            "COVENIA_MODEL_PROMPT_VERSION does not match the frozen prompt manifest"
        )
    config = QwenHttpConfig(
        endpoint=settings.model_endpoint,
        model_revision=settings.model_revision,
        prompt_version=PROMPT_VERSION,
        deployment_id=settings.model_deployment_id,
        system_prompt=CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
        api_key=os.environ.get("COVENIA_MODEL_API_KEY") or None,
    )
    return QwenHttpProvider(config, image_loader=images.provider_image)


def build_runtime(
    settings: Settings | None = None,
    *,
    overrides: RuntimeOverrides | None = None,
) -> Runtime:
    """Assemble the one composition root without performing resource I/O."""

    resolved = settings or get_settings()
    chosen = overrides or RuntimeOverrides()
    notices: list[str] = []

    clock = chosen.clock or _build_clock(resolved)
    repository = chosen.ledger_repository or LazyLedgerRepository(resolved.sqlite_path)
    metrics = chosen.metrics_sink if chosen.metrics_sink is not None else ComposedMetricsSink()
    images: Any = chosen.image_resolver or _build_image_resolver(resolved)
    case_source = chosen.case_source or _build_case_source(resolved)
    journeys = chosen.journeys or VerifiedJourneyStore()

    model_provider = _build_model_provider(
        resolved, images, model_provider=chosen.model_provider
    )
    if isinstance(model_provider, UnconfiguredModelProvider):
        notices.append(
            "model deployment is not registered; analyze answers MODEL_UNAVAILABLE "
            f"(missing: {', '.join(model_provider.missing)})"
        )
    if resolved.cache_mode == "disabled":
        notices.append("extraction cache is disabled; every analyze calls the model provider")
    else:
        notices.append(
            f"cache_mode={resolved.cache_mode} is configured but no locked ExtractionStore "
            "adapter exists yet; analyze calls the model provider directly"
        )
    notices.append(
        "verified extractions are process-owned and in memory; after a restart analyze "
        "must run again before evaluate"
    )

    declarations = LazyImageDeclarations(_resolve(resolved.image_manifest_path))
    fact_loader = FactLoader(
        case_source=case_source,
        image_resolver=images,
        image_no_pii_declarations=declarations,
    )
    provider_mode = "TEST_DOUBLE" if chosen.provider_mode == "TEST_DOUBLE" else "LIVE"
    analyze_service = RecordingAnalyzeService(
        AnalyzeService(
            fact_loader=fact_loader,
            provider=model_provider,
            ledger_repository=repository,
            metrics_sink=cast(MetricsSink, metrics),
            provider_mode=cast(Any, provider_mode),
        ),
        journeys,
    )
    evaluate_service = EvaluateService(
        case_source=case_source,
        journey_source=journeys,
        ledger_repository=cast(LedgerRepository, repository),
        metrics_sink=cast(MetricsSink, metrics),
        budget_seconds=(
            resolved.evaluate_budget_seconds
            if chosen.evaluate_budget_seconds is None
            else chosen.evaluate_budget_seconds
        ),
    )
    approval_service = ApprovalService(repository=cast(Any, repository), clock=clock)
    shipment_service = ShipmentEventService(repository=cast(Any, repository))
    return Runtime(
        settings=resolved,
        clock=clock,
        repository=repository,
        metrics=metrics,
        model_provider=model_provider,
        image_resolver=images,
        case_source=case_source,
        journeys=journeys,
        analyze_service=analyze_service,
        evaluate_service=evaluate_service,
        approval_service=approval_service,
        shipment_service=shipment_service,
        analysis_timeout_seconds=(
            resolved.analysis_timeout_seconds
            if chosen.analysis_timeout_seconds is None
            else chosen.analysis_timeout_seconds
        ),
        notices=tuple(notices),
    )


def _install_analyze_router(app: FastAPI, runtime: Runtime) -> None:
    installed = getattr(app.state, "analysis_service", None)
    if installed is not None:
        if installed is not runtime.analyze_service:
            raise RuntimeConfigurationError("analyze router already has a different service")
        return
    timeout = runtime.analysis_timeout_seconds
    if timeout <= 0 or timeout > DEFAULT_ANALYSIS_TIMEOUT_SECONDS:
        raise RuntimeConfigurationError(
            "COVENIA_ANALYSIS_TIMEOUT_SECONDS must be greater than zero and at most 20 seconds"
        )
    app.state.analysis_service = runtime.analyze_service
    app.include_router(
        create_analyze_router(runtime.analyze_service, timeout_seconds=timeout)
    )


def _install_evaluate_router(app: FastAPI, runtime: Runtime) -> None:
    installed = getattr(app.state, "evaluate_service", None)
    if installed is not None:
        if installed is not runtime.evaluate_service:
            raise RuntimeConfigurationError("evaluate router already has a different service")
        return
    app.state.evaluate_service = runtime.evaluate_service
    app.include_router(create_evaluate_router(runtime.evaluate_service), prefix=EVALUATE_PREFIX)


def installed_route_inventory(app: FastAPI) -> list[dict[str, object]]:
    """Return every mounted operation as ``{method, path, name}`` entries."""

    inventory: list[dict[str, object]] = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or ())
        path = getattr(route, "path", None)
        if not methods or path is None:
            continue
        for method in methods:
            if method in {"HEAD"}:
                continue
            inventory.append(
                {
                    "method": method,
                    "path": path,
                    "name": getattr(route, "name", None),
                }
            )
    return sorted(inventory, key=lambda entry: (str(entry["path"]), str(entry["method"])))


def verify_single_composition(app: FastAPI) -> list[dict[str, object]]:
    """Fail composition unless the mounted app is exactly the frozen four routes."""

    inventory = installed_route_inventory(app)
    mounted = [(str(entry["method"]), str(entry["path"])) for entry in inventory]
    expected = sorted((method, path) for method, path in EXPECTED_BUSINESS_ROUTES)
    if sorted(mounted) != expected:
        raise RuntimeConfigurationError(
            f"composition mounted {sorted(mounted)} instead of the frozen {expected}"
        )
    return inventory


def compose_application(
    settings: Settings | None = None,
    *,
    runtime: Runtime | None = None,
) -> FastAPI:
    """Build the one ASGI application: seams, CORS, trace log, four routers."""

    resolved = settings or get_settings()
    assembled = runtime or build_runtime(resolved)
    application = FastAPI(
        title="Covenia backend",
        version="0.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = resolved
    application.state.runtime = assembled
    install_api_seams(application)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Added last, so it is the outermost middleware and can read the request ID
    # that the transport seam attached while serving the request.
    application.add_middleware(
        RequestTraceMiddleware,
        log_path=_resolve(resolved.request_log_path),
    )

    _install_analyze_router(application, assembled)
    _install_evaluate_router(application, assembled)
    install_approve_router(application, approval_service=assembled.approval_service)
    install_shipment_router(application, shipment_service=assembled.shipment_service)
    verify_single_composition(application)
    return application


def route_inventory_document(
    app: FastAPI,
    *,
    settings: Settings,
    runtime: Runtime,
) -> dict[str, object]:
    """Return the declared, mounted and documentation route facts for the batch report."""

    inventory = installed_route_inventory(app)
    business = [entry for entry in inventory if entry["method"] == "POST"]
    return {
        "artifact": "reports/batches/BATCH-27/route-inventory.json",
        "batch_id": "BATCH-27",
        "contract_source": "docs/05-api-and-ui.md section 1 (frozen four-endpoint baseline)",
        "business_post_routes": business,
        "business_post_route_count": len(business),
        "all_mounted_operations": inventory,
        "expected_business_routes": [
            {"method": method, "path": path} for method, path in EXPECTED_BUSINESS_ROUTES
        ],
        "documentation_routes": {
            "docs_url": app.docs_url,
            "redoc_url": app.redoc_url,
            "openapi_url": app.openapi_url,
            "openapi_route_mounted": any(
                getattr(route, "path", None) == "/openapi.json" for route in app.routes
            ),
            "statement": (
                "The interactive documentation endpoints are disabled by construction "
                "(docs_url=redoc_url=openapi_url=None on the application factory), so no "
                "fifth business API and no schema UI is served. Setting any of those "
                "arguments would re-open them; competition runs keep them closed."
            ),
        },
        "cors": {
            "allowed_origins": list(settings.cors_origins),
            "allow_credentials": False,
            "allow_methods": ["POST", "OPTIONS"],
            "allow_headers": ["Content-Type", REQUEST_ID_HEADER],
            "options_note": (
                "CORS preflight is answered by Starlette's CORSMiddleware before routing, so "
                "no OPTIONS route exists in the mounted route table; it is framework "
                "behaviour for the four POST routes, not a fifth business API."
            ),
        },
        "authentication_boundary": (
            "The competition build has no authentication or authorization boundary. The "
            "listener is loopback-only (COVENIA_LISTEN_HOST defaults to 127.0.0.1); any "
            "local process that can reach the port may call all four endpoints. Do not "
            "expose this process beyond the local host."
        ),
        "model_provider": {
            "configured": not isinstance(runtime.model_provider, UnconfiguredModelProvider),
            "missing_settings": list(missing_model_settings(settings)),
            "blocker_behaviour": (
                "An unregistered deployment yields MODEL_UNAVAILABLE (503) from analyze; no "
                "synthetic or cached candidate is returned."
            ),
        },
        "runtime_notices": list(runtime.notices),
    }
