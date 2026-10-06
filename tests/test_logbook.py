import json
import uuid

import pytest

from trip_agent.logbook import write_logbook
from trip_agent.persistence import ArtifactStore
from trip_agent.schemas import Fact, TripState


def test_logbook_integrates_turns_and_keeps_previous_editions(sessions, session):
    path = sessions.resolve('Test trip')
    store = ArtifactStore(path, 'turn-1')
    request = store.save('requests', {'text': 'Leaving JFK <script>alert(1)</script>'})
    state = TripState(origin=Fact(value='JFK', status='user_stated', source_artifact_ids=[request]))
    state_id = store.save_state(state)
    store.save('tool_calls', {'name': 'search_destinations', 'toolUseId': 'call-1', 'input': {'tags': ['food']}})
    result_id = store.save('tool_results', {'tool_name': 'search_destinations', 'result': {
        'status': 'success', 'content': [{'text': json.dumps({'status': 'ok', 'destinations': [{'id': 'porto'}]})}]}})
    store.save('final_responses', {'message': 'Consider Porto.', 'status': 'suggestions'})
    store.event('turn_completed')
    first = sorted((path / 'logbooks').glob('*.html'))[-1]
    original = first.read_bytes()
    assert 'Consider Porto.' in original.decode()
    assert result_id in original.decode()
    assert '&lt;script&gt;' in original.decode()
    assert '<script>' not in original.decode()
    store = ArtifactStore(path, 'turn-2')
    correction = store.save('requests', {'text': 'Actually SFO'})
    store.save_state(TripState(origin=Fact(value='SFO', status='user_stated', source_artifact_ids=[correction])))
    store.save('errors', {'type': 'ConnectionError', 'message': 'Unavailable'})
    store.event('turn_failed')
    latest = sorted((path / 'logbooks').glob('*.html'))[-1].read_text()
    assert first.read_bytes() == original
    assert 'Consider Porto.' in latest and 'Actually SFO' in latest and 'Unavailable' in latest
    assert 'failed' in latest and 'completed' in latest
    assert latest.index('id="artifact-' + request) < latest.index('id="artifact-' + correction)
    assert state_id in latest and 'State changes' in latest


def test_artifact_collision_never_overwrites_saved_evidence(sessions, session, monkeypatch):
    store = ArtifactStore(sessions.resolve('Test trip'), 'turn-1')
    original_id = store.save('requests', {'text': 'Keep this original'})
    original = (store.path / 'artifacts' / 'requests' / f'{original_id}.json').read_bytes()
    events = (store.path / 'events.jsonl').read_bytes()
    monkeypatch.setattr('trip_agent.persistence.uuid.uuid4', lambda: uuid.UUID(original_id))
    with pytest.raises(FileExistsError):
        store.save('requests', {'text': 'Must not replace it'})
    assert (store.path / 'artifacts' / 'requests' / f'{original_id}.json').read_bytes() == original
    assert (store.path / 'events.jsonl').read_bytes() == events


def test_generate_editions_without_mutating_sources_and_preserve_on_restore(sessions, session):
    path = sessions.resolve('Test trip')
    store = ArtifactStore(path, 'turn-1')
    record = store.save('requests', {'text': 'Original request'})
    source = path / 'artifacts' / 'requests' / f'{record}.json'
    original = source.read_bytes()
    events = (path / 'events.jsonl').read_bytes()
    first, second = write_logbook(path), write_logbook(path)
    assert first != second and first.read_bytes() == second.read_bytes()
    assert source.read_bytes() == original and (path / 'events.jsonl').read_bytes() == events
    sessions.move('Test trip')
    sessions.move(session['session_id'], restore=True)
    assert first.is_file() and second.is_file() and source.read_bytes() == original
