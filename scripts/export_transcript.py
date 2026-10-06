"""Export genuine user/assistant/tool records from a local Codex JSONL session.

Private reasoning, system/developer instructions, telemetry and duplicate events
are excluded. Content is never reconstructed. Redactions are counted in a manifest.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values


def export(source, destination, env_file):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Choose a new export directory; existing exports are never overwritten')
    raw = source.read_bytes()  # A consistent snapshot even while the conversation continues.
    records, omitted, redactions = [], Counter(), Counter()
    secrets = [value for value in dotenv_values(env_file).values() if value and len(value) >= 8]

    def redact(text):
        for secret in secrets:
            redactions['credential_values'] += text.count(secret)
            text = text.replace(secret, '[REDACTED_CREDENTIAL]')
        text, count = re.subn(r'\b(?:sk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,})\b',
                              '[REDACTED_CREDENTIAL]', text)
        redactions['credential_patterns'] += count
        home = str(Path.home())
        redactions['home_path'] += text.count(home)
        return text.replace(home, '<USER_HOME>')

    for line_number, line in enumerate(raw.splitlines(), 1):
        row = json.loads(line)
        payload = row.get('payload', {})
        kind = payload.get('type')
        keep = row.get('type') == 'response_item' and (
            kind in {'function_call', 'function_call_output', 'custom_tool_call', 'custom_tool_call_output'} or
            (kind == 'message' and payload.get('role') in {'user', 'assistant'}
             and payload.get('channel') not in {'analysis', 'summary'}))
        if not keep:
            omitted[f"{row.get('type')}:{kind}:{payload.get('role', '')}"] += 1
            continue
        records.append(json.loads(redact(json.dumps({'source_line': line_number, 'timestamp': row.get('timestamp'),
                                                     'payload': payload}, ensure_ascii=False))))
    destination.mkdir(parents=True)
    with (destination / 'transcript.jsonl').open('x') as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')
    with (destination / 'conversation.md').open('x') as file:
        file.write('# Genuine coding conversation\n\nExported in source order. Tool records are in `transcript.jsonl`. '
                   'Credentials and home paths are redacted; internal reasoning/instructions/telemetry are omitted.\n\n')
        for record in records:
            payload = record['payload']
            if payload.get('type') != 'message':
                continue
            text = '\n'.join(block.get('text', '') for block in payload.get('content', []) if isinstance(block, dict))
            file.write(f"## {payload['role']} · {record['timestamp']} · source line {record['source_line']}\n\n{text}\n\n")
    manifest = {'exported_at': datetime.now(timezone.utc).isoformat(), 'source_filename': source.name,
        'source_snapshot_sha256': hashlib.sha256(raw).hexdigest(), 'source_snapshot_bytes': len(raw),
        'last_record_timestamp': records[-1]['timestamp'] if records else None,
        'records_included': len(records), 'omitted_record_counts': dict(omitted), 'redactions': dict(redactions),
        'files_sha256': {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                        for name in ['transcript.jsonl', 'conversation.md']},
        'authenticity': 'Filtered export of original records, not a reconstruction or a verbatim raw-session file. '
                        'No user/assistant response text was authored to fill gaps. Snapshot cutoff is explicit.'}
    with (destination / 'manifest.json').open('x') as file:
        json.dump(manifest, file, indent=2)
        file.write('\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    args = parser.parse_args()
    result = export(args.source, args.output, args.env_file)
    print(json.dumps({'output': str(args.output), 'records': result['records_included'], 'redactions': result['redactions']}))
