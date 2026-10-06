"""Portable original evidence for evaluation; no model calls or local-path fallback."""

import copy
import uuid
from pathlib import Path

from trip_agent.config import AppError
from trip_agent.persistence import ArtifactStore


class EmbeddedEvidenceStore(ArtifactStore):
    def __init__(self, evidence):
        if evidence.get('version') != 1:
            raise AppError('Unsupported portable evidence version')
        self.session_id = evidence['session_id']
        self.records = {}
        for record in evidence['artifacts']:
            artifact_id = record['artifact_id']
            if str(uuid.UUID(artifact_id)) != artifact_id or record['session_id'] != self.session_id:
                raise AppError('Invalid or cross-session portable evidence')
            if artifact_id in self.records or record['kind'] not in ArtifactStore.KINDS:
                raise AppError('Duplicate or invalid portable artifact')
            self.records[artifact_id] = copy.deepcopy(record)

    def read(self, artifact_id):
        try:
            return copy.deepcopy(self.records[artifact_id])
        except KeyError:
            raise AppError(f'Portable evidence is missing artifact {artifact_id}') from None


def evidence_store(output):
    if 'evidence' in output:
        store = EmbeddedEvidenceStore(output['evidence'])
        if store.session_id != output.get('session_id'):
            raise AppError('Portable evidence belongs to a different output session')
        return store
    path = Path(output['session_path'])
    if not (path / 'session.json').is_file():
        raise AppError('Original session evidence is unavailable; use a portable evidence bundle')
    return ArtifactStore(path)
