#!/usr/bin/env python3
"""Deterministic tests for MCP-first local benchmark preflight."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "langfuse-trace-pipeline.py"
SPEC = importlib.util.spec_from_file_location("langfuse_trace_pipeline", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_langfuse", SCRIPT_DIR / "verify-langfuse.py"
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
verify = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verify)

def write_warm_cache(root: Path, compound_key: str) -> None:
    entry = root / compound_key.split(":", 1)[1]
    entry.mkdir(parents=True)
    records = []
    for filename in verify.CANONICAL_FILES:
        content = json.dumps({"artifact": filename}).encode()
        (entry / filename).write_bytes(content)
        records.append({
            "name": filename,
            "bytes": len(content),
            "sha256": "sha256:" + verify.hashlib.sha256(content).hexdigest(),
        })
    (entry / "manifest.json").write_text(json.dumps({
        "compound_key": compound_key, "files": records,
    }))


def main() -> int:
    repo_tmp = pipeline.PROJECT_ROOT / "tmp"
    repo_tmp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repo_tmp) as temp_dir:
        benchmark = Path(temp_dir).resolve()
        workspace = benchmark / "workspace"
        workspace.mkdir()
        context = benchmark / "jira-context.json"
        context.write_text(json.dumps({
            "schema_version": 1,
            "source": "atlassian-mcp",
            "ticket": {
                "key": "RHOAIUX-3239",
                "summary": "Tool calling visibility",
                "description": "Acceptance Criteria\n- Show tool calls",
            },
        }))

        resolved = pipeline.resolve_local_inputs(
            key="RHOAIUX-3239",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
        )
        assert resolved["workspace"] == str(workspace)
        assert resolved["jira_context_file"] == str(context)

        browser_context = benchmark / "jira-browser-context.json"
        browser_context.write_text(json.dumps({
            "source": "jira-authenticated-browser",
            "source_url": "https://redhat.atlassian.net/browse/RHOAIUX-3239",
            "staged_by": "authenticated read-only browser extraction",
            "ticket": {
                "key": "RHOAIUX-3239",
                "summary": "Tool calling visibility",
                "description": "Acceptance Criteria\n- Show tool calls",
            },
        }))
        browser_resolved = pipeline.resolve_local_inputs(
            key="RHOAIUX-3239",
            workspace=str(workspace),
            jira_context_file=str(browser_context),
            benchmark_dir=str(benchmark),
        )
        assert browser_resolved["jira_context_file"] == str(browser_context)

        prompt = pipeline.build_prompt(
            "RHOAIUX-3239",
            "http://localhost:9000",
            str(workspace),
            "--no-fix",
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
            consistency_report=str(
                workspace
                / ".artifacts"
                / "RHOAIUX-3239"
                / "eval"
                / "consistency-report.json"
            ),
        )
        assert str(pipeline.SKILL_DIR) in prompt
        assert str(context) in prompt
        assert "Validated source consistency report" in prompt
        assert ".claude" in prompt and "Do not discover" in prompt
        assert "credential" in prompt

        invalid_context = benchmark / "invalid.json"
        invalid_context.write_text(json.dumps({
            "source": "manual",
            "ticket": {
                "key": "RHOAIUX-3239",
                "summary": "Invalid",
                "description": "Invalid",
            },
        }))
        try:
            pipeline.resolve_local_inputs(
                key="RHOAIUX-3239",
                workspace=str(workspace),
                jira_context_file=str(invalid_context),
                benchmark_dir=str(benchmark),
            )
        except ValueError as error:
            assert "atlassian-mcp" in str(error)
        else:
            raise AssertionError("non-MCP Jira context should fail")

        identity = {
            "intent_key": "sha256:" + "1" * 64,
            "build_key": "sha256:" + "2" * 64,
            "evaluator_key": "sha256:" + "3" * 64,
        }
        compound_key = verify._compound_key(identity)
        canonical_states = []
        condition_workspaces = []
        for condition in ("legacy", "optimized-cold", "optimized-warm"):
            condition_workspace = benchmark / "conditions" / condition
            state = condition_workspace / ".artifacts" / "RHOAIUX-3239" / "eval" / "state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"identity": {**identity, "compound_key": compound_key}}))
            canonical_states.append(f"{condition}={state}")
            condition_workspaces.append(f"{condition}={condition_workspace}")
        args = SimpleNamespace(
            env_file=None,
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context=str(context),
            source_revision="a" * 40,
            personas="data-scientist+junior,data-scientist+senior",
            canonical_state=canonical_states,
            condition_workspace=condition_workspaces,
        )
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "LANGFUSE_HOST": "http://langfuse.test",
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        }, clear=True), patch.object(verify, "workspace_revision", return_value="a" * 40), patch.object(verify, "check_openai_auth"), patch.object(verify, "check_health"), patch.object(verify, "check_auth"), patch.object(verify, "check_prototype_url"), patch.object(verify.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            try:
                verify.run_preflight(args)
            except RuntimeError as error:
                assert "benchmark OpenAI upper-bound estimate $33.840240 exceeds the $25.00 program cap" in str(error)
            else:
                raise AssertionError("over-cap benchmark plan must stop before remote checks")
            safe_cost = verify.expected_openai_cost()
            safe_cost["program_openai_cost_usd"] = 24.0
            with patch.object(verify, "expected_openai_cost", return_value=safe_cost):
                preflight = verify.run_preflight(args)
        cost_estimate = verify.expected_openai_cost()
        assert cost_estimate["program_openai_cost_usd"] == 33.84024
        assert cost_estimate["openai_cap_usd"] == 25
        assert preflight["model_invoked"] is False
        assert preflight["canonical_compound_key"] == compound_key
        assert set(preflight["condition_workspaces"]) == {"legacy", "optimized-cold", "optimized-warm"}
        journey_estimate = next(
            item for item in preflight["expected_cost"]["phases"]
            if item["phase"] == "eval-journey"
        )
        assert journey_estimate == {
            "phase": "eval-journey", "model": "gpt-6-sol",
            "input_tokens_bound": 10_028, "output_tokens_bound": 1_614,
            "openai_cost_usd": 0.036196,
        }
        personal_args = SimpleNamespace(
            env_file=None,
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context=str(context),
            personas="data-scientist+junior,data-scientist+senior",
        )
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "LANGFUSE_HOST": "http://langfuse.test",
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        }, clear=True), patch.object(pipeline.verify_langfuse, "check_openai_auth"), patch.object(
            pipeline.verify_langfuse, "check_health"
        ), patch.object(pipeline.verify_langfuse, "check_auth"), patch.object(
            pipeline.verify_langfuse, "check_prototype_url"
        ), patch.object(
            pipeline.importlib.util, "find_spec", return_value=object()
        ):
            personal = pipeline.run_personal_preflight(personal_args)
        assert personal["mode"] == "personal"
        assert personal["model_invoked"] is False
        assert personal["estimate"]["single_run_openai_cost_usd"] == round(sum(
            item["openai_cost_usd"] for item in personal["estimate"]["phases"]
        ), 6)
        assert {item["model"] for item in personal["estimate"]["phases"]} == {"gpt-6-sol"}

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
