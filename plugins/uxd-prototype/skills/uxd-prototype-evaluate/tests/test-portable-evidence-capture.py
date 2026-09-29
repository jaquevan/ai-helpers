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
            "<body><h1>GenAI Studio</h1>"
            "<button class='pf-v6-c-button pf-m-primary' aria-label='Run model'>Run</button>"
            "<a href='#tool-calls'>Tool calls</a>"
            + "".join(f"<button>Action {index}</button>" for index in range(8))
            + "</body></html>"
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
        assert len(evidence["crops"]) == 6
        assert evidence["model_screenshots"] == [item["image"]["path"] for item in evidence["crops"]]
        assert all((artifacts / relative).is_file() for relative in evidence["model_screenshots"])
        assert evidence["input_metrics"]["selected_pixels"] < evidence["input_metrics"]["raw_pixels"]
        assert evidence["input_metrics"]["pixel_ratio"] < 1
        for item in evidence["crops"]:
            crop = item["crop"]
            image = item["image"]
            expected_width = min(1440, crop["x"] + crop["width"] + crop["padding"]) - max(0, crop["x"] - crop["padding"])
            expected_height = min(900, crop["y"] + crop["height"] + crop["padding"]) - max(0, crop["y"] - crop["padding"])
            assert image["width"] == expected_width
            assert image["height"] == expected_height
        assert result["model_screenshot_paths"] == evidence["model_screenshots"]
        assert result["selected_pixel_ratio"] < 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
