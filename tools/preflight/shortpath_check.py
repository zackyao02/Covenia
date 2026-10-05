r"""Short-path preflight with correctly decoded, REAL filesystem measurements.

Cross-line maintenance tool. Basis: CROSS-LINE-PREFLIGHT-QUOTEPATH-20261005.

Why this exists
---------------
The earlier ad-hoc integration preflight measured the raw output of
``git ls-files``.  Git's default ``core.quotepath=true`` octal-escapes
non-ASCII names, so a Chinese-named file is reported as
``"\350\265\233\351\242\230 1..."`` instead of its real name.  That inflated a
~90-character path to 271 and **falsely tripped the 250-character guard twice**
(BATCH-20 and BATCH-23 integration), each time blocking a batch that had no
real short-path problem.

This tool therefore measures only REAL paths:

1. ``disk``     -- every file actually present under ``--repo`` (os.walk, .git skipped)
2. ``tracked``  -- files from ``git -c core.quotepath=false ls-files`` resolved against
                   the real repo root (quoting disabled, never the escaped form)
3. ``venv``     -- the largest real path under ``<run-dir>/venv`` (MASTER_PLAN 5.5-9)

The naive ``git ls-files`` value is also printed, labelled and *not* used for the
verdict, so the defect stays visible.

Usage
-----
    python tools/preflight/shortpath_check.py --repo <REPO_ROOT> [--run-dir <RUN_DIR>] [--limit 250]
    python tools/preflight/shortpath_check.py --selftest

Exit codes: 0 = all real measurements below the limit; 1 = a real measurement
reaches the limit, or the repo cannot be inspected.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_LIMIT = 250


def _longest(paths, label):
    best = ("", 0)
    for p in paths:
        s = str(p)
        if len(s) > best[1]:
            best = (s, len(s))
    return {"label": label, "length": best[1], "path": best[0]}


def disk_longest(repo: Path):
    """Real on-disk files only; .git skipped."""
    files = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            files.append(os.path.join(dirpath, name))
    return _longest(files, "disk (os.walk)")


def git_ls_files(repo: Path, *, quotepath: bool):
    args = ["git", "-C", str(repo)]
    if not quotepath:
        args += ["-c", "core.quotepath=false"]
    args += ["ls-files"]
    out = subprocess.run(args, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip())
    return [line for line in out.stdout.decode("utf-8", "replace").splitlines() if line.strip()]


def tracked_longest(repo: Path):
    """Tracked files, quoting disabled, joined against the REAL repo root."""
    entries = git_ls_files(repo, quotepath=False)
    return _longest([repo / e for e in entries], "tracked (core.quotepath=false)")


def tracked_longest_naive(repo: Path):
    """The defective measurement, kept for contrast only. Never used for the verdict."""
    entries = git_ls_files(repo, quotepath=True)
    return _longest([repo / e for e in entries], "tracked (NAIVE, defective)")


def venv_longest(run_dir: Path):
    venv = run_dir / "venv"
    if not venv.is_dir():
        return {"label": "venv", "length": 0, "path": "(no venv at %s)" % venv}
    return _longest((str(p) for p in venv.rglob("*")), "venv (MASTER_PLAN 5.5-9)")


def _report(row, limit, *, verdict: bool):
    mark = "OK " if row["length"] < limit else "FAIL"
    tag = "" if verdict else "  [informational only]"
    print("  %-4s %-34s %4d  %s%s" % (mark, row["label"], row["length"], row["path"][:110], tag))
    return row["length"] < limit if verdict else True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="REPO_ROOT to inspect")
    ap.add_argument("--run-dir", help="RUN_DIR whose venv is measured (5.5-9)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--selftest", action="store_true", help="demonstrate the quotepath artefact")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.repo:
        ap.error("--repo is required (or use --selftest)")

    repo = Path(a.repo).resolve()
    if not repo.is_dir():
        print("FAIL: repo not found: %s" % repo)
        return 1

    print("shortpath preflight")
    print("  repo  : %s  (root length %d)" % (repo, len(str(repo))))
    print("  limit : >= %d characters is a failure" % a.limit)

    results = [disk_longest(repo), tracked_longest(repo)]
    if a.run_dir:
        results.append(venv_longest(Path(a.run_dir).resolve()))

    print("\nreal measurements (verdict-bearing):")
    ok = all([_report(r, a.limit, verdict=True) for r in results])

    naive = tracked_longest_naive(repo)
    print("\nfor contrast (NOT used for the verdict):")
    _report(naive, a.limit, verdict=False)
    if naive["length"] >= a.limit > max(r["length"] for r in results):
        print("  NOTE: the naive measurement would have failed this preflight while every")
        print("        real measurement passes -- this is exactly the quotepath defect.")

    print("\nverdict: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def selftest() -> int:
    print("selftest: git quoting inflates non-ASCII names")
    for quotepath in (True, False):
        try:
            out = subprocess.run(
                ["git", "-c", "core.quotepath=%s" % ("true" if quotepath else "false"),
                 "config", "--get", "core.quotepath"],
                capture_output=True,
            )
        except OSError as exc:  # pragma: no cover
            print("  FAIL: git unavailable: %s" % exc)
            return 1
        print("  core.quotepath=%-5s -> %s" % (quotepath, out.stdout.decode().strip() or "(unset)"))
    print("  A file named '<CJK>.docx' is reported by git as a ~4x-longer octal escape")
    print("  when core.quotepath is true; this tool always disables quoting for real paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
