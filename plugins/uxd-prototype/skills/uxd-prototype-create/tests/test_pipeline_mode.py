#!/usr/bin/env python3
"""Zero-spend contract tests for creator deterministic serving."""

from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_mode.py"
SPEC = importlib.util.spec_from_file_location("creator_pipeline_mode", SCRIPT)
assert SPEC and SPEC.loader
pipeline_mode = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline_mode)

EVALUATOR_TRACE = (
    Path(__file__).resolve().parents[4] / "uxd-prototype" / "skills"
    / "uxd-prototype-evaluate" / "scripts" / "langfuse_trace.py"
)
TRACE_SPEC = importlib.util.spec_from_file_location("evaluator_cost_authority", EVALUATOR_TRACE)
assert TRACE_SPEC and TRACE_SPEC.loader
evaluator_trace = importlib.util.module_from_spec(TRACE_SPEC)
TRACE_SPEC.loader.exec_module(evaluator_trace)


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
        check=False, env=env,
    )


def main() -> None:
    class FakeLiveTrace:
        payload = None
        started = []
        finished = []

        def __init__(self, payload):
            type(self).payload = payload
            self.client = object()
            self.summary = {"trace_id": "a" * 32, "logged": True}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def start_phase(self, **kwargs):
            type(self).started.append(kwargs)
            return "phase-observation"

        def finish_phase(self, observation, **kwargs):
            assert observation == "phase-observation"
            type(self).finished.append(kwargs)

        def finish(self, _payload):
            return self.summary

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        artifacts = root / ".artifacts" / "TRACE-1"
        benchmark = artifacts / "benchmark"
        benchmark.mkdir(parents=True)
        env_file = root / ".env.creator"
        env_file.write_text(
            "LANGFUSE_HOST=https://creator.langfuse.test\n"
            "LANGFUSE_PUBLIC_KEY=pk-lf-creator-fixture\n"
            "LANGFUSE_SECRET_KEY=sk-lf-creator-fixture\n"
        )
        pipeline_mode.append_event(
            artifacts, phase="create-intake", status="skipped",
            program_run_id="create-TRACE-1-run", key="TRACE-1",
            details={"jira_url": "https://redhat.atlassian.net/browse/TRACE-1"},
        )
        pipeline_mode.append_event(
            artifacts, phase="create-serve", status="completed",
            program_run_id="create-TRACE-1-run", key="TRACE-1",
            details={
                "server_type": "existing-prototype", "http_status": 200,
                "journey_http_status": 200, "prototype_url": "http://127.0.0.1:1",
                "source_revision": "deadbeef",
            },
        )

        class FakeVerifier:
            langfuse_trace = SimpleNamespace(LivePipelineTrace=FakeLiveTrace)
            auth_values = []

            @staticmethod
            def load_env_file(_path):
                return env_file

            @staticmethod
            def check_health(_host):
                return None

            @staticmethod
            def check_auth(*args):
                FakeVerifier.auth_values = list(args)
                return None

        trace_args = SimpleNamespace(
            key="TRACE-1", env_file=str(env_file), benchmark_name="creator-test",
            artifacts_dir=str(artifacts), benchmark_dir=str(benchmark),
            jira_url="https://redhat.atlassian.net/browse/TRACE-1",
            gitlab_url="https://gitlab.example.test/project.git",
            prototype_url="http://127.0.0.1:1", source_revision="deadbeef",
        )
        with patch.object(pipeline_mode, "evaluator_verifier", return_value=FakeVerifier):
            with patch.dict(os.environ, {
                "LANGFUSE_HOST": "http://langfuse.test",
                "LANGFUSE_PUBLIC_KEY": "pk-lf-evaluator-fixture",
                "LANGFUSE_SECRET_KEY": "sk-lf-evaluator-fixture",
            }):
                trace_result = pipeline_mode.export_create_serve_trace(
                    trace_args, artifacts, "create-TRACE-1-run"
                )
        assert trace_result["logged"] is True
        assert FakeLiveTrace.payload["eval_run_id"] == "create-TRACE-1-run"
        assert FakeLiveTrace.payload["jira_url"] == "https://redhat.atlassian.net/browse/TRACE-1"
        assert FakeLiveTrace.payload["source_revision"] == "deadbeef"
        assert Path(FakeLiveTrace.payload["trace_context_path"]) == (
            pipeline_mode.creator_trace_context_path(benchmark.resolve(), "create-TRACE-1-run")
        ), FakeLiveTrace.payload["trace_context_path"]
        assert pipeline_mode.creator_trace_context_path(
            benchmark, "create-TRACE-1-run"
        ) != pipeline_mode.creator_trace_context_path(benchmark, "create-TRACE-1-next")
        assert [phase["name"] for phase in FakeLiveTrace.started] == [
            "create-intake", "create-serve",
        ]
        assert '"jira_url": "https://redhat.atlassian.net/browse/TRACE-1"' in FakeLiveTrace.started[0]["input_text"]
        assert '"source_revision": "deadbeef"' in FakeLiveTrace.started[1]["input_text"]
        assert all(item["phase"]["provider"] == "local" for item in FakeLiveTrace.finished)
        assert FakeVerifier.auth_values == [
            "https://creator.langfuse.test",
            "pk-lf-creator-fixture",
            "sk-lf-creator-fixture",
        ]

    trace_env = os.environ.get("CREATOR_LANGFUSE_ENV_FILE")
    with tempfile.TemporaryDirectory() as directory:
        artifacts = Path(directory) / ".artifacts" / "DEMO-1"
        prototype = artifacts / "prototype"
        prototype.mkdir(parents=True)
        (prototype / "index.html").write_text("<html><head><title>Inventory Console</title></head><body><h1>Inventory Console</h1></body></html>")
        (artifacts / "metadata.json").write_text(json.dumps({"title": "Inventory Console"}))
        program_run_id = "program-DEMO-1-fixture"
        intake = run("--key", "DEMO-1", "--artifacts-dir", str(artifacts), "--program-run-id", program_run_id,
                     "--record-phase", "create-intake")
        assert intake.returncode == 0, intake.stderr
        trace_args = (
            ("--env-file", trace_env, "--benchmark-name", "round1-create-serve-metadata")
            if trace_env else ()
        )
        result = run("--key", "DEMO-1", "--artifacts-dir", str(artifacts), "--journey-route", "/inventory",
                     "--program-run-id", program_run_id, *trace_args)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["model_invoked"] is False
        if trace_env:
            assert payload["langfuse"]["logged"] is True
            assert payload["langfuse"]["trace_id"]
        assert urllib.request.urlopen(payload["url"] + "/inventory", timeout=3).status == 200
        config = (artifacts / "pipeline-config.yaml").read_text()
        assert "approval_required: true" in config
        assert payload["program_run_id"] == program_run_id
        assert program_run_id in config
        events = [json.loads(line) for line in (artifacts / "creator-phase-events.jsonl").read_text().splitlines()]
        completed = events[-1]
        assert completed["component"] == "creator"
        assert completed["privacy_mode"] == "metadata_only"
        assert completed["model_invoked"] is False
        assert "expected_text" not in completed

        source_workspace = Path(directory) / "real-case-workspace"
        source_workspace.mkdir()
        (source_workspace / "README.md").write_text("real case\n")
        subprocess.run(["git", "init", "-q"], cwd=source_workspace, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source_workspace, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=source_workspace, check=True)
        subprocess.run(["git", "add", "README.md"], cwd=source_workspace, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source_workspace, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.example.com/uxd/prototype.git"],
            cwd=source_workspace, check=True,
        )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=source_workspace,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        external_artifacts = Path(directory) / ".artifacts" / "REAL-1"
        external = run(
            "--key", "REAL-1", "--artifacts-dir", str(external_artifacts),
            "--workspace", str(source_workspace), "--prototype-url", payload["url"],
            "--jira-url", "https://jira.example.com/browse/REAL-1",
            "--gitlab-url", "https://gitlab.example.com/uxd/prototype.git",
            "--source-revision", revision, "--expected-text", "Inventory Console",
        )
        assert external.returncode == 0, external.stderr
        external_payload = json.loads(external.stdout)
        assert external_payload["pid"] == 0
        assert 'type: "existing-prototype"' in (external_artifacts / "pipeline-config.yaml").read_text()
        stopped = run("--key", "DEMO-1", "--artifacts-dir", str(artifacts), "--stop")
        assert stopped.returncode == 0, stopped.stderr
        time.sleep(0.1)

    with tempfile.TemporaryDirectory() as directory:
        artifacts = Path(directory) / ".artifacts" / "LOGIN-1"
        prototype = artifacts / "prototype"
        prototype.mkdir(parents=True)
        (prototype / "index.html").write_text("<html><head><title>Sign in</title></head><body>Sign in</body></html>")
        result = run("--key", "LOGIN-1", "--artifacts-dir", str(artifacts))
        assert result.returncode == 2
        events = [json.loads(line) for line in (artifacts / "creator-phase-events.jsonl").read_text().splitlines()]
        assert events[-1]["status"] == "failed"
        run("--key", "LOGIN-1", "--artifacts-dir", str(artifacts), "--stop")

    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / "workspace"
        artifacts = Path(directory) / ".artifacts" / "WORKSPACE-1"
        workspace.mkdir()
        (workspace / "package.json").write_text(json.dumps({
            "name": "fixture", "private": True,
            "scripts": {"build": "mkdir -p dist && cp index-source.html dist/index.html"},
        }))
        fake_bin = Path(directory) / "bin"
        fake_bin.mkdir()
        fake_npm = fake_bin / "npm"
        fake_npm.write_text(
            "#!/bin/bash\n"
            "if [[ \"$1\" == \"run\" && \"$2\" == \"build\" ]]; then\n"
            "  mkdir -p dist\n"
            "  cp index-source.html dist/index.html\n"
            "fi\n"
        )
        fake_npm.chmod(0o755)
        (workspace / "index-source.html").write_text(
            "<html><head><title>Workspace Prototype</title></head><body>Workspace Prototype</body></html>"
        )
        result = run("--key", "WORKSPACE-1", "--artifacts-dir", str(artifacts),
                     "--workspace", str(workspace), "--expected-text", "Workspace Prototype",
                     env={**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin"})
        assert result.returncode == 0, result.stderr
        config = (artifacts / "pipeline-config.yaml").read_text()
        assert 'type: "workspace-build"' in config
        run("--key", "WORKSPACE-1", "--artifacts-dir", str(artifacts), "--stop")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        artifacts = root / ".artifacts" / "BUDGET-1"
        estimate = run("--key", "BUDGET-1", "--artifacts-dir", str(artifacts),
                       "--benchmark-dir", str(root / "benchmark"), "--estimate-only")
        assert estimate.returncode == 0, estimate.stderr
        estimate_payload = json.loads(estimate.stdout)
        assert estimate_payload["cap_usd"] == 15.0
        assert estimate_payload["estimated_openai_cost_usd"] == 12.02
        assert estimate_payload["model_invoked"] is False
        assert estimate_payload["ledger_path"].endswith("openai-budget-ledger-creator.json")
        assert estimate_payload["model_defaults"] == {"skill": "gpt-6-sol", "judge": "gpt-6-luna"}
        assert [phase["phase"] for phase in estimate_payload["paid_phases"]] == [
            "create-plan", "create-generate", "create-refine",
        ]
        assert Path(estimate_payload["ledger_path"]).is_file()
        assert json.loads(Path(estimate_payload["ledger_path"]).read_text())["cap_usd"] == 15.0

        creator = pipeline_mode.creator_cost_authority(
            root / "benchmark",
            phase_bounds={"create-generate": (30_000_000, 0)},
        )
        evaluator = evaluator_trace.OpenAICostAuthority(
            cap_usd=25.0,
            ledger_path=root / "benchmark" / "openai-budget-ledger.json",
            phase_bounds={"eval-load": (60_000_000, 0)},
            reservation_namespace="eval",
        )
        creator_reservation = creator.reserve("create-generate", "gpt-5.6-luna")
        assert creator_reservation is not None
        assert creator_reservation["reserved_usd"] == 12.0
        evaluator_reservation = evaluator.reserve("eval-load", "gpt-5.6-luna")
        assert evaluator_reservation is not None
        assert evaluator_reservation["reserved_usd"] == 24.0
        assert creator.ledger_path != evaluator.ledger_path
        assert creator.release(creator_reservation, reason="fake-provider abandoned")["completed_openai_usd"] == 0.0
        assert evaluator.release(evaluator_reservation, reason="fake-provider abandoned")["completed_openai_usd"] == 0.0
        assert json.loads(creator.ledger_path.read_text())["cap_usd"] == 15.0
        assert json.loads(evaluator.ledger_path.read_text())["cap_usd"] == 25.0

    print("PASS")


if __name__ == "__main__":
    main()
