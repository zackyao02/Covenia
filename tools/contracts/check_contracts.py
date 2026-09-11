"""Offline validator for the BATCH-03 contract lock and test vectors.

This tool validates schemas and contract artifacts only.  It intentionally does
not start the FastAPI app, load fixtures, call a model, or implement a route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"
VECTOR_DIR = REPO_ROOT / "tests" / "contract-vectors"
LOCK_PATH = REPO_ROOT / "docs" / "contracts" / "b-contract-lock.json"
APPROVAL_PATH = REPO_ROOT / "docs" / "approvals" / "b-decisions.json"
FIREWALL_RULES_PATH = REPO_ROOT / "docs" / "03-firewall-rules.md"

D03_APPROVED_CHOICE = (
    "重复索证归 E1/300/INTERVENE（HTTP 200 + DecisionResult）；"
    "P0_PROHIBITED_ACTION/400 仅用于 accountability_state.prohibited_actions 列表命中的动作；"
    "ASK_SAME_EVIDENCE 保留为展示用禁止项，不单独触发 P0。"
)
D03_LOCKED_BINDING = (
    "Same-scope ASK_EVIDENCE is HTTP 200 / DecisionResult / INTERVENE / E1 / 300; "
    "ASK_SAME_EVIDENCE is display-only and never independently triggers P0; "
    "P0 400 only blocks a corresponding action in accountability_state.prohibited_actions "
    "and remains above H1 350, E1 300, E2 100, and E0 0."
)
D03_FIREWALL_SENTENCE = (
    "**D03 锁定映射：**`ASK_SAME_EVIDENCE` 仅为展示禁止项；同范围 `ASK_EVIDENCE` "
    "返回 `HTTP 200 / DecisionResult / INTERVENE / E1 / 300`，不得单独触发 "
    "`P0_PROHIBITED_ACTION`。"
)

ERROR_HTTP_STATUS = {
    "SCHEMA_INVALID": 400,
    "VALIDATION_ERROR": 400,
    "P0_PROHIBITED_ACTION": 400,
    "INVALID_EVENT_TRANSITION": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "MODEL_OUTPUT_INVALID": 502,
    "MODEL_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
}
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time")
def is_timezone_aware_datetime(value: object) -> bool:
    """Require an actually parseable ISO/RFC-3339-style timestamp with an offset."""

    if not isinstance(value, str) or "T" not in value:
        return False
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


class ContractCheckError(RuntimeError):
    """Raised when an on-disk contract artifact violates the lock."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractCheckError(f"Cannot load JSON {path.relative_to(REPO_ROOT)}: {error}") from error


def canonical_content_sha256(path: Path) -> str:
    """Hash UTF-8 content after Git-style end-of-line normalization.

    This makes the lock stable across a Windows CRLF checkout and the committed
    LF blob. It does not discard any non-EOL bytes.
    """

    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest().upper()


def iter_refs(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str):
            yield reference
        for child in value.values():
            yield from iter_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_refs(child)


def load_schema_registry() -> tuple[dict[str, dict[str, Any]], Registry]:
    schemas: dict[str, dict[str, Any]] = {}
    registry = Registry()

    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = load_json(path)
        if not isinstance(schema, dict):
            raise ContractCheckError(f"Schema is not an object: {path.relative_to(REPO_ROOT)}")
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ContractCheckError(f"Schema must declare Draft 2020-12: {path.relative_to(REPO_ROOT)}")
        if schema.get("$id") != path.name:
            raise ContractCheckError(f"Schema $id must equal filename: {path.relative_to(REPO_ROOT)}")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as error:  # jsonschema exposes several schema exceptions.
            raise ContractCheckError(f"Invalid Draft 2020-12 schema {path.name}: {error}") from error
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(resource.id(), resource)
        schemas[path.name] = schema

    if not schemas:
        raise ContractCheckError("No schemas found")

    for name, schema in schemas.items():
        resolver = registry.resolver(base_uri=schema["$id"])
        for reference in iter_refs(schema):
            try:
                resolver.lookup(reference)
            except Exception as error:  # Unresolvable is intentionally normalized for users.
                raise ContractCheckError(f"Unresolvable offline $ref in {name}: {reference}: {error}") from error

    return schemas, registry


def validator_for(
    schema_name: str,
    schemas: Mapping[str, dict[str, Any]],
    registry: Registry,
) -> Draft202012Validator:
    try:
        schema = schemas[schema_name]
    except KeyError as error:
        raise ContractCheckError(f"Vector names an unknown schema: {schema_name}") from error
    return Draft202012Validator(schema, registry=registry, format_checker=FORMAT_CHECKER)


