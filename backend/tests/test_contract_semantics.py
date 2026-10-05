from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_decision_result_success_schema_rejects_p0_but_keeps_suppressed_audit_id() -> None:
    schema_files = list((PROJECT_ROOT / "schemas").glob("*.json"))
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in schema_files]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = next(item for item in schemas if item["$id"] == "decision-result.schema.json")
    validator = Draft202012Validator(schema, registry=registry)
    example = json.loads(
        (PROJECT_ROOT / "frontend/src/api/examples/02-evaluate-action.json").read_text(encoding="utf-8")
    )
    p0_success = copy.deepcopy(example["response"]["data"])
    p0_success.update(decision="INTERVENE", rule_id="P0_PROHIBITED_ACTION", rule_priority=400)

    errors = list(validator.iter_errors(p0_success))
    assert any(list(error.path)[-1:] == ["rule_id"] for error in errors)
    assert any(list(error.path)[-1:] == ["rule_priority"] for error in errors)

    p0_success["rule_id"] = "E1"
    p0_success["rule_priority"] = 300
    p0_success["fact_trace"]["suppressed_rule_ids"] = ["P0_PROHIBITED_ACTION"]
    assert not list(validator.iter_errors(p0_success))
