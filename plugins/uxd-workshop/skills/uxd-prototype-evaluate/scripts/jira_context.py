#!/usr/bin/env python3
"""Validate Jira context staged by the host Atlassian MCP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
    if data.get("source") != "atlassian-mcp":
        raise ValueError("Jira context source must be 'atlassian-mcp'")

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
