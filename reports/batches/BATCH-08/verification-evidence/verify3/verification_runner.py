from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


BASE_INTEGRATION_SHA = "abaad9ae9228432ea514a45817c2fc166b27bad3"
ORIGINAL_CODE_SHA = "2373bcb22e24d491935d8c2b5d1efb512dde35cc"
ORIGINAL_REPORT_SHA = "8568ee512aad3c780ef5807d22821448b7403894"
REPAIR_CODE_SHA = "d06754cfd8974164e1ba87aa00695d033877b743"
REVIEW_SHA = "6717c2803cb1bfe3598505cf5363dab0024331b0"
SURROGATE_REPORT_SHA = "81277d24217b993094cf22d54365e48f5faf11cd"
PLAN_AUTHORITY_SHA = "190d8c884b912103d799441d50213d192e6b4d78"
EXPECTED_PLAN_HASHES = {
    "MASTER_PLAN.md": "dbe269f06f4bbe3d8c1f915dd8e4a2d78e0e4f021abb396270c8b846d5ffa74e",
    "batches.json": "18da555ce5adea5062f680837aec8214158f58cbc1a918cf6bbc31ef48448e2e",
}
DEPENDENCY_INTEGRATION_SHA = "9d093a492e576d7cb02b46c2ca60ebf2cac1c244"


