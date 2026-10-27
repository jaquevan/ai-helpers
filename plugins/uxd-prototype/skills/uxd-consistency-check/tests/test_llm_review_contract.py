"""Offline validation tests for LLM findings and guideline-rooted fix handoffs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from guideline_sources import load_guidelines
from guideline_resolver import read_index
from llm_review_contract import validate_llm_review
from guideline_selection import confirm_selection, propose_selection
from guideline_snapshot import freeze_selected_readme_sources, bind_manifest_selection
from schema_assertions import assert_schema
from scoped_sources import read_sources


class LLMReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "index.html").write_text("<html>\n<div>Before</div>\n</html>\n")
        self.rule = self.root / "rules/product-guideline.md"
        self.rule.parent.mkdir()
        self.rule.write_text("---\nid: custom-css\n---\n\n## Styling\nUse approved tokens in component styling.\n")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "index.html"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "base"], check=True)
        (self.root / "index.html").write_text("<html>\n<div style=\"color:red\">Custom</div>\n</html>\n")
        self.manifest = load_guidelines(self.root, [f"product={self.rule}"])
        self.selection = self.approved_selection()
        self.legacy_manifest = self.manifest
        self.manifest = bind_manifest_selection(self.root, self.manifest, self.selection)
        self.files, self.changed_lines, self.inputs = read_sources(self.root, changed=True, base_ref="HEAD", approved_scope=self.manifest['review_scope'])
        self.run_id = "fixture-run-001"
        self.scope_report = {"run_id": self.run_id, "inputs": self.inputs}
        document, = self.manifest["documents"]
        self.raw = {"schema_version": "1.1.0", "status": "completed", "method": "llm",
                    "model": "fixture-model", "checker_version": "consistency-checker-llm-v1.1",
                    "run_id": self.run_id, "prompt_version": "llm-review-contract-v1.1",
                    "prompt_sha256": "a" * 64, "guideline_ref": None,
                    "reviews": [{"guideline_id": document["id"], "status": "violation", "severity": "warning",
                        "confidence": "medium", "guideline": {"path": str(self.rule), "heading": "Styling",
                            "quote": "Use approved tokens in component styling.", "sha256": document["sha256"],
                            "ref": None},
                        "source_evidence": {"file": "index.html", "line_start": 2, "line_end": 2,
                            "excerpt": '<div style="color:red">Custom</div>'},
                        "rationale": "Inline styling conflicts with the cited guidance.", "limitations": [],
                        "suggested_fix": "Replace the inline color with the approved token-backed class.",
                        "side_effects": "Confirm the token exists in this product release.",
                        "test_suggestion": "Add a focused assertion for the token-backed class.",
                        "acceptance_condition": "The inline style is absent and the approved token is applied.",
                        "verifier": None}]}

    def approved_selection(self):
        index = self.rule.parent / 'README.md'
        index.write_text('---\nproduct: Fixture\n---\n# Guidelines\n[Styling](product-guideline.md#styling)\n')
        catalog = read_index(self.root, index)
        source, = read_index(self.root, index, topics=catalog['topics'])['sources']
        proposal = propose_selection(self.root, index, source_ids=[source['id']],
            review_scope={'kind':'code_paths', 'directories':['.'], 'files':[]}, method='model')
        approval = {'kind':'explicit_instruction', 'reference':'fixture:binding',
            'quote':'Review only the explicitly selected scope and section.', 'proposal_sha256':proposal['sha256']}
        return confirm_selection(self.root, proposal, approval, exceptions=[source['id']], model_approval=approval)

    def test_violation_is_linked_to_exact_rule_and_code_and_fix_stays_proposed(self):
        report, handoff = validate_llm_review(self.raw, manifest=self.manifest, workspace=self.root,
                                               scope_report=self.scope_report)
        assert_schema(self, self.raw, json.loads((SKILL / "schemas/v1/llm-review.schema.json").read_text()))
        assert_schema(self, self.manifest, json.loads((SKILL / "schemas/v1/selected-guideline-snapshot.schema.json").read_text()))
        assert_schema(self, report, json.loads((SKILL / "schemas/v1/llm-review-report.schema.json").read_text()))
        assert_schema(self, handoff, json.loads((SKILL / "schemas/v1/fix-proposals.schema.json").read_text()))
        finding, = report["reviews"]
        proposal, = handoff["proposals"]
        self.assertEqual(finding["status"], "violation")
        self.assertEqual(finding["guideline"]["href"], "rules/product-guideline.md#styling")
        self.assertEqual(finding["source_evidence"]["href"], "index.html#L2-L2")
        self.assertEqual(report["summary"]["nonpassing_rules"], 0)
        self.assertEqual(proposal["finding_id"], finding["finding_id"])
        self.assertFalse(proposal["applied"])
        self.assertEqual(proposal["approval_state"], "pending_human_approval")
        self.assertEqual(report["coverage"]["deterministic"]["status"], "not_run")

    def test_no_issue_is_not_a_deterministic_pass_and_every_rule_must_be_covered(self):
        raw = copy.deepcopy(self.raw)
        review = raw["reviews"][0]
        review.update(status="no_issue_found", severity=None, suggested_fix=None, side_effects=None,
                      test_suggestion=None, acceptance_condition=None)
        review["rationale"] = "No mismatch found in the selected changed excerpt."
        report, handoff = validate_llm_review(raw, manifest=self.manifest, workspace=self.root,
                                               scope_report=self.scope_report)
        self.assertEqual(report["summary"]["no_issue_found"], 1)
        self.assertEqual(report["coverage"]["deterministic"]["status"], "not_run")
        self.assertEqual(handoff["proposals"], [])
        raw["reviews"] = []
        with self.assertRaisesRegex(ValueError, "every selected rule"):
            validate_llm_review(raw, manifest=self.manifest, workspace=self.root, scope_report=self.scope_report)

    def test_invalid_guideline_citation_source_excerpt_and_changed_scope_are_rejected(self):
        mutations = [
            (lambda raw: raw["reviews"][0]["guideline"].update(quote="invented rule"), "exact excerpt"),
            (lambda raw: raw["reviews"][0]["guideline"].update(path=str(self.root / "other.md")), "exact selected source"),
            (lambda raw: raw["reviews"][0]["guideline"].update(sha256="0" * 64), "hash differs"),
            (lambda raw: raw["reviews"][0]["source_evidence"].update(file="other.html"), "changed MR scope"),
            (lambda raw: raw["reviews"][0]["source_evidence"].update(excerpt="different"), "does not match"),
            (lambda raw: raw["reviews"][0]["source_evidence"].update(line_start=1, line_end=1, excerpt="<html>"), "does not intersect a changed line"),
            (lambda raw: raw["reviews"][0].update(status="unsupported"), "only violation results"),
        ]
        for mutate, expected in mutations:
            raw = copy.deepcopy(self.raw)
            mutate(raw)
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                validate_llm_review(raw, manifest=self.manifest, workspace=self.root,
                                    scope_report=self.scope_report)

    def test_stale_source_and_wrong_changed_line_are_rejected(self):
        (self.root / "index.html").write_text("<html>\n<div>Changed after scope capture</div>\n</html>\n")
        with self.assertRaisesRegex(ValueError, "scope report differs from the current pinned MR delta"):
            validate_llm_review(self.raw, manifest=self.manifest, workspace=self.root,
                                scope_report=self.scope_report)
        (self.root / "index.html").write_text("<html>\n<div style=\"color:red\">Custom</div>\n</html>\n")
        changed_scope = copy.deepcopy(self.scope_report)
        changed_scope["inputs"]["changed_lines"]["index.html"] = [3]
        with self.assertRaisesRegex(ValueError, "scope report differs from the current pinned MR delta"):
            validate_llm_review(self.raw, manifest=self.manifest, workspace=self.root,
                                scope_report=changed_scope)

    def test_product_readme_to_selected_snapshot_to_mr_cited_review(self):
        index = self.root / ".design/product/design-guidelines/README.md"
        index.parent.mkdir(parents=True)
        rule = index.parent / "controls.md"
        rule.write_text("---\nid: controls\n---\n\n## Product controls\nUse a product-approved color token.\n")
        index.write_text("---\nproduct: Example product\nrelease: 3.6\n---\n\n# Guidelines\n\n[Controls](controls.md#product-controls)\n")
        candidates = read_index(self.root, index)
        source, = read_index(self.root, index, topics=candidates["topics"])["sources"]
        proposal = propose_selection(self.root, index, source_ids=[source["id"]],
                                     review_scope={'kind':'code_paths', 'directories':['.'], 'files':[]}, method="model")
        approval = {"kind": "explicit_instruction", "reference": "fixture:selection",
                    "quote": "Use this selected product rule for model review of src.",
                    "proposal_sha256": proposal["sha256"]}
        selection = confirm_selection(self.root, proposal, approval, exceptions=[source["id"]],
                                      model_approval=approval)
        frozen = freeze_selected_readme_sources(self.root, selection)
        snapshot = frozen["snapshot"]
        self.assertEqual(snapshot["documents"][0]["id"], "controls")
        self.assertEqual(snapshot["documents"][0]["identity_kind"], "source_authored")
        rule.unlink()  # Frozen replay must not re-open the live product source.
        raw = copy.deepcopy(self.raw)
        review = raw["reviews"][0]
        review["guideline_id"] = snapshot["documents"][0]["id"]
        review["guideline"] = {"path": ".design/product/design-guidelines/controls.md",
            "heading": "Product controls", "quote": "Use a product-approved color token.",
            "sha256": snapshot["documents"][0]["sha256"], "ref": snapshot['documents'][0]['provenance']['ref']}
        raw["guideline_ref"] = snapshot['documents'][0]['provenance']['ref']
        report, handoff = validate_llm_review(raw, manifest=snapshot, workspace=self.root,
                                               scope_report=self.scope_report)
        self.assertEqual(report["guideline_manifest_sha256"], snapshot["snapshot_sha256"])
        self.assertEqual(report["reviews"][0]["guideline"]["href"],
                         ".design/product/design-guidelines/controls.md#product-controls")
        self.assertEqual(handoff["proposals"][0]["guideline_id"], snapshot["documents"][0]["id"])
        raw["prompt_sha256"] = hashlib.sha256((SKILL / "references/llm-review-contract.md").read_bytes()).hexdigest()
        artifacts = self.root / ".artifacts/consistency/fixture"
        artifacts.mkdir(parents=True)
        input_path = artifacts / "raw-review.json"
        scope_path = artifacts / "scope-report.json"
        input_path.write_text(json.dumps(raw))
        scope_path.write_text(json.dumps({"workspace": str(self.root), "run_id": self.run_id, "inputs": self.inputs,
            "coverage": {"evaluated_rules": [], "unevaluated_rules": []},
            "guideline_manifest": str(frozen["path"])}))
        output_path = artifacts / "llm-consistency-report.json"
        fix_path = artifacts / "fix-proposals.json"
        result = subprocess.run([sys.executable, "-S", str(SKILL / "scripts/validate_llm_review.py"),
            "--workspace", str(self.root), "--input", str(input_path), "--scope-report", str(scope_path),
            "--guideline-manifest", str(frozen["path"]), "--output", str(output_path), "--fix-output", str(fix_path)],
            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output_path.read_text())["report_type"], "product_guideline_llm_review")
        self.assertFalse(json.loads(fix_path.read_text())["proposals"][0]["applied"])

    def test_invalid_review_schema_is_rejected(self):
        for mutate in (lambda raw: raw["reviews"][0].pop("verifier"),
                       lambda raw: raw["reviews"][0].update(status="pass"),
                       lambda raw: raw["reviews"][0].update(unexpected="field")):
            raw = copy.deepcopy(self.raw)
            mutate(raw)
            with self.subTest(review=raw["reviews"][0]), self.assertRaises(ValueError):
                validate_llm_review(raw, manifest=self.manifest, workspace=self.root,
                                    scope_report=self.scope_report)

    def test_high_impact_reviews_require_independent_verification_and_disagreements_remain_visible(self):
        raw = copy.deepcopy(self.raw)
        review = raw["reviews"][0]
        review["severity"] = "error"
        review["verifier"] = {"model": "independent-fixture", "status": "no_issue_found",
                              "agrees": False, "rationale": "The cited change may be acceptable in context."}
        report, _ = validate_llm_review(raw, manifest=self.manifest, workspace=self.root,
                                        scope_report=self.scope_report)
        self.assertEqual(report["reviews"][0]["disagreement"]["resolution"],
                         "unresolved; primary reviewer verdict retained")
        review["verifier"] = None
        with self.assertRaisesRegex(ValueError, "require an independent verifier"):
            validate_llm_review(raw, manifest=self.manifest, workspace=self.root,
                                scope_report=self.scope_report)


if __name__ == "__main__":
    unittest.main()
