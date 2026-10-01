from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


PREFIX = "reports/batches/BATCH-08/"
CANONICAL_REPORT = PREFIX + "VERIFICATION_REPORT.json"
HISTORY_REPORT = (
    PREFIX
    + "history/81277d24217b993094cf22d54365e48f5faf11cd/VERIFICATION_REPORT.json"
)
SOURCE_COMMIT = "81277d24217b993094cf22d54365e48f5faf11cd"


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    ).stdout


def _record(payload: bytes) -> dict[str, Any]:
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve()
    output_relative = output.relative_to(repo).as_posix()

    changed_paths = [
        line
        for line in _git(repo, "diff", "--cached", "--name-only", "--").decode().splitlines()
        if line and line != output_relative
    ]
    outside_scope = [path for path in changed_paths if not path.startswith(PREFIX)]
    if outside_scope:
        raise RuntimeError(f"Staged paths outside BATCH-08 reports: {outside_scope}")

    artifacts = {
        path: _record(_git(repo, "show", f":{path}")) for path in changed_paths
    }
    source_history = _git(repo, "show", f"{SOURCE_COMMIT}:{CANONICAL_REPORT}")
    staged_history = _git(repo, "show", f":{HISTORY_REPORT}")
    canonical = json.loads(_git(repo, "show", f":{CANONICAL_REPORT}"))

    json_paths = [path for path in changed_paths if path.endswith(".json")]
    json_parse_failures: list[dict[str, str]] = []
    for path in json_paths:
        try:
            json.loads(_git(repo, "show", f":{path}"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            json_parse_failures.append({"path": path, "error": str(error)})

    report_required_checks = {
        "batch_id": canonical.get("batch_id") == "BATCH-08",
        "verdict": canonical.get("verdict") in {"PASS", "FAIL", "BLOCKED"},
        "commit_verified": canonical.get("commit_verified")
        == "6717c2803cb1bfe3598505cf5363dab0024331b0",
        "independent_context": canonical.get("independent_context") is True,
        "code_modified": canonical.get("code_modified") is False,
        "next_batch_started": canonical.get("next_batch_started") is False,
        "criteria_nonempty": bool(canonical.get("criteria")),
        "commands_nonempty": bool(canonical.get("commands")),
    }
    history_exact = source_history == staged_history
    passed = (
        not outside_scope
        and not json_parse_failures
        and history_exact
        and all(report_required_checks.values())
    )
    result = {
        "manifest_version": "1.0",
        "hash_method": "SHA-256 over staged Git blob bytes from git show :<path>",
        "self_excluded": output_relative,
        "changed_paths_hashed": len(changed_paths),
        "artifacts": artifacts,
        "history_preservation": {
            "source_commit": SOURCE_COMMIT,
            "source_path": CANONICAL_REPORT,
            "history_path": HISTORY_REPORT,
            "source_sha256": hashlib.sha256(source_history).hexdigest(),
            "history_sha256": hashlib.sha256(staged_history).hexdigest(),
            "byte_for_byte_equal": history_exact,
        },
        "json_validation": {
            "parsed": len(json_paths),
            "failures": json_parse_failures,
            "passed": not json_parse_failures,
        },
        "canonical_report_checks": report_required_checks,
        "passed": passed,
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
