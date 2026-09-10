#!/usr/bin/env python3
"""Verify screenshot evidence capture works outside the skill working directory."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "capture-prototype-evidence.js"
)


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        unrelated_cwd = root / "caller"
        artifacts = root / "workspace" / ".artifacts" / "TEST-1" / "eval"
        unrelated_cwd.mkdir()
        artifacts.mkdir(parents=True)
        prototype = root / "prototype.html"
        prototype.write_text(
            "<!doctype html><html><head><title>Ground truth</title></head>"
            "<body><h1>GenAI Studio</h1><button aria-label='Run model'>Run</button>"
            "<a href='#tool-calls'>Tool calls</a></body></html>"
        )
        completed = subprocess.run(
            ["node", str(SCRIPT), str(artifacts), prototype.as_uri(), "--json"],
            cwd=unrelated_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        evidence = json.loads((artifacts / "prototype-evidence.json").read_text())
        assert result["model_invoked"] is False
        assert evidence["screenshots"] == ["screenshots/journey-baseline.png"]
        assert not Path(evidence["screenshots"][0]).is_absolute()
        assert (artifacts / evidence["screenshots"][0]).is_file()
        assert evidence["page"]["title"] == "Ground truth"
        assert evidence["page"]["headings"][0]["text"] == "GenAI Studio"
        assert any(control["name"] == "Run model" for control in evidence["page"]["controls"])

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
