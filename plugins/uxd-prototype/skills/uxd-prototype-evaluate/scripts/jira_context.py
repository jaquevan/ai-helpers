#!/usr/bin/env python3
"""Validate Jira context staged by an authenticated Jira reader."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_SOURCES = {"atlassian-mcp", "jira-authenticated-browser"}


def load_jira_context(path: str | Path, expected_key: str) -> dict[str, Any]:
    context_path = Path(path).expanduser().resolve()
    if not context_path.is_file():
        raise ValueError(f"Jira context file does not exist: {context_path}")

    try:
        data = json.loads(context_path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"Jira context is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError("Jira context must be a JSON object")
    source = data.get("source")
    if source not in ALLOWED_SOURCES:
        raise ValueError(
            "Jira context source must be 'atlassian-mcp' or "
            "'jira-authenticated-browser'"
        )
    if source == "jira-authenticated-browser":
        expected_url = f"https://redhat.atlassian.net/browse/{expected_key}"
        if data.get("source_url") != expected_url or not str(data.get("staged_by") or "").strip():
            raise ValueError(
                "Authenticated-browser Jira context requires the exact Red Hat Jira URL "
                "and staged_by provenance"
            )

    ticket = data.get("ticket")
    if not isinstance(ticket, dict):
        raise ValueError("Jira context must include a ticket object")
    if ticket.get("key") != expected_key:
        raise ValueError(
            f"Jira context key {ticket.get('key')!r} does not match {expected_key!r}"
        )
    for field in ("summary", "description"):
        if not isinstance(ticket.get(field), str) or not ticket[field].strip():
            raise ValueError(f"Jira context ticket.{field} must be non-empty text")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    data = load_jira_context(args.file, args.key)
    related = data.get("related_issues") or []
    print(
        json.dumps({
            "status": "valid",
            "key": data["ticket"]["key"],
            "source": data["source"],
            "related_issue_count": len(related),
        })
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
