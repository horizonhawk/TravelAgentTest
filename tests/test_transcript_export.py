"""The process export copies real records and documents exclusions/redactions."""

import json

import pytest

from scripts.export_transcript import export


def test_transcript_preserves_conversation_and_tool_order_without_private_records(tmp_path):
    source = tmp_path / 'source.jsonl'
    rows = [
        {'type': 'session_meta', 'payload': {'base_instructions': 'internal instructions'}},
        {'type': 'response_item', 'timestamp': '1', 'payload': {'type': 'message', 'role': 'user',
          'content': [{'type': 'input_text', 'text': 'Please test this exact prompt.'}]}},
        {'type': 'response_item', 'timestamp': '2', 'payload': {'type': 'reasoning', 'text': 'private reasoning'}},
        {'type': 'response_item', 'timestamp': '3', 'payload': {'type': 'custom_tool_call_output',
          'output': 'test-secret-credential'}},
        {'type': 'response_item', 'timestamp': '4', 'payload': {'type': 'message', 'role': 'assistant',
          'content': [{'type': 'output_text', 'text': 'The test failed; no success is claimed.'}]}},
    ]
    source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    original = source.read_bytes()
    env = tmp_path / '.env'
    env.write_text('OPENAI_API_KEY=test-secret-credential\n')
    destination = tmp_path / 'export'
    manifest = export(source, destination, env)
    records = [json.loads(line) for line in (destination / 'transcript.jsonl').read_text().splitlines()]
    assert [r['source_line'] for r in records] == [2, 4, 5]
    assert records[0]['payload']['content'][0]['text'] == 'Please test this exact prompt.'
    assert records[-1]['payload']['content'][0]['text'] == 'The test failed; no success is claimed.'
    text = (destination / 'transcript.jsonl').read_text()
    assert 'test-secret-credential' not in text and 'private reasoning' not in text
    assert manifest['redactions']['credential_values'] == 1
    assert source.read_bytes() == original
    with pytest.raises(ValueError, match='never overwritten'):
        export(source, destination, env)
