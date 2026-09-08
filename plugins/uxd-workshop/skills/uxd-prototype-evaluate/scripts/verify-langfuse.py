#!/usr/bin/env python3
"""Verify Langfuse endpoint/auth and emit one metadata-only smoke trace."""

from __future__ import annotations

import json
import os
import sys
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import langfuse_trace  # noqa: E402


def check_health(host: str) -> None:
    url = host.rstrip("/") + "/api/public/health"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"health endpoint returned HTTP {response.status}")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"health endpoint returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"cannot reach Langfuse host: {error.reason}") from error


def check_auth(host: str, public_key: str, secret_key: str) -> None:
    """Validate project keys against Langfuse's read-only public API."""
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    now = datetime.now(timezone.utc)
    query = urlencode({
        "fromStartTime": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "toStartTime": now.isoformat().replace("+00:00", "Z"),
        "limit": 1,
    })
    url = host.rstrip("/") + "/api/public/v2/observations?" + query
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"authenticated API returned HTTP {response.status}")
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise RuntimeError("Langfuse project keys were rejected") from error
        raise RuntimeError(f"authenticated API returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"cannot reach authenticated Langfuse API: {error.reason}") from error


def main() -> int:
    required = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return 2

    host = os.environ["LANGFUSE_HOST"]
    print(f"Checking Langfuse health: {host}")
    try:
        check_health(host)
        print("Health: PASS")
    except RuntimeError as error:
        print(f"Health: FAIL — {error}", file=sys.stderr)
        return 1

    try:
        check_auth(host, os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
        print("Credentials: PASS")
    except RuntimeError as error:
        print(f"Credentials: FAIL — {error}", file=sys.stderr)
        return 1

    if not langfuse_trace.is_enabled():
        print("Langfuse SDK/auth configuration is disabled", file=sys.stderr)
        return 1

    model = os.environ.get("LANGFUSE_VERIFY_MODEL", "gpt-5.6-terra")
    payload = {
        "prototype_key": "LANGFUSE-VERIFY",
        "eval_run_id": langfuse_trace.make_eval_run_id("LANGFUSE-VERIFY", seed="verify"),
        "experiment": "langfuse-openai-verify",
        "invocation": os.environ.get("AI_HELPERS_PLATFORM", "api"),
        "provider": "openai",
        "model": model,
        "billing_source": "provider_estimate",
        "run_result": {
            "cost_usd": 0.0,
            "token_usage": {"input_tokens": 1, "output_tokens": 1},
        },
        "phases": [{
            "phase": "langfuse-verify",
            "provider": "openai",
            "model": model,
            "input_tokens": 1,
            "output_tokens": 1,
            "llm_cost_usd": 0.0,
        }],
        "quality": {"langfuse_configured": 1},
    }
    result = langfuse_trace.log_pipeline_run(payload)
    print(json.dumps(result, indent=2))
    if not result.get("logged"):
        print("Smoke trace: FAIL — SDK could not confirm export", file=sys.stderr)
        return 1
    print("Smoke trace: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
