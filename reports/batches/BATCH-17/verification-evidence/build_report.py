from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
BATCH_ROOT = REPO_ROOT / "reports" / "batches" / "BATCH-17"
EVIDENCE_ROOT = BATCH_ROOT / "verification-evidence"
REPORT_PATH = BATCH_ROOT / "VERIFICATION_REPORT.json"

REVIEW_SHA = "5cfbce2715fe543c28cda34856aa29e89ecc29eb"
BASE_SHA = "eb231c479cf07f314205d3b529bfcbad5a3b7217"
REVIEW_PARENT = "cc82915b260ac108137ada27ffda56d1b4b1bc3d"
REPORT_SHA = "60df6c2958f269960c2b716cce70681ee2064d49"
SCHEMA_AUTH_SHA = "f507e37d94c0532f377a9475de2129c52f75d584"


def read_json(name: str):
    return json.loads((EVIDENCE_ROOT / name).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    commands = read_json("commands.json")
    run_summary = read_json("run-summary.json")
    environment = read_json("environment.json")
    preflight = read_json("preflight.json")
    probe = read_json("11-independent-probe.json")
    raw_hashes = read_json("raw-blob-hashes.json")
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    current_integration_ref = subprocess.check_output(
        ["git", "rev-parse", "integration/covenia-b"], cwd=REPO_ROOT, text=True
    ).strip()
    post_ref_check = {
        "checked_at": checked_at,
        "fixed_reviewed_base_sha": BASE_SHA,
        "integration_ref_at_initial_preflight": preflight["base_branch_sha"],
        "integration_ref_after_verification": current_integration_ref,
        "drifted_after_or_during_verification": current_integration_ref != BASE_SHA,
        "action": "No ref reset, merge, integration, or re-verification against the drifted ref.",
    }
    write_json(EVIDENCE_ROOT / "post-ref-check.json", post_ref_check)

    for command in commands:
        command["required_for_verdict"] = True
        if command["id"] in {
            "00-runner-syntax-failure",
            "00b-runner-record-syntax-failure",
        }:
            command["required_for_verdict"] = False
            command["classification"] = "VERIFIER_HARNESS_FAILURE_RECOVERED"
        elif command["id"] == "12-full-backend-default-temp":
            command["required_for_verdict"] = False
            command["classification"] = "EXPECTED_ENVIRONMENT_ACL_FAILURE_PRESERVED"

    artifact_hashes = {
        item["path"]: {
            "sha256": item["sha256"],
            "source_commit": item["commit"],
            "bytes": item["bytes"],
            "basis": item["basis"],
        }
        for item in raw_hashes["artifacts"]
    }

    scope_audit = {
        "passed": True,
        "reviewed_range": f"{REVIEW_PARENT}..{REVIEW_SHA}",
        "reviewed_code_commit_paths": [
            "backend/src/covenia_b/receipts/__init__.py",
            "backend/src/covenia_b/receipts/projection.py",
            "backend/tests/receipts/test_projection.py",
        ],
        "allowed_paths_checked": [
            "backend/src/covenia_b/receipts/**",
            "backend/tests/receipts/**",
            "reports/batches/BATCH-17/**",
            "backend/requirements-dev.lock",
        ],
        "forbidden_changes": [],
        "requirements_dev_lock_changed": False,
        "schema_changed": False,
        "verification_report_precreated_in_review_commit": False,
        "implementation_report_commit": {
            "sha": REPORT_SHA,
            "parent_is_review_sha": True,
            "changed_path_count": 8,
            "all_paths_under": "reports/batches/BATCH-17/**",
            "contains_verification_report": False,
        },
        "base_to_review_topology": {
            "base_sha": BASE_SHA,
            "review_sha": REVIEW_SHA,
            "merge_base": REVIEW_PARENT,
            "base_is_review_ancestor": False,
            "direct_tree_diff_path_count": 63,
            "batch17_paths_in_direct_tree_diff": 3,
            "parallel_batch08_paths_in_direct_tree_diff": 60,
            "interpretation": (
                "The fixed integration baseline contains a parallel BATCH-08 tree "
                "advance, while the repair commit is a sibling from cc82915. The "
                "60 BATCH-08 paths are context only and are not attributed to BATCH-17."
            ),
        },
        "final_worktree_status": "?? reports/batches/BATCH-17/",
        "evidence": [
            "reports/batches/BATCH-17/verification-evidence/15a-review-commit-name-status.txt",
            "reports/batches/BATCH-17/verification-evidence/15b-base-to-review-name-status.txt",
            "reports/batches/BATCH-17/verification-evidence/15c-report-commit-name-status.txt",
            "reports/batches/BATCH-17/verification-evidence/16-status-short.txt",
        ],
    }
    write_json(EVIDENCE_ROOT / "scope-audit.json", scope_audit)

    anti_shortcut = {
        "passed": True,
        "skip_or_xfail_markers_in_review_receipt_tests": [],
        "fixture_id_markers_in_review_receipt_tree": [],
        "notes": (
            "The reviewed tests execute the projector and current JSON schema; "
            "the independent probe uses fresh AUDIT-V17 identifiers and fresh times."
        ),
    }
    write_json(EVIDENCE_ROOT / "anti-shortcut-review.json", anti_shortcut)

    criteria = [
        {
            "id": "B17-V-001",
            "criterion": "公开 consumer_view 删除 next_update_state，并排除内部字段和未确认通知草稿。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/11-independent-probe.json",
                "reports/batches/BATCH-17/verification-evidence/05-receipts-pytest.txt",
            ],
        },
        {
            "id": "B17-V-002",
            "criterion": "终态两时间字段均为 null，且没有通知草稿；latest_update_at 保留。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/11-independent-probe.json",
                "reports/batches/BATCH-17/verification-evidence/05-receipts-pytest.txt",
            ],
        },
        {
            "id": "B17-V-003",
            "criterion": "SCHEDULED 的 next_check_at、next_update_by、commits_next_update_at 完全相等，且通知文案包含同一时间。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/11-independent-probe.json",
                "reports/batches/BATCH-17/verification-evidence/05-receipts-pytest.txt",
            ],
        },
        {
            "id": "B17-V-004",
            "criterion": "ACTIVE、AT_RISK、COMPLETED 正例均通过当前 service_progress_receipt schema。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/11-independent-probe.json",
                "reports/batches/BATCH-17/verification-evidence/05-receipts-pytest.txt",
                "reports/batches/BATCH-17/verification-evidence/08-contract-check-strict.txt",
            ],
        },
        {
            "id": "B17-V-005",
            "criterion": "终态 future/draft 和 SCHEDULED 三时间任一不等的负向测试均拒绝；next_update_state 作为公开额外字段也被 schema 拒绝。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/11-independent-probe.json",
                "reports/batches/BATCH-17/verification-evidence/05-receipts-pytest.txt",
            ],
        },
        {
            "id": "B17-V-006",
            "criterion": "通知保持 requires_human_approval=true、is_sent=false，不进入消费者已接收回执。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/11-independent-probe.json",
                "reports/batches/BATCH-17/verification-evidence/05-receipts-pytest.txt",
            ],
        },
        {
            "id": "B17-V-007",
            "criterion": "使用本批一级隔离 venv、绝对解释器、路径小于 250；安装、pytest/jsonschema import、pip check、契约、ruff、diff check 和受控完整 backend 重跑通过。",
            "result": "PASS",
            "evidence": [
                "reports/batches/BATCH-17/verification-evidence/environment.json",
                "reports/batches/BATCH-17/verification-evidence/01-interpreter.txt",
                "reports/batches/BATCH-17/verification-evidence/04-imports.txt",
                "reports/batches/BATCH-17/verification-evidence/07-pip-check.txt",
                "reports/batches/BATCH-17/verification-evidence/08-contract-check-strict.txt",
                "reports/batches/BATCH-17/verification-evidence/09-contract-pytest.txt",
                "reports/batches/BATCH-17/verification-evidence/10-ruff.txt",
                "reports/batches/BATCH-17/verification-evidence/13-full-backend-confined-temp.txt",
                "reports/batches/BATCH-17/verification-evidence/14a-diff-check-review-commit.txt",
                "reports/batches/BATCH-17/verification-evidence/14b-diff-check-base-to-review-tree.txt",
                "reports/batches/BATCH-17/verification-evidence/14c-diff-check-worktree.txt",
            ],
        },
    ]

    report = {
        "report_version": "1.0",
        "batch_id": "BATCH-17",
        "task_id": "BATCH-17-VERIFY-1",
        "verdict": "PASS",
        "commit_verified": REVIEW_SHA,
        "reviewed_base_sha": BASE_SHA,
        "reviewed_base_ref": "integration/covenia-b",
        "reviewed_base_ref_at_initial_preflight": preflight["base_branch_sha"],
        "integration_ref_after_verification": current_integration_ref,
        "integration_ref_drift_observed": current_integration_ref != BASE_SHA,
        "reviewed_sha": REVIEW_SHA,
        "reviewed_code_commits": [REVIEW_SHA],
        "implementation_report_commit": REPORT_SHA,
        "implementation_report_parent_verified": True,
        "contract_version": "8314c76502cbc9d47d8432b7fe53f7d9fb82de82 / BATCH-03 contract-lock-v1",
        "schema_authorization": SCHEMA_AUTH_SHA,
        "plan_sha256": {
            "MASTER_PLAN.md": "DBE269F06F4BBE3D8C1F915DD8E4A2D78E0E4F021ABB396270C8B846D5FFA74E",
            "batches.json": "18DA555CE5ADEA5062F680837AEC8214158F58CBC1A918CF6BBC31EF48448E2E",
            "basis": "Independent SHA-256 over git show <reviewed_sha>:<path> raw bytes; git blob LF",
        },
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "independent_context": True,
        "worktree": {
            "path": str(REPO_ROOT),
            "branch": preflight["branch"],
            "initial_status_clean": preflight["initial_worktree_clean_before_evidence"],
            "commit_verified_matches_HEAD": preflight["commit_verified"] == REVIEW_SHA,
        },
        "environment": environment,
        "dependency_checks": [
            {
                "dependency": "BATCH-13",
                "result": "PASS",
                "verified_report": "reports/batches/BATCH-13/VERIFICATION_REPORT.json",
                "reviewed_report_blob_sha256": "4052ED03BE8BF40454DA4298C15000DA3D6553835332EABD8E158710EB93F9EB",
                "integration_commit": "c703e95fd2f8386c94d11cea7b34e585da840b73",
                "code_commit": "5af1ff0a0d59023d41aea357fcf65ea0ae243d1a",
                "code_and_integration_are_ancestors_of_base": True,
                "external_integration_receipt": {
                    "path": "C:\\Users\\WONG Tsun Ming\\covenia-orchestration\\runs\\covenia-b-20260910-01\\integration-receipts\\BATCH-13.json",
                    "status": "SUCCESS",
                    "hash": None,
                    "hash_note": "External read-only receipt is not a Git blob; no substituted working-copy hash used.",
                },
            },
            {
                "dependency": "backend/requirements-dev.lock",
                "result": "PASS",
                "changed_in_review_commit": False,
                "raw_blob_sha256": "177865457F146985726B02EF5C640363624E2A0C9B76B67FBED3929DADA13D04",
            },
        ],
        "external_gate_checks": [
            {
                "gate": "BATCH-17 external_gates",
                "result": "NOT_REQUIRED",
                "detail": "The BATCH-17 package declares no external gates.",
            }
        ],
        "scope_audit": scope_audit,
        "criteria": criteria,
        "commands": commands,
        "checks": {
            "required_command_run_summary": run_summary,
            "preflight": preflight,
            "schema_receipt_properties": {
                "additionalProperties": False,
                "next_update_by_types": ["string", "null"],
                "terminal_description_verified": True,
            },
            "anti_shortcut_review": anti_shortcut,
            "raw_blob_hash_claim_checks": raw_hashes["claim_checks"],
        },
        "artifact_hashes": artifact_hashes,
        "negative_controls": probe["negative_cases"],
        "findings": [
            {
                "id": "V17-OBS-001",
                "severity": "INFO",
                "category": "ENVIRONMENT",
                "finding": "Default pytest TEMP remains ACL-blocked for six tmp_path fixtures; the exact output is preserved and the confined RUN_DIR retry passed all 141 backend tests.",
                "evidence": [
                    "reports/batches/BATCH-17/verification-evidence/12-full-backend-default-temp.txt",
                    "reports/batches/BATCH-17/verification-evidence/13-full-backend-confined-temp.txt",
                ],
            },
            {
                "id": "V17-OBS-002",
                "severity": "INFO",
                "category": "BASELINE_TOPOLOGY",
                "finding": "The requested integration baseline and repair commit are siblings from cc82915; the direct tree diff contains 60 parallel BATCH-08 paths. Only the three paths in the fixed repair commit were attributed to BATCH-17.",
                "evidence": [
                    "reports/batches/BATCH-17/verification-evidence/15a-review-commit-name-status.txt",
                    "reports/batches/BATCH-17/verification-evidence/15b-base-to-review-name-status.txt",
                    "reports/batches/BATCH-17/verification-evidence/preflight.json",
                ],
            },
            {
                "id": "V17-OBS-003",
                "severity": "INFO",
                "category": "VERIFIER_HARNESS",
                "finding": "Two verifier-only harness parse attempts failed before acceptance execution; both are preserved, corrected within verification-evidence, and do not alter the reviewed implementation tree.",
                "evidence": [
                    "reports/batches/BATCH-17/verification-evidence/00-runner-syntax-failure.txt",
                    "reports/batches/BATCH-17/verification-evidence/00b-runner-record-syntax-failure.txt",
                ],
            },
            {
                "id": "V17-OBS-004",
                "severity": "INFO",
                "category": "EXTERNAL_REF_DRIFT",
                "finding": f"The fixed integration ref was eb231c... at initial preflight, then advanced externally to {current_integration_ref[:12]}... during report finalization. This verification remains pinned to the user-specified eb231c... SHA.",
                "evidence": [
                    "reports/batches/BATCH-17/verification-evidence/preflight.json",
                    "reports/batches/BATCH-17/verification-evidence/post-ref-check.json",
                ],
            },
        ],
        "risks": [
            {
                "risk": "The system TEMP ACL issue is environmental and remains present.",
                "mitigation": "Use C:\\cov-run\\v17oct2 TEMP/TMP/basetemp/cache for reproducible verification; do not modify ACL or delete the system directory.",
            },
            {
                "risk": "The review commit is not a descendant of the requested integration baseline because the baseline contains a parallel BATCH-08 advance.",
                "mitigation": "This report accepts only the fixed repair commit's three-file delta; integration must apply the exact commit to the baseline and run its own smoke gate.",
            },
            {
                "risk": "integration/covenia-b advanced from the fixed baseline SHA during the verification window.",
                "mitigation": "The verdict is for pinned eb231c479cf07f314205d3b529bfcbad5a3b7217 only; no current-ref content was substituted and no integration was started.",
            },
        ],
        "minimal_fix_list": [],
        "recheck_commands": [
            f"& '{environment['python']}' -m pytest backend/tests/receipts -q",
            f"& '{environment['python']}' tools/contracts/check_contracts.py --strict",
            f"& '{environment['python']}' -m ruff check --no-cache backend/src/covenia_b/receipts backend/tests/receipts",
            f"& '{environment['python']}' -m pip check",
            f"git diff --check {REVIEW_PARENT} {REVIEW_SHA}",
            f"& '{environment['python']}' -m pytest backend/tests -q --basetemp 'C:\\cov-run\\v17oct2\\pytest-tmp' -o 'cache_dir=C:\\cov-run\\v17oct2\\pytest-cache\\recheck'",
        ],
        "rollback_review": {
            "passed": True,
            "notes": "If later authorized, revert only 5cfbce2715fe543c28cda34856aa29e89ecc29eb; preserve schema authorization f507e37, responsibility history, and confirmation records. No force-reset, source deletion, or external send exists in this pure projection.",
        },
        "code_modified": False,
        "schema_modified": False,
        "lock_modified": False,
        "implementation_report_modified": False,
        "integration_started": False,
        "next_batch_started": False,
        "stop_after_pass": True,
        "evidence_root": "reports/batches/BATCH-17/verification-evidence/",
    }

    write_json(REPORT_PATH, report)


if __name__ == "__main__":
    main()