def _display_command(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(
    records: list[dict[str, Any]],
    evidence_dir: Path,
    command_id: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    output_path = evidence_dir / f"{command_id}.txt"
    rendered = (
        f"command={_display_command(argv)}\n"
        f"cwd={cwd}\n"
        f"exit_code={completed.returncode}\n"
        "stdout:\n"
        f"{completed.stdout}"
        "stderr:\n"
        f"{completed.stderr}"
    )
    _write_text(output_path, rendered)
    records.append(
        {
            "id": command_id,
            "command": _display_command(argv),
            "cwd": str(cwd),
            "exit_code": completed.returncode,
            "output": output_path.relative_to(cwd).as_posix(),
        }
    )
    return completed


def _git(repo: Path, *args: str, check: bool = True) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
    ).stdout


def _git_text(repo: Path, *args: str) -> str:
    return _git(repo, *args).decode("utf-8", errors="strict")


def _git_show(repo: Path, commit: str, path: str) -> bytes:
    return _git(repo, "show", f"{commit}:{path}")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _blob_record(repo: Path, commit: str, path: str) -> dict[str, Any]:
    payload = _git_show(repo, commit, path)
    return {"bytes": len(payload), "sha256": _sha256(payload)}


def _name_status(repo: Path, left: str, right: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    output = _git_text(repo, "diff", "--name-status", left, right, "--")
    for line in output.splitlines():
        fields = line.split("\t")
        rows.append({"status": fields[0], "path": fields[-1]})
    return rows


def _allowed(path: str) -> bool:
    return (
        path.startswith("backend/src/covenia_b/images/")
        or path.startswith("backend/tests/images/")
        or path.startswith("reports/batches/BATCH-08/")
        or path == "backend/requirements-dev.lock"
    )


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _scope_and_hashes(repo: Path, dependency_receipt: Path) -> dict[str, Any]:
    full_scope = _name_status(repo, BASE_INTEGRATION_SHA, REVIEW_SHA)
    repair_scope = _name_status(repo, ORIGINAL_REPORT_SHA, REPAIR_CODE_SHA)
    evidence_scope = _name_status(repo, REPAIR_CODE_SHA, REVIEW_SHA)
    surrogate_scope = _name_status(repo, REVIEW_SHA, SURROGATE_REPORT_SHA)

    plan_hashes = {
        path: _blob_record(repo, PLAN_AUTHORITY_SHA, path)
        for path in EXPECTED_PLAN_HASHES
    }
    plan_hashes_match = all(
        plan_hashes[path]["sha256"] == expected
        for path, expected in EXPECTED_PLAN_HASHES.items()
    )

    required_outputs = [
        "reports/batches/BATCH-08/resolver-contract.json",
        "reports/batches/BATCH-08/security-cases.json",
        "reports/batches/BATCH-08/IMPLEMENTATION_REPORT.json",
        "reports/batches/BATCH-08/IMPLEMENTATION_REPORT.md",
        "reports/batches/BATCH-08/commands.json",
        "reports/batches/BATCH-08/environment.json",
        "reports/batches/BATCH-08/pip-check.txt",
    ]
    implementation_artifacts = {
        path: _blob_record(repo, REVIEW_SHA, path) for path in required_outputs
    }
    code_artifacts = {
        path: _blob_record(repo, REVIEW_SHA, path)
        for path in (
            "backend/src/covenia_b/images/resolver.py",
            "backend/src/covenia_b/images/__init__.py",
            "backend/tests/images/test_resolver.py",
            "backend/requirements-dev.lock",
        )
    }

    dependency_report_path = (
        repo / "reports" / "batches" / "BATCH-04" / "VERIFICATION_REPORT.json"
    )
    dependency_report = json.loads(dependency_report_path.read_text(encoding="utf-8"))
    dependency_receipt_json = json.loads(dependency_receipt.read_text(encoding="utf-8"))
    dependency_checks = {
        "verification_report_verdict": dependency_report.get("verdict"),
        "receipt_status": dependency_receipt_json.get("status"),
        "receipt_integration_commit": dependency_receipt_json.get("integration_commit"),
        "expected_integration_commit": DEPENDENCY_INTEGRATION_SHA,
        "dependency_integration_is_ancestor_of_batch_base": _is_ancestor(
            repo, DEPENDENCY_INTEGRATION_SHA, BASE_INTEGRATION_SHA
        ),
        "receipt_sha256": _sha256(dependency_receipt.read_bytes()),
        "passed": False,
    }
    dependency_checks["passed"] = (
        dependency_checks["verification_report_verdict"] == "PASS"
        and dependency_checks["receipt_status"] == "SUCCESS"
        and dependency_checks["receipt_integration_commit"]
        == dependency_checks["expected_integration_commit"]
        and dependency_checks["dependency_integration_is_ancestor_of_batch_base"]
    )

    repair_paths = [row["path"] for row in repair_scope]
    repair_scope_exact = repair_paths == [
        "backend/src/covenia_b/images/resolver.py",
        "backend/tests/images/test_resolver.py",
    ]
    evidence_scope_only_reports = all(
        row["path"].startswith("reports/batches/BATCH-08/") for row in evidence_scope
    )
    surrogate_scope_exact = sorted(row["path"] for row in surrogate_scope) == [
        "reports/batches/BATCH-08/VERIFICATION_REPORT.json",
        "reports/batches/BATCH-08/verification-evidence/verifier-probe.py",
    ]
    lock_at_base = _blob_record(repo, BASE_INTEGRATION_SHA, "backend/requirements-dev.lock")
    lock_at_review = _blob_record(repo, REVIEW_SHA, "backend/requirements-dev.lock")

    assertions = {
        "commit_chain": all(
            _is_ancestor(repo, left, right)
            for left, right in (
                (BASE_INTEGRATION_SHA, ORIGINAL_CODE_SHA),
                (ORIGINAL_CODE_SHA, ORIGINAL_REPORT_SHA),
                (ORIGINAL_REPORT_SHA, REPAIR_CODE_SHA),
                (REPAIR_CODE_SHA, REVIEW_SHA),
                (REVIEW_SHA, SURROGATE_REPORT_SHA),
            )
        ),
        "full_scope_allowlisted": all(_allowed(row["path"]) for row in full_scope),
        "repair_scope_exact": repair_scope_exact,
        "repair_evidence_scope_only_reports": evidence_scope_only_reports,
        "surrogate_scope_exact": surrogate_scope_exact,
        "requirements_lock_unchanged": lock_at_base == lock_at_review,
        "plan_hashes_match_expected": plan_hashes_match,
        "dependency_passed": dependency_checks["passed"],
    }
    return {
        "hash_method": "SHA-256 over raw bytes returned by git show <commit>:<path>",
        "commits": {
            "base_integration": BASE_INTEGRATION_SHA,
            "original_code": ORIGINAL_CODE_SHA,
            "original_report": ORIGINAL_REPORT_SHA,
            "repair_code": REPAIR_CODE_SHA,
            "reviewed_implementation": REVIEW_SHA,
            "surrogate_report": SURROGATE_REPORT_SHA,
        },
        "full_scope_base_to_review": full_scope,
        "repair_scope": repair_scope,
        "repair_evidence_scope": evidence_scope,
        "surrogate_report_scope": surrogate_scope,
        "plan_authority_commit": PLAN_AUTHORITY_SHA,
        "plan_hashes": plan_hashes,
        "expected_plan_hashes": EXPECTED_PLAN_HASHES,
        "requirements_lock": {"base": lock_at_base, "review": lock_at_review},
        "code_artifacts": code_artifacts,
        "implementation_artifacts": implementation_artifacts,
        "surrogate_report_artifacts": {
            "VERIFICATION_REPORT.json": _blob_record(
                repo,
                SURROGATE_REPORT_SHA,
                "reports/batches/BATCH-08/VERIFICATION_REPORT.json",
            ),
            "verifier-probe.py": _blob_record(
                repo,
                SURROGATE_REPORT_SHA,
                "reports/batches/BATCH-08/verification-evidence/verifier-probe.py",
            ),
        },
        "dependency_checks": dependency_checks,
        "assertions": assertions,
        "all_passed": all(assertions.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--base-python", required=True, type=Path)
    parser.add_argument("--dependency-receipt", required=True, type=Path)
    args = parser.parse_args()

    repo = args.repo.resolve()
    run_dir = args.run_dir.resolve()
    evidence_dir = Path(__file__).resolve().parent
    venv_dir = run_dir / "venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    child_env = dict(os.environ)
    child_env.pop("PYTHONPATH", None)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    records: list[dict[str, Any]] = []

    if run_dir.exists():
        raise RuntimeError(f"Refusing to reuse existing RUN_DIR: {run_dir}")

    create = _run(
        records,
        evidence_dir,
        "01-create-venv",
        [str(args.base_python), "-m", "venv", str(venv_dir)],
        cwd=repo,
        env=child_env,
    )
    if create.returncode != 0 or not venv_python.is_file():
        _write_text(
            evidence_dir / "commands.json",
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        )
        return 1

    preflight_code = (
        "import json, os, site, sys; from pathlib import Path; "
        "expected=Path(sys.argv[1]).resolve(); actual=Path(sys.executable).resolve(); "
        "assert actual == expected and sys.prefix != sys.base_prefix; "
        "print(json.dumps({'sys_executable':str(actual),'python_version':sys.version,"
        "'sys_prefix':sys.prefix,'sys_base_prefix':sys.base_prefix,"
        "'pythonpath':os.environ.get('PYTHONPATH','UNSET'),"
        "'enable_user_site':site.ENABLE_USER_SITE}, ensure_ascii=False))"
    )
    commands = [
        ("02-preflight", [str(venv_python), "-c", preflight_code, str(venv_python)]),
        (
            "03-lock-install",
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "-r",
                "backend/requirements-dev.lock",
            ],
        ),
        (
            "04-editable-install",
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "-e",
                "backend",
            ],
        ),
        (
            "05-imports",
            [
                str(venv_python),
                "-c",
                "import pytest, jsonschema; print('pytest/jsonschema import OK')",
            ],
        ),
        (
            "06-images-pytest",
            [str(venv_python), "-m", "pytest", "backend/tests/images", "-q"],
        ),
        ("07-pip-list", [str(venv_python), "-m", "pip", "list", "--format=json"]),
        ("08-pip-check", [str(venv_python), "-m", "pip", "check"]),
        (
            "09-focused-dqt-dht",
            [
                str(venv_python),
                "-m",
                "pytest",
                "backend/tests/images/test_resolver.py",
                "-q",
                "-k",
                "jpeg_missing",
            ],
        ),
        (
            "10-ruff",
            [
                str(venv_python),
                "-m",
                "ruff",
                "check",
                "backend/src/covenia_b/images",
                "backend/tests/images",
            ],
        ),
        (
            "11-independent-probe",
            [
                str(venv_python),
                str(evidence_dir / "independent_probe.py"),
                "--repo",
                str(repo),
                "--run-dir",
                str(run_dir),
                "--output",
                str(evidence_dir / "independent-probe.json"),
            ],
        ),
        (
            "12-diff-check-reviewed-range",
            [
                "git",
                "-C",
                str(repo),
                "diff",
                "--check",
                BASE_INTEGRATION_SHA,
                REVIEW_SHA,
                "--",
            ],
        ),
        ("13-diff-check-worktree", ["git", "-C", str(repo), "diff", "--check"]),
        ("14-status-short", ["git", "-C", str(repo), "status", "--short"]),
    ]
    for command_id, argv in commands:
        _run(records, evidence_dir, command_id, argv, cwd=repo, env=child_env)

    longest_path = max(
        (path for path in venv_dir.rglob("*") if path.is_file()),
        key=lambda path: len(str(path)),
    )
    pyvenv_cfg = (venv_dir / "pyvenv.cfg").read_text(encoding="utf-8")
    environment = {
        "run_dir": str(run_dir),
        "venv": str(venv_dir),
        "venv_direct_child": venv_dir.parent == run_dir,
        "interpreter": str(venv_python),
        "pythonpath_child_state": "UNSET",
        "include_system_site_packages_enabled": False,
        "include_system_site_packages_false_confirmed": (
            "include-system-site-packages = false" in pyvenv_cfg.lower()
        ),
        "longest_venv_file": str(longest_path),
        "longest_venv_path_length": len(str(longest_path)),
        "longest_venv_path_lt_250": len(str(longest_path)) < 250,
    }
    _write_text(
        evidence_dir / "environment.json",
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n",
    )

    scope_and_hashes = _scope_and_hashes(repo, args.dependency_receipt)
    _write_text(
        evidence_dir / "scope-and-hashes.json",
        json.dumps(scope_and_hashes, ensure_ascii=False, indent=2) + "\n",
    )
    _write_text(
        evidence_dir / "commands.json",
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
    )

    command_pass = all(record["exit_code"] == 0 for record in records)
    overall = (
        command_pass
        and environment["venv_direct_child"]
        and environment["include_system_site_packages_false_confirmed"]
        and environment["longest_venv_path_lt_250"]
        and scope_and_hashes["all_passed"]
    )
    print(
        json.dumps(
            {
                "overall_passed": overall,
                "command_passed": command_pass,
                "environment_passed": environment,
                "scope_and_hashes_passed": scope_and_hashes["all_passed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
