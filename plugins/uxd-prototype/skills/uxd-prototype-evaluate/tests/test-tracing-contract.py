#!/usr/bin/env python3
"""Offline regressions: unknown cost, failed spend, bridge and approval identity."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from tracing_contract import phase_record, save_estimate, require_estimate, validate_session_mode
from jira_context import load_jira_context
import langfuse_trace


class Observation:
    def update(self, **kwargs):
        self.update_data = kwargs
    def end(self):
        pass


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        phase = phase_record({"phase": "eval-consistency-visual", "model": "test-model", "attempt_id": "synthetic-attempt-1",
                              "status": "failed", "input_tokens": 100, "output_tokens": 20,
                              "llm_cost_usd": None, "known_usage_cost_usd": 0.0735414,
                              "usage_known": False})
        with patch.object(langfuse_trace, "_get_client", return_value=None):
            trace = langfuse_trace.LivePipelineTrace({"prototype_key": "TEST-1", "privacy_mode": "sanitized_artifact_output"})
        observation = Observation()
        trace.finish_phase(observation, phase=phase, output_text="failed fixture")
        assert observation.update_data["metadata"]["status"] == phase["status"]
        assert observation.update_data["metadata"]["estimated_cost_usd"] == phase["known_usage_cost_usd"]
        assert observation.update_data["metadata"]["output_tokens"] == 20
        assert observation.update_data["metadata"]["attempt_id"] == phase["attempt_id"]
        assert observation.update_data["metadata"]["usage_known"] is False
        assert observation.update_data["level"] == "ERROR"
        artifacts = root / ".artifacts/TEST-1/eval"
        payload = {"eval_run_id": "synthetic-run", "prototype_key": "TEST-1", "phases": [phase],
                   "totals": {"llm_cost_usd": None, "known_usage_cost_usd": 0.0735414, "usage_known": False}}
        result = subprocess.run(["node", str(SCRIPTS / "log-cost-ledger.js"), "--artifacts-dir", str(artifacts)],
                                cwd=root, env={**os.environ, "UXD_PROJECT_ROOT": str(root)},
                                input=json.dumps(payload), text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        ledger = json.loads((artifacts / "cost-ledger.jsonl").read_text())
        index = json.loads((root / ".artifacts/eval/cost-ledger-index.jsonl").read_text())
        assert ledger["totals"]["llm_cost_usd"] is None
        assert ledger["totals"]["known_usage_cost_usd"] == 0.0735414
        assert ledger["totals"]["usage_known"] is False
        assert index["llm_cost_usd"] is None
        assert ledger["phases"][0]["status"] == observation.update_data["metadata"]["status"]
        with patch.dict(os.environ, {"OPENCODE_DEDICATED_TRACE": "1"}, clear=True):
            try: langfuse_trace.injected_trace_context()
            except ValueError: pass
            else: raise AssertionError("Missing bridge must fail closed")
        env = {"OPENCODE_DEDICATED_TRACE": "1", "LANGFUSE_TRACE_ID": "a" * 32,
               "LANGFUSE_PARENT_SPAN_ID": "b" * 16, "UXD_TRACE_RUN_ID": "synthetic-run",
               "UXD_TRACE_INPUT_FINGERPRINT": "synthetic-input", "UXD_TRACE_RUN_KIND": "manual-smoke"}
        context = root / "jira-context.json"
        context.write_text(json.dumps({"source": "synthetic-smoke", "ticket": {"key": "none", "summary": "Smoke", "description": "Click button", "acceptance_criteria": ["Button changes status"]}}))
        args = argparse.Namespace(jira_context=str(context), benchmark_dir=str(root), key="none", estimate_only=True, approve_estimate=False)
        with patch.dict(os.environ, env, clear=True):
            validate_session_mode(args, "openai")
            args.estimate_only = False
            try: validate_session_mode(args, "openai")
            except ValueError: pass
            else: raise AssertionError("Cannot call paid phases directly in estimate-only session")
            args.estimate_only = True
            try: validate_session_mode(args, "anthropic")
            except ValueError: pass
            else: raise AssertionError("Cannot bypass the approval gate through another provider")
            assert load_jira_context(context, "none")["source"] == "synthetic-smoke"
            assert langfuse_trace.injected_trace_context()["trace_id"] == "a" * 32
            save_estimate(args, {"estimate": {"cost": 1}})
            args.estimate_only = False; args.approve_estimate = True
            os.environ["UXD_TRACE_ESTIMATE_APPROVED"] = "true"
            validate_session_mode(args, "openai")
            require_estimate(args, {"estimate": {"cost": 1}})
            try: require_estimate(args, {"estimate": {"cost": 1}})
            except ValueError: pass
            else: raise AssertionError("Cannot reuse an approval")
            save_estimate(args, {"estimate": {"cost": 1}})
            context.write_text(context.read_text() + "\n")
            try: require_estimate(args, {"estimate": {"cost": 1}})
            except ValueError: pass
            else: raise AssertionError("Changed context must invalidate approval")
        with patch.dict(os.environ, {}, clear=True):
            try: load_jira_context(context, "none")
            except ValueError: pass
            else: raise AssertionError("Synthetic context must be limited to consented smoke runs")
    print("PASS: tracing contract")


if __name__ == "__main__":
    main()
