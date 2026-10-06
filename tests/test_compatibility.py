import copy
import io
import json

import pytest
from pydantic import ValidationError

from conftest import ScriptedModel, clarification
from trip_agent.agent import run_turn
from trip_agent.compatibility import normalize_containers
from trip_agent.openrouter_model import OpenRouterChatModel
from trip_agent.persistence import ArtifactStore
from trip_agent.schemas import TripResponse


def test_schema_directed_decoding_preserves_strings_and_original():
    original = {'status': 'needs_clarification', 'message': '["This is literal user-facing text"]',
                'trip_state': '{"open_questions": "[\\"When?\\"]"}',
                'questions': '["When?"]', 'caveats': '["Mock data"]'}
    before = copy.deepcopy(original)
    value, changes = normalize_containers(original, TripResponse.model_json_schema())
    parsed = TripResponse.model_validate(value)
    assert parsed.questions == ['When?'] and parsed.trip_state.open_questions == ['When?']
    assert value['message'] == original['message']
    assert original == before
    assert {c['path'] for c in changes} == {'$.trip_state', '$.trip_state.open_questions', '$.questions', '$.caveats'}


@pytest.mark.parametrize('bad', ['[broken', 'null', '{"not": "a list"}', 'plain text'])
def test_invalid_containers_are_not_guessed(bad):
    original = {'status': 'needs_clarification', 'message': 'More information needed', 'trip_state': {}, 'questions': bad}
    value, changes = normalize_containers(original, TripResponse.model_json_schema())
    assert value == original and not changes
    with pytest.raises(ValidationError):
        TripResponse.model_validate(value)


def test_state_and_final_tools_decode_with_separate_immutable_audit_records(sessions, session):
    path = sessions.resolve('Test trip')
    config = sessions.metadata(path)['model_config']
    config.update(provider='openrouter', model_id='openrouter/free')
    sessions.update(path, model_config=config)
    store = ArtifactStore(path)

    def state():
        return {'destination': {'value': 'Porto', 'status': 'user_stated',
            'source_artifact_ids': json.dumps([store.list('requests')[0]['artifact_id']])}}

    def final(messages):
        return 'TripResponse', {'status': 'needs_clarification', 'message': 'Where are you departing from?',
            'trip_state': json.dumps(state()), 'questions': '["Where are you departing from?"]', 'caveats': '["Mock data"]'}

    result = run_turn(sessions, 'Test trip', 'Porto', output=io.StringIO(), model=ScriptedModel([
        lambda messages: ('update_trip_state', {'state': json.dumps(state())}), final]))
    assert result['response']['questions'] == ['Where are you departing from?']
    assert len(store.list('trip_states')) == 2
    corrections = [store.read(a['artifact_id']) for a in store.list('normalizations')]
    assert len(corrections) == 2
    for corrected in corrections:
        original = store.read(corrected['source_artifact_ids'][0])
        assert original['kind'] == 'tool_calls'
        field = 'state' if original['data']['name'] == 'update_trip_state' else 'questions'
        assert isinstance(original['data']['input'][field], str)
        assert isinstance(corrected['data']['effective_input'][field], (dict, list))


def test_bad_final_response_still_requires_model_correction(sessions, session):
    path = sessions.resolve('Test trip')
    config = sessions.metadata(path)['model_config']
    config.update(provider='openrouter', model_id='openrouter/free')
    sessions.update(path, model_config=config)
    run_turn(sessions, 'Test trip', 'Help', output=io.StringIO(), model=ScriptedModel([
        ('TripResponse', {}), clarification]))
    store = ArtifactStore(path)
    results = [store.read(a['artifact_id'])['data']['result'] for a in store.list('tool_results')]
    assert results[0]['status'] == 'error' and results[1]['status'] == 'success'
    assert not store.list('normalizations')


def test_reasoning_projection_preserves_memory_tool_calls_and_results(caplog):
    messages = [
        {'role': 'assistant', 'content': [{'reasoningContent': {'reasoningText': {'text': 'fixture'}}}]},
        {'role': 'assistant', 'content': [{'reasoningContent': {'reasoningText': {'text': 'fixture'}}},
            {'text': 'Looking up Porto'}, {'toolUse': {'name': 'search_destinations', 'toolUseId': 'call-1', 'input': {'destination_id': 'porto'}}}]},
        {'role': 'user', 'content': [{'toolResult': {'toolUseId': 'call-1', 'status': 'success', 'content': [{'text': 'Mock Porto result'}]}}]},
    ]
    before = copy.deepcopy(messages)
    formatted = OpenRouterChatModel.format_request_messages(messages)
    assert messages == before
    assert 'fixture' not in json.dumps(formatted)
    assert formatted[0]['tool_calls'][0]['id'] == 'call-1'
    assert any(m['role'] == 'tool' and m['tool_call_id'] == 'call-1' for m in formatted)
    assert 'reasoningContent is not supported' not in caplog.text
