#!/usr/bin/env python3
"""Zero-spend tests for the bounded eval-fix artifact-first contract."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from openai_bounded_fix import run_bounded_fix  # noqa: E402


def packet_for(workspace: Path, artifacts: Path) -> dict:
    return {
        "phase": "eval-fix",
        "key": "RHAISTRAT-1745",
        "workspace": str(workspace),
        "artifacts_dir": str(artifacts),
        "jira_context_file": str(workspace / "jira-context.json"),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp) / "workspace"
        artifacts = workspace / ".artifacts" / "RHAISTRAT-1745" / "eval"
        artifacts.mkdir(parents=True)
        (workspace / "src").mkdir()
        (workspace / "src" / "app.tsx").write_text("export const App = () => null;\n")

        (artifacts / "refinement-suggestions.json").write_text("[]")
        local_noop = run_bounded_fix(
            packet_for(workspace, artifacts), model="gpt-6-sol", reasoning_effort="high",
            max_turns=4, agent_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("paid fix invoked for empty suggestions")),
        )
        assert local_noop["status"] == "completed" and local_noop["model_invoked"] is False
        assert local_noop["token_usage"] == {} and local_noop["cost_usd"] == 0
        assert len(json.loads((artifacts / "fix-log.json").read_text())) == 1
        assert json.loads((artifacts / "fix-log.json").read_text())[0]["applied"] is False
        (artifacts / "refinement-suggestions.json").unlink()
        (artifacts / "fix-log.json").unlink()

        captured_prompt = ""

        def fake_noop(prompt: str, *, after_turn, **_kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            (artifacts / "fix-log.json").write_text(json.dumps([{
                "description": "No actionable refinement suggestion matched this prototype.",
                "applied": False,
                "timestamp": "2026-09-21T00:00:00Z",
                "rationale": "Suggested change is outside editable prototype scope.",
                "evidence_summary": "Rendered prototype already shows the available deployment control.",
                "suggestion_context": "Deployment-flow continuation suggestion.",
                "recommended_next_step": "Confirm product behavior with the designer.",
            }]))
            gate = after_turn(2)
            assert gate == ("valid eval-fix no-op logged by turn 2", True)
            return {
                "exit_code": 0,
                "status": "completed",
                "output_text": "No actionable suggestion; wrote no-op fix log.",
                "turns_used": 2,
                "token_usage": {},
                "duration_s": 0,
            }

        noop = run_bounded_fix(
            packet_for(workspace, artifacts), model="fake", reasoning_effort="low",
            max_turns=4, agent_runner=fake_noop,
        )
        assert noop["status"] == "completed"
        assert noop["turns_used"] <= 2
        assert noop["fix_safety"]["changed_file_count"] == 0
        assert "before any third turn" in captured_prompt
        assert "applied=false" in captured_prompt
        assert "all-false log is final success" in captured_prompt
        assert "Never write an empty array" in captured_prompt
        assert "MUST start with '['" in captured_prompt
        assert "evidence_summary" in captured_prompt
        assert "{\"fixes\":[...]} is invalid" in captured_prompt
        assert json.loads((artifacts / "fix-log.json").read_text())[0]["applied"] is False

        (artifacts / "fix-log.json").unlink()
        (artifacts / "refinement-suggestions.json").write_text(json.dumps([{
            "criterion_id": "AC-1", "fix_action": "Update the focused heading.",
            "fix_file": "src/app.tsx",
        }]))

        def fake_edit(prompt: str, *, tool_handler, tool_definitions, after_turn,
                      max_input_tokens, max_total_output_tokens, **_kwargs):
            assert [tool["name"] for tool in tool_definitions] == [
                "eval_fix_write_file", "eval_fix_validate_outputs",
            ]
            assert "run_shell" not in json.dumps(tool_definitions)
            assert max_input_tokens == 80_000
            assert max_total_output_tokens == 12_000
            assert '"path": "src/app.tsx"' in prompt
            assert "export const App = () => null;" in prompt
            denied = tool_handler("eval_fix_write_file", json.dumps({
                "path": "../outside.txt", "content": "unsafe",
            }))
            assert denied.startswith("Scope denied:")
            written = tool_handler("eval_fix_write_file", json.dumps({
                "path": "src/app.tsx", "content": "export const App = () => <h1>Focused</h1>;\n",
            }))
            assert json.loads(written)["status"] == "written"
            entry = [{
                "description": "Updated the focused heading.",
                "applied": True,
                "timestamp": "2026-09-21T00:00:00Z",
            }]
            log_path = ".artifacts/RHAISTRAT-1745/eval/fix-log.json"
            tool_handler("eval_fix_write_file", json.dumps({
                "path": log_path, "content": json.dumps(entry),
            }))
            validation = json.loads(tool_handler("eval_fix_validate_outputs", "{}"))
            assert validation["valid"] is True
            assert validation["changed_files"] == ["src/app.tsx"]
            assert after_turn(2) is None
            return {
                "exit_code": 0, "status": "completed", "output_text": "bounded fix written",
                "turns_used": 2, "token_usage": {"input_tokens": 50, "output_tokens": 20},
                "duration_s": 0,
            }

        edited = run_bounded_fix(
            packet_for(workspace, artifacts), model="fake", reasoning_effort="low",
            max_turns=4, agent_runner=fake_edit,
        )
        assert edited["status"] == "completed"
        assert edited["fix_safety"]["changed_file_count"] == 1
        assert "Focused" in (workspace / "src" / "app.tsx").read_text()

        (artifacts / "fix-log.json").unlink()

        def fake_missing_log(_prompt: str, **_kwargs):
            return {
                "exit_code": 0,
                "status": "completed",
                "output_text": "Stopped without writing the artifact.",
                "turns_used": 4,
                "token_usage": {},
                "duration_s": 0,
            }

        missing = run_bounded_fix(
            packet_for(workspace, artifacts), model="fake", reasoning_effort="low",
            max_turns=4, agent_runner=fake_missing_log,
        )
        assert missing["status"] == "failed"
        assert missing["exit_code"] == 2
        assert missing["output_text"] == (
            "eval-fix artifact contract failed: fix-log.json is missing or invalid"
        )

        (artifacts / "fix-log.json").write_text(json.dumps({"fixes": [{
            "description": "Incorrect wrapper shape.",
            "applied": False,
            "timestamp": "2026-09-21T00:00:00Z",
        }]}))

        wrapped = run_bounded_fix(
            packet_for(workspace, artifacts), model="fake", reasoning_effort="low",
            max_turns=4,
            agent_runner=fake_missing_log,
        )
        assert wrapped["status"] == "failed"
        assert wrapped["output_text"] == (
            "eval-fix artifact contract failed: fix-log.json must be a flat array"
        )

        (artifacts / "fix-log.json").write_text(json.dumps([{
            "description": "Unsupported no-op.",
            "applied": False,
            "timestamp": "2026-09-21T00:00:00Z",
        }]))
        unsupported_noop = run_bounded_fix(
            packet_for(workspace, artifacts), model="fake", reasoning_effort="low",
            max_turns=4, agent_runner=fake_missing_log,
        )
        assert unsupported_noop["status"] == "failed"
        assert "applied:false entries require rationale" in unsupported_noop["output_text"]

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
