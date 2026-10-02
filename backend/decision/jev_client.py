from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name: str, default: str | None = None) -> str | None:
    if os.getenv(name):
        return os.getenv(name)
    return _env_file_values().get(name, default)


def typesafe_configured() -> bool:
    return bool(setting("TYPESAFE_API_KEY"))


def ask_jev(state: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Call TypeSafe/JEV and return a provider-neutral transport envelope.

    No exception escapes this function. The decision engine decides how to
    degrade when the provider is unavailable.
    """

    api_key = setting("TYPESAFE_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "source": "RULE_FALLBACK",
            "attempted": False,
            "error": {"code": "TYPESAFE_API_KEY_NOT_SET", "message": "TYPESAFE_API_KEY is not configured."},
            "latency_ms": 0,
            "raw": None,
        }

    url = setting("TYPESAFE_API_URL", DEFAULT_TYPESAFE_URL) or DEFAULT_TYPESAFE_URL
    model_version = setting("TYPESAFE_MODEL_VERSION", "jev-latest") or "jev-latest"
    try:
        timeout = float(setting("TYPESAFE_TIMEOUT_SECONDS", "10") or "10")
    except ValueError:
        timeout = 10.0

    questions_payload = {
        str(question["id"]): {key: value for key, value in question.items() if key != "id"}
        for question in questions
        if isinstance(question, dict) and question.get("id")
    }
    payload = {
        "state": state,
        "questions": questions_payload,
        "model": model_version,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            raw = json.loads(response_body) if response_body else {}
            return {
                "ok": True,
                "source": "JEV",
                "attempted": True,
                "error": None,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "raw": raw,
                "model_version": model_version,
            }
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")[:500]
        return {
            "ok": False,
            "source": "RULE_FALLBACK",
            "attempted": True,
            "error": {"code": f"TYPESAFE_HTTP_{exc.code}", "message": message or exc.reason},
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "raw": None,
            "model_version": model_version,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {
            "ok": False,
            "source": "RULE_FALLBACK",
            "attempted": True,
            "error": {"code": "TYPESAFE_UNAVAILABLE", "message": str(exc)},
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "raw": None,
            "model_version": model_version,
        }
