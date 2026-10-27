"""Offline evaluator regressions; all runtime writes stay in TMPDIR."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
CHECKER = SKILL.parent / "uxd-consistency-check"


class ConsistencyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eval-consistency-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / "skills" / SKILL.name
        for name in ("scripts", "config", "templates"):
            shutil.copytree(SKILL / name, self.skill / name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.artifacts = self.project / ".artifacts" / "PROJ-1" / "eval"
        shutil.copytree(SKILL / "tests/fixtures/minimal/report", self.artifacts)
        self.env = dict(os.environ, HOME=str(self.home), UXD_PROJECT_ROOT=str(self.project),
                        PYTHONDONTWRITEBYTECODE="1",
                        EVAL_OVERLAY_PATH=str(self.root / "overlay.yaml"))
        for key in ("UXD_OVERLAY_PATH", "UXD_INTERNAL_HELPERS", "USABILITY_TESTING_REPO"):
            self.env.pop(key, None)

    def run_command(self, *args, success=True):
        result = subprocess.run(args, cwd=self.project, env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def node(self, script, *args, **kwargs):
        return self.run_command("node", str(self.skill / "scripts" / script), *map(str, args), **kwargs)

    def write_report(self, report):
        (self.artifacts / "consistency-report.json").write_text(json.dumps(report))

    def render(self):
        self.node("render-report.js", self.artifacts)
        return (self.artifacts / "evaluation-report.html").read_text()

    def assert_repair_message(self, text):
        self.assertIn("Install or restore", text)
        self.assertIn("uxd-consistency-check", text)
        self.assertIn("SKILL.md", text)
        self.assertIn("scripts/analyze.py", text)
        self.assertIn("rerun evaluation", text)
        for stale in ("CONSISTENCY_CHECKER_REPO", "context_repos.consistency_checker",
                      ".context/consistency-checker", "pf-css-token-check"):
            self.assertNotIn(stale, text)

    def selected_receipt(self, *, remote=False, prose=False):
        # Approval identities below are synthetic fixture events, not live user consent.
        import sys
        sys.path.insert(0, str(CHECKER / 'scripts'))
        from guideline_selection import propose_selection, confirm_selection
        from guideline_staging import propose_staging, confirm_staging
        index = self.project / '.design/guidelines/README.md'
        index.parent.mkdir(parents=True)
        index.write_text('# Product index\n')
        rule = index.parent / 'rule.md'
        rule.write_text('---\nid: root\ntitle: Product root theme\ncheck: ' +
                        ('manual-product-review' if prose else 'required-html-class') +
                        '\nrequired_class: product-theme\nseverity: error\n---\nProduct rule.\n')
        evidence = index.parent / 'drawing.txt'
        evidence.write_text('Product visual evidence, not executable policy.\n')
        source = dict(id='product', rule_ids=['root'], title='Product rules', topic='root',
                      scope='settings', owner=None, authority=None, policy_status='approved',
                      locator={'kind': 'local', 'path': 'rule.md'}, examples=[], assets=[])
        manual = {**source, 'id': 'drawing', 'rule_ids': [],
                  'locator': {'kind': 'local', 'path': 'drawing.txt'}}
        if remote:
            manual['locator'] = {'kind': 'web', 'url': 'https://example.test/drawing', 'section': None}
        index.with_name('sources.json').write_text(json.dumps(dict(
            schema_version='1.0.0', product='Fixture product', release='1', sources=[source, manual])))
        scope = self.project / 'src/settings'
        scope.mkdir(parents=True)
        (scope / 'index.html').write_text('<html><body>Missing product theme</body></html>')
        (self.project / 'index.html').write_text('<html><body>Outside approved scope</body></html>')
        proposal = propose_selection(self.project, index, source_ids=['product', 'drawing'],
                                     review_scope='src/settings', method='deterministic')
        selection = confirm_selection(self.project, proposal, {
            'kind': 'explicit_instruction', 'reference': 'fixture:task-1',
            'quote': 'Use product and drawing for deterministic review of src/settings.',
            'proposal_sha256': proposal['sha256']})
        receipt = confirm_staging(self.project, propose_staging(self.project, selection))
        shutil.copytree(CHECKER, self.skill.parent / CHECKER.name)
        return receipt, rule, evidence

    def consume_selection(self, receipt, *scope_args, **kwargs):
        return self.run_command('python3', '-S', str(self.skill / 'scripts/run-consistency-selection.py'),
                                '--workspace', str(self.project), '--staging-receipt', receipt['receipt_path'],
                                '--artifacts-dir', str(self.artifacts), *scope_args, **kwargs)

    def test_selection_report_publication_is_confined_and_can_replace_prior_json(self):
        import importlib.util
        from unittest.mock import patch
        self.selected_receipt()
        spec = importlib.util.spec_from_file_location(
            'selection_consumer', self.skill / 'scripts/run-consistency-selection.py')
        assert spec is not None and spec.loader is not None
        consumer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consumer)
        writer = getattr(consumer, 'write_consumer_json', None)
        self.assertTrue(callable(writer), 'selection output needs descriptor-confined atomic publication')
        assert callable(writer)
        destination = self.artifacts / 'consistency-selection.json'
        writer(self.project, destination, {'currentness': 'unknown'})
        writer(self.project, destination, {'currentness': 'local_bytes_revalidated'})
        self.assertEqual(json.loads(destination.read_text()), {'currentness': 'local_bytes_revalidated'})
        outside = self.root / 'outside-output'
        outside.mkdir()
        saved = self.artifacts.with_name('eval-saved')
        real_open = os.open
        swapped = False

        def replace_parent(path, flags, *args, **kwargs):
            nonlocal swapped
            if str(path) == self.artifacts.name and not swapped:
                swapped = True
                self.artifacts.rename(saved)
                self.artifacts.symlink_to(outside, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)

        try:
            with patch('os.open', replace_parent), self.assertRaises((OSError, ValueError)):
                writer(self.project, destination, {'must_not_write': True})
            self.assertTrue(swapped)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            if swapped:
                self.artifacts.unlink()
                saved.rename(self.artifacts)

    def test_llm_report_renders_rule_and_changed_code_links_separately(self):
        guideline = self.project / "docs/product-rule.md"
        guideline.parent.mkdir(parents=True)
        guideline.write_text("## Styling\nUse the selected product token.\n")
        code = self.project / "src/app.js"
        code.parent.mkdir(parents=True)
        code.write_text("const color = 'custom';\n")
        (self.artifacts / "llm-consistency-report.json").write_text(json.dumps({
            "schema_version": "1.0.0", "report_type": "product_guideline_llm_review", "method": "llm",
            "model": "fixture-model", "guideline_ref": "git:fixture", "workspace": str(self.project),
            "coverage": {"statuses": {"violation": 1, "no_issue_found": 0, "uncertain": 0,
                "unsupported": 0, "unavailable": 0, "not_applicable": 0}},
            "reviews": [{"guideline_id": "product:style", "status": "violation", "confidence": "medium",
                "guideline": {"path": "docs/product-rule.md", "heading": "Styling", "anchor": "styling",
                    "ref": "git:fixture", "sha256": "a" * 64, "quote": "Use the selected product token."},
                "source_evidence": {"file": "src/app.js", "line_start": 1, "line_end": 1,
                    "excerpt": "const color = 'custom';"}, "rationale": "Fixture evidence.",
                "suggested_fix": "Use the selected token.", "limitations": []}]}))
        (self.artifacts / "fix-proposals.json").write_text(json.dumps({
            "artifact_type": "guideline_rooted_fix_proposals", "proposals": [{"finding_id": "finding-1"}]}))
        html = self.render()
        self.assertIn("LLM semantic review", html)
        self.assertIn("LLM “no issue found”", html)
        self.assertIn("not applied; human approval pending", html)
        self.assertIn("docs/product-rule.md#styling", html)
        self.assertIn("src/app.js#L1", html)
        self.assertIn("Use the selected product token.", html)
        self.assertIn('Legacy evidence:',html)

    def test_incomplete_jsx_scan_does_not_render_a_clean_pass(self):
        rule = self.project/'rule.md'
        rule.write_text('---\nid: styling\ncheck: no-custom-css\nseverity: error\n---\n## Rule\nAvoid inline styles.\n')
        target = self.project/'view.tsx'
        target.write_text('<Button {...unknownProps} />\n')
        self.run_command('python3','-S',str(CHECKER/'scripts/analyze.py'),'--workspace',str(self.project),
            '--guidelines',str(rule),'--json-file',str(self.artifacts/'consistency-report.json'))
        report = json.loads((self.artifacts/'consistency-report.json').read_text())
        self.assertEqual(report['summary']['passes'],0)
        self.assertEqual(report['coverage']['incomplete_rules']['local:styling']['files'],['view.tsx'])
        html = self.render()
        self.assertIn('Incomplete deterministic coverage',html)
        self.assertIn('not a deterministic pass',html)

    def test_fix_handoff_append_preserves_other_phases_and_deduplicates_by_finding(self):
        script = self.skill / "scripts/append-consistency-fix-proposals.py"
        shutil.copytree(CHECKER, self.skill.parent / CHECKER.name)
        handoff_path = self.artifacts / "fix-proposals.json"
        report_path = self.artifacts / "llm-consistency-report.json"
        suggestions_path = self.artifacts / "refinement-suggestions.json"
        initial = [{"type": "usability", "criterion_id": "US-1", "fix": "Keep this"}]
        suggestions_path.write_text(json.dumps(initial))
        guideline = {"path": "docs/rule.md", "heading": "Rule", "anchor": "rule",
            "href": "docs/rule.md#rule", "quote": "Use the rule.", "sha256": "a" * 64, "ref": None,
            'ref_status':'unverifiable_legacy_ref', 'selected_scope':{'kind':'section','anchor':'rule'}}
        evidence = {"file": "src/app.js", "line_start": 2, "line_end": 2, "excerpt": "bad();",
            "href": "src/app.js#L2-L2", "sha256": "b" * 64, 'evidence_type':'source_excerpt','column_start':1}
        proposal = {"finding_id": "finding-abc", "guideline_id": "product:rule", "status": "violation",
            "severity": "warning", "confidence": "medium", "guideline": guideline,
            "source_evidence": evidence, "proposed_change": "Use the rule.",
            "why_it_satisfies_rule": "It follows the cited guidance.", "side_effects_or_unknowns": "Check callers.",
            "smallest_safe_file_scope": ["src/app.js"], "test_suggestion": "Add a focused test.",
            "acceptance_condition": "The cited rule is met.", "applied": False,
            "approval_state": "pending_human_approval"}
        approved_scope = {'kind':'code_paths','directories':['src'],'files':[]}
        handoff = {"schema_version": "1.1.0", "artifact_type": "guideline_rooted_fix_proposals",
            'approved_scope':approved_scope, 'selection_sha256':'c'*64,
            "guideline_ref": None, "applied": False, "approval_state": "pending_human_approval",
            "proposals": [proposal]}
        handoff_path.write_text(json.dumps(handoff))
        report_path.write_text(json.dumps({"schema_version": "1.1.0", "report_type": "product_guideline_llm_review",
            'approved_scope':approved_scope, 'selection_sha256':'c'*64,
            "method": "llm", "guideline_ref": None, "reviews": [{"finding_id": "finding-abc",
                "guideline_id": "product:rule", "status": "violation", "guideline": guideline,
                'severity':'warning','confidence':'medium','applicability':{'outcome':'applicable'},
                "source_evidence": evidence, "suggested_fix": "Use the rule."}]}))
        result = self.run_command("python3", str(script), "--workspace", str(self.project),
            "--handoff", str(handoff_path), "--llm-report", str(report_path), "--suggestions", str(suggestions_path))
        self.assertEqual(json.loads(result.stdout)["appended"], 1)
        appended = json.loads(suggestions_path.read_text())
        self.assertEqual(appended[0], initial[0])
        self.assertEqual(appended[1]["guideline"], guideline)
        self.assertEqual(appended[1]["source_evidence"], evidence)
        self.assertFalse(appended[1]["applied"])
        self.assertEqual(json.loads(self.run_command("python3", str(script), "--workspace", str(self.project),
            "--handoff", str(handoff_path), "--llm-report", str(report_path),
            "--suggestions", str(suggestions_path)).stdout)["appended"], 0)
        before = suggestions_path.read_bytes()
        handoff["proposals"][0]["guideline"] = {**guideline, "quote": "Different rule."}
        handoff_path.write_text(json.dumps(handoff))
        result = self.run_command("python3", str(script), "--workspace", str(self.project),
            "--handoff", str(handoff_path), "--llm-report", str(report_path),
            "--suggestions", str(suggestions_path), success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(suggestions_path.read_bytes(), before)

    def test_changed_selection_consumption_excludes_unchanged_violations(self):
        receipt, _, _ = self.selected_receipt()
        scope = self.project / 'src/settings'
        changed = scope / 'changed.html'
        changed.write_text('<html class="product-theme"><body>Before</body></html>\n')
        # Git writes are confined to this owned disposable consumer fixture.
        self.run_command('git', 'init', '-q')
        self.run_command('git', 'add', 'src/settings')
        self.run_command('git', '-c', 'user.name=Offline Test', '-c', 'user.email=test@example.invalid',
                         'commit', '-qm', 'Fixture base')
        base = self.run_command('git', 'rev-parse', 'HEAD').stdout.strip()
        changed.write_text('<html class="product-theme"><body>After</body></html>\n')
        self.run_command('git', 'add', 'src/settings/changed.html')
        self.run_command('git', '-c', 'user.name=Offline Test', '-c', 'user.email=test@example.invalid',
                         'commit', '-qm', 'Fixture change')
        for extra, expected_scope in (([], 'changed'), (['--tracked-only'], 'changed'),
                                      (['--merge-base'], 'committed')):
            with self.subTest(extra=extra):
                self.consume_selection(receipt, '--changed', '--base-ref', base, *extra)
                report = json.loads((self.artifacts / 'consistency-report.json').read_text())
                self.assertEqual(report['workspace'], str(scope))
                self.assertEqual(report['source_mode']['violations'], [])
                self.assertEqual(report['inputs']['scope'], expected_scope)
                self.assertEqual(report['inputs']['base'], base)
                self.assertEqual(report['inputs']['target_files'], ['changed.html'])

    def test_selection_consumer_rejects_incomplete_changed_scope_options(self):
        receipt, _, _ = self.selected_receipt()
        before = (self.artifacts / 'consistency-report.json').read_bytes()
        cases = [(['--changed'], '--changed requires an explicit --base-ref'),
                 (['--base-ref', 'HEAD'], '--base-ref requires --changed'),
                 (['--merge-base'], '--merge-base requires --changed'),
                 (['--tracked-only'], '--tracked-only requires --changed')]
        for options, diagnostic in cases:
            with self.subTest(options=options):
                result = self.consume_selection(receipt, *options, success=False)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual((self.artifacts / 'consistency-report.json').read_bytes(), before)
                self.assertFalse((self.artifacts / 'consistency-selection.json').exists())

    def test_receipt_replacement_at_open_cannot_follow_file_or_ancestor_symlinks(self):
        receipt, _, _ = self.selected_receipt()
        for replacement in ('file', 'ancestor'):
            with self.subTest(replacement=replacement):
                self.assert_receipt_replacement_rejected(receipt, replacement)

    def test_receipt_fifo_replacement_at_open_fails_without_blocking(self):
        receipt, _, _ = self.selected_receipt()
        self.assert_receipt_replacement_rejected(receipt, 'fifo')

    def assert_receipt_replacement_rejected(self, receipt, replacement):
        # Both the consumer and the simulated outside target are owned scratch.
        outside = self.root / ('outside-' + replacement)
        outside.mkdir()
        path = Path(receipt['receipt_path'])
        outside_receipt = outside / path.name
        outside_receipt.write_bytes(path.read_bytes())
        before = (self.artifacts / 'consistency-report.json').read_bytes()
        script = r'''
import json, os, pathlib, runpy, sys
script, workspace, receipt, artifacts, outside, replacement = sys.argv[1:]
receipt, outside = pathlib.Path(receipt), pathlib.Path(outside)
target = receipt.parent if replacement == 'ancestor' else receipt
saved = target.with_name(target.name + '-saved')
outside_identity = (outside.stat().st_dev, outside.stat().st_ino)
path_open, fd_open = pathlib.Path.open, os.open
attacked, outside_reads = False, []
def swap():
    global attacked
    if not attacked:
        attacked = True
        target.rename(saved)
        if replacement == 'fifo':
            os.mkfifo(target)
        else:
            target.symlink_to(outside.parent if replacement == 'ancestor' else outside,
                              target_is_directory=replacement == 'ancestor')
def record(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == outside_identity:
        outside_reads.append(str(receipt))
def open_path(path, *args, **kwargs):
    if path == receipt:
        swap()
    stream = path_open(path, *args, **kwargs)
    record(stream.fileno())
    return stream
def open_fd(path, flags, *args, **kwargs):
    if str(path) == target.name:
        swap()
    fd = fd_open(path, flags, *args, **kwargs)
    record(fd)
    return fd
pathlib.Path.open, os.open = open_path, open_fd
sys.argv = [script, '--workspace', workspace, '--staging-receipt', str(receipt),
            '--artifacts-dir', artifacts]
try:
    try:
        runpy.run_path(script, run_name='__main__')
    except SystemExit as error:
        code = error.code
finally:
    pathlib.Path.open, os.open = path_open, fd_open
    if attacked:
        target.unlink()
        saved.rename(target)
print(json.dumps({'code': code, 'attacked': attacked, 'outside_reads': outside_reads}))
'''
        try:
            result = subprocess.run(
                ['python3', '-S', '-c', script, str(self.skill / 'scripts/run-consistency-selection.py'),
                 str(self.project), str(path), str(self.artifacts), str(outside_receipt), replacement],
                cwd=self.project, env=self.env, capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            self.fail('FIFO replacement blocked the receipt reader')
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.splitlines()[-1])
        self.assertTrue(observed['attacked'])
        self.assertEqual(observed['outside_reads'], [], 'outside receipt was opened')
        self.assertEqual(observed['code'], 2, result.stderr)
        self.assertIn('Consistency selection failed:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual((self.artifacts / 'consistency-report.json').read_bytes(), before)
        self.assertFalse((self.artifacts / 'consistency-selection.json').exists())

    def test_malformed_receipts_fail_cleanly_without_replacing_reports(self):
        receipt, _, _ = self.selected_receipt()
        path = Path(receipt['receipt_path'])
        original = path.read_bytes()
        before = (self.artifacts / 'consistency-report.json').read_bytes()
        cases = {
            'duplicate key': (b'{"schema_version":"ignored",' + original.lstrip()[1:],
                              'duplicate index JSON key'),
            'deep JSON': (b'{"nested":' + b'[' * 2000 + b']' * 2000 + b',' + original.lstrip()[1:],
                          'Consistency selection failed:'),
            'invalid UTF-8': (b'\xff', 'utf-8'),
            'UTF-16 without BOM': (original.decode('utf-8').encode('utf-16-le'), 'Consistency selection failed:'),
            'UTF-32 without BOM': (original.decode('utf-8').encode('utf-32-le'), 'Consistency selection failed:'),
            'invalid JSON': (b'{', 'Expecting property name'),
            'oversized': (b' ' * (4 * 1024 * 1024 + 1), 'staging receipt exceeds 4MiB'),
        }
        for name, (data, diagnostic) in cases.items():
            with self.subTest(name=name):
                (self.artifacts / 'consistency-report.json').write_bytes(before)
                (self.artifacts / 'consistency-selection.json').unlink(missing_ok=True)
                path.write_bytes(data)
                result = self.consume_selection(receipt, success=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Consistency selection failed:', result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual((self.artifacts / 'consistency-report.json').read_bytes(), before)
                self.assertFalse((self.artifacts / 'consistency-selection.json').exists())

    def test_receipt_consumption_preserves_narrow_scope_manual_evidence_and_frozen_links(self):
        receipt, rule, evidence = self.selected_receipt()
        result = self.consume_selection(receipt, success=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.artifacts / 'consistency-report.json').read_text())
        self.assertEqual(report['workspace'], str(self.project / 'src/settings'))
        self.assertEqual(report['coverage']['evaluated_rules'], ['product:root'])
        self.assertEqual(len(report['source_mode']['violations']), 1)
        self.node('validate-consistency.js', self.artifacts, '--json')
        sidecar = json.loads((self.artifacts / 'consistency-selection.json').read_text())
        self.assertEqual(sidecar['currentness'], 'local_bytes_revalidated')
        self.assertEqual(sidecar['manual_evidence'][0]['status'], 'unevaluated')
        self.assertTrue(sidecar['links'])
        rule.unlink()
        evidence.unlink()
        html = self.render()
        self.assertIn('Product root theme', html)
        self.assertIn('Selection currentness: local_bytes_revalidated', html)
        self.assertIn('Separate manual evidence', html)
        for link in sidecar['links']:
            self.assertIn(link['href'], html)
            self.assertTrue((self.artifacts / link['href']).is_file(), link)
        # The analyzer snapshot must replay even when original and staged inputs disappear.
        for argument in receipt['guidelines']:
            Path(argument.split('=', 1)[1]).unlink()
        manifest = self.project / 'src/settings' / report['guideline_manifest']
        replay = self.run_command('python3', '-S', str(CHECKER / 'scripts/analyze.py'),
                                  '--workspace', report['workspace'], '--guideline-manifest', str(manifest),
                                  '--json-file', str(self.project / 'src/settings/.artifacts/replay/report.json'),
                                  success=False)
        self.assertEqual(replay.returncode, 1, replay.stderr)
        replay_report = json.loads(replay.stdout)
        self.assertEqual(replay_report['source_mode'], report['source_mode'])
        self.write_report(replay_report)
        self.node('validate-consistency.js', self.artifacts, '--json')
        replay_html = self.render()
        self.assertIn('Product root theme', replay_html)
        for link in sidecar['links']:
            self.assertIn(link['href'], replay_html)
            self.assertTrue((self.artifacts / link['href']).is_file(), link)

    def test_unknown_remote_currentness_and_unavailable_evidence_remain_visible(self):
        receipt, _, _ = self.selected_receipt(remote=True)
        self.assertEqual(self.consume_selection(receipt, success=False).returncode, 1)
        sidecar = json.loads((self.artifacts / 'consistency-selection.json').read_text())
        self.assertEqual(sidecar['currentness'], 'unknown')
        self.assertEqual(sidecar['manual_evidence'][0]['status'], 'unavailable')
        html = self.render()
        self.assertIn('Selection currentness: unknown', html)
        self.assertIn('drawing: unavailable', html)
        self.assertIn('Model review requires separate authorization', html)
        self.node('validate-consistency.js', self.artifacts, '--json')

    def test_prose_only_selection_consumption_has_zero_passes(self):
        receipt, _, _ = self.selected_receipt(prose=True)
        self.consume_selection(receipt)
        report = json.loads((self.artifacts / 'consistency-report.json').read_text())
        self.assertEqual(report['summary']['total_guidelines_checked'], 0)
        self.assertEqual(report['summary']['passes'], 0)
        self.assertEqual(report['coverage']['unevaluated_rules'], ['product:root'])
        self.node('validate-consistency.js', self.artifacts, '--json')
        html = self.render()
        self.assertIn('No product guidelines were evaluated', html)
        self.assertIn('Separate manual evidence', html)

    def test_selection_consumer_rejects_changed_material_without_replacing_report(self):
        receipt, rule, _ = self.selected_receipt()
        before = (self.artifacts / 'consistency-report.json').read_bytes()
        rule.write_text(rule.read_text() + 'Changed product guidance.\n')
        result = self.consume_selection(receipt, success=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('confirmation required', result.stderr.lower())
        self.assertEqual((self.artifacts / 'consistency-report.json').read_bytes(), before)
        self.assertFalse((self.artifacts / 'consistency-selection.json').exists())

    def test_selection_consumer_reports_incomplete_selection_runtime_as_error(self):
        receipt, _, _ = self.selected_receipt()
        (self.skill.parent / CHECKER.name / 'scripts/guideline_staging.py').unlink()
        result = self.consume_selection(receipt, success=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('selection runtime', result.stderr)
        self.assertIn('Install or restore', result.stderr)
        self.assertFalse((self.artifacts / 'consistency-selection.json').exists())

    def test_skipped_report_renders_actionable_sibling_repair_not_pf_audit(self):
        self.write_report({"skipped": True, "reason": "Checker absent <unsafe>"})
        html = self.render()
        self.assert_repair_message(html)
        self.assertIn("Checker absent &lt;unsafe&gt;", html)
        for claim in ("PF Compliance", "Hardcoded color values vs", "Detected PatternFly Components"):
            self.assertNotIn(claim, html)

    def test_skipped_schema_diagnostic_explains_sibling_repair(self):
        self.write_report({"skipped": True, "reason": "Checker absent"})
        result = self.node("validate-artifact-schemas.js", self.artifacts, "--json", success=False)
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        diagnostic = next(row for row in data["results"] if row["scorer"] == "consistency was skipped")
        self.assertFalse(diagnostic["pass"])
        self.assert_repair_message(diagnostic["detail"])

    def test_missing_or_incomplete_sibling_has_no_pf_fallback(self):
        sibling = self.skill.parent / "uxd-consistency-check"
        for missing in ("both", "SKILL.md", "scripts/analyze.py"):
            with self.subTest(missing=missing):
                shutil.rmtree(sibling, ignore_errors=True)
                (sibling / "scripts").mkdir(parents=True)
                if missing != "both":
                    present = "scripts/analyze.py" if missing == "SKILL.md" else "SKILL.md"
                    (sibling / present).touch()
                result = self.run_command("bash", str(self.skill / "scripts/bootstrap-consistency-checker.sh"))
                self.assertIn("CONSISTENCY_AVAILABLE=false", result.stdout)
                self.assert_repair_message(result.stdout)
        self.assertFalse((self.project / ".context/consistency-checker").exists())

    def test_selected_product_report_and_frozen_replay_render_generic_source_links(self):
        (self.project / "index.html").write_text("<html><body>Product</body></html>\n")
        rule = self.project / "product-rule.md"
        rule.write_text("---\nid: root-theme\ntitle: Product root theme\nseverity: error\n"
                        "check: required-html-class\nrequired_class: product-theme\n"
                        "source_url: https://example.test/product/rule\n---\n"
                        "## Rule\nUse the selected product root class.\n")
        command = ("python3", "-S", str(CHECKER / "scripts/analyze.py"),
                   "--workspace", str(self.project), "--json-file",
                   str(self.artifacts / "consistency-report.json"))
        result = self.run_command(*command, "--guidelines", "product=" + str(rule), success=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["coverage"]["evaluated_rules"], ["product:root-theme"])
        self.node("validate-consistency.js", self.artifacts, "--json")
        html = self.render()
        self.assertTrue("Product root theme" in html)
        self.assertTrue("https://example.test/product/rule" in html)
        self.assertTrue("Guideline source" in html)
        self.assertFalse("PatternFly docs" in html)
        rule.unlink()
        replay = self.run_command(*command, "--guideline-manifest",
                                  str(self.project / report["guideline_manifest"]), success=False)
        self.assertEqual(replay.returncode, 1, replay.stderr)
        self.assertEqual(json.loads(replay.stdout)["source_mode"], report["source_mode"])
        self.node("validate-consistency.js", self.artifacts, "--json")
        self.assertTrue("Product root theme" in self.render())

    def test_no_selected_guidance_and_prose_only_rules_do_not_claim_passes(self):
        (self.project / "index.html").write_text("<html><body>Product</body></html>\n")
        rule = self.project / "prose.md"
        rule.write_text("---\nid: prose\ntitle: Product prose\ncheck: manual-product-review\n---\n"
                        "Product guidance requiring human review.\n")
        for selection in ([], ["--guidelines", "product=" + str(rule)]):
            with self.subTest(selection=selection):
                result = self.run_command("python3", "-S", str(CHECKER / "scripts/analyze.py"),
                                          "--workspace", str(self.project), "--json-file",
                                          str(self.artifacts / "consistency-report.json"), *selection)
                report = json.loads(result.stdout)
                self.assertEqual(report["summary"]["total_guidelines_checked"], 0)
                self.assertEqual(report["summary"]["passes"], 0)
                self.assertEqual(report["internal_consistency"]["status"], "not_evaluated")
                if selection:
                    self.assertEqual(report["coverage"]["unevaluated_rules"], ["product:prose"])
                html = self.render()
                self.assertTrue("No product guidelines were evaluated" in html)
                self.assertFalse("All 0" in html)

    def test_preflight_missing_sibling_warns_without_invoking_substitute_audit(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        npx = bin_dir / "npx"
        npx.write_text('#!/bin/sh\nprintf "Version offline-test\\n"\n')
        npx.chmod(0o755)
        self.env.update(PATH=str(bin_dir) + os.pathsep + self.env["PATH"], MCP_ATLASSIAN_AVAILABLE="true")
        result = self.run_command("bash", str(self.skill / "scripts/preflight-check.sh"))
        self.assertIn("[WARN] Local consistency checker unavailable", result.stdout)
        self.assertIn("restore sibling uxd-consistency-check", result.stdout)
        self.assertIn("scripts/analyze.py", result.stdout)
        self.assertNotIn("pf-css-token-check", result.stdout)

    def test_missing_report_uses_same_sibling_repair_message(self):
        (self.artifacts / "consistency-report.json").unlink()
        self.assert_repair_message(self.render())

    def test_available_sibling_requires_no_guideline_bundle_or_network(self):
        sibling = self.skill.parent / "uxd-consistency-check"
        (sibling / "scripts").mkdir(parents=True)
        (sibling / "SKILL.md").touch()
        (sibling / "scripts/analyze.py").touch()
        result = self.run_command("bash", str(self.skill / "scripts/bootstrap-consistency-checker.sh"))
        self.assertIn("CONSISTENCY_AVAILABLE=true", result.stdout)
        self.assertNotIn("fallback", result.stdout)
        self.assertFalse((self.project / ".context").exists())

    def test_overlay_removes_dead_checker_paths_but_keeps_usability_metadata(self):
        overlay = self.skill / "scripts/overlay-get.js"
        result = self.run_command("node", "-e", "const fs=require('fs'); "
                                  "const o=require(process.argv[1]); "
                                  "console.log(JSON.stringify(o.parseSimpleYaml(fs.readFileSync(process.argv[2],'utf8'))))",
                                  str(overlay), str(self.skill / "config/product-overlay.yaml"))
        data = json.loads(result.stdout)
        self.assertNotIn("consistency_checker", data["context_repos"])
        self.assertNotIn("design_system", data)
        self.assertIn("usability_testing", data["context_repos"])
        self.assertEqual(data["personas"]["context_path"], ".context/usability-testing/personas/")
        self.assertEqual(data["personas"]["rubric_path"], ".context/usability-testing/prompts/evaluate-flow.md")
        self.assertEqual(data["git"]["base_branch"], "main")
        self.assertEqual(data["jira"]["ticket_label"], "Ticket")

    def test_unconfigured_usability_still_uses_bundled_catalog(self):
        result = self.run_command("bash", str(self.skill / "scripts/bootstrap-usability-testing.sh"))
        self.assertIn("USABILITY_TESTING_REPO", result.stdout)
        self.assertIn("context_repos.usability_testing", result.stdout)
        self.assertIn("Phase B still uses the bundled persona catalog", result.stdout)
        self.assertFalse((self.project / ".context/usability-testing").exists())

    def test_configured_usability_bootstrap_retains_overlay_and_env_precedence(self):
        # Record git invocations without network, credentials, or fixture commits.
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        git = bin_dir / "git"
        git.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$GIT_CALL_LOG"\n')
        git.chmod(0o755)
        log = self.root / "git-calls"
        self.env.update(PATH=str(bin_dir) + os.pathsep + self.env["PATH"], GIT_CALL_LOG=str(log))
        (self.root / "overlay.yaml").write_text('context_repos:\n  usability_testing: "overlay-personas"\n')
        script = str(self.skill / "scripts/bootstrap-usability-testing.sh")
        self.run_command("bash", script)
        self.assertIn("clone --depth 1 --filter=blob:none --no-checkout overlay-personas", log.read_text())
        self.assertIn("sparse-checkout set personas prompts tools", log.read_text())
        self.env["USABILITY_TESTING_REPO"] = "env-personas"
        log.unlink()
        self.run_command("bash", script)
        self.assertIn("clone --depth 1 --filter=blob:none --no-checkout env-personas", log.read_text())
        self.assertNotIn("overlay-personas", log.read_text())


if __name__ == "__main__":
    unittest.main()
