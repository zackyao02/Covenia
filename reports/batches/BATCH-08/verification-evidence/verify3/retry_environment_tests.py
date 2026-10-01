from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _run(
    command_id: str,
    argv: list[str],
    *,
    repo: Path,
    evidence_dir: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=repo,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    output_path = evidence_dir / f"{command_id}.txt"
    output_path.write_text(
        f"command={subprocess.list2cmdline(argv)}\n"
        f"cwd={repo}\n"
        f"TEMP={env['TEMP']}\n"
        f"TMP={env['TMP']}\n"
        f"exit_code={completed.returncode}\n"
        f"stdout:\n{completed.stdout}"
        f"stderr:\n{completed.stderr}",
        encoding="utf-8",
    )
    return {
        "id": command_id,
        "command": subprocess.list2cmdline(argv),
        "cwd": str(repo),
        "environment_override": {"TEMP": env["TEMP"], "TMP": env["TMP"]},
        "exit_code": completed.returncode,
        "output": output_path.relative_to(repo).as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()

    repo = args.repo.resolve()
    run_dir = args.run_dir.resolve()
    venv_python = run_dir / "venv" / "Scripts" / "python.exe"
    evidence_dir = Path(__file__).resolve().parent
    temp_dir = run_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)

    commands = [
        (
            "15-images-pytest-temp-override",
            [str(venv_python), "-m", "pytest", "backend/tests/images", "-q"],
        ),
        (
            "16-focused-dqt-dht-temp-override",
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
            "17-independent-probe-retry",
            [
                str(venv_python),
                str(evidence_dir / "independent_probe.py"),
                "--repo",
                str(repo),
                "--run-dir",
                str(run_dir),
                "--output",
                str(evidence_dir / "independent-probe-retry.json"),
            ],
        ),
    ]
    records = [
        _run(
            command_id,
            argv,
            repo=repo,
            evidence_dir=evidence_dir,
            env=env,
        )
        for command_id, argv in commands
    ]
    (evidence_dir / "retry-commands.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    passed = all(record["exit_code"] == 0 for record in records)
    print(json.dumps({"passed": passed, "commands": records}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
