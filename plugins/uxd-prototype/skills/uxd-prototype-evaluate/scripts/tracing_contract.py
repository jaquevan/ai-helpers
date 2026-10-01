"""Shared accounting for observations, receipts and ledgers; never invoice data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def phase_record(phase):
    record = dict(phase)
    local = phase.get("model_invoked") is False or phase.get("provider") == "local"
    known = phase.get("known_usage_cost_usd", phase.get("llm_cost_usd"))
    usage_known = bool(phase.get("usage_known", not phase.get("usage_unknown", False)))
    record.update({
        "status": phase.get("status", "unknown"),
        "known_usage_cost_usd": known, "estimated_cost_usd": known,
        "llm_cost_usd": phase.get("llm_cost_usd") if usage_known else None,
        "usage_known": usage_known, "usage_unknown": not usage_known,
        "cost_complete": usage_known and known is not None,
        "billing_source": "local_no_model_cost" if local else "provider_usage_price_card_estimate",
        "output_tokens": phase.get("output_tokens"),
    })
    return record


def validate_session_mode(args, provider):
    if os.environ.get("OPENCODE_DEDICATED_TRACE") != "1":
        return
    if provider != "openai":
        raise ValueError("Dedicated evaluator sessions support the bounded OpenAI pipeline only.")
    approved = os.environ.get("UXD_TRACE_ESTIMATE_APPROVED") == "true"
    if approved:
        if not args.approve_estimate or args.estimate_only:
            raise ValueError("Approved invocation must consume the previous estimate, not replace it.")
    elif not args.estimate_only or args.approve_estimate:
        raise ValueError("This session is estimate-only. Separate launcher paid approval is required.")


def write_session_result(result):
    """Publish structured accounting to the session plugin, never parse stdout."""
    target = os.environ.get("UXD_TRACE_PIPELINE_RESULT")
    if not target or os.environ.get("OPENCODE_DEDICATED_TRACE") != "1":
        return
    record = {
        "run_id": os.environ["UXD_TRACE_RUN_ID"],
        "trace_id": os.environ["LANGFUSE_TRACE_ID"],
        "status": result.get("status", "unknown"),
        "cost_ledger_status": result.get("cost_ledger_status", "not_applicable"),
        "cost_usd": result.get("cost_usd"),
        "known_usage_cost_usd": result.get("known_usage_cost_usd"),
        "usage_known": result.get("usage_known", False),
        "billing_source": result.get("billing_source", "unavailable"),
        "phases": [phase_record(p) for p in result.get("phases", [])],
        "artifacts_dir": result.get("artifacts_dir"),
    }
    output = Path(target)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(output)


def estimate_identity(args):
    excluded = {"estimate_only", "approve_estimate", "env_file"}
    arguments = {k: v for k, v in vars(args).items() if k not in excluded}
    context_hash = hashlib.sha256(Path(args.jira_context).read_bytes()).hexdigest()
    return {"arguments": arguments, "context_sha256": context_hash,
            "session_input_fingerprint": os.environ.get("UXD_TRACE_INPUT_FINGERPRINT")}


def save_estimate(args, preflight):
    if os.environ.get("OPENCODE_DEDICATED_TRACE") != "1":
        return
    target = Path(args.benchmark_dir) / "reviewed-estimate.json"
    target.write_text(json.dumps({"identity": estimate_identity(args),
                                  "estimate": preflight.get("estimate"),
                                  "estimate_run_id": os.environ["UXD_TRACE_RUN_ID"]}, indent=2) + "\n")
    target.chmod(0o600)
    target.with_suffix(".consumed").unlink(missing_ok=True)


def require_estimate(args, preflight):
    if os.environ.get("OPENCODE_DEDICATED_TRACE") != "1":
        return
    if os.environ.get("UXD_TRACE_ESTIMATE_APPROVED") != "true":
        raise ValueError("Separate launcher paid approval is required.")
    target = Path(args.benchmark_dir) / "reviewed-estimate.json"
    try:
        saved = json.loads(target.read_text())
    except (OSError, ValueError) as error:
        raise ValueError("No valid saved estimate. Run estimate-only and review it first.") from error
    if saved.get("identity") != estimate_identity(args) or saved.get("estimate") != preflight.get("estimate"):
        raise ValueError("Estimate inputs, staged context or pricing changed. Run estimate-only again.")
    try:
        with target.with_suffix(".consumed").open("x") as marker:
            marker.write(os.environ["UXD_TRACE_RUN_ID"] + "\n")
    except FileExistsError as error:
        raise ValueError("This estimate was already used. Do not retry paid work.") from error
