"""Regressions derived from the user's two live evaluation runs."""

import io
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from strands_evals.types.evaluation import EvaluationData
from strands.types.exceptions import ModelThrottledException

from conftest import ScriptedModel, clarification
from evals.evaluators import ContractEvaluator, ConstraintEvaluator, EvidenceEvaluator, ToolUsageEvaluator
from trip_agent.agent import run_turn
from trip_agent.config import AppError
from trip_agent.failures import classify_failure
from trip_agent.persistence import ArtifactStore
from trip_agent.schemas import TripResponse
from trip_agent.tools.context import payload


def test_actual_model_schemas_preserve_nullability_and_response_list_types(sessions, session):
    model = ScriptedModel([clarification])
    run_turn(sessions, 'Test trip', 'Help', model=model, output=io.StringIO())
    specs = {s['name']: s for s in model.seen_specs[0]}
    budget = specs['calculate_trip_budget']['inputSchema']['json']
    args = dict(destination_id='porto', accommodation_artifact_id='example', accommodation_id='porto-boutique',
                travelers=2, nights=3, days=4, budget_usd=None, flight_artifact_id=None)
    Draft202012Validator(budget).validate(args)
    args.pop('budget_usd')
    Draft202012Validator(budget).validate(args)
    stay = specs['search_accommodations']['inputSchema']['json']
    Draft202012Validator(stay).validate({'destination_id': 'porto', 'max_nightly_usd': None})
    final = specs['TripResponse']['inputSchema']['json']
    candidate = clarification([])[1]
    candidate['trip_state']['open_questions'] = None
    assert not Draft202012Validator(final).is_valid(candidate)
    candidate['trip_state']['open_questions'] = []
    Draft202012Validator(final).validate(candidate)
    TripResponse.model_validate(candidate)
    from trip_agent.openai_model import TravelOpenAIResponsesModel
    adapter = TravelOpenAIResponsesModel(model_id='offline', client_args={'api_key': 'offline'}, stateful=False)
    request = adapter._format_request([], model.seen_specs[0])
    assert all(tool['strict'] is False for tool in request['tools'])


@pytest.mark.parametrize('explicit_null', [False, True])
def test_no_total_budget_can_be_priced_through_real_strands_loop(sessions, session, explicit_null):
    store = ArtifactStore(sessions.resolve('Test trip'))

    def budget(messages):
        stay = next(r for r in store.list('tool_results')
                    if store.read(r['artifact_id'])['data']['tool_name'] == 'search_accommodations')
        args = dict(destination_id='porto', accommodation_artifact_id=stay['artifact_id'],
                    accommodation_id='porto-boutique', travelers=2, nights=3, days=4)
        if explicit_null:
            args['budget_usd'] = None
        return 'calculate_trip_budget', args

    run_turn(sessions, 'Test trip', 'Porto, hotel under 300/night, no total budget', model=ScriptedModel([
        ('search_accommodations', {'destination_id': 'porto', 'max_nightly_usd': 300}), budget, clarification]),
        output=io.StringIO())
    records = [store.read(r['artifact_id']) for r in store.list('tool_results')]
    result = payload(next(r for r in records if r['data']['tool_name'] == 'calculate_trip_budget'))
    assert result['status'] == 'ok' and result['budget_usd'] is None
    assert result['budget_assessment'] == 'unknown'
    assert result['total_range_usd'] == [740, 1130]  # Flights still unknown, never priced at zero.


def test_repeated_invalid_call_stops_and_corrected_arguments_can_recover(sessions, session):
    invalid = ('search_accommodations', {'destination_id': 'porto', 'max_nightly_usd': 0})
    with pytest.raises(AppError, match='Repeated identical invalid tool') as caught:
        run_turn(sessions, 'Test trip', 'Porto', model=ScriptedModel([invalid] * 5), output=io.StringIO())
    assert classify_failure(caught.value)['category'] == 'repeated_invalid_tool_input'
    store = ArtifactStore(sessions.resolve('Test trip'))
    assert len(store.list('tool_calls')) == 3 and len(store.list('tool_results')) == 2
    assert not store.list('final_responses')
    result = run_turn(sessions, 'Test trip', 'No nightly limit', model=ScriptedModel([
        invalid, ('search_accommodations', {'destination_id': 'porto', 'max_nightly_usd': None}), clarification]),
        output=io.StringIO())
    assert result['response']['status'] == 'needs_clarification'


def test_quota_failure_is_persisted_and_quality_dimensions_are_not_applicable(sessions, session):
    with pytest.raises(AppError, match='quota is exhausted') as caught:
        run_turn(sessions, 'Test trip', 'Antarctica', model=ScriptedModel([
            ModelThrottledException('Rate limit exceeded: free-models-per-day')]), output=io.StringIO())
    store = ArtifactStore(sessions.resolve('Test trip'))
    errors = [store.read(r['artifact_id'])['data'] for r in store.list('errors')]
    assert any(e.get('category') == 'provider_quota' and e['provider_blocked'] for e in errors)
    assert not store.list('tool_calls')
    case = EvaluationData(input='Antarctica', actual_output={'error': str(caught.value)},
                          metadata={'required_tools': ['search_destinations']})
    for evaluator in [ContractEvaluator(), ConstraintEvaluator(), EvidenceEvaluator(), ToolUsageEvaluator()]:
        verdict = evaluator.evaluate(case)[0]
        assert verdict.not_applicable and 'PROVIDER BLOCKED' in verdict.reason


def test_exclusion_accepts_clarifying_preliminary_suggestions_but_not_lost_constraints():
    cases = json.loads((Path(__file__).parents[1] / 'evals/cases.json').read_text())
    metadata = next(c['metadata'] for c in cases if c['name'] == 'explicit-exclusion')
    response = {'status': 'suggestions', 'trip_state': {'origin': {'status': 'unknown'},
        'duration': {'status': 'unknown'}, 'exclusions': [{'value': 'Santorini'}]},
        'questions': ['Where will you depart from, and for how long?'],
        'suggestions': [{'destination_id': 'porto', 'budget_artifact_id': None}]}
    case = EvaluationData(input='Anniversary', actual_output={'response': response}, metadata=metadata)
    assert ConstraintEvaluator().evaluate(case)[0].test_pass
    case.actual_output['response']['questions'] = []
    assert not ConstraintEvaluator().evaluate(case)[0].test_pass
    case.actual_output['response']['questions'] = ['Origin?']
    case.actual_output['response']['suggestions'][0]['destination_id'] = 'santorini'
    assert not ConstraintEvaluator().evaluate(case)[0].test_pass


def test_provider_blocked_replay_has_separate_counts_nonzero_exit_and_preserves_original(tmp_path, monkeypatch):
    from evals.run import main
    source = tmp_path / 'original.json'
    source.write_text(json.dumps({'unsupported-catalog': {'error':
        "Agent call failed (ModelThrottledException): Error code: 429 - free-models-per-day"}}))
    before = source.read_bytes()
    monkeypatch.setattr(sys, 'argv', ['evals.run', '--only', 'unsupported-catalog', '--replay', str(source),
                                    '--output', str(tmp_path / 'reports')])
    assert main() == 1
    summary = json.loads(next((tmp_path / 'reports').glob('*/summary.json')).read_text())
    assert summary['counts']['provider_blocked_cases'] == 1
    assert summary['counts']['applicable_checks'] == 0
    assert summary['counts']['passed_cases'] == 0
    assert source.read_bytes() == before
