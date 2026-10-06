"""Adversarial scoring and replay on a moved, credential-free submission bundle."""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest
from strands_evals.types.evaluation import EvaluationData

from evals.evaluators import ConstraintEvaluator, EvidenceEvaluator
from evals.evidence import evidence_store
from trip_agent.config import AppError


BUNDLE = Path(__file__).parents[1] / 'submission/evidence/openai-20261006T044810289114Z'


def case(name):
    outputs = json.loads((BUNDLE / 'outputs.json').read_text())
    spec = next(c for c in json.loads((BUNDLE / 'cases.json').read_text()) if c['name'] == name)
    return EvaluationData(input=spec['input'], metadata=spec['metadata'], actual_output=outputs[name])


@pytest.mark.parametrize('name', ['beach-budget', 'nightly-hotel-limit', 'tokyo-excluding-flights', 'contradiction'])
def test_original_generated_responses_pass_stronger_checks(name):
    data = case(name)
    assert EvidenceEvaluator().evaluate(data)[0].test_pass
    assert ConstraintEvaluator().evaluate(data)[0].test_pass


@pytest.mark.parametrize('field,claim', [
    ('message', 'This entire trip costs USD 1 including everything.'),
    ('rough_budget', 'USD 1 all-in, with no excluded costs.'),
    ('rough_budget', 'USD 1,930–2,990 all-in, with no excluded costs.'),
    ('rough_budget', 'USD 1,930–2,990, plus USD 500 for an invented fee.'),
    ('rough_budget', 'USD 1,930–2,800 for the covered categories.'),
])
def test_false_budget_or_scope_claims_fail_even_with_correct_cited_tool_math(field, claim):
    data = case('beach-budget')
    target = data.actual_output['response'] if field == 'message' else data.actual_output['response']['suggestions'][0]
    target[field] = claim
    result = EvidenceEvaluator().evaluate(data)[0]
    assert not result.test_pass, result.reason


@pytest.mark.parametrize('message,questions', [
    ('Tokyo is outside Japan, so both requirements can be met.', ['What is your budget?']),
    ('These requirements conflict.', ['What is your budget?']),
    ('I can satisfy both requirements.', ['Which hotel do you want in Tokyo?']),
])
def test_conflict_status_alone_does_not_pass(message, questions):
    data = case('contradiction')
    data.actual_output['response'].update(message=message, questions=questions)
    assert not ConstraintEvaluator().evaluate(data)[0].test_pass


def test_missing_and_cross_session_portable_evidence_fail():
    data = case('beach-budget')
    artifact_id = data.actual_output['response']['suggestions'][0]['budget_artifact_id']
    data.actual_output['evidence']['artifacts'] = [r for r in data.actual_output['evidence']['artifacts']
                                                if r['artifact_id'] != artifact_id]
    assert not EvidenceEvaluator().evaluate(data)[0].test_pass
    data = case('beach-budget')
    data.actual_output['evidence']['artifacts'][0]['session_id'] = 'other-session'
    with pytest.raises(AppError, match='cross-session'):
        evidence_store(data.actual_output)


def test_replay_moved_bundle_without_original_sessions_or_credentials(tmp_path, monkeypatch):
    from evals.run import main
    moved = tmp_path / 'reviewer-bundle'
    shutil.copytree(BUNDLE, moved)
    outputs = json.loads((moved / 'outputs.json').read_text())
    assert all('session_path' not in x for x in outputs.values())
    monkeypatch.chdir(tmp_path)
    for key in ['OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, 'argv', ['evals.run', '--replay', str(moved / 'outputs.json'), '--output', str(tmp_path / 'results')])
    assert main() == 0
    report = json.loads(next((tmp_path / 'results').glob('*/summary.json')).read_text())
    assert report['evaluation_version'] == 5 and report['counts']['passed_cases'] == 8
    with (moved / 'outputs.json').open('a') as file:
        file.write(' ')
    with pytest.raises(AppError, match='integrity'):
        main()
