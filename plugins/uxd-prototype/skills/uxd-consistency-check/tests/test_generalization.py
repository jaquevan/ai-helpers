"""Offline stdlib regressions; fixtures are not official design-system guidance."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from guideline_sources import load_guidelines, load_manifest, validate_manifest, manifest_version
from schema_assertions import assert_schema
from validate_ai_review import validate_review
from artifact_io import local_path, output_path, protect_inputs


class GeneralizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS's default temporary root can contain an OS-level /var symlink.
        # Use its canonical location without weakening source symlink guards.
        self.root = Path(self.temp.name).resolve()
        (self.root / "index.html").write_text('<html><button>Save</button></html>\n')

    def rule(self, name="rules/policy.md", **metadata):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        info = {"id": "team-policy", "title": "Team policy", "severity": "error",
                "check": "required-html-class", "required_class": "team-theme", **metadata}
        path.write_text("---\n" + "\n".join(f"{k}: {v}" for k, v in info.items()) + "\n---\n\n## Rule\nLocal test policy.\n")
        return path

    def analyze(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, "-S", str(SKILL / "scripts/analyze.py"),
                                 "--workspace", str(self.root), *map(str, arguments)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(json.loads((self.root / report["artifact"]).read_text()), report)
        return report

    def test_root_class_uses_actual_html_attributes(self):
        policy = self.rule()
        cases = [
            ('<html data-class="team-theme">', 1),
            ('<html title="class=\'team-theme\'">', 1),
            ('<HTML CLASS="team-theme">', 0),
            ('<html title=">" class="team-theme">', 0),
            ('<html class=team-theme>', 0),
            ('<html class="TEAM-THEME">', 1),
        ]
        for markup, expected in cases:
            with self.subTest(markup=markup):
                (self.root / "index.html").write_text(markup + "</html>\n")
                report = self.analyze("--guidelines", f"product={policy}", expected=expected)
                self.assertEqual(report["summary"]["passes"], 1 - expected)
                self.assertEqual(report["summary"]["violations"], expected)

    def test_namespaced_product_sources_preserve_colliding_rules_without_baseline(self):
        first = self.rule("alpha/policy.md", id="theme", source_url="https://example.test/pinned/rule.md",
                          version="3.6", retrieved_at="2026-10-20T17:36:20Z")
        second = self.rule("beta/policy.md", id="theme", check="product-context-review")
        report = self.analyze("--design-system", "patternfly", "--guidelines", f"alpha={first}",
                              "--guidelines", f"beta={second}", expected=1)
        documents = {d["id"]: d for d in report["guideline_context"]["documents"]}
        self.assertEqual(set(documents), {"alpha:theme", "beta:theme"})
        self.assertEqual(report["coverage"], {"evaluated_rules": ["alpha:theme"],
                                            "unevaluated_rules": ["beta:theme"]})
        self.assertEqual(documents["alpha:theme"]["original_id"], "theme")
        self.assertEqual(documents["alpha:theme"]["version"], "3.6")
        snapshot = json.loads((self.root / report["guideline_manifest"]).read_text())
        self.assertEqual(next(d for d in snapshot["documents"] if d["namespace"] == "alpha")["text"], first.read_text())

    def test_frozen_replay_uses_selected_identity_without_original_sources(self):
        policy = self.rule(design_system="mui")
        report = self.analyze("--design-system", "mui", "--guidelines", f"mui={policy}", expected=1)
        snapshot = self.root / report["guideline_manifest"]
        policy.unlink()
        replay = self.analyze("--guideline-manifest", snapshot, expected=1)
        self.assertEqual(replay["source_mode"], report["source_mode"])
        self.assertEqual(replay["coverage"], report["coverage"])
        self.assertEqual(replay["guidelines_version"], report["guidelines_version"])
        self.assertEqual(replay["design_system"], report["design_system"])
        self.assertEqual(load_manifest(snapshot, self.root, "mui")["schema_version"], "1.1.0")
        with self.assertRaisesRegex(ValueError, "design system"):
            load_manifest(snapshot, self.root, "carbon")

    def test_frozen_provenance_tampering_is_rejected_not_only_text_hashes(self):
        policy = self.rule(source_url="https://example.test/pinned/rule.md", version="1",
                           retrieved_at="2026-10-20T17:36:20Z")
        original = load_guidelines(self.root, [f"team={policy}"])
        self.assertEqual(validate_manifest(original), original)
        mutations = {
            "kind": lambda m: (m["documents"][0].update(kind="baseline"), m["sources"][0].update(kind="baseline")),
            "identity": lambda m: m["documents"][0].update(original_id="other"),
            "namespace": lambda m: m["sources"][0].update(namespace="other"),
            "source attribution": lambda m: m["documents"][0]["sources"].append(str(self.root / "unselected.md")),
            "source location": lambda m: (m["sources"][0].update(location=str(self.root / "moved.md")), m["documents"][0].update(sources=[str(self.root / "moved.md")])),
            "remote attribution": lambda m: m["documents"][0].update(source_url="https://wrong.test/rule"),
            "retrieval time": lambda m: m["documents"][0].update(retrieved_at="yesterday"),
            "text": lambda m: m["documents"][0].update(text="different text"),
            "workspace": lambda m: m.update(workspace=str(self.root / "other")),
            "design system": lambda m: m.update(design_system="carbon"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = copy.deepcopy(original)
                mutate(value)
                with self.assertRaises(ValueError):
                    validate_manifest(value)

    def test_published_schema_accepts_namespaced_manifest_and_rejects_bad_metadata(self):
        policy = self.rule()
        manifest = load_guidelines(self.root, [policy])
        schema = json.loads((SKILL / "schemas/v1/guideline-manifest.schema.json").read_text())
        assert_schema(self, manifest, schema)
        for target, field, value in [("documents", "namespace", None), ("documents", "original_id", "bad:id"),
                                     ("documents", "id", "raw-id"), ("sources", "namespace", "bad:name"),
                                     ("sources", "kind", "remote")]:
            with self.subTest(target=target, field=field):
                changed = copy.deepcopy(manifest)
                changed[target][0][field] = value
                with self.assertRaises(AssertionError):
                    assert_schema(self, changed, schema)
        report = self.analyze("--guidelines", policy, expected=1)
        assert_schema(self, report, json.loads((SKILL / "schemas/v1/consistency-report.schema.json").read_text()))

    def test_identical_duplicates_merge_provenance_once_per_namespace(self):
        first = self.rule("rules/first.md")
        second = self.root / "rules/second.md"
        second.write_text(first.read_text())
        manifest = load_guidelines(self.root, ["team=rules", f"other={first}"])
        self.assertEqual([d["id"] for d in manifest["documents"]], ["other:team-policy", "team:team-policy"])
        team = manifest["documents"][1]
        self.assertEqual(team["sources"], sorted([str(first), str(second)]))
        self.assertEqual(manifest["sources"][0]["document_ids"], ["team:team-policy"])
        validate_manifest(manifest)
        assert_schema(self, manifest, json.loads((SKILL / "schemas/v1/guideline-manifest.schema.json").read_text()))
        second.write_text(first.read_text() + "Different rule text.\n")
        with self.assertRaisesRegex(ValueError, "conflicting guideline ID: team:team-policy"):
            load_guidelines(self.root, ["team=rules"])

    def test_replay_rejects_inconsistent_namespaces_even_with_recomputed_fingerprint(self):
        original = load_guidelines(self.root, [self.rule()])
        for mutate in [lambda m: m["sources"][0].pop("namespace"),
                       lambda m: m["documents"][0].update(namespace=42),
                       lambda m: m["documents"][0].update(original_id="different"),
                       lambda m: m["sources"][0]["document_ids"].append("local:team-policy"),
                       lambda m: m["documents"][0].pop("retrieved_at")]:
            changed = copy.deepcopy(original)
            mutate(changed)
            changed["version"] = manifest_version(changed)
            with self.assertRaises(ValueError):
                validate_manifest(changed)
        empty = load_guidelines(self.root)
        empty["sources"] = [{"kind": "explicit", "location": str(self.root), "document_ids": [], "namespace": "bad:name"}]
        empty["version"] = manifest_version(empty)
        with self.assertRaises(ValueError):
            validate_manifest(empty)

    def test_custom_only_mui_fixture_has_generic_policy_evidence_not_patternfly(self):
        fixture = SKILL / "tests/fixtures/unofficial-mui"
        report = self.analyze("--design-system", "mui", "--guidelines", f"demo={fixture}", expected=1)
        self.assertEqual(report["coverage"], {"evaluated_rules": ["demo:app-theme"],
                         "unevaluated_rules": ["demo:contextual-components"]})
        self.assertEqual(report["guideline_consistency"]["baseline"]["selected_rules"], [])
        finding, = report["source_mode"]["violations"]
        self.assertEqual((finding["guideline_id"], finding["severity"], finding["verdict"],
                          finding["confidence"], finding["review_candidate"], finding["check_method"]),
                         ("demo:app-theme", "error", "VIOLATION", "high", False, "automated"))
        self.assertIn("selected guideline", finding["description"])
        (self.root / "index.html").write_text('<html class="demo-theme"><button>Save</button></html>\n')
        passing = self.analyze("--design-system", "mui", "--guidelines", f"demo={fixture}")
        self.assertEqual(passing["summary"]["passes"], 1)
        self.assertEqual(passing["coverage"]["unevaluated_rules"], ["demo:contextual-components"])

    def test_supplemental_prose_review_stays_separate_and_uses_qualified_identity(self):
        policy = self.rule(check="unsupported-context-review", automatable="true")
        report = self.analyze("--guidelines", f"product={policy}")
        self.assertEqual(report["coverage"]["unevaluated_rules"], ["product:team-policy"])
        self.assertEqual(report["summary"], {"total_guidelines_checked": 0, "violations": 0, "warnings": 0, "passes": 0})
        self.assertEqual(report["source_mode"]["violations"], [])
        deterministic_bytes = (self.root / report["artifact"]).read_bytes()
        raw = {"status": "completed", "mode": "source", "model": "fixture-model",
               "non_deterministic": True, "findings": [{"guideline_id": "product:team-policy",
               "file": "index.html", "line_start": 1, "line_end": 1, "evidence": "<button>Save</button>",
               "rationale": "Illustrative context judgment.", "suggestion": "Review the chosen treatment.", "confidence": "low"}]}
        raw_path = self.root / ".artifacts/raw-review.json"
        raw_path.write_text(json.dumps(raw))
        result = subprocess.run([sys.executable, "-S", str(SKILL / "scripts/validate_ai_review.py"),
                                 "--mode", "source", "--input", str(raw_path), "--source-root", str(self.root),
                                 "--guideline-manifest", str(self.root / report["guideline_manifest"])],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        supplemental = json.loads((self.root / ".artifacts/consistency-source-review.json").read_text())
        self.assertEqual(supplemental["report_type"], "supplemental_review")
        self.assertTrue(supplemental["non_deterministic"])
        self.assertEqual(supplemental["findings"][0]["check_method"], "model_review")
        self.assertEqual(supplemental["findings"][0]["guideline_sources"], [str(policy)])
        self.assertEqual((self.root / report["artifact"]).read_bytes(), deterministic_bytes)
        raw["findings"][0]["guideline_id"] = "team-policy"
        with self.assertRaisesRegex(ValueError, "unknown guideline_id"):
            validate_review(raw, mode="source", source_root=self.root,
                            guideline_manifest=self.root / report["guideline_manifest"])

    def test_supplemental_review_rejects_rules_for_another_design_system(self):
        policy = self.rule(design_system="carbon", check="unsupported-context-review")
        manifest = load_guidelines(self.root, [policy], "mui")
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps(manifest))
        screenshot = self.root / "screenshot.png"
        screenshot.write_bytes(b"illustrative screenshot reference")
        finding = {"guideline_id": "local:team-policy", "file": "index.html",
                   "line_start": 1, "line_end": 1, "evidence": "<button>Save</button>",
                   "screenshot": "screenshot.png", "rationale": "Contextual review.",
                   "suggestion": "Review treatment.", "confidence": "high"}
        for mode in ("source", "visual"):
            raw = {"status": "completed", "mode": mode, "model": "fixture-model",
                   "non_deterministic": True, "findings": [finding]}
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "applicable|unknown guideline_id"):
                validate_review(raw, mode=mode, source_root=self.root,
                                guideline_manifest=snapshot, screenshots=["screenshot.png"])
        policy = self.rule(design_system="any", check="unsupported-context-review")
        snapshot.write_text(json.dumps(load_guidelines(self.root, [policy], "mui")))
        raw["mode"] = "source"
        self.assertEqual(len(validate_review(raw, mode="source", source_root=self.root,
                                            guideline_manifest=snapshot)["findings"]), 1)

    def test_legacy_frozen_manifest_replays_raw_ids_without_live_sources(self):
        policy = self.rule()
        legacy = load_guidelines(self.root, [policy])
        legacy["schema_version"] = "1.0.0"
        for document in legacy["documents"]:
            document["id"] = document.pop("original_id")
            document.pop("namespace")
        for source in legacy["sources"]:
            source.pop("namespace")
            source["document_ids"] = [identity.split(":", 1)[1] for identity in source["document_ids"]]
        # The 1.0 producer emitted repeated membership when identical rules
        # appeared twice in one directory. Replay must accept those snapshots.
        duplicate = self.root / "rules/duplicate.md"
        legacy["documents"][0]["sources"].append(str(duplicate))
        legacy["sources"][0]["location"] = str(policy.parent)
        legacy["sources"][0]["document_ids"].append("team-policy")
        legacy["version"] = "sha256:" + hashlib.sha256(json.dumps(sorted((d["id"], d["sha256"]) for d in legacy["documents"])).encode()).hexdigest()
        policy.unlink()
        self.assertEqual(validate_manifest(legacy), legacy)
        assert_schema(self, legacy, json.loads((SKILL / "schemas/v1/guideline-manifest.schema.json").read_text()))
        path = self.root / "legacy.json"
        path.write_text(json.dumps(legacy))
        replay = self.analyze("--guideline-manifest", path, expected=1)
        self.assertEqual(replay["coverage"]["evaluated_rules"], ["team-policy"])

    def test_url_and_invalid_local_source_inputs_fail_closed(self):
        for value in ["https://example.test/rules", "team=https://example.test/rules", "bad:name=rules", "empty=", "missing"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_guidelines(self.root, [value])
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, "no usable Markdown"):
            load_guidelines(self.root, [empty])
        for identity in ["bad:id", "../escape", "with spaces"]:
            with self.subTest(identity=identity):
                policy = self.rule(id=identity)
                with self.assertRaisesRegex(ValueError, "invalid guideline ID"):
                    load_guidelines(self.root, [policy])

    def test_source_filters_require_exact_qualified_id_and_do_not_count_prose(self):
        first = self.rule("rules/policy.md")
        self.rule("rules/prose.md", id="prose", check="unsupported")
        report = self.analyze("--guidelines", first.parent, "--guideline", "local:team-policy", expected=1)
        self.assertEqual(report["coverage"], {"evaluated_rules": ["local:team-policy"], "unevaluated_rules": []})
        self.assertEqual(len(report["guideline_context"]["documents"]), 2)
        self.assertEqual(report["source_mode"]["violations"][0]["guideline_id"], "local:team-policy")

    def test_only_selected_system_or_any_rules_are_evaluated(self):
        self.rule("rules/mui.md", id="mui", design_system="mui")
        self.rule("rules/any.md", id="any", design_system="any")
        report = self.analyze("--design-system", "carbon", "--guidelines", "rules", expected=1)
        self.assertEqual(report["coverage"], {"evaluated_rules": ["local:any"], "unevaluated_rules": ["local:mui"]})

    def test_invalid_metadata_is_rejected_before_a_manifest_can_be_published(self):
        with self.assertRaises(ValueError):
            load_guidelines(self.root, design_system="")
        for field in ["title", "category", "version", "design_system"]:
            policy = self.rule(**{field: ""})
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_guidelines(self.root, [policy])

    def test_frozen_text_preserves_utf8_bom_and_crlf_without_changing_identity(self):
        policy = self.rule()
        original = b"\xef\xbb\xbf" + policy.read_bytes().replace(b"\n", b"\r\n")
        policy.write_bytes(original)
        manifest = load_guidelines(self.root, [policy])
        document, = manifest["documents"]
        self.assertEqual(document["text"].encode("utf-8"), original)
        self.assertEqual(document["original_id"], "team-policy")
        self.assertEqual(document["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(validate_manifest(manifest), manifest)

    def test_ambiguous_frontmatter_cannot_promote_execution_metadata(self):
        policy = self.root / "nested.md"
        for header in ["id: nested\nextra:\n  check: no-custom-css\n  severity: error",
                       "id: duplicate\ncheck: unsupported\ncheck: no-custom-css"]:
            policy.write_text("---\n" + header + "\n---\n\n## Rule\nInert prose.\n")
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, "scalar|duplicate"):
                load_guidelines(self.root, [policy])

    def test_custom_css_policy_has_no_implicit_patternfly_asset_exemption(self):
        for label in ("custom", "patternfly"):
            policy = self.rule(check="no-custom-css", design_system=label)
            (self.root / "index.html").write_text('<html><link rel="stylesheet" href="patternfly-custom.css">\n<link rel="stylesheet" href="uxd-prototype-bar.css"></html>\n')
            report = self.analyze("--design-system", label, "--guidelines", policy, expected=1)
            self.assertEqual(len(report["source_mode"]["violations"]), 2)
            self.assertEqual({item["guideline_id"] for item in report["source_mode"]["violations"]}, {"local:team-policy"})

    def test_no_custom_css_detects_case_insensitive_html_and_unquoted_rel(self):
        policy = self.rule(check="no-custom-css")
        cases = [
            ('<html STYLE="color: red">\n', 1),
            ('<STYLE>body { color: red }</STYLE>\n', 1),
            ('<link rel=stylesheet href="custom.css">\n', 1),
        ]
        for markup, expected_line in cases:
            with self.subTest(markup=markup):
                (self.root / "index.html").write_text(markup)
                report = self.analyze("--guidelines", f"product={policy}", expected=1)
                finding, = report["source_mode"]["violations"]
                self.assertEqual(finding["file"], "index.html")
                self.assertEqual(finding["line"], expected_line)

    def test_removed_checks_are_unevaluated_on_import_and_both_replay_versions(self):
        (self.root / "index.html").write_text('<html><button style="color: #fff">Save</button></html>\n')
        for check in ("patternfly-component-usage", "css-token-usage"):
            with self.subTest(check=check):
                policy = self.rule(check=check, id=check, design_system="patternfly")
                report = self.analyze("--design-system", "patternfly", "--guidelines", policy)
                self.assertEqual(report["coverage"], {"evaluated_rules": [], "unevaluated_rules": ["local:" + check]})
                self.assertEqual(report["source_mode"]["violations"], [])
                manifest = json.loads((self.root / report["guideline_manifest"]).read_text())
                policy.unlink()
                self.assertEqual(self.analyze("--guideline-manifest", self.root / report["guideline_manifest"])["coverage"], report["coverage"])
                manifest["schema_version"] = "1.0.0"
                doc = manifest["documents"][0]
                doc["id"] = doc.pop("original_id")
                doc.pop("namespace")
                manifest["sources"][0].pop("namespace")
                manifest["sources"][0]["document_ids"] = [check]
                manifest["version"] = "sha256:" + hashlib.sha256(json.dumps([(check, doc["sha256"])]).encode()).hexdigest()
                legacy_path = self.root / "legacy.json"
                legacy_path.write_text(json.dumps(manifest))
                replay = self.analyze("--guideline-manifest", legacy_path)
                self.assertEqual(replay["coverage"], {"evaluated_rules": [], "unevaluated_rules": [check]})
                self.assertEqual(replay["summary"]["passes"], 0)

    def test_root_class_coverage_requires_html_targets_not_stylesheets(self):
        (self.root / "index.html").unlink()
        (self.root / "styles.css").write_text('.example { margin: 0; }\n')
        report = self.analyze("--guidelines", self.rule())
        self.assertEqual(report["coverage"], {"evaluated_rules": [], "unevaluated_rules": ["local:team-policy"]})
        self.assertEqual(report["summary"]["passes"], 0)

    def test_target_extension_case_does_not_turn_a_policy_failure_into_a_pass(self):
        policy = self.rule()
        (self.root / "index.html").rename(self.root / "index.HTML")
        report = self.analyze("--guidelines", policy, expected=1)
        self.assertEqual(report["source_mode"]["violations"][0]["file"], "index.HTML")
        (self.root / "index.HTML").unlink()
        (self.root / "styles.CSS").write_text('.example { margin: 0; }\n')
        policy = self.rule(check="no-custom-css")
        report = self.analyze("--guidelines", policy, expected=1)
        self.assertIsNone(report["source_mode"]["violations"][0]["line"])

    def test_no_policy_does_not_audit_peers_even_with_patternfly_label(self):
        (self.root / "index.html").write_text('<html><button class="primary">Save</button>\n<button class="secondary">Save</button></html>\n')
        report = self.analyze("--design-system", "patternfly")
        self.assertEqual(report["internal_consistency"], {
            "status": "not_evaluated", "reason": "Peer audits are outside selected product-guideline scope.",
            "comparisons": [], "findings": [], "uncompared_targets": []})
        self.assertEqual(report["coverage"], {"evaluated_rules": [], "unevaluated_rules": []})
        self.assertEqual(report["summary"]["passes"], 0)

    def test_imported_baseline_kind_cannot_run_neutral_policy(self):
        manifest = load_guidelines(self.root, [self.rule()])
        manifest["documents"][0]["kind"] = "baseline"
        manifest["sources"][0]["kind"] = "baseline"
        manifest["version"] = manifest_version(manifest)
        path = self.root / "baseline.json"
        path.write_text(json.dumps(manifest))
        report = self.analyze("--guideline-manifest", path)
        self.assertEqual(report["coverage"], {"evaluated_rules": [], "unevaluated_rules": ["local:team-policy"]})
        self.assertEqual(report["guideline_consistency"]["baseline"], {
            "status": "not_evaluated", "selected_rules": [], "evaluated_rules": []})

    def test_unscoped_internal_supplement_is_rejected(self):
        raw = {"status": "completed", "mode": "internal", "model": "fixture-model",
               "non_deterministic": True, "findings": []}
        with self.assertRaisesRegex(ValueError, "mode"):
            validate_review(raw, mode="internal", source_root=self.root)

    def test_source_and_artifact_paths_fail_closed(self):
        policy = self.rule()
        link = self.root / "linked.md"
        link.symlink_to(policy)
        for value in (link, "rules/../rules/policy.md"):
            with self.subTest(value=str(value)), self.assertRaisesRegex(ValueError, "traversal|symlink"):
                local_path(value, self.root)
        with self.assertRaisesRegex(ValueError, "artifacts"):
            output_path("report.json", self.root)
        with self.assertRaisesRegex(ValueError, "replace"):
            protect_inputs(policy, [str(policy)])

    def test_changed_scope_keeps_only_changed_product_policy_evidence(self):
        def git(*args):
            result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        git("init", "-q")
        git("add", "index.html")
        git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Fixture")
        (self.root / "index.html").write_text('<html><button>Save</button></html>\n<div style="color: red">Changed</div>\n')
        policy = self.rule(check="no-custom-css")
        report = self.analyze("--guidelines", policy, "--changed", "--base-ref", "HEAD", expected=1)
        self.assertEqual([item["line"] for item in report["source_mode"]["violations"]], [2])
        self.assertEqual(report["inputs"]["scope"], "changed")
        committed = self.analyze("--guidelines", policy, "--changed", "--merge-base", "--base-ref", "HEAD")
        self.assertEqual(committed["coverage"]["evaluated_rules"], [])
        self.assertEqual(committed["summary"]["passes"], 0)

    def test_product_prose_can_mention_patternfly_without_gaining_a_check(self):
        policy = self.rule(check="product-context-review", id="patternfly-component-usage")
        text = policy.read_text() + "Compose using PatternFly when the product owner selects it.\n"
        policy.write_text(text)
        report = self.analyze("--guidelines", f"product={policy}")
        snapshot = json.loads((self.root / report["guideline_manifest"]).read_text())
        self.assertEqual(snapshot["documents"][0]["text"], text)
        self.assertEqual(report["coverage"], {"evaluated_rules": [], "unevaluated_rules": ["product:patternfly-component-usage"]})

    def test_schema_rejects_active_compatibility_groups(self):
        report = self.analyze()
        schema = json.loads((SKILL / "schemas/v1/consistency-report.schema.json").read_text())
        for mutate in (
            lambda r: r["guideline_consistency"]["baseline"].update(status="evaluated"),
            lambda r: r["guideline_consistency"]["baseline"].update(selected_rules=["old:rule"]),
            lambda r: r["internal_consistency"].update(status="evaluated"),
            lambda r: r["internal_consistency"].update(findings=[{"description": "out of scope"}]),
        ):
            changed = copy.deepcopy(report)
            mutate(changed)
            with self.assertRaises(AssertionError):
                assert_schema(self, changed, schema)

    def test_no_implicit_baseline_or_workspace_discovery(self):
        self.rule(".design/product-design/guidelines/policy.md")
        report = self.analyze()
        self.assertEqual(report["guideline_context"]["documents"], [])
        self.assertEqual(report["coverage"]["evaluated_rules"], [])
        self.assertEqual(report["guideline_consistency"]["status"], "not_evaluated")
        self.assertEqual(report["summary"]["passes"], 0)


if __name__ == "__main__":
    unittest.main()
