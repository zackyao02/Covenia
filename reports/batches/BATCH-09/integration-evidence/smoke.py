"""BATCH-09 integration smoke using the installed package and frozen MetricsSink."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema
import pytest

from covenia_b.domain.types import RuntimeMetrics
from covenia_b.observability import (
    LOCKED_MODEL_ID,
    GovernanceContext,
    GovernanceLogWriteError,
    InputSourceKind,
    JsonlGovernanceSink,
    ModelIdentity,
    ProviderUsage,
    RuntimeMetricsCollector,
    SafeInputSource,
)
from covenia_b.observability import runtime as installed_runtime
from covenia_b.ports.contracts import MetricsSink


def main() -> None:
    run_dir = Path(r"C:\cov-run\i09oct1")
    venv = run_dir / "venv"
    repo = Path.cwd().resolve()
    assert Path(sys.executable).resolve() == venv / "Scripts" / "python.exe"
    assert Path(sys.prefix).resolve() == venv
    assert sys.prefix != sys.base_prefix
    assert os.environ.get("PYTHONPATH") is None
    config = (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    assert "include-system-site-packages = false" in config
    longest = max((str(p) for p in venv.rglob("*")), key=len)
    assert len(longest) < 250
    source_path = Path(installed_runtime.__file__).resolve()
    assert source_path.is_relative_to(repo / "backend" / "src")

    with TemporaryDirectory(prefix="smoke-", dir=run_dir) as scratch:
        log_path = Path(scratch) / "governance.jsonl"
        sink = JsonlGovernanceSink(log_path)
        raw_identifier = "integration-private-source-sentinel"
        source = SafeInputSource.from_identifier(
            phase="MODEL", kind=InputSourceKind.CHAT, identifier=raw_identifier
        )
        context = GovernanceContext(
            request_id="req-i09-model", run_id="run-i09oct1", endpoint="analyze",
            input_sources=(source,), pii_masked_count=1,
            model=ModelIdentity(model_id=LOCKED_MODEL_ID, model_revision="i09-smoke-v1",
                                prompt_version="i09-smoke-v1"),
        )
        ticks = iter((0, 5_000_000, 6_000_000, 13_000_000))
        session = RuntimeMetricsCollector(sink, monotonic_ns=lambda: next(ticks)).start_request(context)
        assert isinstance(session, MetricsSink)
        session.begin_model_attempt(attempt_id="i09-attempt-1").complete(
            provider_usage=ProviderUsage(input_tokens=11, output_tokens=4)
        )
        session.begin_model_attempt(attempt_id="i09-attempt-2").complete(
            provider_usage={"prompt_tokens": 3, "completion_tokens": 2}
        )
        before_cache = session.runtime_metrics
        assert session.record_cache_hit(event_id="i09-cache-1") == before_cache
        assert before_cache.model_dump() == {
            "input_tokens": 14, "output_tokens": 6,
            "inference_latency_ms": 12, "rule_substitution_count": 0,
        }
        rule_context = GovernanceContext(
            request_id="req-i09-rule", run_id="run-i09oct1", endpoint="evaluate",
            input_sources=(SafeInputSource.from_identifier(
                phase="RULE", kind=InputSourceKind.RULE, identifier="rule-chain-v1"
            ),), pii_masked_count=0,
        )
        rule_session = RuntimeMetricsCollector(sink).start_request(rule_context)
        rule_metrics = rule_session.record_rule_evaluation(event_id="i09-rule-1")
        assert rule_metrics.model_dump() == {
            "input_tokens": 0, "output_tokens": 0,
            "inference_latency_ms": 0, "rule_substitution_count": 1,
        }
        payload = log_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in payload.splitlines()]
        assert raw_identifier not in payload
        assert [r["event_kind"] for r in records] == [
            "MODEL_ATTEMPT", "MODEL_ATTEMPT", "CACHE_HIT", "RULE_EVALUATION"
        ]
        assert records[0]["input_sources"][0]["reference_sha256"] == source.reference_sha256
        assert records[-1]["request_id"] == rule_context.request_id

        class UnavailableSink:
            def write(self, record: object) -> None:
                raise OSError("integration smoke audit unavailable")

        failed = RuntimeMetricsCollector(UnavailableSink()).start_request(rule_context)
        try:
            failed.record_rule_evaluation(event_id="i09-audit-failure")
        except GovernanceLogWriteError:
            pass
        else:
            raise AssertionError("audit failure must propagate")
        assert failed.runtime_metrics == RuntimeMetrics(
            input_tokens=0, output_tokens=0, inference_latency_ms=0, rule_substitution_count=0
        )

    print(json.dumps({
        "status": "PASS", "scope": "local observability/domain/MetricsSink and JSONL; no live model or HTTP",
        "environment": {
            "interpreter": sys.executable, "python_version": sys.version.split()[0],
            "sys_prefix": sys.prefix, "sys_base_prefix": sys.base_prefix,
            "run_dir": str(run_dir), "venv": str(venv), "venv_direct_child": venv.parent == run_dir,
            "include_system_site_packages": False, "pythonpath": "UNSET",
            "longest_venv_path": longest, "longest_venv_path_length": len(longest),
            "longest_venv_path_lt_250": True, "installed_runtime": str(source_path),
            "required_imports": {"pytest": pytest.__version__, "jsonschema": jsonschema.__file__},
        },
        "checks": ["installed integration source", "frozen MetricsSink compatibility",
                   "exact provider usage across two attempts", "cache does not reimport tokens",
                   "pure-rule metrics", "redacted JSONL source/request trace", "audit failure propagation"],
        "model_metrics": before_cache.model_dump(), "rule_metrics": rule_metrics.model_dump(),
        "governance_records": records,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
