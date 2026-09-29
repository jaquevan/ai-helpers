#!/usr/bin/env python3
"""Offline audit contract: lineage, parity, real PNG hashes and privacy."""

import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from judge_manifests import data_flow_manifest, report_quality_manifest  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cff00000040101005fe5c4b90000000049454e44ae426082")


def main():
    ledger_schema = json.loads((Path(__file__).resolve().parents[1] / "config" / "cost-ledger-schema.json").read_text())
    assert "api" in ledger_schema["properties"]["invocation"]["enum"]
    assert ledger_schema["properties"]["eval_run_id"]["pattern"] == "^(eval|evaluator)-"
    phase_properties = ledger_schema["properties"]["phases"]["items"]["properties"]
    assert "cache_write_tokens" in phase_properties and "model" in phase_properties
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state.json").write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(), "cache": {"decision": "miss"}, "identity": {"intent_key": "sha256:test"}}))
        (root / "screenshots").mkdir()
        (root / "screenshots" / "prototype.png").write_bytes(PNG)
        (root / "evaluation-report.html").write_text(f'<h2>Heuristic Evaluation</h2><h2>Evaluation cost estimate</h2><p>price-card estimate, not an invoice</p>$0.001000<img alt="prototype" src="data:image/png;base64,{base64.b64encode(PNG).decode()}">')
        (root / "evaluation.json").write_text(json.dumps({"ac_results": [{"verdict": "FLAGGED"}], "usability": {"dimensions": [{"score": 2}]}}))
        (root / "evaluation-summary.json").write_text(json.dumps({"counts": {"pass": 0, "fail": 0, "flagged": 1}, "usability": {"overall_score": 2}}))
        (root / "evaluation-cost.json").write_text(json.dumps({"total_estimated_usd": 0.001, "invoice_reconciled": False, "phases": [{"model": "gpt-6-sol", "model_invoked": True, "llm_cost_usd": 0.001}]}))
        (root / "persona-results.json").write_text("[]")
        (root / "heuristic-evaluation.json").write_text('{"findings":[]}')
        specs = ({"name": "eval-journey", "required": ("evaluation.json",), "outputs": ("journey-log.json",)},)
        flow = data_flow_manifest(root, "run-1", [{"phase": "eval-journey", "status": "completed", "validation": "passed"}], specs, "completed")
        assert flow["phases"][0]["input_artifacts"] == ["evaluation.json"]
        assert any(edge["artifact"] == "journey-log.json" and edge["schema_validation"] == "stale-or-missing" for edge in flow["artifact_edges"])
        assert flow["cache"]["decision"] == "miss"
        assert next(edge for edge in flow["artifact_edges"] if edge["artifact"] == "state.json")["schema_validation"] == "canonical-phase-a-output-validated"
        quality = report_quality_manifest(root, "run-1", "completed")
        assert quality["canonical_parity"]["ac_counts_match"] and quality["canonical_parity"]["usability_score_matches"]
        assert quality["screenshots"]["all_embedded_from_prototype"]
        assert quality["cost_tracking"]["phase_sum_matches"]
        assert quality["cost_tracking"]["estimate_disclosure_present"]
        assert quality["cost_tracking"]["paid_models"] == ["gpt-6-sol"]
        assert "data:image" not in json.dumps(quality)
        (root / "evaluation-report.html").write_text('<img alt="unrelated" src="data:image/png;base64,YmFk">')
        assert not report_quality_manifest(root, "run-1", "completed")["screenshots"]["all_embedded_from_prototype"]
        (root / "state.json").write_text(json.dumps({"created_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}))
        stale = data_flow_manifest(root, "run-2", [], specs, "failed")
        assert next(edge for edge in stale["artifact_edges"] if edge["artifact"] == "evaluation-report.html")["schema_validation"] == "stale-or-missing"
        ledger_script = Path(__file__).resolve().parents[1] / "scripts" / "log-cost-ledger.js"
        payload = {"eval_run_id": "run-1", "prototype_key": "TEST-1", "invocation": "api",
                   "totals": {"llm_cost_usd": 0.00279, "total_tokens": 1100},
                   "phases": [{"phase": "eval-journey", "model": "gpt-6-sol", "llm_cost_usd": 0.00279}]}
        written = subprocess.run(["node", str(ledger_script), "--artifacts-dir", str(root)], input=json.dumps(payload),
                                 text=True, capture_output=True, env={**os.environ, "UXD_PROJECT_ROOT": tmp}, cwd=tmp)
        assert written.returncode == 0, written.stderr
        rows = (root / "cost-ledger.jsonl").read_text().splitlines()
        assert len(rows) == 1 and json.loads(rows[0])["totals"]["llm_cost_usd"] == 0.00279
    print("PASS")


if __name__ == "__main__":
    main()
