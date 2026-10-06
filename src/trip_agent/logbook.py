"""A self-contained, rebuildable human view of a session's source artifacts."""

import html
import json
import os
import tempfile
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


def escape(value):
    return html.escape(str(value), quote=True)


def pretty(value):
    return '<pre>' + escape(json.dumps(value, indent=2, ensure_ascii=False)) + '</pre>'


def details(label, content):
    return f'<details><summary>{escape(label)}</summary>{content}</details>'


def prose(value):
    return f'<div class="prose">{escape(value)}</div>'


def facts(state):
    rows = []
    for name, value in state.items():
        if isinstance(value, dict):
            text = f"{value.get('value') or 'Unknown'} [{value.get('status', 'unknown')}]"
        elif isinstance(value, list):
            text = '\n'.join(f"{v.get('value')} [{v.get('status', 'unknown')}]" if isinstance(v, dict)
                             else str(v) for v in value) or 'None recorded'
        else:
            text = str(value)
        rows.append(f'<tr><th>{escape(name.replace("_", " ").title())}</th><td>{prose(text)}</td></tr>')
    return '<table>' + ''.join(rows) + '</table>'


def response_view(data):
    parts = [prose(data.get('message', ''))]
    for suggestion in data.get('suggestions', []):
        parts += [f'<h4>{escape(suggestion.get("destination_id", "Suggestion"))}</h4>',
                  prose(suggestion.get('reasoning', '')), prose('Budget: ' + suggestion.get('rough_budget', ''))]
        if suggestion.get('caveats'):
            parts.append(details('Suggestion caveats', prose('\n'.join(suggestion['caveats']))))
    message = ' '.join(data.get('message', '').casefold().split())
    questions = [q for q in data.get('questions', []) if ' '.join(q.casefold().split()) not in message]
    if questions:
        parts += ['<h4>To continue</h4>', prose('\n'.join(dict.fromkeys(questions)))]
    for field in ('assumptions', 'caveats'):
        if data.get(field):
            parts.append(details(field.title(), prose('\n'.join(data[field]))))
    return ''.join(parts)


def artifact_view(record, previous_state):
    kind, data = record['kind'], record['data']
    identifier = record['artifact_id']
    label = kind.replace('_', ' ').title()
    body = ''
    css = 'evidence'
    if kind == 'requests':
        label, css, body = 'You', 'user', prose(data['text'])
    elif kind == 'final_responses':
        label, css = 'Agent · ' + data.get('status', '').replace('_', ' '), 'agent'
        body = response_view(data)
    elif kind == 'model_responses':
        text = '\n\n'.join(b['text'] for b in data.get('message', {}).get('content', []) if b.get('text'))
        label = 'Agent · intermediate response'
        body = prose(text) if text else '<p class="muted">Model selected tools or structured output.</p>'
    elif kind == 'tool_calls':
        label = 'Tool call · ' + data['name']
        body = details('Arguments · ' + data.get('toolUseId', ''), pretty(data['input']))
    elif kind == 'tool_results':
        from .terminal import readable_tool_result
        result = data['result']
        label = 'Tool result · ' + data['tool_name'] + ' · ' + result.get('status', 'unknown')
        body = details('Full returned result', pretty(readable_tool_result(result)))
    elif kind == 'trip_states':
        changed = {key: {'before': previous_state.get(key), 'after': value} for key, value in data.items()
                   if previous_state.get(key) != value}
        body = details('State changes · ' + (', '.join(changed) or 'no changes'), pretty(changed))
        body += details('Complete state at this point', facts(data))
        previous_state = data
    elif kind == 'normalizations':
        label = 'Compatibility adjustment · ' + data['tool_name']
        body = details('Schema-directed JSON decoding', pretty(data['changes']))
        body += details('Effective tool arguments', pretty(data['effective_input']))
    elif kind == 'errors':
        label, css, body = 'Error · ' + data.get('type', 'failure'), 'error', prose(data.get('message', ''))
    else:
        body = '<p class="muted">Technical context retained below in the complete source record.</p>'
    links = ' '.join(f'<a href="#artifact-{escape(source)}">{escape(source)}</a>'
                     for source in record.get('source_artifact_ids', []))
    source = ('<p>Source records: ' + links + '</p>') if links else ''
    raw = details('Complete source record · ' + identifier, source + pretty(record))
    content = (f'<article class="{css}" id="artifact-{escape(identifier)}"><h3>{escape(label)}</h3>'
               f'<div class="meta">{escape(record["created_at"])} · {escape(identifier)}</div>{body}{raw}</article>')
    # Keep the conversation readable while retaining every diagnostic record inline.
    if kind in {'prompt_configs', 'model_inputs', 'model_responses', 'tool_calls', 'tool_results', 'trip_states', 'normalizations'}:
        content = details(label + ' · ' + record['created_at'], content)
    return content, previous_state


STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;line-height:1.6}
body{max-width:1050px;margin:auto;padding:32px;background:#f6f8fb;color:#202b3b}
h1,h2,h3,h4{line-height:1.3}h1{margin-bottom:8px}h3{margin:0 0 6px}
a{color:#126a91;overflow-wrap:anywhere}header,section{margin-bottom:28px}
.meta,.muted{font-size:.85rem;color:#536276;overflow-wrap:anywhere}
.prose{white-space:pre-wrap;overflow-wrap:anywhere;margin:10px 0}
article,.overview{background:white;border:1px solid #dbe2eb;border-radius:10px;padding:18px;margin:14px 0}
.user{border-left:5px solid #73849e}.agent{border-left:5px solid #078299}.error{border-left:5px solid #c24343}
details{padding:8px 12px;margin:7px 0;background:#edf1f6;border-radius:6px}
summary{cursor:pointer;font-size:.9rem;font-weight:600;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem;line-height:1.5;tab-size:2}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;vertical-align:top;padding:7px;border-bottom:1px solid #dbe2eb}th{width:150px}
nav ol{padding-left:24px}.badge{font-size:.8rem;font-weight:normal;margin-left:12px}
@media(prefers-color-scheme:dark){body{background:#111a24;color:#e3eaf3}article,.overview{background:#172332;border-color:#354558}details{background:#202f40}.meta,.muted{color:#b0bfd1}a{color:#7ad5ed}th,td{border-color:#354558}}
@media print{body{background:white;color:black;max-width:none;padding:0}article{break-inside:avoid}}
"""


def render_logbook(path: Path):
    metadata = json.loads((path / 'session.json').read_text())
    records = []
    for file in (path / 'artifacts').glob('*/*.json'):
        if not file.is_symlink():
            record = json.loads(file.read_text())
            if record['session_id'] == metadata['session_id']:
                records.append(record)
    records.sort(key=lambda r: (r['created_at'], r['artifact_id']))
    events = []
    event_path = path / 'events.jsonl'
    if event_path.exists():
        for line in event_path.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    groups = OrderedDict()
    for record in records:
        groups.setdefault(record.get('turn_id'), []).append(record)
    for event in events:
        if event.get('turn_id'):
            groups.setdefault(event['turn_id'], [])
    def start(item):
        turn, items = item
        timestamps = [r['created_at'] for r in items]
        timestamps += [e['timestamp'] for e in events if e.get('turn_id') == turn]
        return min(timestamps, default=metadata['created_at'])
    groups = OrderedDict(sorted(groups.items(), key=start))
    nav, sections = [], []
    previous_state = {}
    for index, (turn, items) in enumerate(groups.items(), 1):
        turn_events = [e for e in events if e.get('turn_id') == turn and e['event'] != 'artifact_saved']
        status = 'partial / no completion recorded'
        for event in turn_events:
            if event['event'] in {'turn_completed', 'turn_failed', 'turn_interrupted'}:
                status = event['event'].replace('turn_', '')
        request = next((r['data']['text'] for r in items if r['kind'] == 'requests'), 'Session records')
        nav.append(f'<li><a href="#turn-{index}">{escape(request[:100])}</a> <span class="badge">{escape(status)}</span></li>')
        body = []
        for record in items:
            content, previous_state = artifact_view(record, previous_state)
            body.append(content)
        sections.append(f'<section id="turn-{index}"><h2>Turn {index} <span class="badge">{escape(status)}</span></h2>'
                        f'<p class="meta">{escape(turn or "Session-level records")}</p>' + ''.join(body)
                        + details('Turn lifecycle', pretty(turn_events)) + '</section>')
    profile = metadata.get('model_config', {})
    header = (f'<header><h1>Agent logbook · {escape(metadata["name"])}</h1>'
              f'<p class="meta">Session {escape(metadata["session_id"])} · {escape(metadata["status"])}<br>'
              f'{escape(profile.get("provider", ""))} / {escape(profile.get("model_id", ""))} · '
              f'{len(groups)} turns · {len(records)} source records</p>'
              '<p>Complete saved history in one file. Read the conversation, then expand diagnostics for full JSON, '
              'model context, state changes, and evidence. Dates include timezone offsets. '
              'This immutable edition is generated from recorded evidence, without an LLM summary. '
              'Later turns produce new editions; this file does not change.</p></header>')
    overview = '<div class="overview"><h2>Latest recorded trip state</h2>' + (facts(previous_state) if previous_state else '<p>No trip state recorded yet.</p>') + '</div>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>Agent logbook · ' + escape(metadata['name']) + '</title><style>' + STYLE + '</style></head><body>'
            + header + overview + '<nav><h2>Conversation history</h2><ol>' + ''.join(nav) + '</ol></nav>'
            + ''.join(sections) + details('Complete session metadata', pretty(metadata))
            + details('Complete event timeline', pretty(events)) + '</body></html>')


def write_logbook(path: Path) -> Path:
    """Caller holds the session lock. Publish a new immutable edition, never replace one."""
    document = render_logbook(path)
    directory = path / 'logbooks'
    directory.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = directory / f'{timestamp}-{uuid.uuid4()}.html'
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.writing-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(document)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
