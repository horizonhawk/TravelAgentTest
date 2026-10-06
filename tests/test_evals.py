"""Test scorer/harness behavior offline, without claiming live LLM evaluation scores."""

import io
import json
import sys

import pytest

from strands_evals import Case, Experiment
from strands_evals.types.evaluation import EvaluationData

from conftest import ScriptedModel, clarification
from evals.evaluators import ContractEvaluator, ConstraintEvaluator, EvidenceEvaluator, ToolUsageEvaluator, tool_trajectory
from trip_agent.agent import run_turn
from trip_agent.persistence import ArtifactStore


def test_experiment_integration_and_failures(sessions, session):
    output = run_turn(sessions, "Test trip", "Cheap", model=ScriptedModel([clarification]), output=io.StringIO())
    output["session_path"] = str(sessions.resolve("Test trip"))
    output["tool_results"] = []
    experiment = Experiment(cases=[Case(name="offline-harness", input="Cheap", metadata={
        "statuses": ["needs_clarification"], "unknown": ["origin"]})], evaluators=[
        ContractEvaluator(), ConstraintEvaluator(), EvidenceEvaluator(), ToolUsageEvaluator()])
    report = experiment.run_evaluations(lambda case: {"output": output})
    assert all(report.test_passes)
    assert len(report.test_passes) == 4
    assert not ContractEvaluator().evaluate(EvaluationData(input="Cheap", actual_output={}))[0].test_pass
    assert not EvidenceEvaluator().evaluate(EvaluationData(input="Cheap", actual_output={
        **output, "session_path": "/does-not-exist"}))[0].test_pass
    data = EvaluationData(input="Cheap", actual_output=output, metadata={
        "statuses": ["suggestions"], "required_tools": ["search_flights"]})
    result = ToolUsageEvaluator().evaluate(data)[0]
    assert not result.test_pass
    assert "search_flights" in result.reason


def tool_case(names, **metadata):
    return EvaluationData(input='Test request', actual_output={'tool_calls': [
        {'data': {'name': name}} for name in names]}, metadata=metadata)


def test_required_tools_allow_extra_calls_duplicates_and_any_order():
    case = tool_case(['read_artifact', 'calculate_trip_budget', 'search_accommodations', 'read_artifact'],
                     required_tools=['search_accommodations', 'calculate_trip_budget'])
    assert ToolUsageEvaluator().evaluate(case)[0].test_pass
    assert tool_trajectory(case.actual_output) == ['read_artifact', 'calculate_trip_budget', 'search_accommodations', 'read_artifact']
    missing = tool_case(['search_accommodations'], required_tools=['search_accommodations', 'calculate_trip_budget'])
    result = ToolUsageEvaluator().evaluate(missing)[0]
    assert not result.test_pass and result.score == 0.5 and 'calculate_trip_budget' in result.reason


@pytest.mark.parametrize(('sdk_status', 'business_status', 'expected'), [
    ('success', 'ok', True), ('success', 'no_match', True),
    ('success', 'missing_input', False), ('success', 'invalid_input', False),
    ('error', 'ok', False),
])
def test_required_success_is_distinct_from_a_call_attempt(sdk_status, business_status, expected):
    case = tool_case(['search_destinations'], required_successful_tools=['search_destinations'])
    case.actual_output['tool_results'] = [{'data': {'tool_name': 'search_destinations', 'result': {
        'status': sdk_status, 'content': [{'text': json.dumps({'status': business_status})}]}}}]
    assert ToolUsageEvaluator().evaluate(case)[0].test_pass == expected


def test_forbidden_tools_missing_trace_and_no_requirements():
    evaluator = ToolUsageEvaluator()
    assert not evaluator.evaluate(tool_case(['search_flights'], forbidden_tools=['search_flights']))[0].test_pass
    assert evaluator.evaluate(tool_case([], forbidden_tools=['search_flights']))[0].test_pass
    missing = EvaluationData(input='Help', actual_output={'response': 'I called search_flights'}, metadata={
        'forbidden_tools': ['search_flights']})
    assert not evaluator.evaluate(missing)[0].test_pass  # Missing evidence does not prove absence.
    result = evaluator.evaluate(tool_case([]))[0]
    assert result.not_applicable and result.test_pass


def test_replay_runner_includes_tool_dimension_and_preserves_original_outputs(sessions, session, tmp_path, monkeypatch):
    from evals.run import main
    output = run_turn(sessions, 'Test trip', 'Consider Porto', model=ScriptedModel([
        ('search_destinations', {'destination_id': 'porto'}), clarification]), output=io.StringIO())
    store = ArtifactStore(sessions.resolve('Test trip'))
    output['session_path'] = str(store.path)
    # Older saved runs have only results: replay still derives the trajectory.
    output['tool_results'] = [store.read(a['artifact_id']) for a in store.list('tool_results')]
    source = tmp_path / 'original.json'
    source.write_text(json.dumps({'offline-replay': output}))
    before = source.read_bytes()
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'name': 'offline-replay', 'input': 'Consider Porto', 'metadata': {
        'statuses': ['needs_clarification'], 'required_tools': ['search_destinations'],
        'required_successful_tools': ['search_destinations']}}]))
    monkeypatch.setattr(sys, 'argv', ['evals.run', '--replay', str(source), '--cases', str(cases),
                                    '--output', str(tmp_path / 'reports')])
    assert main() == 0
    summary = json.loads(next((tmp_path / 'reports').glob('*/summary.json')).read_text())
    assert summary['mode'] == 'replay' and len(summary['test_passes']) == 4
    assert all(summary['test_passes']) and 'search_destinations' in json.dumps(summary['cases'])
    assert source.read_bytes() == before