def validation_messages(validator: Draft202012Validator, instance: Any) -> list[str]:
    return [
        error.message
        for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
    ]


def normalize_evaluate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Model the A34 normalization boundary without implementing evaluate."""

    normalized: dict[str, Any] = {
        "case_id": request["case_id"],
        "prepared_action": request["prepared_action"],
        "challenge_mode": request.get("challenge_mode", False) is True,
    }
    if "evaluation_time" in request:
        normalized["evaluation_time"] = request["evaluation_time"]
    if normalized["challenge_mode"] and "challenge_overrides" in request:
        normalized["challenge_overrides"] = request["challenge_overrides"]
    return normalized


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractCheckError(message)


def validate_approval_archive(lock: Mapping[str, Any]) -> None:
    approval = lock["approved_input"]
    expected_hash = approval["content_sha256"]
    actual_hash = canonical_content_sha256(APPROVAL_PATH)
    require(
        actual_hash == expected_hash,
        "Approved-record hash mismatch: expected "
        f"{expected_hash}, got {actual_hash}",
    )
    record = load_json(APPROVAL_PATH)
    require(record.get("gate") == "X-FREEZE", "Approved record must be X-FREEZE")
    require(record.get("approved_by") == "Zack", "Approved record owner must be Zack")
    require(record.get("approved_at") == "2026-09-10T23:59:00+08:00", "Unexpected approval time")

    completed = subprocess.run(
        ["git", "diff", "--quiet", "--", "docs/approvals/b-decisions.json"],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    require(completed.returncode == 0, "Approved record has an uncommitted content change")


def validate_lock_hashes(lock: Mapping[str, Any]) -> None:
    locked_files = lock.get("locked_files")
    require(isinstance(locked_files, dict) and locked_files, "Lock must name hashed contract files")
    for relative_path, expected_hash in locked_files.items():
        path = REPO_ROOT / relative_path
        require(path.is_file(), f"Locked file is missing: {relative_path}")
        actual_hash = canonical_content_sha256(path)
        require(
            actual_hash == expected_hash,
            f"Locked file hash mismatch for {relative_path}: expected {expected_hash}, got {actual_hash}",
        )


def validate_d03_repeat_evidence_semantics(
    lock: Mapping[str, Any], all_vectors: Mapping[str, Mapping[str, Any]],
) -> None:
    """Bind the repeat-evidence vector and firewall text to approved D03."""

    record = load_json(APPROVAL_PATH)
    decisions = record.get("decisions")
    require(isinstance(decisions, list), "Approved record must contain decisions")
    d03 = next((decision for decision in decisions if decision.get("id") == "D03"), None)
    require(isinstance(d03, Mapping), "Approved record is missing D03")
    require(d03.get("verdict") == "APPROVED", "D03 must remain approved")
    require(
        d03.get("choice") == D03_APPROVED_CHOICE,
        "Approved D03 repeat-evidence choice differs from the locked contract",
    )
    require(
        lock.get("decision_bindings", {}).get("D03") == D03_LOCKED_BINDING,
        "D03 contract-lock binding differs from the approved repeat-evidence mapping",
    )
    firewall_rules = FIREWALL_RULES_PATH.read_text(encoding="utf-8")
    require(
        D03_FIREWALL_SENTENCE in firewall_rules,
        "Firewall rules must state the approved D03 E1 success mapping",
    )

    repeat_vector = all_vectors.get("evaluate-d03-repeat-evidence-e1")
    require(repeat_vector is not None, "D03 repeat-evidence vector is missing")
    request = repeat_vector["request"]
    response = repeat_vector["response"]
    expected = repeat_vector["expected"]
    require(
        request["prepared_action"]["action_type"] == "ASK_EVIDENCE",
        "D03 vector must evaluate ASK_EVIDENCE",
    )
    require(expected.get("http_status") == 200, "D03 repeat evidence must return HTTP 200")
    require(response.get("error") is None and response.get("data") is not None, "D03 must return DecisionResult")
    require(
        expected.get("decision")
        == {"decision": "INTERVENE", "rule_id": "E1", "rule_priority": 300},
        "D03 repeat evidence must remain INTERVENE/E1/300",
    )
    data = response["data"]
    require(
        data.get("decision") == "INTERVENE"
        and data.get("rule_id") == "E1"
        and data.get("rule_priority") == 300,
        "D03 response data differs from INTERVENE/E1/300",
    )
    require(
        data["fact_trace"].get("scope_match") is True,
        "D03 vector must be a same-scope request",
    )
    require(
        "ASK_SAME_EVIDENCE" in data["accountability_state"]["prohibited_actions"],
        "D03 vector must retain ASK_SAME_EVIDENCE as a display-only prohibited item",
    )

    p0_vector = all_vectors.get("evaluate-a29-p0-precedes-h1")
    require(p0_vector is not None, "Genuine P0 precedence vector is missing")
    p0_expected = p0_vector["expected"]
    require(
        p0_vector["request"]["prepared_action"]["action_type"]
        == "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "P0 precedence must use a corresponding prohibited action",
    )
    require(
        p0_expected.get("server_prohibited_action") == "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "P0 vector must name the server-derived prohibited action",
    )
    require(
        p0_expected.get("rule_precedence")
        == {
            "matched": ["P0_PROHIBITED_ACTION", "H1"],
            "selected": "P0_PROHIBITED_ACTION",
            "priority": 400,
        },
        "P0 precedence must remain above H1 for a genuinely prohibited action",
    )


def validate_vector_semantics(
    vector: Mapping[str, Any],
    all_vectors: Mapping[str, Mapping[str, Any]],
) -> None:
    expected = vector["expected"]
    response = vector["response"]
    data = response["data"]

    normalized_request = expected.get("normalized_request")
    if normalized_request is not None:
        require(
            normalize_evaluate_request(vector["request"]) == normalized_request,
            f"{vector['id']}: A34 normalization differs from the locked request",
        )

    same_as = expected.get("same_response_data_as")
    if same_as is not None:
        comparison = all_vectors.get(same_as)
        require(comparison is not None, f"{vector['id']}: missing comparison vector {same_as}")
        require(
            data == comparison["response"]["data"],
            f"{vector['id']}: disabled Challenge response data differs from baseline",
        )

    decision = expected.get("decision")
    if decision is not None:
        require(data is not None, f"{vector['id']}: decision assertion needs success data")
        for key, value in decision.items():
            if key == "suppressed_rule_ids":
                actual = data["fact_trace"].get("suppressed_rule_ids", [])
            else:
                actual = data.get(key)
            require(actual == value, f"{vector['id']}: expected {key}={value!r}, got {actual!r}")

    precedence = expected.get("rule_precedence")
    if precedence is not None:
        precedence_order = {
            "P0_PROHIBITED_ACTION": 400,
            "H1": 350,
            "E1": 300,
            "E2": 100,
            "E0_NO_RULE_MATCHED": 0,
        }
        matched = precedence["matched"]
        selected = precedence["selected"]
        require(matched and selected in matched, f"{vector['id']}: invalid precedence assertion")
        require(
            selected == max(matched, key=lambda rule: precedence_order[rule]),
            f"{vector['id']}: selected rule is not the highest locked priority",
        )
        require(
            precedence_order[selected] == precedence["priority"],
            f"{vector['id']}: selected rule priority is wrong",
        )
        require(response["error"] is not None, f"{vector['id']}: P0 precedence must be an error envelope")
        require(
            response["error"]["code"] == selected,
            f"{vector['id']}: P0 precedence error code differs from selected rule",
        )

    cached_result = expected.get("cached_result")
    if cached_result is not None:
        require(data is not None, f"{vector['id']}: cache assertion needs success data")
        outer_metadata = data["model_metadata"]
        journey_metadata = data["extracted_journey"]["model_metadata"]
        require(outer_metadata == journey_metadata, f"{vector['id']}: model metadata projections differ")
        require(
            outer_metadata["cached_result"] is cached_result,
            f"{vector['id']}: cached_result is not visible as required",
        )

    if expected.get("approved_at_from_audit"):
        require(data is not None, f"{vector['id']}: approval assertion needs success data")
        require("approved_at" not in vector["request"], f"{vector['id']}: client supplied approved_at")
        approval_entries = [
            entry for entry in data["audit_trail"] if entry["action"] == "RESOLUTION_APPROVED"
        ]
        require(len(approval_entries) >= 1, f"{vector['id']}: approval audit entry is missing")
        require(
            approval_entries[-1]["at"] == expected["approved_at_from_audit"],
            f"{vector['id']}: approved_at must be expressed by approval audit.at",
        )

    if expected.get("notification_projection"):
        require(data is not None, f"{vector['id']}: notification assertion needs success data")
        draft = data["proactive_notification_draft"]
        state = data["accountability_state"]
        require(draft is not None, f"{vector['id']}: notification draft is missing")
        require(draft["requires_human_approval"] is True, f"{vector['id']}: draft bypasses approval")
        require(state["open_obligation"] is not None, f"{vector['id']}: notification has no obligation")
        require(state["service_progress_receipt"] is not None, f"{vector['id']}: notification has no receipt")
        expected_time = state["open_obligation"]["next_check_at"]
        require(
            draft["commits_next_update_at"] == expected_time
            and state["service_progress_receipt"]["next_update_by"] == expected_time,
            f"{vector['id']}: next-update projections disagree",
        )


def validate_vectors(
    schemas: Mapping[str, dict[str, Any]],
    registry: Registry,
    lock: Mapping[str, Any],
) -> int:
    manifest = load_json(VECTOR_DIR / "manifest.json")
    vector_files = manifest.get("vector_files")
    require(isinstance(vector_files, list) and vector_files, "Vector manifest must list vector files")

    loaded: list[tuple[dict[str, Any], dict[str, Any]]] = []
    all_vectors: dict[str, Mapping[str, Any]] = {}
    for filename in vector_files:
        payload = load_json(VECTOR_DIR / filename)
        require(isinstance(payload, dict), f"Vector payload must be an object: {filename}")
        vectors = payload.get("vectors")
        require(isinstance(vectors, list) and vectors, f"No vectors in {filename}")
        for vector in vectors:
            vector_id = vector.get("id")
            require(isinstance(vector_id, str) and vector_id, f"Unnamed vector in {filename}")
            require(vector_id not in all_vectors, f"Duplicate vector id: {vector_id}")
            all_vectors[vector_id] = vector
            loaded.append((payload, vector))

    validate_d03_repeat_evidence_semantics(lock, all_vectors)

    envelope_validator = validator_for("api-envelope.schema.json", schemas, registry)
    count = 0
    endpoints: set[str] = set()
    for payload, vector in loaded:
        vector_id = vector["id"]
        endpoints.add(payload["endpoint"])
        request_validator = validator_for(payload["request_schema"], schemas, registry)
        request_messages = validation_messages(request_validator, vector["request"])
        expected = vector["expected"]
        expected_request_valid = expected["request_schema_valid"]
        require(
            (not request_messages) is expected_request_valid,
            f"{vector_id}: request schema validity expected {expected_request_valid}, got {request_messages}",
        )

        response = vector["response"]
        envelope_messages = validation_messages(envelope_validator, response)
        require(not envelope_messages, f"{vector_id}: invalid ApiEnvelope: {envelope_messages}")
        status = expected["http_status"]
        require(isinstance(status, int), f"{vector_id}: HTTP status must be an integer")
        if status == 200:
            require(response["data"] is not None and response["error"] is None, f"{vector_id}: 200 must be success")
            data_validator = validator_for(payload["success_data_schema"], schemas, registry)
            data_messages = validation_messages(data_validator, response["data"])
            require(not data_messages, f"{vector_id}: invalid success data: {data_messages}")
        else:
            require(response["data"] is None and response["error"] is not None, f"{vector_id}: error must be envelope error")
            error_code = response["error"]["code"]
            require(
                ERROR_HTTP_STATUS.get(error_code) == status,
                f"{vector_id}: {error_code} cannot use HTTP {status}",
            )
            require(error_code == expected["error_code"], f"{vector_id}: unexpected error code")
        validate_vector_semantics(vector, all_vectors)
        count += 1

    required_endpoints = {
        "POST /api/cases/analyze",
        "POST /api/actions/evaluate",
        "POST /api/resolutions/approve",
        "POST /api/events/shipment",
    }
    require(endpoints == required_endpoints, f"Vectors must cover exactly four endpoints, got {sorted(endpoints)}")
    return count


def validate_contracts(*, strict: bool = False) -> dict[str, Any]:
    lock = load_json(LOCK_PATH)
    require(lock.get("lock_version") == "1.0", "Unsupported contract lock version")
    require(lock.get("schema_dialect") == "https://json-schema.org/draft/2020-12/schema", "Wrong schema dialect")
    require(lock.get("contract_version"), "Contract version is missing")
    validate_approval_archive(lock)
    validate_lock_hashes(lock)
    schemas, registry = load_schema_registry()
    vector_count = validate_vectors(schemas, registry, lock)
    if strict:
        require(lock.get("change_control", {}).get("requires_new_approval") is True, "Strict lock needs approval control")
        require(
            lock.get("change_control", {}).get("invalidates_affected_passes") is True,
            "Strict lock needs PASS invalidation control",
        )
    return {
        "schemas_validated": len(schemas),
        "vectors_validated": vector_count,
        "strict": strict,
        "lock": LOCK_PATH.relative_to(REPO_ROOT).as_posix(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="enforce change-control lock fields")
    args = parser.parse_args(argv)
    try:
        summary = validate_contracts(strict=args.strict)
    except ContractCheckError as error:
        print(f"contract check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
