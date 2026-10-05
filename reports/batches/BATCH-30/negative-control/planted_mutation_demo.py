#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BATCH-30 planted negative control for tools/verification/check_no_case_branches.py.

This driver proves the auditor really fails on a planted shortcut.  It:

1. verifies each target file is clean: the worktree bytes are LF-normalized (the
   controlled checkout normalisation MASTER_PLAN 5.5-8 prescribes instead of a raw
   worktree hash, because ``core.autocrlf=true`` checks the blobs out as CRLF) and
   the result is compared with the committed blob from
   ``git show <sha>:<path>``; ``git status --porcelain`` must additionally be
   empty for the path;
2. saves the exact original bytes outside the repository (so a crash cannot lose
   them, and no production source is committed into the report tree);
3. appends inert, never-called planted definitions that (a) branch on DEMO_001,
   (b) branch on a file name, (c) hardcode positive image observations, (d) read an
   untrusted request field, and (e) read a ground-truth artefact;
4. runs the auditor in ``--strict`` mode and records the exit code and full stdout;
5. restores the original bytes in a ``finally`` block and re-verifies that the
   restored sha256 equals both the pre-mutation worktree hash and the committed
   blob hash.

The planted definitions are never imported by a caller, so the module stays
importable and no production behaviour changes while the mutation is present.

Nothing here is committed: the driver is executed once, its output is stored as
evidence, and the targets are byte-identical afterwards.

Usage:
  <RUN_DIR>/venv/Scripts/python.exe \
      reports/batches/BATCH-30/negative-control/planted_mutation_demo.py \
      --repo <repo> --python <RUN_DIR>/venv/Scripts/python.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCANNER = "tools/verification/check_no_case_branches.py"
EVIDENCE_DIR = "reports/batches/BATCH-30/negative-control"
LITERAL_BLACKLIST = re.compile(r"DEMO_00[1-9]|S00001|6920185815517983396|BH919209358357")

PLANT_ENGINE = '''

# --- BATCH-30 planted negative control (temporary, never committed) ----------
# Defensive decoy: this module is imported by the production tests, so the plants
# are inert definitions that nothing calls.

def _planted_demo_shortcut(state, prepared_action):
    if state.case_id == "DEMO_001":
        return "INTERVENE"
    return "ALLOW"


def _planted_filename_branch(entry):
    if entry.file_name.endswith("_gift.png"):
        return "GIFT"
    return "PRIMARY"


def _planted_hardcoded_observation(entry):
    return ImageObservation(
        evidence_id=entry.evidence_id,
        readability="HIGH",
        sku_match="MATCH",
        product_identifiable=True,
        issue_visible=True,
        coverage=["DAMAGE_DETAIL"],
    )
'''

PLANT_ANALYZE = '''

# --- BATCH-30 planted negative control (temporary, never committed) ----------

def _planted_request_state_shortcut(request, state):
    if request.evidence_status == "VALID":
        return "E1"
    return "E0_NO_RULE_MATCHED"


def _planted_fixture_ingress(case_id):
    import json as _planted_json
    from pathlib import Path as _planted_path

    payload = _planted_path("fixtures/ground-truth.json").read_text(encoding="utf-8")
    return _planted_json.loads(payload)[case_id]
'''

#: file -> (planted source, judgements the auditor must report for this file)
PLANTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "backend/src/covenia_b/rules/engine.py",
        PLANT_ENGINE,
        (
            "J1_CASE_LITERAL_IN_DECISION",
            "J2_DESCRIPTOR_DECIDES_VERDICT",
            "J3_OBSERVED_RESULT_HARDCODED",
        ),
    ),
    (
        "backend/src/covenia_b/services/analyze.py",
        PLANT_ANALYZE,
        (
            "J4_GROUND_TRUTH_INGRESS",
            "J7_REQUEST_STATE_REACHES_RULES",
        ),
    ),
)


@dataclass
class Target:
    path: str
    original: bytes
    mutated: bytes
    blob_sha256: str
    governed_sha256_before: str
    worktree_raw_sha256_before: str
    governed_sha256_after_restore: str = ""
    worktree_raw_sha256_after_restore: str = ""
    git_status_after_restore: str = ""
    restored_identical: bool = False
    expected_judgments: tuple[str, ...] = ()
    literal_blacklist_hits: int = 0
    hit_lines: list[int] = field(default_factory=list)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def governed_sha256(payload: bytes) -> str:
    """Hash the LF-normalised content: the committed blob form (MASTER_PLAN 5.5-8).

    ``core.autocrlf=true`` checks the LF blobs out as CRLF, so the raw working-copy
    hash can never equal the blob hash. The governed hash normalises CRLF to LF, which
    is exactly the inverse of the checkout filter, and is compared with
    ``sha256(git show <sha>:<path>)``.
    """

    return sha256_bytes(payload.replace(b"\r\n", b"\n"))


