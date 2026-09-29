#!/usr/bin/env python3
"""Offline bounds, approval, settlement, and trace tests for creator phases."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "creator-phase-runner.py"
SPEC = importlib.util.spec_from_file_location("creator_phase_runner", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
import creator_phase_tools  # noqa: E402


class FakeTrace:
    def __init__(self, payload):
        self.payload = payload
        self.client = object()
        self.summary = {"logged": True, "langfuse_trace_url": "https://langfuse.test/trace/fixture"}
        self.finished_phase = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def start_phase(self, **kwargs):
        self.started_phase = kwargs
        return object()

    def finish_phase(self, _observation, **kwargs):
        self.finished_phase = kwargs

    def finish(self, payload, **_kwargs):
        self.payload = payload
        return self.summary


def test_phase_trace_artifact_paths() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir) / "workspace"
        artifacts = workspace / ".artifacts" / "run-1"
        benchmark = artifacts / "benchmark"
        code = artifacts / "code"
        source = code / "src"
        source.mkdir(parents=True)
        (artifacts).mkdir(parents=True, exist_ok=True)
        (artifacts / "creator-task.md").write_text("approved task")
        (artifacts / "workspace-analysis.json").write_text("{}\n")
        for name, content in (
            ("metadata.json", '{"title":"Demo"}\n'),
            ("prototype-summary.yaml", "prototype_summary: {}\n"),
            ("consistency-report.json", '{"summary":{}}\n'),
        ):
            (artifacts / name).write_text(content)
        (source / "changed.tsx").write_text("export const Changed = true;\n")
        (source / "unchanged.tsx").write_text("export const Unchanged = true;\n")
        subprocess.run(["git", "-C", str(code), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(code), "config", "user.email", "fixture@example.test"], check=True)
        subprocess.run(["git", "-C", str(code), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(code), "add", "src/unchanged.tsx", "src/changed.tsx"], check=True)
        subprocess.run(["git", "-C", str(code), "commit", "-qm", "fixture"], check=True)
        (source / "changed.tsx").write_text("export const Changed = false;\n")
        (source / "new.tsx").write_text("export const NewFile = true;\n")
        generate_args = SimpleNamespace(
            key="DEMO-1", phase="create-generate", workspace=str(workspace),
            artifacts_dir=str(artifacts), benchmark_dir=str(benchmark),
            prompt_file=str(artifacts / "creator-task.md"), mode="workspace",
            model=None, run_id="create-DEMO-1-generate", comparison_id="fixture",
            jira_url=None,
        )
        generate_resolved = runner.resolve_inputs(generate_args)
        captured_paths = runner.phase_trace_artifact_paths(generate_args, generate_resolved)
        assert "code/src/changed.tsx" in captured_paths
        assert "code/src/new.tsx" in captured_paths
        assert "code/src/unchanged.tsx" not in captured_paths
        assert "metadata.json" in captured_paths
        assert "creator-task.md" in captured_paths
        manifest = runner.build_creator_artifact_manifest(generate_args, generate_resolved)
        manifest_paths = {item["path"] for item in manifest["data_flow"]["outputs"]}
        assert ".artifacts/run-1/code/src/changed.tsx" in manifest_paths
        assert ".artifacts/run-1/code/src/new.tsx" in manifest_paths
        assert ".artifacts/run-1/code/src/unchanged.tsx" not in manifest_paths
        manifest_args = SimpleNamespace(
            key="DEMO-1", run_id="create-DEMO-1-generate",
            comparison_id="fixture", benchmark_name="creator-cost-test",
        )
        manifest_without_phase = runner.build_creator_artifact_manifest(
            manifest_args,
            {"workspace": workspace, "artifacts": artifacts, "benchmark": benchmark,
             "run_id": manifest_args.run_id, "prompt_file": artifacts / "creator-task.md"},
        )
        output_paths = {item["path"] for item in manifest_without_phase["data_flow"]["outputs"]}
        assert ".artifacts/run-1/code/src/changed.tsx" in output_paths
        assert ".artifacts/run-1/code/src/new.tsx" in output_paths
        assert ".artifacts/run-1/code/src/unchanged.tsx" not in output_paths

        original_run = subprocess.run

        def fake_analyzer(report):
            def run(command, **kwargs):
                if any(str(part).endswith("uxd-consistency-check/scripts/analyze.py") for part in command):
                    report_path = Path(command[command.index("--json-file") + 1])
                    report_path.write_text(json.dumps(report) + "\n")
                    return subprocess.CompletedProcess(command, 1)
                return original_run(command, **kwargs)
            return run

        baseline_report = {
            "summary": {"total_guidelines_checked": 2, "violations": 1, "warnings": 1, "passes": 0},
            "source_mode": {"violations": [
                {"guideline_id": "project-felt-adoption", "severity": "error", "file": "./src/index.html"},
                {"guideline_id": "status-label-interactivity", "severity": "warning", "file": "src/changed.tsx"},
            ]},
        }
        with patch.object(creator_phase_tools.subprocess, "run", side_effect=fake_analyzer(baseline_report)):
            baseline_validation = creator_phase_tools._run_consistency_check(generate_args, generate_resolved)
        assert baseline_validation["validation"]["status"] == "completed_with_baseline_findings"
        assert baseline_validation["validation"]["baseline_errors"] == [{
            "guideline_id": "project-felt-adoption", "file": "src/index.html", "severity": "error",
        }]
        changed_report = {
            **baseline_report,
            "source_mode": {"violations": [
                *baseline_report["source_mode"]["violations"],
                {"guideline_id": "new-error", "severity": "error", "file": "src/changed.tsx"},
            ]},
        }
        with patch.object(creator_phase_tools.subprocess, "run", side_effect=fake_analyzer(changed_report)):
            try:
                creator_phase_tools._run_consistency_check(generate_args, generate_resolved)
            except RuntimeError as error:
                assert "error(s) in changed source files" in str(error)
            else:
                raise AssertionError("consistency errors in changed files must block validation")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        artifacts = workspace / ".artifacts" / "DEMO-1"
        benchmark = artifacts / "benchmark"
        prompt_file = root / "prompt.md"
        prompt_file.write_text("Create a small inventory prototype from the approved brief.")
        workspace.mkdir()
        prompt_file.rename(workspace / "creator-task.md")

        args = SimpleNamespace(
            key="DEMO-1",
            phase="create-plan",
            workspace=str(workspace),
            artifacts_dir=str(artifacts),
            benchmark_dir=str(benchmark),
            prompt_file=str(workspace / "creator-task.md"),
            mode="standalone",
            model=None,
            run_id="create-DEMO-1-fixture",
            comparison_id="creator-DEMO-1-rev-a",
            benchmark_name="creator-cost-test",
            attempt_id=None,
            env_file=None,
            estimate_only=False,
            approve_estimate=True,
        )
        resolved = runner.resolve_inputs(args)
        estimate = runner.estimate(args, resolved)
        assert estimate["model"] == "gpt-6-sol"
        assert estimate["reserved_estimate_usd"] == 2.3
        assert estimate["max_turns"] is None
        assert estimate["model_invoked"] is False
        assert estimate["remaining_cap_after_estimate_usd"] == 12.7
        updated_ledger_estimate = {
            **estimate,
            "completed_openai_usd": 0.5,
            "remaining_cap_after_estimate_usd": 13.3,
        }
        assert runner.estimate_approval_matches(estimate, updated_ledger_estimate)
        assert runner.attempt_path_for(benchmark, args.run_id, args.phase) != runner.attempt_path_for(
            benchmark, args.run_id, args.phase, "fresh-output-check"
        )

        assert runner.langfuse_trace.redact_content({
            "design": "Keep the approval wording clear.",
            "api_key": "sk-fixture-secret-123456789",
        }) == {
            "design": "Keep the approval wording clear.",
            "api_key": "[REDACTED]",
        }
        assert creator_phase_tools.allowed_output(
            ".artifacts/DEMO-1/user-stories.json", phase="create-plan",
            mode="standalone", key="DEMO-1", workspace=workspace,
        ) == (artifacts / "user-stories.json").resolve()
        run_scoped_artifacts = workspace / ".artifacts" / "creator-runs" / "create-DEMO-1-fixture"
        assert creator_phase_tools.allowed_output(
            ".artifacts/creator-runs/create-DEMO-1-fixture/user-stories.json",
            phase="create-plan", mode="standalone", key="DEMO-1",
            workspace=workspace, artifacts=run_scoped_artifacts,
        ) == (run_scoped_artifacts / "user-stories.json").resolve()

        for denied_path in (
            ".artifacts/DEMO-1/consistency-report.json",
            ".artifacts/DEMO-1/benchmark/extra.json",
            ".artifacts/DEMO-1/prototype/index.html",
        ):
            try:
                creator_phase_tools.allowed_output(
                    denied_path, phase="create-plan", mode="standalone",
                    key="DEMO-1", workspace=workspace,
                )
            except ValueError:
                pass
            else:
                raise AssertionError(f"creator plan must not write {denied_path}")
        assert creator_phase_tools.allowed_output(
            ".artifacts/DEMO-1/prototype/index.html", phase="create-generate",
            mode="standalone", key="DEMO-1", workspace=workspace,
        ) == (artifacts / "prototype" / "index.html").resolve()
        prototype_source = artifacts / "prototype" / "src"
        prototype_source.mkdir(parents=True)
        (prototype_source / "Button.tsx").write_text("export const Button = () => null;\n")
        (prototype_source / "unrelated.tsx").write_text("do not stage unrelated source\n")
        (artifacts / "changeset.md").write_text(
            "Updated `.artifacts/DEMO-1/prototype/src/Button.tsx` for keyboard focus.\n"
        )
        refine_args = SimpleNamespace(
            key="DEMO-1", phase="create-refine", mode="standalone",
        )
        packet = creator_phase_tools.build_context_packet(
            refine_args, resolved, [(artifacts / "changeset.md").resolve()],
        )
        assert [item["path"] for item in packet["staged_source_files"]] == ["prototype/src/Button.tsx"]
        assert "unrelated.tsx" not in json.dumps(packet)

        stale_eval = artifacts / "eval" / "prior-run.json"
        stale_eval.parent.mkdir(parents=True, exist_ok=True)
        stale_eval.write_text('{"prior":true}\n')
        isolated_root = workspace / ".artifacts" / "creator-runs" / "create-DEMO-1-fixture"
        isolated_root.mkdir(parents=True, exist_ok=True)
        isolated_output = isolated_root / "user-stories.json"
        isolated_output.write_text('{"stories":[{"id":"US-1"}]}\n')
        isolated_args = SimpleNamespace(
            key="DEMO-1", run_id=args.run_id, comparison_id="fixture",
            phase="create-plan", mode="standalone",
        )
        isolated_manifest = runner.build_creator_artifact_manifest(
            isolated_args,
            {"workspace": workspace, "artifacts": isolated_root, "benchmark": isolated_root / "benchmark",
             "run_id": args.run_id, "prompt_file": None,
             "phase_spec": runner.load_creator_routing()["phases"]["create-plan"]},
        )
        assert [item["path"] for item in isolated_manifest["data_flow"]["outputs"]] == [
            ".artifacts/creator-runs/create-DEMO-1-fixture/user-stories.json"
        ]

        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "user-stories.json").write_text('{"stories":[{"id":"US-1"}]}\n')
        (artifacts / "journeys.json").write_text(
            '{"journeys":[{"id":"journey-1","steps":[{"id":"step-1","action":"click"}]}]}\n'
        )
        (artifacts / "scenarios.json").write_text('{"routes":[{"path":"/"}]}\n')
        invalid_artifacts = runner.validate_phase_artifacts(args, resolved)
        assert invalid_artifacts["present"] is False
        assert any("requires id, name, and route" in item for item in invalid_artifacts["invalid"])
        assert any("pages array (not routes)" in item for item in invalid_artifacts["invalid"])
        (artifacts / "user-stories.json").write_text('{"stories":[{"id":"US-1","phase":"old"}]}\n')
        (artifacts / "journeys.json").write_text(
            '{"prototype_id":"DEMO-1","journeys":[{"id":"journey-1","steps":[{"id":"home","name":"Playground","route":"/"}]}]}\n'
        )
        (artifacts / "scenarios.json").write_text(
            '{"prototype_id":"DEMO-1","extracted_at":"old","pages":[{"route":"/","scenarios":[{"id":"default","default":true}]}]}\n'
        )
        stale_snapshot = runner.snapshot_phase_outputs(args, resolved)
        stale_artifacts = runner.validate_phase_artifacts(args, resolved, stale_snapshot)
        assert stale_artifacts["present"] is False
        assert len(stale_artifacts["stale"]) == 3

        benchmark.mkdir(parents=True, exist_ok=True)
        (benchmark / "creator-phase-estimates.json").write_text(json.dumps({
            "estimates": {"create-DEMO-1-fixture:create-plan": estimate},
        }))
        fake_trace = FakeTrace({})

        def fake_run_agent(_prompt, **kwargs):
            assert kwargs["model"] == "gpt-6-sol"
            assert kwargs["max_turns"] is None
            assert kwargs["max_output_tokens"] == 5000
            assert kwargs["max_input_tokens"] == 500000
            assert kwargs["max_total_output_tokens"] == 20000
            assert kwargs["max_total_cost_usd"] == 2.3
            assert callable(kwargs["after_turn"])
            assert callable(kwargs["turn_feedback"])
            assert kwargs["prototype_export_dir"] == str(runner.PROTOTYPE_EXPORT_DIR)
            assert str(runner.PROTOTYPE_EXPORT_DIR) in kwargs["additional_allowed_roots"]
            assert [tool["name"] for tool in kwargs["tool_definitions"]] == [
                "creator_write_output", "creator_validate_outputs",
            ]
            assert "run_shell" not in json.dumps(kwargs["tool_definitions"])
            assert "pages[]" in kwargs["turn_feedback"](1)
            journal = runner.UsageJournal(
                kwargs["usage_journal_path"], run_id=kwargs["run_id"],
                attempt_id=kwargs["attempt_id"], phase=kwargs["phase"],
                model=kwargs["model"],
            )
            request_id = journal.begin("mock-request")
            journal.response(request_id, {
                "id": "mock-response", "status": "completed",
                "usage": {
                    "input_tokens": 300, "output_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 20},
                },
            })
            (artifacts / "user-stories.json").write_text('{"prototype_id":"DEMO-1","stories":[{"id":"US-2","phase":"current"}]}\n')
            (artifacts / "journeys.json").write_text(
                '{"prototype_id":"DEMO-1","extracted_at":"current","journeys":[{"id":"journey-1","title":"Open the prototype","source":"jira","steps":[{"id":"home","name":"Playground","route":"/"}]}]}\n'
            )
            (artifacts / "scenarios.json").write_text(
                '{"prototype_id":"DEMO-1","extracted_at":"current","pages":[{"route":"/","scenarios":[{"id":"default","name":"Default","default":true}]}]}\n'
            )
            assert kwargs["after_turn"](3) == (
                "Required outputs are present and valid after tool round 3.", True
            )
            assert kwargs["turn_feedback"](3) is None
            return {
                "exit_code": 0,
                "status": "completed",
                "output_text": "Plan artifacts completed",
                "turns_used": 2,
                "duration_s": 1.0,
                "tool_calls": 7,
                "tool_failures": 1,
                "tool_failure_diagnostics": [{
                    "turn": 1,
                    "category": "scope_denied",
                    "reason": "path_outside_allowed_roots",
                }],
                "error_categories": ["tool_nonzero_exit"],
                "recovery_actions": ["continued_after_tool_failure"],
                "token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 100,
                    "cached_input_tokens": 20,
                    "cache_write_tokens": 0,
                },
            }

        with (
            patch.object(runner, "load_paid_preflight"),
            patch.object(runner.langfuse_trace, "LivePipelineTrace", return_value=fake_trace),
            patch.object(runner, "run_agent", side_effect=fake_run_agent),
        ):
            result = runner.run_paid_phase(args, resolved, estimate)

        assert result["status"] == "completed"
        assert result["model_invoked"] is True
        assert result["expected_outputs_present"] is True
        assert result["input_tokens"] == 300
        assert result["cache_read_tokens"] == 20
        assert result["output_tokens"] == 100
        assert result["llm_cost_usd"] > 0
        assert result["langfuse_logged"] is True
        assert result["tool_calls"] == 7
        assert result["tool_failures"] == 1
        assert result["tool_failure_diagnostics"][0]["reason"] == "path_outside_allowed_roots"
        assert result["error_categories"] == ["tool_nonzero_exit"]
        assert result["comparison_id"] == "creator-DEMO-1-rev-a"
        assert fake_trace.finished_phase["phase"]["model"] == "gpt-6-sol"
        ledger = json.loads((benchmark / "openai-budget-ledger-creator.json").read_text())
        assert ledger["cap_usd"] == 15.0
        assert ledger["completed_openai_usd"] == result["llm_cost_usd"]
        phase_rows = [
            json.loads(line)
            for line in (benchmark / "creator-phase-results.jsonl").read_text().splitlines()
        ]
        assert len(phase_rows) == 1
        assert phase_rows[0]["run_id"] == args.run_id
        assert phase_rows[0]["tool_calls"] == 7
        assert phase_rows[0]["tool_failure_diagnostics"][0]["reason"] == "path_outside_allowed_roots"

        manifest = runner.build_creator_artifact_manifest(args, resolved)
        assert manifest["privacy_mode"] == "full_raw"
        assert manifest["trace_content"] == "full"
        assert manifest["source"]["url"] == "https://redhat.atlassian.net/browse/DEMO-1"
        assert manifest["data_flow"]["input_tasks"][0]["sha256"] == resolved["prompt_sha256"]
        manifest_paths = {item["path"] for item in manifest["data_flow"]["outputs"]}
        assert ".artifacts/DEMO-1/user-stories.json" in manifest_paths
        assert all(item["content_recorded"] is True for item in manifest["data_flow"]["outputs"])
        assert manifest["data_flow"]["phase_attempts"][0]["run_id"] == args.run_id
        assert "benchmark" not in " ".join(manifest_paths)

        metadata_artifacts = workspace / ".artifacts" / "METADATA-ONLY"
        (metadata_artifacts / "benchmark").mkdir(parents=True)
        metadata_manifest = runner.build_creator_artifact_manifest(
            SimpleNamespace(
                key="METADATA-ONLY", run_id="create-METADATA-ONLY",
                comparison_id="deterministic-only",
            ),
            {
                "workspace": workspace,
                "artifacts": metadata_artifacts,
                "benchmark": metadata_artifacts / "benchmark",
                "prompt_file": None,
                "run_id": "create-METADATA-ONLY",
            },
        )
        assert metadata_manifest["privacy_mode"] == "metadata_only"
        assert metadata_manifest["trace_content"] == "metadata"

        try:
            runner.run_paid_phase(args, resolved, estimate)
        except RuntimeError as error:
            assert "already has a paid attempt" in str(error)
        else:
            raise AssertionError("a paid creator phase must not be retried with the same run ID")

        # The creator env file must override LANGFUSE_* values already
        # exported in the environment, so creator traces land in the creator
        # project even when the evaluator's keys are in the session env.
        env_file = root / ".env.creator-test"
        env_file.write_text(
            'LANGFUSE_HOST="https://creator-langfuse.test"\n'
            "LANGFUSE_PUBLIC_KEY=\"pk-creator\"\n"
            "LANGFUSE_SECRET_KEY='sk-creator'\n"
        )
        with patch.dict(
            os.environ,
            {
                "LANGFUSE_HOST": "https://evaluator-langfuse.test",
                "LANGFUSE_PUBLIC_KEY": "pk-evaluator",
                "LANGFUSE_SECRET_KEY": "sk-evaluator",
            },
            clear=False,
        ):
            runner.force_creator_langfuse_env(env_file)
            assert os.environ["LANGFUSE_HOST"] == "https://creator-langfuse.test"
            assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-creator"
            assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-creator"

    test_phase_trace_artifact_paths()
    print("PASS")


if __name__ == "__main__":
    main()
