"""Behavioral proof that a configured fifth source reaches the whole workflow."""
import base64
import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from hrtrustgraph.deterministic.onboarding import generate_onboarding_pack, onboarding_policy
from hrtrustgraph.deterministic.pipeline import analyze
from hrtrustgraph.deterministic.policy import load_policy, validate_policy
from hrtrustgraph.deterministic.reference_docs import preview_references
from hrtrustgraph.deterministic.scenario import simulate_patch
from hrtrustgraph.deterministic.web import Handler, Workspace, ensure_builtin_pack
from tests.test_web_core import MemorySocket


class FifthSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config' / 'demo_policy.json').write_text(json.dumps(load_policy()))
        self.pack = self.root / 'datasets' / 'onboarding'
        self.manifest = generate_onboarding_pack(self.pack)
        self.inputs = self.pack / 'input'
        self.policy = load_policy(self.pack / 'policy.json')
        self.documents = {name: (self.inputs / name).read_bytes().decode('utf-8') for name in ('data_dictionary.md', 'dependencies.md')}
        self.preview = preview_references(self.policy, self.documents)
        self.workspace = Workspace(self.root)
        self.addCleanup(lambda: self.workspace.executor.shutdown(wait=True))
        self.server = SimpleNamespace(workspace=self.workspace, server_port=8765)

    def request(self, path, body=None, token=True, raw=False):
        payload = json.dumps(body).encode() if body is not None else b''
        method = 'POST' if body is not None else 'GET'
        headers = [f'{method} {path} HTTP/1.0', 'Host: 127.0.0.1:8765', f'Content-Length: {len(payload)}']
        if token:
            headers.append('X-HR-Workspace: ' + self.workspace.csrf)
        socket = MemorySocket(('\r\n'.join(headers) + '\r\n\r\n').encode() + payload)
        Handler(socket, ('127.0.0.1', 12345), self.server)
        header, content = socket.output.getvalue().split(b'\r\n\r\n', 1)
        return int(header.split(b' ')[1]), content if raw else json.loads(content)

    def upload(self):
        return {'mode': 'upload', 'as_of': '2026-10-01', 'synthetic_confirmed': True,
                'policy': self.policy, 'reference_documents': self.documents,
                'reference_digest': self.preview['digest'], 'references_reviewed': True,
                'files': {source: base64.b64encode((self.inputs / config['filename']).read_bytes()).decode()
                          for source, config in self.policy['sources'].items()}}

    def run_analysis(self):
        return analyze(self.inputs, self.preview['policy'], '2026-10-01', self.root / 'result', simulation_limit=3)

    def test_fifth_source_has_importable_references_and_independent_formats(self):
        self.assertTrue(self.preview['ready'], self.preview['errors'])
        self.assertEqual(len(self.preview['definitions']), 54)
        self.assertEqual(len(self.preview['dependencies']), 34)
        self.assertEqual(self.manifest['source_counts']['benefits'], 7)
        self.assertFalse((self.pack / 'truth').exists())
        result = self.run_analysis()
        benefits = [r for r in result['snapshot'].records if r['source_system'] == 'benefits']
        row = next(r for r in benefits if r['values']['email'].startswith('a@'))
        self.assertEqual(row['values']['birth_date'], '1990-02-14')
        self.assertEqual(row['values']['location'], 'DUBAI')
        self.assertEqual(row['raw']['service_city'], 'DXB_BEN')
        self.assertEqual(row['raw']['date_of_birth'], '1990/02/14')
        person = result['matches'].assignments[row['record_id']]['person_id']
        group = [r for r in result['snapshot'].records if result['matches'].assignments[r['record_id']]['person_id'] == person]
        self.assertEqual({r['source_system'] for r in group}, set(self.policy['sources']))
        self.assertEqual(len({r['source_id'] for r in group}), 5)

    def test_reference_heading_can_use_the_new_sources_configured_display_name(self):
        documents = dict(self.documents)
        documents['data_dictionary.md'] = documents['data_dictionary.md'].replace('### benefits\n', '### Benefits administration\n')
        preview = preview_references(self.policy, documents)
        self.assertTrue(preview['ready'], preview['errors'])
        self.assertEqual(len([d for d in preview['definitions'] if d['source'] == 'benefits']), 10)

    def test_new_source_uses_existing_rules_and_authority_with_safe_abstention(self):
        result = self.run_analysis()
        self.assertEqual(result['summary']['source_record_count'], 27)
        self.assertEqual(result['summary']['person_groups'], 6)
        self.assertEqual(len(result['issues']), 7)
        self.assertTrue(all(issue['source_system'] == 'benefits' for issue in result['issues']))
        rows = {r['record_id']: r for r in result['snapshot'].records}
        expected = {'a': ('missing_value', 'department', 'ENG-01'),
                    'b': ('invalid_code', 'job_code', 'ANALYST'),
                    'c': ('cross_system_conflict', 'location', 'DUBAI')}
        for key, (kind, field, value) in expected.items():
            issue = next(i for i in result['issues'] if rows[i['record_id']]['values']['email'].startswith(key + '@'))
            self.assertEqual((issue['issue_type'], issue['field'], issue['suggested_value']), (kind, field, value))
            self.assertEqual(issue['recommendation_status'], 'proposed')
            self.assertGreater(len(issue['evidence']['source_record_ids']), 1)
        unmatched = next(i for i in result['issues'] if i['source_id'] == 'BEN-UNMATCHED')
        self.assertEqual(unmatched['recommendation_status'], 'investigate')
        self.assertIsNone(unmatched['suggested_value'])
        self.assertEqual(sum(i['issue_type'] == 'duplicate_identifier' for i in result['issues']), 2)
        self.assertTrue(any(i['issue_type'] == 'out_of_date_record' for i in result['issues']))
        self.assertTrue(any(row['source_system'] == 'benefits' for row in result['trust']))

    def test_fifth_source_fix_has_declared_exposure_without_fabricated_report_effects(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.inputs.iterdir()}
        result = self.run_analysis()
        snapshot_before = copy.deepcopy(result['snapshot'])
        issue = next(i for i in result['issues'] if i['field'] == 'department' and i['recommendation_status'] == 'proposed')
        row = next(r for r in result['snapshot'].records if r['record_id'] == issue['record_id'])
        simulation = simulate_patch(result['snapshot'], result['matches'], result['policy'], '2026-10-01',
                                    {'record_id': row['record_id'], 'field': issue['field'], 'expected_value': None, 'value': issue['suggested_value']})
        self.assertEqual(simulation['target_system'], 'benefits')
        self.assertEqual(simulation['coverage']['potential_only_reports'], ['benefits_eligibility_summary'])
        self.assertTrue(all(report['delta'] == 0 for report in simulation['reports'].values()))
        self.assertEqual(issue['dependencies'], ['report:benefits_eligibility_summary'])
        self.assertEqual(issue['priority_base_score'], 52)
        self.assertEqual(result['snapshot'], snapshot_before)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.inputs.iterdir()})
        with (self.root / 'result' / 'issues.csv').open() as stream:
            self.assertIn('benefits', stream.read())

    def test_source_configuration_is_generic_and_protected_before_any_analysis(self):
        status, result = self.request('/api/sources/preview', {'policy': self.policy})
        self.assertEqual(status, 200)
        self.assertEqual(len(result['sources']), 5)
        benefit = next(s for s in result['sources'] if s['source_system'] == 'benefits')
        self.assertEqual((benefit['name'], benefit['filename']), ('Benefits administration', 'benefits.csv'))
        self.assertEqual(self.request('/api/sources/preview', {'policy': self.policy}, token=False)[0], 403)
        other = copy.deepcopy(self.policy)
        source = other['sources'].pop('benefits')
        source.update(display_name='Travel profiles', filename='travel.csv')
        other['sources']['travel_profiles'] = source
        status, result = self.request('/api/sources/preview', {'policy': other})
        self.assertEqual(status, 200)
        self.assertTrue(any(s['source_system'] == 'travel_profiles' and s['name'] == 'Travel profiles' for s in result['sources']))
        self.assertFalse(self.workspace.runs())

    def test_five_csv_upload_reaches_cards_filters_matching_impact_and_export(self):
        status, job = self.request('/api/analyze', self.upload())
        self.assertEqual(status, 200)
        self.workspace.executor.shutdown(wait=True)
        complete = self.workspace.jobs[job['id']]
        self.assertEqual(complete['status'], 'complete', complete)
        run = complete['run']
        status, sources = self.request('/api/sources?' + urlencode({'run': run}))
        self.assertEqual(status, 200)
        self.assertEqual(len(sources['sources']), 5)
        self.assertTrue(sources['reference_import']['reviewed'])
        status, queue = self.request('/api/issues?' + urlencode({'run': run, 'source_system': 'benefits'}))
        self.assertEqual(queue['total'], 7)
        issue = next(i for i in queue['items'] if i['field'] == 'department' and i['recommendation_status'] == 'proposed')
        status, employee = self.request('/api/employee?' + urlencode({'run': run, 'id': issue['person_id']}))
        self.assertEqual(len(employee['employee']['sources']), 5)
        status, simulation = self.request('/api/simulate', {'run': run, 'issue_id': issue['issue_id']})
        self.assertEqual(status, 200)
        self.assertIn('benefits_eligibility_summary', simulation['coverage']['potential_only_reports'])
        context = self.workspace.context(run)
        self.assertEqual(context.summary['source_record_count'], 27)
        status, exported = self.request('/api/download?' + urlencode({'run': run, 'file': 'issues.csv'}), raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(exported, (context.directory / 'issues.csv').read_bytes())
        exported_rows = list(csv.DictReader(io.StringIO(exported.decode())))
        self.assertEqual(len(exported_rows), 7)
        self.assertTrue(all(row['source_system'] == 'benefits' for row in exported_rows))
        self.assertFalse((context.directory / 'decisions.jsonl').exists())

    def test_missing_fifth_csv_is_rejected(self):
        payload = self.upload()
        del payload['files']['benefits']
        status, error = self.request('/api/analyze', payload)
        self.assertEqual(status, 400)
        self.assertIn('every source', error['error'])
        self.assertFalse(self.workspace.jobs)

    def test_builtin_demo_is_repeatable_and_does_not_fabricate_human_review(self):
        before = {p.name: p.read_bytes() for p in self.inputs.iterdir()}
        status, job = self.request('/api/analyze', {'mode': 'onboarding', 'as_of': '2026-10-01', 'synthetic_confirmed': True})
        self.assertEqual(status, 200)
        self.workspace.executor.shutdown(wait=True)
        complete = self.workspace.jobs[job['id']]
        self.assertEqual(complete['status'], 'complete', complete)
        context = self.workspace.context(complete['run'])
        self.assertEqual(len(context.sources()), 5)
        self.assertFalse(context.policy['reference_import']['reviewed'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.inputs.iterdir()})
        self.assertTrue(any(run['label'].startswith('Five-source demo') for run in self.workspace.runs()))

    def test_existing_and_incomplete_demo_packs_are_preserved(self):
        before = {p.name: p.read_bytes() for p in self.inputs.iterdir()}
        with self.assertRaisesRegex(ValueError, 'already exists'):
            generate_onboarding_pack(self.pack)
        ensure_builtin_pack(self.root, 'onboarding')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.inputs.iterdir()})
        (self.inputs / 'benefits.csv').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            ensure_builtin_pack(self.root, 'onboarding')
        self.assertEqual((self.inputs / 'core_hr.csv').read_bytes(), before['core_hr.csv'])

    def test_bad_source_identifiers_and_mappings_fail_before_rendering_uploads(self):
        for field, invalid in (('name', 'Benefits profiles'), ('filename', '../benefits.csv'), ('fields', {'salary': ['annual_salary']})):
            policy = copy.deepcopy(self.policy)
            if field == 'name':
                policy['sources'][invalid] = policy['sources'].pop('benefits')
            else:
                policy['sources']['benefits'][field] = invalid
            with self.subTest(field=field):
                status, error = self.request('/api/sources/preview', {'policy': policy})
                self.assertEqual(status, 400)
                self.assertTrue(error['error'])


if __name__ == '__main__':
    unittest.main()
