"""Import pinned BATCH-08 Git blobs, then smoke the resulting integration commit.

Only Git performs the mechanical code/test import. Generated evidence is scoped
to this batch or its explicitly authorized short runtime and external receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
BASE = "cc82915b260ac108137ada27ffda56d1b4b1bc3d"
IMPLEMENTATION = "6717c2803cb1bfe3598505cf5363dab0024331b0"
VERIFICATION = "48ea15acf45c46ec48d52475480610254dafb841"
PRIOR = "81277d24217b993094cf22d54365e48f5faf11cd"
FIRST_FAIL = "bce2c606a03ea3c0f6d2d588600d7ed66b1799c7"
REPORT = "reports/batches/BATCH-08/VERIFICATION_REPORT.json"
REPORT_HASH = "55007495ed2aaf7425969a97a4fd51c5d918f77e3cda841e6e05e7985c54c8a6"
RUN = Path(r"C:\cov-run\i08oct1")
PYTHON = RUN / "venv" / "Scripts" / "python.exe"
BOOTSTRAP = Path(r"D:\python\python.exe")
RECEIPT = Path(
    r"C:\Users\WONG Tsun Ming\covenia-orchestration\runs"
    r"\covenia-b-20260910-01\integration-receipts\BATCH-08.json"
)
PREFIXES = (
    "backend/src/covenia_b/images/",
    "backend/tests/images/",
    "reports/batches/BATCH-08/",
)
PLAN_HASHES = {
    "MASTER_PLAN.md": "dbe269f06f4bbe3d8c1f915dd8e4a2d78e0e4f021abb396270c8b846d5ffa74e",
    "batches.json": "18da555ce5adea5062f680837aec8214158f58cbc1a918cf6bbc31ef48448e2e",
}
HASH_METHOD = "SHA-256 over raw git show <sha>:<path> bytes; git blob LF; never CRLF working-copy expectations"


def now():
    return datetime.now().astimezone().isoformat()


def git(*args, ok=(0,)):
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=REPO, capture_output=True,
    )
    if result.returncode not in ok:
        raise RuntimeError(
            f"git {args!r} exit={result.returncode}: "
            + result.stderr.decode("utf-8", errors="replace")
        )
    return result


def text_git(*args):
    return git(*args).stdout.decode("utf-8").strip()


def blob(sha, path):
    return git("show", f"{sha}:{path}").stdout


def digest(body):
    return hashlib.sha256(body).hexdigest()


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def tree(sha):
    entries = {}
    for row in git("ls-tree", "-r", "-z", sha).stdout.split(b"\0"):
        if row:
            metadata, path = row.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            entries[path.decode("utf-8")] = {"mode": mode, "type": kind, "oid": oid}
    return entries


def allowed(path):
    return path.startswith(PREFIXES)


def main_refs():
    rows = text_git("for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    return dict(row.split(" ", 1) for row in rows if row.split(" ", 1)[0].endswith("/main"))


def child_env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update({
        "TEMP": str(RUN / "tmp"), "TMP": str(RUN / "tmp"),
        "PIP_CACHE_DIR": str(RUN / "cache" / "pip"),
        "RUFF_CACHE_DIR": str(RUN / "cache" / "ruff"),
        "PYTEST_ADDOPTS": f"-o cache_dir={(RUN / 'cache' / 'pytest').as_posix()}",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    })
    return env


def run_command(name, args, mode, filename=None):
    env = child_env()
    started = now()
    print(f"RUN {name}: {subprocess.list2cmdline([str(a) for a in args])}", flush=True)
    start = time.monotonic()
    result = subprocess.run(
        [str(a) for a in args], cwd=REPO, env=env, capture_output=True,
    )
    duration = round(time.monotonic() - start, 3)
    output = RUN / "logs" / (filename or f"{name}.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        f"started_at={started}\ncommand={subprocess.list2cmdline([str(a) for a in args])}\n"
        f"cwd={REPO}\nexit_code={result.returncode}\nduration_seconds={duration}\n"
        f"mode={mode}\n\nSTDOUT\n".encode("utf-8") + result.stdout
        + b"\nSTDERR\n" + result.stderr
    )
    entry = {
        "name": name, "command": subprocess.list2cmdline([str(a) for a in args]),
        "argv": [str(a) for a in args], "cwd": str(REPO),
        "started_at": started, "exit_code": result.returncode,
        "duration_seconds": duration, "mode": mode, "output": str(output),
        "integration_sha": text_git("rev-parse", "HEAD"),
        "environment": {k: env.get(k) for k in (
            "TEMP", "TMP", "PIP_CACHE_DIR", "RUFF_CACHE_DIR", "PYTEST_ADDOPTS",
            "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
        )},
    }
    commands_path = RUN / "commands.json"
    commands = load(commands_path) if commands_path.exists() else []
    commands.append(entry)
    dump(commands_path, commands)
    print(result.stdout.decode("utf-8", errors="replace").strip(), flush=True)
    if result.stderr:
        print(result.stderr.decode("utf-8", errors="replace").strip(), flush=True)
    print(f"RESULT {name}: exit={result.returncode}, seconds={duration}, log={output}", flush=True)
    if result.returncode:
        dump(RUN / "blocker.json", {"at": now(), "command": entry, "status": "BLOCKED"})
        raise RuntimeError(f"{name} failed; no product/test repair permitted; see {output}")
    return entry, result


def preflight():
    assert str(REPO) == r"C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\worktrees\covenia-integration"
    assert text_git("branch", "--show-current") == "integration/covenia-b"
    assert text_git("rev-parse", "HEAD") == BASE
    assert not git("diff", "--name-only").stdout
    assert not git("diff", "--cached", "--name-only").stdout
    current = tree(BASE)
    source = tree(VERIFICATION)
    implementation = tree(IMPLEMENTATION)
    raw = blob(VERIFICATION, REPORT)
    assert digest(raw) == REPORT_HASH
    verification = json.loads(raw)
    assert verification["verdict"] == "PASS"
    assert verification["independent_context"] is True
    assert verification["reviewed_sha"] == IMPLEMENTATION
    assert text_git("rev-parse", f"{VERIFICATION}^") == PRIOR
    assert text_git("rev-parse", f"{IMPLEMENTATION}^") == "d06754cfd8974164e1ba87aa00695d033877b743"
    assert git("merge-base", "--is-ancestor", BASE, VERIFICATION, ok=(0, 1)).returncode == 1
    assert git("merge-base", "--is-ancestor", BASE, IMPLEMENTATION, ok=(0, 1)).returncode == 1
    code_paths = [p for p in source if p.startswith(PREFIXES[:2])]
    assert set(code_paths) == {p for p in implementation if p.startswith(PREFIXES[:2])}
    for path in code_paths:
        assert source[path] == implementation[path]
        assert blob(VERIFICATION, path) == blob(IMPLEMENTATION, path)
    import_paths = [p for p in source if allowed(p)]
    untracked = git("ls-files", "--others", "--exclude-standard", "-z", "--", *import_paths).stdout
    assert not untracked, "Untracked import collision; preserve user files and block"
    status = git("status", "--short")
    (EVIDENCE / "initial-status.txt").write_bytes(status.stdout + status.stderr)
    manifests = []
    for path in import_paths:
        body = blob(VERIFICATION, path)
        manifests.append({"path": path, "source_commit": VERIFICATION,
                          **source[path], "bytes": len(body), "sha256": digest(body)})
    protected = {p: entry for p, entry in current.items() if not allowed(p)}
    # Frozen whole-tree equality protects every outside-scope entry, not just a sample.
    dump(EVIDENCE / "protection-base.json", {
        "base_sha": BASE, "main_local_refs": main_refs(),
        "protected_entries": protected,
        "existing_batch_paths": {p: e for p, e in current.items() if allowed(p)},
    })
    dump(EVIDENCE / "source-blobs.json", {"method": HASH_METHOD, "files": manifests})
    plan = {p: {"expected": h, "actual": digest(blob(BASE, p))} for p, h in PLAN_HASHES.items()}
    assert all(row["expected"] == row["actual"] for row in plan.values())
    first_report = blob(FIRST_FAIL, REPORT)
    assert json.loads(first_report)["verdict"] == "FAIL"
    prior_report = blob(PRIOR, REPORT)
    archived_prior = "reports/batches/BATCH-08/history/" + PRIOR + "/VERIFICATION_REPORT.json"
    assert blob(VERIFICATION, archived_prior) == prior_report
    dump(EVIDENCE / "preflight.json", {
        "task_id": os.environ.get("CODEX_THREAD_ID"), "at": now(),
        "worktree": str(REPO), "common_git_dir": text_git("rev-parse", "--git-common-dir"),
        "integration_branch": "integration/covenia-b", "base_sha": BASE,
        "tracked_diff_clean": True, "index_clean": True,
        "initial_status_evidence": "reports/batches/BATCH-08/integration-evidence/initial-status.txt",
        "environment_warning": "warning: could not open directory 'backend/cov-runi09oct1pytest-cache/': Permission denied",
        "environment_warning_action": "Recorded only; no deletion or ACL change",
        "commit_verified": IMPLEMENTATION, "verification_report_commit": VERIFICATION,
        "report_blob_hash_method": HASH_METHOD, "report_blob_sha256": digest(raw),
        "code_test_source_commits_byte_equal": True,
        "plan_blobs": plan, "full_plan_contents_read_into_context": False,
        "source_import_count": len(manifests), "protected_entry_count": len(protected),
        "history": {
            "first_fail_source_commit": FIRST_FAIL, "first_fail_sha256": digest(first_report),
            "base_canonical_sha256": digest(blob(BASE, REPORT)) if REPORT in current else None,
            "review_role_source_commit": PRIOR, "review_role_sha256": digest(prior_report),
            "review_role_existing_source_archive": archived_prior,
        },
        "orchestration_accounting": {
            "wake_reason": "manual wake for integration", "manual_wake": True,
            "resume_attempt_in_batch": 4, "auto_resume_attempts": 2, "repair_attempts": 1,
            "is_automatic_resume": False, "is_implementation_failure_repair": False,
            "tasks_created_this_round": 2, "tasks_this_round": ["fresh verification", "integration"],
            "historical_total_thread_count": None, "new_tasks_created_by_integrator": 0,
            "run_state_modified_by_integrator": False,
        },
        "prior_platform_stoppage": {
            "default_exec": "helper_unknown_error: setup refresh had errors",
            "approval_review": "Automatic approval review failed: You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Oct 2nd, 2026 3:29 AM.\nThe action was not executed because automatic approval review could not be completed. This is a review failure, not a determination that the action is unsafe. Do not bypass the approval check; resolve the error or ask the user for guidance.",
            "available_at_reported": "2026-10-02T03:29:00+08:00",
            "manual_wake_authorized_at": "2026-10-02T00:12:00+08:00",
            "first_successful_normal_sandbox_at": "2026-10-02T00:14:37+08:00",
        },
    })
    print(f"PREFLIGHT PASS report={digest(raw)} import={len(manifests)} protected={len(protected)}")


def environment():
    assert len(str(RUN)) <= 60
    assert not RUN.exists(), "Existing runtime must not be reused or cleared"
    for folder in ("tmp", "logs", "cache/pip", "cache/ruff", "cache/pytest", "probe"):
        (RUN / folder).mkdir(parents=True, exist_ok=True)
    run_command("01-create-venv", [BOOTSTRAP, "-m", "venv", RUN / "venv"], "ENVIRONMENT")
    environment_install()


def environment_install():
    # This phase is only a precise installation retry after a sandbox/network approval.
    assert PYTHON.exists()
    run_command("02-lock-install", [PYTHON, "-m", "pip", "install", "--no-deps", "-r",
                                      "backend/requirements-dev.lock"], "ENVIRONMENT")
    run_command("03-editable-install", [PYTHON, "-m", "pip", "install", "--no-deps",
                                          "--no-build-isolation", "-e", "backend"], "ENVIRONMENT")
    environment_code = (
        "import json,os,sys;from pathlib import Path; "
        "p=Path(sys.argv[1]); assert Path(sys.executable).resolve()==p.resolve(); "
        "assert sys.prefix!=sys.base_prefix; assert os.environ.get('PYTHONPATH') is None; "
        "print(json.dumps({'actual_python':sys.executable,'sys_prefix':sys.prefix,"
        "'sys_base_prefix':sys.base_prefix,'version':sys.version,'pythonpath':os.environ.get('PYTHONPATH')}))"
    )
    _, result = run_command("04-environment", [PYTHON, "-c", environment_code, PYTHON], "ENVIRONMENT")
    actual = json.loads(result.stdout)
    config = (RUN / "venv" / "pyvenv.cfg").read_text(encoding="utf-8")
    assert "include-system-site-packages = false" in config
    longest = max((p for p in (RUN / "venv").rglob("*") if p.is_file()), key=lambda p: len(str(p)))
    assert len(str(longest)) < 250
    actual.update({
        "run_dir": str(RUN), "venv": str(RUN / "venv"), "venv_direct_child": True,
        "include_system_site_packages": False, "longest_venv_file": str(longest),
        "longest_venv_path_length": len(str(longest)), "longest_venv_path_lt_250": True,
        "environment": {k: child_env().get(k) for k in (
            "TEMP", "TMP", "PIP_CACHE_DIR", "RUFF_CACHE_DIR", "PYTEST_ADDOPTS", "PYTHONPATH"
        )},
    })
    dump(RUN / "environment.json", actual)
    print(json.dumps(actual, ensure_ascii=False), flush=True)


def import_blobs():
    assert text_git("rev-parse", "HEAD") == BASE
    assert not git("diff", "--name-only").stdout
    assert not git("diff", "--cached", "--name-only").stdout
    files = load(EVIDENCE / "source-blobs.json")["files"]
    paths = [entry["path"] for entry in files]
    for offset in range(0, len(paths), 12):
        git("restore", f"--source={VERIFICATION}", "--staged", "--worktree", "--", *paths[offset:offset + 12])
    historical = [
        (PRIOR, REPORT, "reports/batches/BATCH-08/verification-history/round-2-review-role-pass-superseded.json"),
        (FIRST_FAIL, REPORT, "reports/batches/BATCH-08/verification-history/round-1-fail.json"),
    ]
    protection = load(EVIDENCE / "protection-base.json")
    old_canonical = protection["existing_batch_paths"].get(REPORT)
    if old_canonical and blob(BASE, REPORT) != blob(FIRST_FAIL, REPORT):
        historical.append((BASE, REPORT, f"reports/batches/BATCH-08/verification-history/base-{BASE}.json"))
    copies = []
    for source_sha, source_path, destination in historical:
        raw = blob(source_sha, source_path)
        if (REPO / destination).exists():
            assert (REPO / destination).read_bytes() == raw, "Do not overwrite differing historical file"
        # Mechanical raw-byte historical copy, no report body rewriting or normalization.
        (REPO / destination).parent.mkdir(parents=True, exist_ok=True)
        (REPO / destination).write_bytes(raw)
        oid = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=REPO,
                             input=raw, capture_output=True, check=True).stdout.decode().strip()
        git("update-index", "--add", "--cacheinfo", f"100644,{oid},{destination}")
        copies.append({"source_commit": source_sha, "source_path": source_path,
                       "destination": destination, "source_blob_oid": oid, "sha256": digest(raw)})
    copies.append({
        "source_commit": PRIOR, "source_path": REPORT,
        "destination": f"reports/batches/BATCH-08/history/{PRIOR}/VERIFICATION_REPORT.json",
        "source_blob_oid": text_git("rev-parse", f"{PRIOR}:{REPORT}"),
        "sha256": digest(blob(PRIOR, REPORT)),
    })
    dump(EVIDENCE / "history-copies.json", {"method": HASH_METHOD, "copies": copies,
                                             "report_bodies_modified": False})
    assert main_refs() == protection["main_local_refs"]
    print(f"IMPORTED {len(paths)} verified paths; history copies={len(copies)}")


def commit():
    assert text_git("rev-parse", "HEAD") == BASE
    assert load(RUN / "environment.json")["longest_venv_path_lt_250"] is True
    # Runtime logs are generated diagnostics. Final smoke/report stay external so
    # the single integration commit can be tested at its final, immutable SHA.
    dump(EVIDENCE / "environment-install-summary.json", {
        "environment": load(RUN / "environment.json"),
        "commands": load(RUN / "commands.json"),
        "status": "ENVIRONMENT_PREPARED_POST_COMMIT_SMOKE_PENDING",
        "final_evidence_directory": str(RUN), "external_receipt": str(RECEIPT),
        "post_commit_smoke_required": True,
    })
    evidence_files = [p.relative_to(REPO).as_posix() for p in EVIDENCE.rglob("*") if p.is_file()]
    git("add", "--", *evidence_files)
    staged_tree = text_git("write-tree")
    check_equivalence(staged_tree)
    git("diff", "--cached", "--check")
    git("diff", "--check")
    git("commit", "-m", "chore(integration): import independently verified BATCH-08 blobs")
    integration_sha = text_git("rev-parse", "HEAD")
    assert text_git("rev-parse", "HEAD^") == BASE
    final = check_equivalence(integration_sha)
    dump(RUN / "commit-and-protection.json", final)
    print(f"INTEGRATION_COMMIT={integration_sha}", flush=True)


def check_equivalence(sha):
    actual_tree = tree(sha)
    baseline = load(EVIDENCE / "protection-base.json")
    outside = {p: e for p, e in actual_tree.items() if not allowed(p)}
    assert outside == baseline["protected_entries"], "Outside-scope tree entry changed"
    assert main_refs() == baseline["main_local_refs"], "Local main refs changed"
    source = load(EVIDENCE / "source-blobs.json")["files"]
    equivalence = []
    for item in source:
        path = item["path"]
        raw = blob(sha, path)
        assert actual_tree[path] == {k: item[k] for k in ("mode", "type", "oid")}
        assert raw == blob(VERIFICATION, path)
        if path.startswith(PREFIXES[:2]):
            assert raw == blob(IMPLEMENTATION, path)
        equivalence.append({"path": path, "source_commit": VERIFICATION,
                            "source_blob_oid": item["oid"], "integrated_blob_oid": actual_tree[path]["oid"],
                            "source_sha256": item["sha256"], "integrated_sha256": digest(raw), "equal": True,
                            "also_equals_implementation_commit": path.startswith(PREFIXES[:2])})
    history = load(EVIDENCE / "history-copies.json")["copies"]
    for item in history:
        assert blob(sha, item["destination"]) == blob(item["source_commit"], item["source_path"])
    source_paths = {i["path"] for i in source}
    retained = []
    for path, metadata in baseline["existing_batch_paths"].items():
        if path not in source_paths:
            assert actual_tree[path] == metadata, f"Existing batch historical path changed: {path}"
            retained.append(path)
    protected_hashes = {}
    for path, metadata in outside.items():
        if metadata["type"] == "blob":
            old = blob(BASE, path)
            new = blob(sha, path)
            assert old == new
            protected_hashes[path] = {"base_sha256": digest(old), "integrated_sha256": digest(new), "equal": True}
    assert digest(blob(sha, REPORT)) == REPORT_HASH
    return {
        "integration_sha": sha, "base_sha": BASE, "hash_method": HASH_METHOD,
        "scope_violations": [], "outside_scope_tree_entries_unchanged": True,
        "protected_entry_count": len(outside), "protected_file_blobs": protected_hashes,
        "source_blob_equivalence": equivalence, "history_copies": history,
        "existing_batch_history_retained": retained,
        "main_local_refs_before": baseline["main_local_refs"], "main_local_refs_after": main_refs(),
        "main_local_refs_unchanged": True, "remote_state_checked": False,
        "report_blob_sha256": REPORT_HASH,
    }


def smoke():
    sha = text_git("rev-parse", "HEAD")
    assert text_git("rev-parse", "HEAD^") == BASE
    assert sha != BASE
    assert text_git("branch", "--show-current") == "integration/covenia-b"
    assert not git("diff", "--name-only").stdout
    assert not git("diff", "--cached", "--name-only").stdout
    assert not git("ls-files", "--others", "--exclude-standard", "-z", "--", *PREFIXES).stdout
    commands = [
        ("05-imports", [PYTHON, "-c", "import pytest,jsonschema;import covenia_b.images;from covenia_b.images import ProviderImageInput;from covenia_b.ports.contracts import ModelProvider;print('images, ProviderImageInput, ModelProvider, pytest/jsonschema import OK')"], "IMPORT_COMPATIBILITY"),
        ("06-images-pytest", [PYTHON, "-m", "pytest", "backend/tests/images", "-q"], "UNIT"),
        ("07-integration-image-smoke", [PYTHON, EVIDENCE / "image_smoke.py", "--repo", REPO, "--run-dir", RUN], "INTEGRATION_SMOKE_REAL_ASSET_AND_PROTOCOL_DOUBLE"),
        ("08-images-ruff", [PYTHON, "-m", "ruff", "check", "backend/src/covenia_b/images", "backend/tests/images"], "STATIC_ANALYSIS"),
        ("09-pip-check", [PYTHON, "-m", "pip", "check"], "ENVIRONMENT"),
        ("10-git-diff-check", ["git", "diff", "--check"], "SCOPE"),
        ("11-git-commit-diff-check", ["git", "diff", "--check", BASE, sha], "SCOPE"),
    ]
    for name, args, mode in commands:
        _, result = run_command(name, args, mode)
        if name == "06-images-pytest":
            assert b"14 passed" in result.stdout and b"skipped" not in result.stdout and b"xfailed" not in result.stdout
    final = check_equivalence(sha)
    dump(RUN / "commit-and-protection.json", final)
    assert text_git("rev-parse", "HEAD") == sha
    status = git("status", "--short")
    (RUN / "logs" / "12-final-status.txt").write_bytes(status.stdout + status.stderr)
    assert not git("diff", "--name-only").stdout
    assert not git("diff", "--cached", "--name-only").stdout
    environment_data = load(RUN / "environment.json")
    # Include every runtime path too; the ownership boundary remains the short RUN.
    longest_runtime = max((p for p in RUN.rglob("*") if p.is_file()), key=lambda p: len(str(p)))
    assert len(str(longest_runtime)) < 250
    environment_data["environment"] = {k: child_env().get(k) for k in (
        "TEMP", "TMP", "PIP_CACHE_DIR", "RUFF_CACHE_DIR", "PYTEST_ADDOPTS", "PYTHONPATH"
    )}
    environment_data.update({"longest_runtime_file": str(longest_runtime),
                             "longest_runtime_path_length": len(str(longest_runtime))})
    dump(RUN / "environment.json", environment_data)
    smoke_commands = [c for c in load(RUN / "commands.json") if c["name"] in {i[0] for i in commands}]
    report = {
        "report_version": "1.0", "batch_id": "BATCH-08", "status": "SUCCESS",
        "task_id": os.environ.get("CODEX_THREAD_ID"), "completed_at": now(),
        "role": "independent integration", "worktree": str(REPO),
        "integration_branch": "integration/covenia-b", "integration_sha": sha, "base_sha": BASE,
        "commit_verified": IMPLEMENTATION, "verification_report_commit": VERIFICATION,
        "report_blob_hash_method": HASH_METHOD, "report_blob_sha256": REPORT_HASH,
        "smoke_commands": smoke_commands, "smoke_results": {
            "pytest": "14 passed", "images_and_frozen_provider_input_import": "PASS",
            "real_images": "5/5", "jpeg_coding_tables_negative_control": "PASS",
            "filename_invariance": "PASS", "ruff": "PASS", "pip_check": "PASS",
            "git_diff_check": "PASS", "git_committed_diff_check": "PASS",
            "all_executed_on_final_integration_sha": True, "live_model_test": "NOT_RUN_NOT_REQUIRED",
        },
        "scope_violations": [], "venv": str(RUN / "venv"),
        "actual_python": environment_data["actual_python"], "sys_prefix": environment_data["sys_prefix"],
        "pip_check": {"exit_code": 0, "output": str(RUN / "logs" / "09-pip-check.txt")},
        "longest_path": {"venv": environment_data["longest_venv_path_length"],
                         "runtime": environment_data["longest_runtime_path_length"], "lt_250": True},
        "environment": environment_data,
        "source_code_test_blob_equivalence": [e for e in final["source_blob_equivalence"] if e["path"].startswith(PREFIXES[:2])],
        "all_imported_source_blob_count": len(final["source_blob_equivalence"]),
        "all_imported_source_blobs_equal": True,
        "verify3_evidence_count": len([e for e in final["source_blob_equivalence"] if "/verify3/" in e["path"]]),
        "verify3_evidence_blob_equivalence": True,
        "history_copies": final["history_copies"],
        "protected_entries_count": final["protected_entry_count"],
        "outside_scope_tree_entries_unchanged": True, "main_local_refs_unchanged": True,
        "main_local_refs_before": final["main_local_refs_before"], "main_local_refs_after": final["main_local_refs_after"],
        "remote_state_checked": False, "main_pushed": False, "run_state_modified": False,
        "other_batches_started": False,
        "receipt_path": str(RECEIPT), "receipt_written": False,
        "report_path": str(RUN / "INTEGRATION_REPORT.json"),
        "evidence": {"commands": str(RUN / "commands.json"),
                     "smoke": str(RUN / "image-smoke.json"),
                     "blob_and_scope_protection": str(RUN / "commit-and-protection.json"),
                     "committed_provenance": "reports/batches/BATCH-08/integration-evidence/"},
        "orchestration_accounting": load(EVIDENCE / "preflight.json")["orchestration_accounting"],
        "risks": ["Existing ignored i09 pytest-cache directory has Permission denied; unchanged and recorded. Dedicated i08 TEMP/TMP/cache used.",
                  "Protocol-double negative controls and real local JPEG parsing are not LIVE model inference."],
        "blockers": [],
    }
    dump(RUN / "INTEGRATION_REPORT.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


def receipt():
    report = load(RUN / "INTEGRATION_REPORT.json")
    assert report["status"] == "SUCCESS"
    assert text_git("rev-parse", "HEAD") == report["integration_sha"]
    assert main_refs() == report["main_local_refs_before"]
    if RECEIPT.exists():
        existing = load(RECEIPT)
        assert existing.get("integration_sha") == report["integration_sha"], "Do not overwrite another receipt"
    report["receipt_written"] = True
    dump(RECEIPT, report)
    assert load(RECEIPT) == report
    dump(RUN / "INTEGRATION_REPORT.json", report)
    print(f"RECEIPT_WRITTEN={RECEIPT}\nINTEGRATION_SHA={report['integration_sha']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "environment", "environment-install", "import", "commit", "smoke", "receipt"))
    args = parser.parse_args()
    phases = {"preflight": preflight, "environment": environment, "environment-install": environment_install,
              "import": import_blobs, "commit": commit, "smoke": smoke, "receipt": receipt}
    try:
        phases[args.phase]()
    except Exception as exc:
        print(f"BLOCKED phase={args.phase}: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
