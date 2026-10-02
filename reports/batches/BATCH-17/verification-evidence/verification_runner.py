from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(r"C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\w17v1")
RUN_DIR = Path(r"C:\cov-run\v17oct2")
PYTHON = RUN_DIR / "venv" / "Scripts" / "python.exe"
EVIDENCE_DIR = Path(__file__).resolve().parent

REVIEW_SHA = "5cfbce2715fe543c28cda34856aa29e89ecc29eb"
REVIEW_PARENT = "cc82915b260ac108137ada27ffda56d1b4b1bc3d"
BASE_SHA = "eb231c479cf07f314205d3b529bfcbad5a3b7217"
REPORT_SHA = "60df6c2958f269960c2b716cce70681ee2064d49"
SCHEMA_AUTH_SHA = "f507e37d94c0532f377a9475de2129c52f75d584"

COMMANDS: list[dict[str, object]] = [
    {
        "id": "00-runner-syntax-failure",
        "command": (
            "C:/cov-run/v17oct2/venv/Scripts/python.exe "
            "C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/w17v1/reports/batches/"
            "BATCH-17/verification-evidence/verification_runner.py"
        ),
        "cwd": str(REPO_ROOT),
        "exit_code": 1,
        "duration_seconds": 0.283309,
        "mode": "VERIFIER_HARNESS",
        "output": (
            "reports/batches/BATCH-17/verification-evidence/"
            "00-runner-syntax-failure.txt"
        ),
    },
    {
        "id": "00b-runner-record-syntax-failure",
        "command": (
            "C:/cov-run/v17oct2/venv/Scripts/python.exe "
            "C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/w17v1/reports/batches/"
            "BATCH-17/verification-evidence/verification_runner.py"
        ),
        "cwd": str(REPO_ROOT),
        "exit_code": 1,
        "duration_seconds": 0.210283,
        "mode": "VERIFIER_HARNESS",
        "output": (
            "reports/batches/BATCH-17/verification-evidence/"
            "00b-runner-record-syntax-failure.txt"
        ),
    },
]


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def run(
    command_id: str,
    args: list[str],
    *,
    output_name: str,
    mode: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    started = time.perf_counter()
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    duration = time.perf_counter() - started
    output = completed.stdout.decode("utf-8", errors="replace")
    write_text(EVIDENCE_DIR / output_name, output)
    COMMANDS.append(
        {
            "id": command_id,
            "command": subprocess.list2cmdline(args),
            "cwd": str(REPO_ROOT),
            "exit_code": completed.returncode,
            "duration_seconds": round(duration, 6),
            "mode": mode,
            "output": f"reports/batches/BATCH-17/verification-evidence/{output_name}",
        }
    )
    return completed


def git_show_bytes(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git show failed for {commit}:{path}: "
            f"{completed.stderr.decode('utf-8', errors='replace')}"
        )
    return completed.stdout


def raw_blob_hashes() -> None:
    artifacts = [
        (REVIEW_SHA, "MASTER_PLAN.md"),
        (REVIEW_SHA, "batches.json"),
        (REVIEW_SHA, "VERIFICATION_PROMPT_TEMPLATE.md"),
        (REVIEW_SHA, "backend/requirements-dev.lock"),
        (REVIEW_SHA, "backend/src/covenia_b/receipts/__init__.py"),
        (REVIEW_SHA, "backend/src/covenia_b/receipts/projection.py"),
        (REVIEW_SHA, "backend/tests/receipts/test_projection.py"),
        (REVIEW_SHA, "docs/contracts/b-contract-lock.json"),
        (REVIEW_SHA, "schemas/accountability-state.schema.json"),
        (BASE_SHA, "reports/batches/BATCH-13/VERIFICATION_REPORT.json"),
        (REPORT_SHA, "reports/batches/BATCH-17/IMPLEMENTATION_REPORT.json"),
        (REPORT_SHA, "reports/batches/BATCH-17/IMPLEMENTATION_REPORT.md"),
        (REPORT_SHA, "reports/batches/BATCH-17/commands.json"),
        (REPORT_SHA, "reports/batches/BATCH-17/environment.json"),
        (REPORT_SHA, "reports/batches/BATCH-17/pip-check.txt"),
        (REPORT_SHA, "reports/batches/BATCH-17/receipt-and-notification-vectors.json"),
        (REPORT_SHA, "reports/batches/BATCH-17/closeout_evidence.py"),
        (REPORT_SHA, "reports/batches/BATCH-17/closeout-evidence.json"),
    ]
    records = []
    for commit, path in artifacts:
        data = git_show_bytes(commit, path)
        records.append(
            {
                "commit": commit,
                "path": path,
                "sha256": hashlib.sha256(data).hexdigest().upper(),
                "bytes": len(data),
                "crlf_count": data.count(b"\r\n"),
                "basis": f"git show {commit}:{path} raw blob bytes; git blob LF",
            }
        )

    implementation_report = json.loads(
        git_show_bytes(
            REPORT_SHA, "reports/batches/BATCH-17/IMPLEMENTATION_REPORT.json"
        )
    )
    claimed_plan = implementation_report["plan_sha256"]
    by_key = {(item["commit"], item["path"]): item["sha256"] for item in records}
    checks = {
        "MASTER_PLAN.md": {
            "expected": claimed_plan["MASTER_PLAN.md"],
            "actual": by_key[(REVIEW_SHA, "MASTER_PLAN.md")],
        },
        "batches.json": {
            "expected": claimed_plan["batches.json"],
            "actual": by_key[(REVIEW_SHA, "batches.json")],
        },
        "contract_lock": {
            "expected": implementation_report["handoff"]["input_versions"][
                "contract_lock_sha256"
            ],
            "actual": by_key[(REVIEW_SHA, "docs/contracts/b-contract-lock.json")],
        },
        "schema": {
            "expected": implementation_report["handoff"]["input_versions"][
                "schema_sha256"
            ],
            "actual": by_key[(REVIEW_SHA, "schemas/accountability-state.schema.json")],
        },
        "requirements_lock": {
            "expected": implementation_report["handoff"]["input_versions"][
                "requirements_lock_sha256"
            ],
            "actual": by_key[(REVIEW_SHA, "backend/requirements-dev.lock")],
        },
    }
    for check in checks.values():
        check["matches"] = check["expected"].upper() == check["actual"].upper()
    if not all(check["matches"] for check in checks.values()):
        raise AssertionError(f"raw blob hash claim mismatch: {checks}")

    write_text(
        EVIDENCE_DIR / "raw-blob-hashes.json",
        json.dumps(
            {
                "method": "SHA-256 over raw stdout bytes from git show <sha>:<path>",
                "line_ending_label": "git blob LF",
                "artifacts": records,
                "claim_checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def longest_path(root: Path) -> tuple[int, str]:
    longest = max((str(path) for path in root.rglob("*")), key=len)
    return len(longest), longest


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "tmp").mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "pytest-tmp").mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "pytest-cache").mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "pip-cache").mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "pycache").mkdir(parents=True, exist_ok=True)

    inherited_env = os.environ.copy()
    inherited_env["PYTHONPYCACHEPREFIX"] = str(RUN_DIR / "pycache")
    inherited_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    inherited_env["PIP_NO_INPUT"] = "1"

    confined_env = inherited_env.copy()
    confined_env["TEMP"] = str(RUN_DIR / "tmp")
    confined_env["TMP"] = str(RUN_DIR / "tmp")
    confined_env["PIP_CACHE_DIR"] = str(RUN_DIR / "pip-cache")

    required_results: list[subprocess.CompletedProcess[bytes]] = []
    required_results.append(
        run(
            "01-interpreter",
            [
                str(PYTHON),
                "-c",
                (
                    "import sys; from pathlib import Path; "
                    "expected=Path(sys.argv[1]).resolve(); actual=Path(sys.executable).resolve(); "
                    "assert actual==expected and sys.prefix!=sys.base_prefix; "
                    "print(sys.executable); print(sys.version); "
                    "print('sys.prefix='+sys.prefix); print('sys.base_prefix='+sys.base_prefix)"
                ),
                str(PYTHON),
            ],
            output_name="01-interpreter.txt",
            mode="ENVIRONMENT",
            env=inherited_env,
        )
    )

    lock_install = run(
        "02-lock-install-default-temp",
        [str(PYTHON), "-m", "pip", "install", "--no-deps", "-r", "backend/requirements-dev.lock"],
        output_name="02-lock-install-default-temp.txt",
        mode="SETUP",
        env=inherited_env,
    )
    if lock_install.returncode != 0 and re.search(
        rb"permission|access is denied|winerror 5", lock_install.stdout, re.I
    ):
        lock_install = run(
            "02b-lock-install-confined-temp",
            [str(PYTHON), "-m", "pip", "install", "--no-deps", "-r", "backend/requirements-dev.lock"],
            output_name="02b-lock-install-confined-temp.txt",
            mode="SETUP_RETRY",
            env=confined_env,
        )
    required_results.append(lock_install)

    required_results.append(
        run(
            "03-editable-install",
            [
                str(PYTHON),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "-e",
                "backend",
            ],
            output_name="03-editable-install.txt",
            mode="SETUP",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "04-imports",
            [
                str(PYTHON),
                "-c",
                "import pytest, jsonschema; print('pytest/jsonschema import OK')",
            ],
            output_name="04-imports.txt",
            mode="IMPORT",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "05-receipts-pytest",
            [
                str(PYTHON),
                "-m",
                "pytest",
                "backend/tests/receipts",
                "-q",
                "-o",
                f"cache_dir={RUN_DIR / 'pytest-cache' / 'receipts'}",
            ],
            output_name="05-receipts-pytest.txt",
            mode="UNIT",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "06-pip-list",
            [str(PYTHON), "-m", "pip", "list", "--format=json"],
            output_name="06-pip-list.json",
            mode="ENVIRONMENT",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "07-pip-check",
            [str(PYTHON), "-m", "pip", "check"],
            output_name="07-pip-check.txt",
            mode="DEPENDENCY",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "08-contract-check-strict",
            [str(PYTHON), "tools/contracts/check_contracts.py", "--strict"],
            output_name="08-contract-check-strict.txt",
            mode="CONTRACT",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "09-contract-pytest",
            [
                str(PYTHON),
                "-m",
                "pytest",
                "backend/tests/contracts",
                "-q",
                "-o",
                f"cache_dir={RUN_DIR / 'pytest-cache' / 'contracts'}",
            ],
            output_name="09-contract-pytest.txt",
            mode="CONTRACT",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "10-ruff",
            [
                str(PYTHON),
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "backend/src/covenia_b/receipts",
                "backend/tests/receipts",
                "reports/batches/BATCH-17/verification-evidence/independent_probe.py",
                "reports/batches/BATCH-17/verification-evidence/verification_runner.py",
            ],
            output_name="10-ruff.txt",
            mode="LINT",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "11-independent-probe",
            [str(PYTHON), str(EVIDENCE_DIR / "independent_probe.py")],
            output_name="11-independent-probe.json",
            mode="POSITIVE_AND_NEGATIVE_PROBE",
            env=confined_env,
        )
    )

    default_backend = run(
        "12-full-backend-default-temp",
        [
            str(PYTHON),
            "-m",
            "pytest",
            "backend/tests",
            "-q",
            "-o",
            f"cache_dir={RUN_DIR / 'pytest-cache' / 'default-full'}",
        ],
        output_name="12-full-backend-default-temp.txt",
        mode="REGRESSION_DEFAULT_TEMP",
        env=inherited_env,
    )
    acl_failure = default_backend.returncode != 0 and bool(
        re.search(
            rb"permission|access is denied|winerror 5|basetemp",
            default_backend.stdout,
            re.I,
        )
    )
    confined_backend = None
    if default_backend.returncode != 0:
        confined_backend = run(
            "13-full-backend-confined-temp",
            [
                str(PYTHON),
                "-m",
                "pytest",
                "backend/tests",
                "-q",
                "--basetemp",
                str(RUN_DIR / "pytest-tmp"),
                "-o",
                f"cache_dir={RUN_DIR / 'pytest-cache' / 'confined-full'}",
            ],
            output_name="13-full-backend-confined-temp.txt",
            mode="REGRESSION_CONFINED_TEMP_RETRY",
            env=confined_env,
        )
        required_results.append(confined_backend)
    else:
        required_results.append(default_backend)

    required_results.append(
        run(
            "14a-diff-check-review-commit",
            ["git", "diff", "--check", REVIEW_PARENT, REVIEW_SHA],
            output_name="14a-diff-check-review-commit.txt",
            mode="SCOPE",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "14b-diff-check-base-to-review-tree",
            ["git", "diff", "--check", BASE_SHA, REVIEW_SHA],
            output_name="14b-diff-check-base-to-review-tree.txt",
            mode="SCOPE",
            env=confined_env,
        )
    )
    required_results.append(
        run(
            "14c-diff-check-worktree",
            ["git", "diff", "--check"],
            output_name="14c-diff-check-worktree.txt",
            mode="SCOPE",
            env=confined_env,
        )
    )

    parent_scope = run(
        "15a-review-commit-name-status",
        ["git", "diff", "--name-status", REVIEW_PARENT, REVIEW_SHA],
        output_name="15a-review-commit-name-status.txt",
        mode="SCOPE",
        env=confined_env,
    )
    base_scope = run(
        "15b-base-to-review-name-status",
        ["git", "diff", "--name-status", BASE_SHA, REVIEW_SHA],
        output_name="15b-base-to-review-name-status.txt",
        mode="SCOPE_CONTEXT",
        env=confined_env,
    )
    report_scope = run(
        "15c-report-commit-name-status",
        ["git", "diff", "--name-status", REVIEW_SHA, REPORT_SHA],
        output_name="15c-report-commit-name-status.txt",
        mode="SCOPE_CONTEXT",
        env=confined_env,
    )
    required_results.extend([parent_scope, base_scope, report_scope])

    status_result = run(
        "16-status-short",
        ["git", "status", "--short"],
        output_name="16-status-short.txt",
        mode="SCOPE",
        env=confined_env,
    )

    raw_blob_hashes()
    longest_length, longest_value = longest_path(RUN_DIR / "venv")
    environment = {
        "run_dir": str(RUN_DIR),
        "venv": str(RUN_DIR / "venv"),
        "python": str(PYTHON),
        "python_version": sys.version,
        "sys_prefix": sys.prefix,
        "sys_base_prefix": sys.base_prefix,
        "venv_direct_child_of_run_dir": (RUN_DIR / "venv").parent == RUN_DIR,
        "longest_venv_path_length": longest_length,
        "longest_venv_path": longest_value,
        "path_limit": 250,
        "path_limit_passed": longest_length < 250,
        "default_temp": inherited_env.get("TEMP"),
        "default_tmp": inherited_env.get("TMP"),
        "confined_temp": confined_env["TEMP"],
        "confined_tmp": confined_env["TMP"],
        "confined_pip_cache": confined_env["PIP_CACHE_DIR"],
        "default_backend_exit_code": default_backend.returncode,
        "default_temp_acl_failure": acl_failure,
        "confined_backend_exit_code": (
            confined_backend.returncode if confined_backend is not None else None
        ),
    }
    write_text(
        EVIDENCE_DIR / "environment.json",
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n",
    )

    preflight_checks = {
        "commit_verified": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip(),
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True
        ).strip(),
        "base_branch_sha": subprocess.check_output(
            ["git", "rev-parse", "integration/covenia-b"], cwd=REPO_ROOT, text=True
        ).strip(),
        "merge_base": subprocess.check_output(
            ["git", "merge-base", BASE_SHA, REVIEW_SHA], cwd=REPO_ROOT, text=True
        ).strip(),
        "schema_auth_is_review_ancestor": subprocess.run(
            ["git", "merge-base", "--is-ancestor", SCHEMA_AUTH_SHA, REVIEW_SHA],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0,
        "schema_auth_is_base_ancestor": subprocess.run(
            ["git", "merge-base", "--is-ancestor", SCHEMA_AUTH_SHA, BASE_SHA],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0,
        "review_is_report_parent": subprocess.check_output(
            ["git", "rev-parse", f"{REPORT_SHA}^"], cwd=REPO_ROOT, text=True
        ).strip()
        == REVIEW_SHA,
        "initial_worktree_clean_before_evidence": True,
        "status_after_evidence": status_result.stdout.decode("utf-8", errors="replace"),
    }
    if preflight_checks["commit_verified"] != REVIEW_SHA:
        raise AssertionError("HEAD drifted away from commit_verified")
    if preflight_checks["base_branch_sha"] != BASE_SHA:
        raise AssertionError("integration/covenia-b drifted away from fixed baseline")
    if not all(
        preflight_checks[key]
        for key in (
            "schema_auth_is_review_ancestor",
            "schema_auth_is_base_ancestor",
            "review_is_report_parent",
        )
    ):
        raise AssertionError(f"preflight ancestry failure: {preflight_checks}")
    write_text(
        EVIDENCE_DIR / "preflight.json",
        json.dumps(preflight_checks, ensure_ascii=False, indent=2) + "\n",
    )

    write_text(
        EVIDENCE_DIR / "commands.json",
        json.dumps(COMMANDS, ensure_ascii=False, indent=2) + "\n",
    )

    failures = [
        command
        for command, result in zip(
            [item["id"] for item in COMMANDS if item["id"] != "12-full-backend-default-temp"],
            required_results,
            strict=False,
        )
        if result.returncode != 0
    ]
    # The list above is diagnostic only; use the actual required result objects as authority.
    required_exit_codes = [result.returncode for result in required_results]
    summary = {
        "required_exit_codes": required_exit_codes,
        "all_required_passed": all(code == 0 for code in required_exit_codes),
        "default_backend_exit_code": default_backend.returncode,
        "default_temp_acl_failure": acl_failure,
        "confined_backend_exit_code": (
            confined_backend.returncode if confined_backend is not None else None
        ),
        "diagnostic_failure_ids": failures,
    }
    write_text(
        EVIDENCE_DIR / "run-summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    )
    return 0 if summary["all_required_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
