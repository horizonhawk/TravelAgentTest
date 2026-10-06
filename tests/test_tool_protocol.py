import io
import json

import pytest

from conftest import ScriptedModel, clarification
from trip_agent.agent import run_turn
from trip_agent.config import AppError
from trip_agent.persistence import ArtifactStore
from trip_agent.prompts import STRUCTURED_OUTPUT_PROMPT


MARKUP = '<tool_call>TripResponse\n<arg_key>trip_state</arg_key>\n<arg_value>'


def test_printed_tool_markup_uses_sdk_correction_without_executing_text(sessions, session):
    model = ScriptedModel([('__text__', MARKUP), clarification])
    display = io.StringIO()
    response = run_turn(sessions, 'Test trip', 'Help me plan', model=model, output=display)
    assert response['response']['status'] == 'needs_clarification'
    assert len(model.seen_messages) == 2
    assert model.seen_choices[-1] == {'tool': {'name': 'TripResponse'}}
    assert STRUCTURED_OUTPUT_PROMPT in json.dumps(model.seen_messages[-1]).replace('\\n', '\n')
    assert MARKUP not in display.getvalue()
    assert 'not executed' in display.getvalue()
    store = ArtifactStore(sessions.resolve('Test trip'))
    assert len(store.list('tool_calls')) == 1  # Only the real native call.
    originals = [store.read(a['artifact_id']) for a in store.list('model_responses')]
    assert any(MARKUP in json.dumps(r).replace('\\n', '\n') for r in originals)
    assert store.list('errors')  # Diagnostic persists even though correction succeeded.


def test_repeated_markup_fails_truthfully_preserves_evidence_and_can_resume(sessions, session):
    model = ScriptedModel([('__text__', MARKUP), ('__text__', MARKUP)])
    with pytest.raises(AppError, match='model/tool-protocol failure'):
        run_turn(sessions, 'Test trip', 'Help', model=model, output=io.StringIO())
    store = ArtifactStore(sessions.resolve('Test trip'))
    assert len(model.seen_messages) == 2
    assert not store.list('tool_calls') and not store.list('final_responses')
    assert len(store.list('model_responses')) == 2
    assert sessions.metadata(store.path)['status'] == 'failed'
    result = run_turn(sessions, 'Test trip', 'Please try again', model=ScriptedModel([clarification]), output=io.StringIO())
    assert result['session_id'] == session['session_id']
    assert len(store.list('requests')) == 2
