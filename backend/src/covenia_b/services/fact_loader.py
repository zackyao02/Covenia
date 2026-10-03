"""Trusted fact loading and model-input preparation for case analysis.

This module is deliberately the only bridge between a ``CaseSource`` and the
model boundary.  It never interprets a model result, writes a ledger, or makes
an HTTP request.  Its job is to bind source facts, manifest-backed image bytes,
and explicit no-PII declarations before a provider can receive anything.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from covenia_b.domain.types import AnalyzeCaseRequest, CaseInput, ResolvedImage
from covenia_b.images import ProviderImageInput, ResolvedEvidence
from covenia_b.importing.case_assembler import CaseAssembler
from covenia_b.ports.contracts import CaseSource, ImageResolver
from covenia_b.ports.errors import CaseNotFound, ImageUnavailable, ImageUnreadable
from covenia_b.privacy import SanitizationResult, sanitize_case_input


class FactLoadingError(ValueError):
    """A source fact cannot safely enter the analysis pipeline."""


class UnknownAnalysisCase(FactLoadingError):
    """The requested case is absent from the configured source."""


class CaseIdentityMismatch(FactLoadingError):
    """A source or challenge payload does not bind to the requested case ID."""


class CaseFactRelationError(FactLoadingError):
    """Trusted case records contain an invalid internal source relation."""


class ImageResolutionError(FactLoadingError):
    """A declared image cannot be resolved to a safe content-addressed handle."""


class ImageSourceBindingError(FactLoadingError):
    """Image provenance or provider bytes do not match the declared source facts."""


class ImageSafetyDeclarationError(FactLoadingError):
    """The A-owned no-PII declaration is absent or not accepted."""


@dataclass(frozen=True, slots=True)
class ImageSafetyDeclarations:
    """Immutable per-image no-PII declarations supplied by the A-owned manifest."""

    by_evidence_id: Mapping[str, bool]

    def __post_init__(self) -> None:
        normalized: dict[str, bool] = {}
        for evidence_id, declared_safe in self.by_evidence_id.items():
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ImageSafetyDeclarationError("image declarations require non-empty IDs")
            if type(declared_safe) is not bool:
                raise ImageSafetyDeclarationError("image declarations must be boolean")
            normalized[evidence_id] = declared_safe
        object.__setattr__(self, "by_evidence_id", MappingProxyType(normalized))

    @classmethod
    def from_accepted_manifest(cls, manifest_path: str | Path) -> ImageSafetyDeclarations:
        """Load only explicit accepted no-PII declarations from an A-line manifest."""

        try:
            raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImageSafetyDeclarationError("image safety manifest is unavailable") from error
        if not isinstance(raw, dict) or raw.get("status") != "ACCEPTED":
            raise ImageSafetyDeclarationError("image safety manifest is not accepted")
        images = raw.get("images")
        if not isinstance(images, list) or not images:
            raise ImageSafetyDeclarationError("image safety manifest has no images")

        declarations: dict[str, bool] = {}
        for entry in images:
            if not isinstance(entry, dict):
                raise ImageSafetyDeclarationError("image safety manifest has an invalid entry")
            evidence_id = entry.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ImageSafetyDeclarationError(
                    "image safety manifest has an invalid evidence ID"
                )
            if evidence_id in declarations:
                raise ImageSafetyDeclarationError("image safety manifest duplicates an evidence ID")
            if entry.get("no_pii_declaration") is not True:
                raise ImageSafetyDeclarationError(
                    "every manifest image needs no_pii_declaration=true"
                )
            declarations[evidence_id] = True
        return cls(declarations)


@dataclass(frozen=True, slots=True)
class ImageBinding:
    """Safe image metadata retained after content and provenance binding."""

    evidence_id: str
    media_type: str
    content_sha256: str
    byte_length: int
    provenance_verified: bool


@dataclass(frozen=True, slots=True)
class LoadedAnalysisFacts:
    """Prepared facts that may cross into the bounded candidate extractor."""

    case_input: CaseInput
    sanitization: SanitizationResult
    image_bindings: tuple[ImageBinding, ...]
    challenge_mode: bool

    @property
    def provider_image_binding_verified(self) -> bool:
        return all(binding.provenance_verified for binding in self.image_bindings)


@dataclass(frozen=True, slots=True)
class AssemblerCaseSource:
    """Adapt BATCH-06's assembler to the frozen read-only ``CaseSource`` port."""

    assembler: CaseAssembler

    def get_case(self, case_id: str) -> CaseInput:
        try:
            assembly = self.assembler.assemble(case_id)
        except ValueError as error:
            raise CaseNotFound("case source cannot resolve the requested case") from error
        if assembly.status != "ASSEMBLED" or assembly.case_input is None:
            raise CaseNotFound("case source has no analysis-ready input for the requested case")
        try:
            return CaseInput.from_contract(assembly.case_input)
        except ValueError as error:
            raise CaseNotFound("case source returned an invalid case input") from error


