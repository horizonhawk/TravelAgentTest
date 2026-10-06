"""Export an existing run as a portable, immutable evidence bundle; never regenerate answers."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from trip_agent.config import AppError
from trip_agent.persistence import ArtifactStore, atomic_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_run(run, destination):
    run, destination = Path(run), Path(destination)
    if destination.exists():
        raise AppError('Choose a new bundle directory; existing exports are never overwritten')
    outputs = json.loads((run / 'outputs.json').read_text())
    original = json.loads((run / 'summary.json').read_text())
    current_cases = {c['name']: c for c in json.loads(Path(__file__).with_name('cases.json').read_text())}
    original_cases = {c['name']: c for c in original['cases']}
    cases, exported = [], copy.deepcopy(outputs)
    for name, output in exported.items():
        case = current_cases.get(name)
        if case is None or case['input'] != original_cases[name]['input']:
            raise AppError(f'Cannot export {name}: case input changed or is unavailable')
        cases.append(case)
        store = ArtifactStore(Path(output['session_path']))
        # No memory, private model reasoning, secrets/config file, or personal manual sessions.
        kinds = {'requests', 'tool_calls', 'tool_results', 'trip_states', 'final_responses',
                 'normalizations', 'prompt_configs', 'errors'}
        records = [store.read(r['artifact_id']) for r in store.list() if r['kind'] in kinds]
        output['evidence'] = {'version': 1, 'session_id': store.session_id, 'artifacts': records}
        output.pop('session_path', None)
        for kind in ['tool_calls', 'tool_results']:
            output[kind] = [r for r in records if r['kind'] == kind]
    destination.mkdir(parents=True)
    atomic_json(destination / 'cases.json', cases, replace=False)
    atomic_json(destination / 'outputs.json', exported, replace=False)
    atomic_json(destination / 'manifest.json', {
        'bundle_version': 1, 'source_run_id': original['run_id'], 'source_mode': original['mode'],
        'source_sha256': {name: digest(run / name) for name in ['outputs.json', 'summary.json']},
        'files_sha256': {name: digest(destination / name) for name in ['cases.json', 'outputs.json']},
        'case_names': list(exported), 'original_evaluation_version': original.get('evaluation_version', 1),
        'description': 'Original generated outputs and selected original evidence, repackaged without local session paths. '
                       'Cases use current evaluator metadata; replay is a rescore, not a new model run. '
                       'Hashes detect accidental edits, not cryptographic provenance or tamper-proof storage.'
    }, replace=False)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(export_run(args.run, args.output))
    except (AppError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Export failed: {exc}\n')


if __name__ == '__main__':
    main()
