"""Small, explicit source-onboarding demonstration; not a blind benchmark.

The fifth source reuses existing canonical employee fields. This generator has
no detector/evaluator dependency and never reads the reserved evaluation pack.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from .policy import load_policy, validate_policy
from .synthetic import _reference_markdown


def onboarding_policy():
    policy = copy.deepcopy(load_policy())
    policy['policy_version'] = 'synthetic-benefits-onboarding-v1'
    policy['description'] = 'Five-source synthetic onboarding demonstration; provisional business rules.'
    policy['sources']['benefits'] = {
        'display_name': 'Benefits administration', 'filename': 'benefits.csv',
        'record_grain': 'one benefit membership per employment',
        'fields': {
            'source_id': ['benefit_member_no'], 'name': ['member_full_name'],
            'email': ['contact_email'], 'birth_date': ['date_of_birth'],
            'employment_id': ['assignment_ref'], 'department': ['cost_centre'],
            'job_code': ['plan_job'], 'location': ['service_city'],
            'hire_date': ['joined_on'], 'updated_at': ['record_refreshed_on'],
        },
        'required': ['source_id', 'name', 'department', 'job_code', 'location', 'hire_date'],
        'date_formats': ['%Y/%m/%d'],
        'domains': {field: list(policy['sources']['core_hr']['domains'][field])
                    for field in ('department', 'job_code', 'location')},
        'value_maps': {'location': {'DXB_BEN': 'DUBAI', 'LON_BEN': 'LONDON'}},
        'max_record_age_days': 730,
        'identifier_scope_fields': [], 'unique_profile_fields': ['employment_id', 'hire_date'],
    }
    for field in ('department', 'job_code', 'location', 'hire_date'):
        policy['authority'][field]['compare_sources'].append('benefits')
    policy['timing']['source_lag_days']['benefits'] = 5
    for field, alias in (('department', 'cost_centre'), ('job_code', 'plan_job'), ('location', 'service_city')):
        policy['dependencies'].extend([
            {'source': 'core_hr.' + field, 'target': 'benefits.' + alias},
            {'source': 'benefits.' + field, 'target': 'report:benefits_eligibility_summary'},
        ])
    return validate_policy(policy)


def generate_onboarding_pack(destination):
    """Create a new local pack; never overwrite any existing inputs."""
    root = Path(destination)
    if root.exists() and any(root.iterdir()):
        raise ValueError('The onboarding pack already exists; choose a new directory to preserve its inputs.')
    policy = onboarding_policy()
    inputs = root / 'input'
    inputs.mkdir(parents=True)
    people = [
        ('A', 'Laila Mansour', '1990-02-14', 'ENG-01', 'ENGINEER', 'DUBAI'),
        ('B', 'Omar Haddad', '1988-04-20', 'FIN-01', 'ANALYST', 'DUBAI'),
        ('C', 'Sara Nasser', '1992-06-17', 'HR-01', 'HRBP', 'DUBAI'),
        ('D', 'Ravi Mehta', '1985-08-09', 'IT-01', 'SPECIALIST', 'LONDON'),
        ('E', 'Maya Salim', '1994-11-25', 'OPS-01', 'MANAGER', 'DUBAI'),
    ]
    observations = {source: [] for source in policy['sources']}
    identifiers = {'core_hr': 'CORE', 'payroll': 'PAY', 'learning': 'LEARN', 'access_directory': 'DIR', 'benefits': 'BEN'}
    for index, (key, name, birthday, department, job, location) in enumerate(people, 1):
        for source, config in policy['sources'].items():
            values = {
                'source_id': identifiers[source] + '-' + hashlib.sha256(f'onboarding:{source}:{key}'.encode()).hexdigest()[:10].upper(),
                'name': name, 'email': key.lower() + '@onboarding.synthetic.example',
                'birth_date': birthday, 'employment_id': source + '-assignment-' + key,
                'department': department, 'job_code': job, 'location': location,
                'hire_date': '2022-01-10', 'updated_at': '2026-09-20',
                'employment_status': 'ACTIVE', 'payroll_status': 'ELIGIBLE',
                'account_status': 'ENABLED', 'is_primary': 'true',
            }
            if source == 'benefits':
                values['location'] = 'DXB_BEN' if location == 'DUBAI' else 'LON_BEN'
                if key == 'A':
                    values.update(name='Mansour Laila', department='')
                elif key == 'B':
                    values['job_code'] = 'UNKNOWN_PLAN_JOB'
                elif key == 'C':
                    values['location'] = 'LON_BEN'
                elif key == 'D':
                    values['updated_at'] = '2020-01-01'
            raw = {}
            for field, aliases in config['fields'].items():
                value = values.get(field, '')
                if field in {'birth_date', 'hire_date', 'updated_at'} and value:
                    value = date.fromisoformat(value).strftime(config['date_formats'][0])
                raw[aliases[0]] = value
            observations[source].append(raw)
            if source == 'benefits' and key == 'E':
                observations[source].append(dict(raw))
    observations['benefits'].append({
        'benefit_member_no': 'BEN-UNMATCHED', 'member_full_name': 'Nora Faris',
        'contact_email': 'nora@onboarding.synthetic.example', 'date_of_birth': '1993/03/12',
        'assignment_ref': 'benefits-unmatched-assignment', 'cost_centre': '',
        'plan_job': 'ANALYST', 'service_city': 'DXB_BEN', 'joined_on': '2022/01/10',
        'record_refreshed_on': '2026/09/20',
    })
    for source, config in policy['sources'].items():
        with (inputs / config['filename']).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=[aliases[0] for aliases in config['fields'].values()], lineterminator='\n')
            writer.writeheader()
            writer.writerows(observations[source])
    dictionary, dependencies = _reference_markdown(policy)
    (inputs / 'data_dictionary.md').write_text(dictionary, encoding='utf-8')
    (inputs / 'dependencies.md').write_text(dependencies, encoding='utf-8')
    (root / 'policy.json').write_text(json.dumps(policy, indent=2) + '\n', encoding='utf-8')
    manifest = {
        'synthetic_only': True, 'purpose': 'source onboarding demonstration, not independent accuracy validation',
        'as_of': '2026-10-01', 'source_counts': {source: len(rows) for source, rows in observations.items()},
        'policy_version': policy['policy_version'],
        'input_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(inputs.iterdir())},
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest
