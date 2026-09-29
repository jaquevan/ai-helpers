#!/usr/bin/env python3
"""Durable, idempotent per-response usage journal for direct API runners."""

from __future__ import annotations

import json
import os
from pathlib import Path
import uuid
from typing import Any

from model_pricing import PRICING, estimated_cost


USAGE_FIELDS = (
    "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
    "cache_write_tokens", "reasoning_tokens",
)


def normalize_usage(response: dict[str, Any]) -> tuple[dict[str, int] | None, bool]:
    raw = response.get("usage")
    if not isinstance(raw, dict) or not all(
        isinstance(raw.get(name), int) and raw.get(name) >= 0
        for name in ("input_tokens", "output_tokens")
    ):
        return None, False
    input_tokens = raw["input_tokens"]
    output_tokens = raw["output_tokens"]
    details_in = raw.get("input_tokens_details") or {}
    details_out = raw.get("output_tokens_details") or {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(raw.get("total_tokens", input_tokens + output_tokens) or 0),
        "cached_input_tokens": int(details_in.get("cached_tokens", 0) or 0),
        "cache_write_tokens": int(details_in.get("cache_write_tokens", 0) or 0),
        "reasoning_tokens": int(details_out.get("reasoning_tokens", 0) or 0),
    }, True


class UsageJournal:
    """Append-only JSONL journal; a response is durable before the next action."""

    def __init__(
        self,
        path: str | Path,
        *,
        run_id: str | None = None,
        attempt_id: str | None = None,
        phase: str | None = None,
        model: str | None = None,
    ):
        self.path = Path(path)
        self.context = {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "phase": phase,
            "model": model,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen_responses: set[str] = set()
        self.events: list[dict[str, Any]] = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    self.events.append(event)
                    response_id = event.get("response_id")
                    if event.get("event") == "response_usage" and response_id:
                        self.seen_responses.add(str(response_id))

    def _append(self, event: dict[str, Any]) -> None:
        payload = {**self.context, **event}
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        self.events.append(payload)

    def begin(self, request_id: str | None = None) -> str:
        request_id = request_id or uuid.uuid4().hex
        self._append({"event": "request_started", "request_id": request_id})
        return request_id

    def response(self, request_id: str, response: dict[str, Any]) -> dict[str, Any]:
        response_id = response.get("id")
        identity = str(response_id) if response_id else request_id
        if identity in self.seen_responses:
            return next(
                event for event in self.events
                if event.get("event") == "response_usage"
                and (event.get("response_id") or event.get("request_id")) == identity
            )
        usage, usage_known = normalize_usage(response)
        model = self.context.get("model")
        cost = None
        if usage_known and model in PRICING:
            cost = estimated_cost(
                model,
                usage["input_tokens"],
                usage["output_tokens"],
                usage["cached_input_tokens"],
                usage["cache_write_tokens"],
            )
        event = {
            "event": "response_usage",
            "request_id": request_id,
            "response_id": response_id,
            "response_status": response.get("status"),
            "usage_known": usage_known,
            "usage": usage,
            "estimated_cost_usd": cost,
            "billing_source": "pinned-price-card-estimate" if cost is not None else None,
        }
        self._append(event)
        self.seen_responses.add(identity)
        return event

    def failed(self, request_id: str, *, category: str, usage_unknown: bool) -> None:
        self._append({
            "event": "request_failed",
            "request_id": request_id,
            "error_category": category,
            "usage_unknown": bool(usage_unknown),
        })

    def summary(self) -> dict[str, Any]:
        totals = {name: 0 for name in USAGE_FIELDS}
        seen: set[str] = set()
        unknown_requests: set[str] = set()
        started: set[str] = set()
        closed: set[str] = set()
        known_usage_cost_usd = 0.0
        cost_known = True
        for event in self.events:
            request_id = str(event.get("request_id") or "")
            if event.get("event") == "request_started":
                started.add(request_id)
            elif event.get("event") == "request_failed":
                closed.add(request_id)
                if event.get("usage_unknown"):
                    unknown_requests.add(request_id)
            elif event.get("event") == "response_usage":
                closed.add(request_id)
                identity = str(event.get("response_id") or request_id)
                if identity in seen:
                    continue
                seen.add(identity)
                if not event.get("usage_known") or not isinstance(event.get("usage"), dict):
                    unknown_requests.add(request_id)
                    continue
                response_usage = event["usage"]
                for name in USAGE_FIELDS:
                    totals[name] += int(response_usage.get(name, 0) or 0)
                response_cost = event.get("estimated_cost_usd")
                model = event.get("model") or self.context.get("model")
                if response_cost is None and model in PRICING:
                    response_cost = estimated_cost(
                        model,
                        int(response_usage.get("input_tokens", 0) or 0),
                        int(response_usage.get("output_tokens", 0) or 0),
                        int(response_usage.get("cached_input_tokens", 0) or 0),
                        int(response_usage.get("cache_write_tokens", 0) or 0),
                    )
                if response_cost is None:
                    cost_known = False
                else:
                    known_usage_cost_usd += float(response_cost)
        pending = started - closed
        unknown_requests.update(pending)
        totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
        return {
            "token_usage": totals,
            "usage_known": not unknown_requests,
            "usage_unknown": bool(unknown_requests),
            "unknown_request_ids": sorted(item for item in unknown_requests if item),
            "responses_recorded": len(seen),
            "known_usage_cost_usd": round(known_usage_cost_usd, 8),
            "cost_known": cost_known,
            "cost_usd": round(known_usage_cost_usd, 8) if not unknown_requests and cost_known else None,
            "journal_path": str(self.path),
        }


def append_trace_event(path: str | Path | None, event: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=False) as stream:
            stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
