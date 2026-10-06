"""Reviewer setup and real SDK protocol checks; HTTP responses here are offline fixtures."""

import json
import os
from pathlib import Path

import httpx
import openai
import pytest

from trip_agent.cli import main
from trip_agent.config import load_settings
from trip_agent.session import Sessions


@pytest.fixture(autouse=True)
def restore_credentials_after_dotenv(monkeypatch):
    # Register even absent variables so keys introduced by dotenv cannot leak to another test.
    for name in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.setenv(name, os.environ.get(name, ''))


@pytest.mark.parametrize(('provider', 'model_id', 'key'), [
    ('openai', 'gpt-6.1-sol', 'OPENAI_API_KEY'),
    ('openrouter', 'openrouter/free', 'OPENROUTER_API_KEY'),
    ('anthropic', 'configured-claude', 'ANTHROPIC_API_KEY'),
    ('bedrock', 'configured-bedrock', None),
])
def test_initialize_check_and_create_session_per_provider(tmp_path, monkeypatch, capsys, provider, model_id, key):
    monkeypatch.chdir(tmp_path)
    if key:
        monkeypatch.delenv(key, raising=False)
    assert main(['config', 'init', '--provider', provider, '--model', model_id]) == 0
    capsys.readouterr()
    assert main(['config', 'check']) == (1 if key else 0)
    if key:
        assert key in capsys.readouterr().err
        (tmp_path / '.env').write_text(f'{key}=offline-test-key\n')
        assert main(['config', 'check']) == 0
    capsys.readouterr()
    assert main(['session', 'create', '--name', 'Reviewer trip']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['model_config']['provider'] == provider
    assert record['model_config']['model_id'] == model_id
    assert 'offline-test-key' not in json.dumps(record)
    if provider == 'bedrock':
        assert record['model_config']['region'] == 'us-west-2'


def test_openrouter_key_is_separate_and_shell_takes_precedence(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-openai-key')
    assert main(['config', 'init', '--provider', 'openrouter', '--model', 'openrouter/free']) == 0
    assert main(['config', 'check']) == 1
    assert 'OPENROUTER_API_KEY' in capsys.readouterr().err
    (tmp_path / '.env').write_text('OPENROUTER_API_KEY=file-test-key\n')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'shell-test-key')
    settings = load_settings(tmp_path / 'trip-agent.toml')
    from trip_agent.models import build_model
    model = build_model(settings.select()[1])
    assert model.client_args['api_key'] == 'shell-test-key'


def test_profile_selection_preserves_default_and_existing_session(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / 'trip-agent.toml'
    assert main(['config', 'init']) == 0
    with config.open('a') as file:
        file.write('\n[profiles.router_free]\nprovider="openrouter"\nmodel_id="openrouter/free"\n')
    assert main(['session', 'create', '--name', 'OpenAI trip']) == 0
    capsys.readouterr()
    assert main(['session', 'create', '--name', 'Router trip', '--profile', 'router_free']) == 0
    router = json.loads(capsys.readouterr().out)
    assert router['active_profile'] == 'router_free'
    assert router['model_config']['provider'] == 'openrouter'
    sessions = Sessions(tmp_path / '.trip-agent')
    assert sessions.metadata(sessions.resolve('OpenAI trip'))['model_config']['provider'] == 'openai'
    assert load_settings(config).default_profile == 'openai'
    assert main(['config', 'check', '--profile', 'unknown']) == 1
    assert 'Unknown profile' in capsys.readouterr().err


def test_openrouter_full_cli_through_real_sdk_with_mock_http(tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    (tmp_path / '.env').write_text('OPENROUTER_API_KEY=offline-router-key\n')
    model_id = 'openrouter/free'
    assert main(['config', 'init', '--provider', 'openrouter', '--model', model_id]) == 0
    assert main(['config', 'check']) == 0
    assert main(['session', 'create', '--name', 'SDK check']) == 0
    calls = []

    def respond(request):
        assert request.url.host == 'openrouter.ai'
        assert request.url.path == '/api/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer offline-router-key'
        data = json.loads(request.content)
        calls.append(data)
        assert data['model'] == model_id
        assert data['provider']['require_parameters'] is True
        assert data['stream'] is True
        assert 'reasoningContent' not in json.dumps(data['messages'])
        assert 'offline reasoning fixture' not in json.dumps(data['messages'])
        names = {tool['function']['name'] for tool in data['tools']}
        assert {'search_destinations', 'TripResponse'} <= names
        if len(calls) == 1:
            name, inputs = 'search_destinations', {'destination_id': 'porto'}
        else:
            results = [m for m in data['messages'] if m['role'] == 'tool']
            assert results and 'porto' in json.dumps(results).lower()
            assert 'Evidence artifact ID:' in json.dumps(results)
            name, inputs = 'TripResponse', {'status': 'needs_clarification',
                'message': 'Porto is in the mock catalog.', 'trip_state': {},
                'questions': '["Where are you departing from?"]', 'caveats': '["Mock catalog only"]'}
        chunks = [
            {'choices': [{'index': 0, 'delta': {'reasoning': 'offline reasoning fixture'}, 'finish_reason': None}]},
            {'choices': [{'index': 0, 'delta': {'role': 'assistant', 'tool_calls': [{
                'index': 0, 'id': f'call-{len(calls)}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(inputs)}}]}, 'finish_reason': None}]},
            {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]},
        ]
        events = ''.join('data: ' + json.dumps({'id': 'offline-stream', 'object': 'chat.completion.chunk',
            'created': 1, 'model': f'offline-routed-model-{len(calls)}', **chunk}) + '\n\n' for chunk in chunks)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=events + 'data: [DONE]\n\n')

    original_client = openai.AsyncOpenAI
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: original_client(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    capsys.readouterr()
    assert main(['run', '--session', 'SDK check', '--json', 'Look up Porto and ask where I depart from.']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['response']['status'] == 'needs_clarification'
    assert len(calls) == 2
    assert main(['run', '--session', 'SDK check', '--json', 'Continue this saved conversation.']) == 0
    assert json.loads(capsys.readouterr().out)['response']['status'] == 'needs_clarification'
    assert len(calls) == 3
    sessions = Sessions(Path('.trip-agent'))
    path = sessions.resolve('SDK check')
    assert list((path / 'artifacts' / 'tool_results').glob('*.json'))
    assert list((path / 'logbooks').glob('*.html'))
    assert list((path / 'artifacts' / 'normalizations').glob('*.json'))
    responses = [json.loads(file.read_text()) for file in (path / 'artifacts' / 'model_responses').glob('*.json')]
    assert 'reasoningContent' in json.dumps(responses)
    assert 'reasoningContent is not supported' not in caplog.text
    identities = [r['data']['provider_responses'] for r in responses]
    assert {item['model'] for group in identities for item in group} == {
        'offline-routed-model-1', 'offline-routed-model-2', 'offline-routed-model-3'}
    assert all(len(group) == 1 for group in identities)