@dataclass(frozen=True, slots=True)
class FactLoader:
    """Load source facts, resolve each declared image, then sanitize model input."""

    case_source: CaseSource | None
    image_resolver: ImageResolver
    image_no_pii_declarations: Mapping[str, bool] | ImageSafetyDeclarations

    def load(self, request: AnalyzeCaseRequest) -> LoadedAnalysisFacts:
        """Prepare one case without treating a request payload as normal-case facts."""

        if not isinstance(request, AnalyzeCaseRequest):
            raise FactLoadingError("analysis requires an AnalyzeCaseRequest")
        case_input = self._select_case_input(request)
        self._validate_case_relations(case_input)

        resolved_images: list[ResolvedImage] = []
        bindings: list[ImageBinding] = []
        for evidence in case_input.evidence_images:
            resolved, binding = self._resolve_image(evidence)
            resolved_images.append(resolved)
            bindings.append(binding)

        declarations = self._declarations()
        try:
            sanitization = sanitize_case_input(
                case_input,
                resolved_images=tuple(resolved_images),
                image_no_pii_declarations=declarations,
            )
        except ValueError as error:
            raise ImageSafetyDeclarationError(
                "case images are not cleared for model input"
            ) from error
        return LoadedAnalysisFacts(
            case_input=case_input,
            sanitization=sanitization,
            image_bindings=tuple(bindings),
            challenge_mode=request.challenge_mode,
        )

    def _select_case_input(self, request: AnalyzeCaseRequest) -> CaseInput:
        supplied = request.case_input
        if supplied is not None:
            if not request.challenge_mode:
                raise FactLoadingError("case_input is only available in challenge mode")
            case_input = supplied
        else:
            if self.case_source is None:
                raise FactLoadingError("normal analysis requires a configured case source")
            try:
                case_input = self.case_source.get_case(request.case_id)
            except CaseNotFound as error:
                raise UnknownAnalysisCase("requested case was not found") from error
            except ValueError as error:
                raise FactLoadingError("case source could not load the requested case") from error

        if not isinstance(case_input, CaseInput):
            raise FactLoadingError("case source must return a CaseInput")
        if case_input.case_id != request.case_id:
            raise CaseIdentityMismatch("case input does not match the requested case ID")
        if request.evaluation_time is not None:
            case_input = case_input.model_copy(update={"evaluation_time": request.evaluation_time})
        try:
            case_input.to_contract()
        except ValueError as error:
            raise FactLoadingError("case input does not satisfy its frozen contract") from error
        return case_input

    def _validate_case_relations(self, case_input: CaseInput) -> None:
        current = case_input.current_issue
        if not any(
            item.fulfillment_item_id == current.fulfillment_item_id
            and item.sku_id == current.sku_id
            for item in case_input.order.items
        ):
            raise CaseFactRelationError("current issue does not match an order item")
        message_ids = {message.message_id for message in case_input.conversation}
        if any(image.source_message_id not in message_ids for image in case_input.evidence_images):
            raise CaseFactRelationError("an evidence image is not bound to a source message")

    def _resolve_image(self, evidence: object) -> tuple[ResolvedImage, ImageBinding]:
        try:
            detail_resolver = getattr(self.image_resolver, "resolve_details", None)
            if callable(detail_resolver):
                details = detail_resolver(evidence)
                return self._bound_detail(evidence, details)
            resolved = self.image_resolver.resolve(evidence)  # type: ignore[arg-type]
        except (ImageUnavailable, ImageUnreadable, OSError, ValueError) as error:
            raise ImageResolutionError("declared image could not be resolved") from error

        self._validate_resolved_handle(evidence, resolved)
        return (
            resolved,
            ImageBinding(
                evidence_id=resolved.evidence_id,
                media_type=resolved.media_type,
                content_sha256=resolved.content_sha256,
                byte_length=resolved.byte_length,
                provenance_verified=False,
            ),
        )

    def _bound_detail(
        self,
        evidence: object,
        details: object,
    ) -> tuple[ResolvedImage, ImageBinding]:
        if not isinstance(details, ResolvedEvidence):
            raise ImageSourceBindingError("detailed image resolver returned an invalid result")
        self._validate_resolved_handle(evidence, details.handle)
        self._validate_provider_image(details.handle, details.provider_image)
        provenance = details.provenance
        if (
            provenance.evidence_id != getattr(evidence, "evidence_id", None)
            or provenance.source_message_id != getattr(evidence, "source_message_id", None)
            or provenance.source_kind != getattr(evidence, "source_kind", None)
            or provenance.competition_reference_path
            != getattr(evidence, "competition_reference_path", None)
        ):
            raise ImageSourceBindingError("image provenance does not match the declared evidence")
        return (
            details.handle,
            ImageBinding(
                evidence_id=details.handle.evidence_id,
                media_type=details.handle.media_type,
                content_sha256=details.handle.content_sha256,
                byte_length=details.handle.byte_length,
                provenance_verified=True,
            ),
        )

    @staticmethod
    def _validate_resolved_handle(evidence: object, resolved: object) -> None:
        if not isinstance(resolved, ResolvedImage):
            raise ImageResolutionError("image resolver returned an invalid handle")
        if resolved.evidence_id != getattr(evidence, "evidence_id", None):
            raise ImageSourceBindingError("image handle does not match declared evidence")
        if (
            not resolved.media_type
            or len(resolved.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in resolved.content_sha256)
            or resolved.byte_length < 1
        ):
            raise ImageResolutionError("image resolver returned an invalid content binding")

    @staticmethod
    def _validate_provider_image(handle: ResolvedImage, provider_image: object) -> None:
        if not isinstance(provider_image, ProviderImageInput):
            raise ImageSourceBindingError("image resolver did not return provider-safe bytes")
        if (
            provider_image.media_type != handle.media_type
            or provider_image.content_sha256 != handle.content_sha256
            or provider_image.byte_length != handle.byte_length
            or provider_image.byte_length != len(provider_image.content)
        ):
            raise ImageSourceBindingError("provider image bytes do not match the resolved handle")

    def _declarations(self) -> Mapping[str, bool]:
        declarations = (
            self.image_no_pii_declarations.by_evidence_id
            if isinstance(self.image_no_pii_declarations, ImageSafetyDeclarations)
            else self.image_no_pii_declarations
        )
        if not isinstance(declarations, Mapping):
            raise ImageSafetyDeclarationError("image safety declarations are invalid")
        return declarations
