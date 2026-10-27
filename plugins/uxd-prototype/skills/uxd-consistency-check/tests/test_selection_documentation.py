"""Documentation examples and strict eval-judge regressions, entirely offline.

Fixture conversations/events are judge inputs, NOT actual provider/model traces.
These tests do not edit resolver/selection runtime tests or dispatch remote tools.
"""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from guideline_resolver import read_index
from guideline_selection import propose_selection


def strict_judge():
    config = (SKILL / 'eval/eval.yaml').read_text()
    section = config.split('  - name: strict_selection_protocol\n', 1)[1]
    body = section.split('    check: |\n', 1)[1].split('\nthresholds:', 1)[0]
    namespace = {}
    exec('def judge(outputs):\n' + textwrap.indent(textwrap.dedent(body), '    '), namespace)
    return namespace['judge']


class SelectionDocumentationTests(unittest.TestCase):
    def test_template_readme_only_example_discovers_candidates_without_sidecar(self):
        template = (SKILL / 'templates/guideline-index/README.md').read_text()
        example, = re.findall(r'```markdown\n(.*?)\n```', template, re.S)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            index = root / '.design/guidelines/README.md'
            index.parent.mkdir(parents=True)
            index.write_text(example + '\n')
            rule = index.parent / 'rules/controls.md'
            rule.parent.mkdir()
            rule.write_text('---\nid: controls\n---\n## Rule\nUse clear controls.\n')
            metadata = read_index(root, index)
            candidate, = read_index(root, index, topics=metadata['topics'])['sources']
            self.assertIsNone(metadata['sidecar'])
            self.assertEqual(candidate['guideline_scope'], {'kind': 'section', 'anchor': 'rule'})
            self.assertEqual(candidate['locator'], {'kind': 'local', 'path': 'rules/controls.md'})
            self.assertFalse((root / '.artifacts').exists())

    def test_documented_cli_request_runs_against_current_runtime(self):
        reference = (SKILL / 'references/selection-workflow.md').read_text()
        blocks = re.findall(r'```json\n(.*?)\n```', reference, re.S)
        request = next(json.loads(b) for b in blocks if '"operation"' in b)
        self.assertEqual(request['operation'], 'propose-selection')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            index_file = root / request['arguments']['index']
            index = index_file.parent
            index.mkdir(parents=True)
            index_file.write_text('# Fixture product index\n')
            catalog = json.loads((SKILL / 'templates/guideline-index/sources.json').read_text())
            catalog['product'] = 'RHOAI'
            source = catalog['sources'][0]
            source.update(id='controls', policy_status='approved', rule_ids=['controls'])
            source['locator'] = {'kind': 'local', 'path': 'rules/controls.md'}
            index_file.with_name('sources.json').write_text(json.dumps(catalog))
            (index / 'rules').mkdir()
            (index / 'rules/controls.md').write_text('---\nid: controls\n---\nFixture prose.\n')
            (root / 'src/settings').mkdir(parents=True)
            path = root / 'selection-request.json'
            path.write_text(json.dumps(request))
            run = subprocess.run([sys.executable, '-S', str(SKILL / 'scripts/guideline_selection.py'),
                                  '--workspace', str(root), '--request', str(path)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            proposal = json.loads(run.stdout)
            self.assertEqual(proposal['purpose'], 'product_design_guidelines')
            self.assertEqual(proposal['product_identity_source'], 'explicit_instruction')
            self.assertEqual(proposal['review_scope'], 'src/settings')
            self.assertEqual([s['id'] for s in proposal['sources']], ['controls'])
            # The documented request only proposes: no policy adoption/receipt write.
            self.assertFalse((root / '.artifacts').exists())

    def test_template_is_metadata_not_policy_or_adoption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            index = root / '.design/guidelines'
            index.mkdir(parents=True)
            for name in ('README.md', 'sources.json'):
                (index / name).write_bytes((SKILL / 'templates/guideline-index' / name).read_bytes())
            metadata = read_index(root, index / 'README.md', topics=['controls'])
            self.assertIsNone(metadata['product'])
            self.assertIsNone(metadata['sources'][0]['owner'])
            self.assertEqual(metadata['sources'][0]['policy_status'], 'draft')
            self.assertEqual(metadata['sources'][0]['rule_ids'], [])
            with self.assertRaisesRegex(ValueError, 'identify the product'):
                propose_selection(root, index / 'README.md', source_ids=['example-controls'],
                                  review_scope='.', method='deterministic')
            (index / 'rules').mkdir()
            (index / 'rules/controls.md').write_text('## Rule\nFixture rule.\n')
            proposal = propose_selection(root, index / 'README.md', source_ids=['example-controls'],
                review_scope='.', method='deterministic', product_identity='RHOAI')
            self.assertEqual(proposal['product'], 'RHOAI')
            self.assertEqual(proposal['product_identity_source'], 'explicit_instruction')
            self.assertFalse((root / '.artifacts').exists())

    def test_strict_eval_judge_requires_every_exact_contract_field(self):
        judge = strict_judge()
        cases = sorted((SKILL / 'eval/cases').glob('*/annotations.yaml'))
        strict = []
        for path in cases:
            # New strict fixture annotations are JSON (a YAML subset), stdlib-readable.
            if not path.read_text().lstrip().startswith('{'):
                continue
            annotation = json.loads(path.read_text())
            if 'strict_expected' not in annotation:
                continue
            strict.append(path.parent.name)
            expected = annotation['strict_expected']
            outputs = {'annotations': annotation, 'conversation': json.dumps(expected), 'events': []}
            self.assertTrue(judge(outputs)[0], path.parent.name)
            for field in expected:
                with self.subTest(case=path.parent.name, missing=field):
                    wrong = copy.deepcopy(expected)
                    del wrong[field]
                    self.assertFalse(judge({**outputs, 'conversation': json.dumps(wrong)})[0])
            for field, value in [('deterministic_passes', False), ('policy_mode', 'patternfly'),
                                 ('peer_audit', True), ('selected_source_ids', ['other-source'])]:
                wrong = {**expected, field: value}
                self.assertFalse(judge({**outputs, 'conversation': json.dumps(wrong)})[0])
            self.assertFalse(judge({**outputs, 'conversation': json.dumps({**expected, 'extra': 'invented'})})[0])
            self.assertFalse(judge({**outputs, 'conversation': 'approved bounded unavailable no pass'})[0])
            self.assertFalse(judge({k: v for k, v in outputs.items() if k != 'events'})[0])
            self.assertFalse(judge({**outputs, 'conversation': json.dumps(expected)[:-1] + ',"status":"other"}'})[0])
        self.assertEqual(strict, ['exact-figma-selection', 'figma-no-node', 'genuine-approval',
                                  'product-only-pf-prose', 'section-full-document',
                                  'selection-abstention', 'unavailable-local-export'])

    def test_strict_eval_judge_rejects_dispatch_and_wrong_nodes(self):
        judge = strict_judge()
        annotation = json.loads((SKILL / 'eval/cases/exact-figma-selection/annotations.yaml').read_text())
        expected = annotation['strict_expected']
        base = {'annotations': annotation, 'conversation': json.dumps(expected), 'events': []}
        for tool in [{'name': 'Bash', 'input': {'command': 'python analyze.py'}},
                     {'name': 'mcp__figma__get_metadata', 'input': {'fileKey': 'BranchKey', 'nodeId': '12:34'}},
                     {'name': 'Skill', 'input': {'skill': 'pf-review'}}]:
            events = [{'type': 'assistant', 'tools': [tool]}]
            self.assertFalse(judge({**base, 'events': events})[0])
        load = [{'type': 'assistant', 'tools': [{'name': 'Skill', 'input': {'skill': 'uxd-prototype:uxd-consistency-check'}}]}]
        self.assertTrue(judge({**base, 'events': load})[0])
        for key, value in [('branch_key', 'RootKey'), ('node_ids', ['12:34']),
                           ('node_ids', ['12-34', '56:78'])]:
            wrong = copy.deepcopy(expected)
            wrong['locator'][key] = value
            self.assertFalse(judge({**base, 'conversation': json.dumps(wrong)})[0])


if __name__ == '__main__':
    unittest.main()
