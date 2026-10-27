"""Audit counterexamples: offline synthetic data, no model or provider traffic."""
import copy
import hashlib
import json
import subprocess
import sys
import unittest

import test_llm_review_contract as fixture
from guideline_sources import load_guidelines
from guideline_selection import propose_selection, confirm_selection
from guideline_snapshot import freeze_selected_readme_sources, bind_manifest_selection, validate_readme_snapshot
from llm_review_contract import validate_llm_review
from scoped_sources import read_sources
from analyze import evaluate


class AuditRegressions(unittest.TestCase):
    setUp = fixture.LLMReviewContractTests.setUp
    approved_selection = fixture.LLMReviewContractTests.approved_selection

    def sidecar_selection(self, guideline_scope=None):
        index = self.rule.parent / 'README.md'
        source = {'id': 'indexed-policy', 'rule_ids': [], 'title': 'Indexed policy',
            'topic': 'styling', 'scope': 'Product styling', 'owner': 'Product team',
            'authority': 'Product guidance', 'policy_status': 'approved',
            'locator': {'kind': 'local', 'path': self.rule.name}, 'examples': [], 'assets': []}
        index.with_name('sources.json').write_text(json.dumps({'schema_version': '1.0.0',
            'product': 'Fixture', 'release': None, 'sources': [source]}))
        proposal = propose_selection(self.root, index, source_ids=[source['id']],
            review_scope={'kind': 'code_paths', 'directories': ['.'], 'files': []},
            method='model', guideline_scopes={source['id']: guideline_scope or {'kind': 'whole_document'}})
        approval = {'kind': 'explicit_instruction', 'reference': 'fixture:sidecar',
            'quote': 'Review this selected local product document.', 'proposal_sha256': proposal['sha256']}
        return confirm_selection(self.root, proposal, approval, model_approval=approval)

    def test_sidecar_local_model_selection_freezes_and_reviews_authored_identity(self):
        selection = self.sidecar_selection()
        snapshot = freeze_selected_readme_sources(self.root, selection)['snapshot']
        doc, = snapshot['documents']
        self.assertEqual((doc['id'], doc['identity_kind'], doc['selection_id']),
                         ('custom-css', 'source_authored', 'indexed-policy'))
        self.assertEqual(doc['text'], self.rule.read_text())
        self.assertEqual(doc['sha256'], hashlib.sha256(self.rule.read_bytes()).hexdigest())
        self.assertEqual(doc['authority'], 'Product guidance')
        self.assertEqual(doc['policy_status'], 'approved')
        raw = copy.deepcopy(self.raw)
        raw['reviews'][0]['guideline_id'] = doc['id']
        report, handoff = validate_llm_review(raw, manifest=snapshot, workspace=self.root,
                                            scope_report=self.scope_report)
        self.assertEqual(report['reviews'][0]['guideline']['selected_scope'], {'kind': 'whole_document'})
        self.assertEqual(handoff['proposals'][0]['guideline_id'], 'custom-css')

    def test_sidecar_local_model_selection_preserves_path_identity_and_replay(self):
        self.rule.write_text('## Styling\nUse approved tokens in component styling.\n')
        selection = self.sidecar_selection()
        snapshot = freeze_selected_readme_sources(self.root, selection)['snapshot']
        doc, = snapshot['documents']
        self.assertEqual((doc['id'], doc['identity_kind']), ('rules/product-guideline.md', 'path_derived'))
        self.rule.unlink()
        self.assertEqual(validate_readme_snapshot(snapshot, self.root), snapshot)

    def test_sidecar_local_model_selection_resolves_sections_before_approval(self):
        selection = self.sidecar_selection({'kind': 'section', 'anchor': 'styling'})
        snapshot = freeze_selected_readme_sources(self.root, selection)['snapshot']
        self.assertEqual(snapshot['documents'][0]['section_bounds']['heading'], 'Styling')
        with self.assertRaisesRegex(ValueError, 'anchor is missing or invalid'):
            self.sidecar_selection({'kind': 'section', 'anchor': 'missing'})

    def carbon_selection(self):
        (self.root/'index.html').write_text('<html lang="en">\n<div>Changed</div>\n</html>\n')
        self.rule.write_text('---\nid: root-class\ndesign_system: carbon\n'
            'check: required-html-class\nrequired_class: carbon-theme\nseverity: error\n---\n'
            '## Styling\nUse the approved root class.\n')
        index = self.rule.parent / 'README.md'
        from guideline_resolver import read_index
        catalog = read_index(self.root, index)
        source, = read_index(self.root, index, topics=catalog['topics'])['sources']
        proposal = propose_selection(self.root, index, source_ids=[source['id']],
            review_scope={'kind': 'code_paths', 'directories': ['.'], 'files': []},
            method='model', design_system='carbon')
        approval = {'kind': 'explicit_instruction', 'reference': 'fixture:carbon',
            'quote': 'Review this Carbon product rule.', 'proposal_sha256': proposal['sha256']}
        return confirm_selection(self.root, proposal, approval, exceptions=[source['id']], model_approval=approval)

    def test_review_selection_adopts_approved_applicability_and_accepts_matching_override(self):
        selection = self.carbon_selection()
        for label in ([], ['--design-system', 'carbon']):
            with self.subTest(label=label):
                output = self.root / '.artifacts' / ('implicit.json' if not label else 'matching.json')
                result = subprocess.run([sys.executable, '-S', str(fixture.SKILL/'scripts/analyze.py'),
                    '--workspace', str(self.root), '--review-selection', selection['receipt_path'],
                    '--guidelines', str(self.rule), '--changed', '--base-ref', 'HEAD',
                    '--json-file', str(output), *label], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['design_system']['id'], 'carbon')
                self.assertEqual(report['coverage']['evaluated_rules'], ['local:root-class'])
                self.assertEqual(report['summary']['violations'], 1)

    def test_review_selection_rejects_conflicting_applicability_without_outputs(self):
        selection = self.carbon_selection()
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in (self.root/'.artifacts').rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, '-S', str(fixture.SKILL/'scripts/analyze.py'),
            '--workspace', str(self.root), '--review-selection', selection['receipt_path'],
            '--guidelines', str(self.rule), '--design-system', 'custom',
            '--json-file', str(self.root/'.artifacts/conflict/report.json')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('approved applicability', result.stderr)
        self.assertEqual(result.stdout, '')
        after = {p.relative_to(self.root): p.read_bytes()
                 for p in (self.root/'.artifacts').rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_review_selection_checks_frozen_manifest_applicability_without_originals(self):
        selection = self.carbon_selection()
        manifests = {label: load_guidelines(self.root, [str(self.rule)], label)
                     for label in ('carbon', 'custom')}
        self.rule.unlink()
        for label, manifest in manifests.items():
            with self.subTest(label=label):
                path = self.root / '.artifacts' / (label + '-manifest.json')
                path.write_text(json.dumps(manifest))
                output = self.root / '.artifacts' / (label + '-replay.json')
                result = subprocess.run([sys.executable, '-S', str(fixture.SKILL/'scripts/analyze.py'),
                    '--workspace', str(self.root), '--review-selection', selection['receipt_path'],
                    '--guideline-manifest', str(path), '--changed', '--base-ref', 'HEAD',
                    '--json-file', str(output)], capture_output=True, text=True)
                if label == 'carbon':
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['design_system']['id'], 'carbon')
                else:
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('manifest design system does not match', result.stderr)
                    self.assertFalse(output.exists())

    def run_review_selection_analysis(self, output):
        return subprocess.run([sys.executable, '-S', str(fixture.SKILL/'scripts/analyze.py'),
            '--workspace', str(self.root), '--review-selection', self.selection['receipt_path'],
            '--changed', '--base-ref', 'HEAD', '--json-file', str(output)], capture_output=True, text=True)

    def test_review_selection_direct_output_alias_is_rejected(self):
        result = self.run_review_selection_analysis(self.selection['receipt_path'])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('output cannot replace', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_review_selection_hard_link_output_alias_is_rejected(self):
        receipt = self.root / self.selection['receipt_path']
        alias = self.root/'.artifacts/receipt-alias.json'
        alias.hardlink_to(receipt)
        self.assertTrue(alias.samefile(receipt))
        result = self.run_review_selection_analysis(alias)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('output cannot replace', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_review_selection_rejection_preserves_bytes_and_publishes_no_partial_outputs(self):
        receipt = self.root / self.selection['receipt_path']
        alias = self.root/'.artifacts/receipt-alias.json'
        alias.hardlink_to(receipt)
        original = receipt.read_bytes()
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for path in (self.root/'.artifacts').rglob('*') if path.is_file()}
        # Run both attempts even if a broken analyzer corrupts the direct receipt.
        for output in (alias, receipt):
            with self.subTest(output=output.name):
                self.run_review_selection_analysis(output)
                self.assertEqual(receipt.read_bytes(), original)
                self.assertEqual(alias.read_bytes(), original)
                after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                         for path in (self.root/'.artifacts').rglob('*') if path.is_file()}
                self.assertEqual(after, before, 'rejection must not publish a report, guideline snapshot, or temporary file')

    def test_review_selection_distinct_output_succeeds_without_changing_receipt(self):
        receipt = self.root / self.selection['receipt_path']
        original = receipt.read_bytes()
        before = {path.relative_to(self.root) for path in (self.root/'.artifacts').rglob('*') if path.is_file()}
        output = self.root/'.artifacts/distinct/report.json'
        result = self.run_review_selection_analysis(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(json.loads(result.stdout), report)
        snapshot = self.root/report['guideline_manifest']
        self.assertTrue(snapshot.is_file())
        self.assertEqual(receipt.read_bytes(), original)
        after = {path.relative_to(self.root) for path in (self.root/'.artifacts').rglob('*') if path.is_file()}
        self.assertEqual(after-before, {output.relative_to(self.root), snapshot.relative_to(self.root)})

    def snapshot(self, scope="src/settings", anchor="selected-section", whole=False):
        index = self.root / '.design/product/design-guidelines/README.md'
        index.parent.mkdir(parents=True, exist_ok=True)
        rule = index.parent / 'rule.md'
        rule.write_text('---\nid: policy\n---\n## Selected section\nSelected rule.\n## Unselected section\nUnselected rule.\n')
        link = 'rule.md' + ('#' + anchor if anchor is not None else '')
        index.write_text(f'---\nproduct: Fixture\n---\n# Guidelines\n[Policy]({link})\n')
        from guideline_resolver import read_index
        catalog = read_index(self.root, index)
        source, = read_index(self.root, index, topics=catalog['topics'])['sources']
        proposal = propose_selection(self.root, index, source_ids=[source['id']],
            review_scope={'kind':'code_paths', 'directories':[scope], 'files':[]}, method='model',
            guideline_scopes={source['id']:{'kind':'whole_document'}} if whole else None)
        approval = {'kind':'explicit_instruction', 'reference':'fixture:audit', 'quote':'Review only the selected scope and section.', 'proposal_sha256':proposal['sha256']}
        receipt = confirm_selection(self.root, proposal, approval, exceptions=[source['id']], model_approval=approval)
        snapshot = freeze_selected_readme_sources(self.root, receipt)['snapshot']
        raw = copy.deepcopy(self.raw)
        doc, = snapshot['documents']
        raw['guideline_ref'] = doc['provenance']['ref']
        review = raw['reviews'][0]
        review['guideline_id'] = doc['id']
        review['guideline'] = {'path':doc['path'], 'heading':'Selected section', 'quote':'Selected rule.', 'sha256':doc['sha256'], 'ref':doc['provenance']['ref']}
        return snapshot, raw

    def test_w1_code_rejects_changed_file_outside_approved_directory(self):
        snapshot, raw = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'outside approved code-path scope'):
            validate_llm_review(raw, manifest=snapshot, workspace=self.root, scope_report=self.scope_report)

    def test_w1_section_rejects_quote_from_unselected_section(self):
        snapshot, raw = self.snapshot(scope='.')
        raw['reviews'][0]['guideline'].update(heading='Unselected section', quote='Unselected rule.')
        with self.assertRaisesRegex(ValueError, 'heading is not present'):
            validate_llm_review(raw, manifest=snapshot, workspace=self.root, scope_report=self.scope_report)

    def test_w1_section_rejects_invalid_selected_anchor(self):
        with self.assertRaises(ValueError):
            self.snapshot(scope='.', anchor='missing-section')

    def test_w2_jsx_arrow_before_style_is_not_a_clean_pass(self):
        doc = {**self.manifest['documents'][0], 'check':'no-custom-css'}
        findings, _ = evaluate([doc], {'view.tsx':'<Button onClick={() => doThing()} style={{color: red}}>Hi</Button>'})
        self.assertEqual(len(findings), 1)

    def test_w3_padded_range_does_not_make_unchanged_excerpt_changed(self):
        raw = copy.deepcopy(self.raw)
        raw['reviews'][0]['source_evidence'].update(line_start=1, line_end=2, excerpt='<html>')
        with self.assertRaisesRegex(ValueError, 'excerpt location does not intersect'):
            validate_llm_review(raw, manifest=self.manifest, workspace=self.root, scope_report=self.scope_report)

    def test_w4_matching_fabricated_refs_are_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw['guideline_ref'] = raw['reviews'][0]['guideline']['ref'] = 'git:completely-wrong-ref'
        with self.assertRaisesRegex(ValueError, 'not established by frozen provenance'):
            validate_llm_review(raw, manifest=self.legacy_manifest, review_selection=self.selection,
                                workspace=self.root, scope_report=self.scope_report)

    def test_w5_manifest_inapplicable_rule_cannot_create_violation(self):
        self.rule.write_text(self.rule.read_text().replace('id: custom-css', 'id: custom-css\ndesign_system: carbon'))
        manifest = load_guidelines(self.root, [f'product={self.rule}'], 'custom')
        selection = self.approved_selection()
        raw = copy.deepcopy(self.raw)
        raw['reviews'][0]['guideline']['sha256'] = manifest['documents'][0]['sha256']
        with self.assertRaisesRegex(ValueError, 'trusted applicability'):
            validate_llm_review(raw, manifest=manifest, review_selection=selection, workspace=self.root, scope_report=self.scope_report)

    def test_original_crlf_bytes_are_hashed_without_normalization(self):
        data = b'<html>\r\n<div>CRLF</div>\r\n</html>\r\n'
        (self.root / 'index.html').write_bytes(data)
        _, _, inputs = read_sources(self.root, changed=True, base_ref='HEAD')
        self.assertEqual(inputs['files']['index.html'], hashlib.sha256(data).hexdigest())

    def test_narrow_scope_positive_and_boundary_matching(self):
        snapshot, raw = self.snapshot()
        target = self.root / 'src/settings/view.tsx'
        target.parent.mkdir(parents=True)
        target.write_text('const value = "changed";\n')
        _, _, inputs = read_sources(self.root, changed=True, base_ref='HEAD', approved_scope=snapshot['review_scope'])
        self.assertEqual(inputs['target_files'], ['src/settings/view.tsx'])
        raw['reviews'][0]['source_evidence'] = {'file':'src/settings/view.tsx', 'line_start':1,
            'line_end':1, 'excerpt':'const value = "changed";'}
        report, handoff = validate_llm_review(raw, manifest=snapshot, workspace=self.root,
            scope_report={'run_id':self.run_id, 'inputs':inputs})
        self.assertEqual(report['approved_scope'], snapshot['review_scope'])
        self.assertEqual(handoff['proposals'][0]['smallest_safe_file_scope'], ['src/settings/view.tsx'])
        from review_scope import in_code_scope, code_scope
        self.assertFalse(in_code_scope('src/settings-old/view.tsx', snapshot['review_scope']))
        for path in ('../src', '/tmp/src', 'src/../other', 'src//settings'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                code_scope({'kind':'code_paths','directories':[path],'files':[]}, self.root)
        (self.root / 'linked').symlink_to(target.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            code_scope({'kind':'code_paths','directories':['linked'],'files':[]}, self.root)

    def test_repeated_excerpt_requires_narrow_unambiguous_changed_occurrence(self):
        target = self.root / 'index.html'
        target.write_text('<html>\nrepeat\nrepeat\n</html>\n')
        subprocess.run(['git','-C',str(self.root),'add','index.html'], check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','repeated base'], check=True)
        target.write_text('<html>\nrepeat\nchanged\nrepeat\n</html>\n')
        _, _, inputs = read_sources(self.root, changed=True, base_ref='HEAD', approved_scope=self.manifest['review_scope'])
        scope = {'run_id':self.run_id,'inputs':inputs}
        raw = copy.deepcopy(self.raw)
        evidence = raw['reviews'][0]['source_evidence']
        evidence.update(line_start=1, line_end=5, excerpt='repeat')
        with self.assertRaisesRegex(ValueError, 'ambiguous repeated'):
            validate_llm_review(raw, manifest=self.manifest, workspace=self.root, scope_report=scope)
        evidence.update(line_start=2,line_end=2)
        with self.assertRaisesRegex(ValueError, 'changed line'):
            validate_llm_review(raw, manifest=self.manifest, workspace=self.root, scope_report=scope)
        evidence.update(line_start=3,line_end=3,excerpt='changed')
        report, _ = validate_llm_review(raw, manifest=self.manifest, workspace=self.root, scope_report=scope)
        self.assertEqual(report['reviews'][0]['source_evidence']['line_start'],3)

    def test_crlf_exact_locations_and_hashes_survive_replay(self):
        data = b'<html>\r\n<div>changed</div>\r\n</html>\r\n'
        (self.root/'index.html').write_bytes(data)
        _, _, inputs = read_sources(self.root,changed=True,base_ref='HEAD',approved_scope=self.manifest['review_scope'])
        raw = copy.deepcopy(self.raw)
        raw['reviews'][0]['source_evidence'].update(line_start=1,line_end=3,excerpt='<div>changed</div>\r\n')
        report, _ = validate_llm_review(raw,manifest=self.manifest,workspace=self.root,
            scope_report={'run_id':self.run_id,'inputs':inputs})
        evidence = report['reviews'][0]['source_evidence']
        self.assertEqual((evidence['line_start'], evidence['line_end'], evidence['column_start']), (2,2,1))
        self.assertEqual(evidence['sha256'],hashlib.sha256(data).hexdigest())
        self.rule.unlink()
        validate_readme_snapshot(self.manifest,self.root)

    def test_manifest_ref_is_explicitly_unverifiable_and_never_model_supplied(self):
        report, handoff = validate_llm_review(self.raw,manifest=self.legacy_manifest,
            review_selection=self.selection,workspace=self.root,scope_report=self.scope_report)
        self.assertIsNone(report['reviews'][0]['guideline']['ref'])
        self.assertEqual(report['reviews'][0]['guideline']['ref_status'],'unverifiable_legacy_ref')
        self.assertFalse(handoff['applied'])
        with self.assertRaisesRegex(ValueError, 'approved structured'):
            validate_llm_review(self.raw,manifest=self.legacy_manifest,workspace=self.root,scope_report=self.scope_report)

    def test_applicability_is_derived_for_manifest_and_readme(self):
        for system in ('carbon','any','custom'):
            with self.subTest(system=system):
                self.rule.write_text(f'---\nid: custom-css\ndesign_system: {system}\n---\n## Styling\nUse approved tokens in component styling.\n')
                selection = self.approved_selection()
                manifest = load_guidelines(self.root,[f'product={self.rule}'],'custom')
                sources = [bind_manifest_selection(self.root,manifest,selection),
                           freeze_selected_readme_sources(self.root,selection)['snapshot']]
                for snapshot in sources:
                    raw = copy.deepcopy(self.raw)
                    doc = snapshot['documents'][0]
                    review = raw['reviews'][0]
                    review['guideline_id'] = doc['id']
                    review['guideline']['sha256'] = doc['sha256']
                    if system == 'carbon':
                        review.update(status='not_applicable',severity=None,source_evidence=None,
                            suggested_fix=None,side_effects=None,test_suggestion=None,acceptance_condition=None)
                    report,handoff = validate_llm_review(raw,manifest=snapshot,workspace=self.root,scope_report=self.scope_report)
                    self.assertEqual(report['reviews'][0]['applicability']['outcome'],
                        'not_applicable' if system == 'carbon' else 'applicable')
                    if system == 'carbon':
                        self.assertEqual(handoff['proposals'],[])

    def test_jsx_unknown_syntax_never_contributes_a_pass(self):
        doc = {**self.manifest['documents'][0], 'check':'no-custom-css'}
        for text in ('<Button {...props} />', '<Button value={`x${thing}`} />',
                     '<Button onClick={() => doThing()} style={{color: red}}>Hi</Button>',
                     '<Button style={{color: red}} onClick={() => doThing()}>Hi</Button>'):
            incomplete = {}
            findings,evaluated = evaluate([doc],{'view.tsx':text},incomplete=incomplete)
            self.assertIn(doc['id'],incomplete)
            self.assertTrue(findings or doc['id'] not in evaluated)

    def test_whole_document_requires_explicit_selection(self):
        with self.assertRaisesRegex(ValueError, 'whole-document or selected section'):
            self.snapshot(scope='.',anchor=None)
        snapshot, raw = self.snapshot(scope='.',anchor=None,whole=True)
        raw['reviews'][0]['guideline'].update(heading='Unselected section',quote='Unselected rule.')
        report,_ = validate_llm_review(raw,manifest=snapshot,workspace=self.root,scope_report=self.scope_report)
        self.assertEqual(report['reviews'][0]['guideline']['selected_scope'],{'kind':'whole_document'})

    def test_local_commit_ref_requires_exact_blob_bytes(self):
        snapshot,_ = self.snapshot(scope='.')
        self.assertIsNone(snapshot['documents'][0]['provenance']['ref'])
        # Only this disposable fixture repository is staged/committed.
        subprocess.run(['git','-C',str(self.root),'add','.design'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture guideline'],check=True)
        snapshot,raw = self.snapshot(scope='.')
        self.assertEqual(snapshot['documents'][0]['provenance']['status'],'verified_git_blob')
        # The code delta's head is refreshed independently from the guideline ref.
        _,_,inputs = read_sources(self.root,changed=True,base_ref='HEAD',approved_scope=snapshot['review_scope'])
        report,_ = validate_llm_review(raw,manifest=snapshot,workspace=self.root,scope_report={'run_id':self.run_id,'inputs':inputs})
        self.assertEqual(report['reviews'][0]['guideline']['ref'],snapshot['repository_ref'])

    def test_duplicate_headings_and_fenced_headings_have_stable_anchors(self):
        from review_scope import section_scope
        text = '## Rule\nFirst.\n```md\n## Rule\n```\n## Rule\nSecond.\n'
        bounds = section_scope(text,{'kind':'section','anchor':'rule-1'})
        self.assertEqual(text[bounds['start']:bounds['end']],'## Rule\nSecond.\n')

    def test_legacy_snapshot_can_be_read_but_cannot_issue_new_fixes(self):
        from guideline_snapshot import _fingerprint
        legacy = copy.deepcopy(self.manifest)
        legacy['schema_version'] = 'readme-guideline-snapshot-1.0.0'
        legacy['snapshot_sha256'] = _fingerprint({k:v for k,v in legacy.items() if k != 'snapshot_sha256'})
        self.assertEqual(validate_readme_snapshot(legacy,self.root),legacy)
        with self.assertRaisesRegex(ValueError, 'replay-only'):
            validate_llm_review(self.raw,manifest=legacy,workspace=self.root,scope_report=self.scope_report)

    def test_manifest_1_0_replay_preserves_raw_id_and_unverified_ref(self):
        manifest = copy.deepcopy(self.legacy_manifest)
        manifest['schema_version'] = '1.0.0'
        for doc in manifest['documents']:
            doc['id'] = doc.pop('original_id')
            doc.pop('namespace')
        for source in manifest['sources']:
            source.pop('namespace')
            source['document_ids'] = [identity.split(':',1)[1] for identity in source['document_ids']]
        manifest['version'] = 'sha256:' + hashlib.sha256(json.dumps(sorted((d['id'],d['sha256']) for d in manifest['documents'])).encode()).hexdigest()
        raw = copy.deepcopy(self.raw)
        raw['reviews'][0]['guideline_id'] = manifest['documents'][0]['id']
        self.rule.unlink()
        report,_ = validate_llm_review(raw,manifest=manifest,review_selection=self.selection,
                                      workspace=self.root,scope_report=self.scope_report)
        self.assertEqual(report['reviews'][0]['guideline_id'],'custom-css')
        self.assertEqual(report['reviews'][0]['guideline']['ref_status'],'unverifiable_legacy_ref')