def git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git %s failed (%d): %s"
            % (" ".join(args), completed.returncode, completed.stderr.decode("utf-8", "replace"))
        )
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", default=None, help="evidence JSON path")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    backup_dir = Path(tempfile.mkdtemp(prefix="batch30-planted-backup-"))
    targets: list[Target] = []
    scanner_stdout = ""
    scanner_stderr = ""
    scanner_exit = -1
    scan_report: dict[str, object] | None = None
    error: str | None = None

    try:
        # Precondition: every target is currently identical to its committed blob once
        # the checkout's CRLF normalisation is inverted.
        for relative, plant, expected in PLANTS:
            path = repo / relative
            original = path.read_bytes()
            blob = git(repo, "show", f"{head}:{relative}")
            blob_digest = sha256_bytes(blob)
            governed_digest = governed_sha256(original)
            if blob_digest != governed_digest:
                raise RuntimeError(
                    f"precondition failed: {relative} worktree differs from {head}:{relative}"
                )
            if git(repo, "status", "--porcelain", "--", relative).decode().strip():
                raise RuntimeError(
                    f"precondition failed: {relative} already has uncommitted changes"
                )
            (backup_dir / Path(relative).name).write_bytes(original)
            payload = plant.encode("utf-8")
            if b"\r\n" in original:
                payload = payload.replace(b"\n", b"\r\n")
            targets.append(
                Target(
                    path=relative,
                    original=original,
                    mutated=original + payload,
                    blob_sha256=blob_digest,
                    governed_sha256_before=governed_digest,
                    worktree_raw_sha256_before=sha256_bytes(original),
                    expected_judgments=expected,
                    literal_blacklist_hits=len(LITERAL_BLACKLIST.findall(plant)),
                )
            )

        for target in targets:
            (repo / target.path).write_bytes(target.mutated)

        completed = subprocess.run(
            [args.python, SCANNER, "--strict"],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
        scanner_exit = completed.returncode
        scanner_stdout = completed.stdout.decode("utf-8", "replace")
        scanner_stderr = completed.stderr.decode("utf-8", "replace")

        report_path = repo / EVIDENCE_DIR / "planted-scan.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                args.python,
                SCANNER,
                "--strict",
                "--quiet",
                "--json",
                str(report_path),
            ],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
        scan_report = json.loads(report_path.read_text(encoding="utf-8"))

        hits = scan_report.get("hits", [])
        for target in targets:
            target.hit_lines = [
                int(hit["line"])
                for hit in hits
                if str(hit["path"]).replace("\\", "/").endswith(
                    target.path.split("covenia_b/")[-1]
                )
            ]
    except Exception as failure:  # noqa: BLE001 - reported as evidence, then restored
        error = f"{type(failure).__name__}: {failure}"
    finally:
        for target in targets:
            (repo / target.path).write_bytes(target.original)
        for target in targets:
            restored = (repo / target.path).read_bytes()
            target.governed_sha256_after_restore = governed_sha256(restored)
            target.worktree_raw_sha256_after_restore = sha256_bytes(restored)
            target.git_status_after_restore = (
                git(repo, "status", "--porcelain", "--", target.path).decode().strip()
            )
            target.restored_identical = (
                restored == target.original
                and target.governed_sha256_after_restore == target.blob_sha256
                and target.git_status_after_restore == ""
            )

    status_lines = git(repo, "status", "--short").decode("utf-8", "replace")
    residual = [
        line
        for line in status_lines.splitlines()
        if any(target.path in line.replace("\\", "/") for target in targets)
    ]

    expected_judgments = sorted(
        {judgment for target in targets for judgment in target.expected_judgments}
    )
    observed_judgments = sorted(
        {str(hit["judgment"]) for hit in (scan_report or {}).get("hits", [])}
    )
    all_restored = bool(targets) and all(target.restored_identical for target in targets)
    demonstrated = (
        error is None
        and scanner_exit == 1
        and set(expected_judgments).issubset(set(observed_judgments))
        and all_restored
        and not residual
    )

    evidence = {
        "artifact": f"{EVIDENCE_DIR}/planted-mutation.json",
        "batch_id": "BATCH-30",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Negative control for tools/verification/check_no_case_branches.py: plant an "
            "identity-branching / hardcoded shortcut, prove the auditor exits non-zero and "
            "names the judgements, then restore the production source byte-for-byte."
        ),
        "repo_head_at_demo": head,
        "python_executable": args.python,
        "scanner": SCANNER,
        "scanner_command": [args.python, SCANNER, "--strict"],
        "scanner_exit_code_while_mutated": scanner_exit,
        "scanner_stdout_while_mutated": scanner_stdout,
        "scanner_stderr_while_mutated": scanner_stderr,
        "observed_judgments_while_mutated": observed_judgments,
        "expected_judgments_while_mutated": expected_judgments,
        "targets": [
            {
                "path": target.path,
                "committed_blob_sha256": target.blob_sha256,
                "governed_lf_sha256_before_plant": target.governed_sha256_before,
                "worktree_raw_sha256_before_plant": target.worktree_raw_sha256_before,
                "governed_lf_sha256_after_restore": target.governed_sha256_after_restore,
                "worktree_raw_sha256_after_restore": target.worktree_raw_sha256_after_restore,
                "git_status_after_restore": target.git_status_after_restore,
                "restored_byte_identical": target.restored_identical,
                "expected_judgments": list(target.expected_judgments),
                "reported_hit_lines": target.hit_lines,
                "four_case_literals_in_planted_text": target.literal_blacklist_hits,
            }
            for target in targets
        ],
        "line_ending_governance": {
            "core_autocrlf": git(repo, "config", "--show-origin", "core.autocrlf")
            .decode("utf-8", "replace")
            .strip(),
            "git_ls_files_eol": git(
                repo, "ls-files", "--eol", "--", *[target.path for target in targets]
            )
            .decode("utf-8", "replace")
            .strip()
            .splitlines(),
            "rule": (
                "MASTER_PLAN 5.5-8: file-hash verification uses the blob bytes from "
                "git show <sha>:<path>; the worktree is CRLF because core.autocrlf=true, so "
                "the worktree comparison is made on the LF-normalised content, which is the "
                "inverse of the checkout filter and therefore equals the blob hash."
            ),
        },
        "literal_only_comparison": {
            "note": (
                "A literal-only scanner would have found only the DEMO_001 plant. Every other "
                "planted shortcut contains none of the four forbidden identifiers."
            ),
            "plants_matched_by_a_four_literal_blacklist": sum(
                target.literal_blacklist_hits for target in targets
            ),
            "plants_missed_by_a_four_literal_blacklist": sum(
                1 for target in targets for _ in target.expected_judgments
            )
            - sum(target.literal_blacklist_hits for target in targets),
        },
        "restore_verification": {
            "all_targets_restored_byte_identical": all_restored,
            "git_status_lines_for_targets_after_restore": residual,
            "git_status_clean_for_targets": not residual,
            "crash_recovery_backup_dir_outside_repo": str(backup_dir),
            "note": (
                "Restoration is performed in a finally block from bytes held in memory and "
                "mirrored to a directory outside the repository. The report never commits "
                "production source text. '' means git reports no change for the path."
            ),
        },
        "error": error,
        "negative_control_demonstrated": demonstrated,
        "conclusion": (
            "check_no_case_branches.py exits 1 and names identity-branch, hardcoded-observation, "
            "request-state and ground-truth shortcuts that a four-literal blacklist misses; the "
            "production source is byte-identical afterwards."
            if demonstrated
            else "the planted negative control did not reproduce as expected; treat as a tool defect."
        ),
    }

    destination = Path(args.out) if args.out else repo / EVIDENCE_DIR / "planted-mutation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"planted negative control: {'DEMONSTRATED' if demonstrated else 'NOT DEMONSTRATED'}")
    print(f"  scanner exit code while mutated: {scanner_exit}")
    print(f"  expected judgements: {expected_judgments}")
    print(f"  observed judgements: {observed_judgments}")
    for target in targets:
        print(
            f"  {target.path}: restored_identical={target.restored_identical} "
            f"blob={target.blob_sha256[:16]} after={target.governed_sha256_after_restore[:16]} "
            f"git_status={target.git_status_after_restore!r}"
        )
    print(f"  git status residual for targets: {residual or 'none'}")
    print(f"  evidence: {destination}")
    if error:
        print(f"  error: {error}", file=sys.stderr)
    return 0 if demonstrated else 1


if __name__ == "__main__":
    raise SystemExit(main())
