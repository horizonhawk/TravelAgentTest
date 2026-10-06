"""Session-local evidence. Completed artifacts are immutable JSON records."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppError


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: Any, *, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Same-directory hard link publishes a complete file and fails if it exists.
            # Unlike replace(), a UUID collision cannot overwrite historical evidence.
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ArtifactStore:
    KINDS = {"requests", "prompt_configs", "model_inputs", "model_responses", "tool_calls",
             "tool_results", "trip_states", "final_responses", "errors", "normalizations"}

    def __init__(self, session_path: Path, turn_id: str | None = None, secrets: list[str] | None = None):
        self.path = session_path
        self.session_id = session_path.name
        self.turn_id = turn_id
        self.secrets = [value for value in secrets or [] if value]

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        return value

    def event(self, event: str, **data) -> None:
        record = self.redact({"timestamp": now(), "session_id": self.session_id,
                              "turn_id": self.turn_id, "event": event, **data})
        with (self.path / "events.jsonl").open("a") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
        # A derived human view must never turn a successful agent operation into a failure.
        if event in {"session_created", "session_renamed", "session_deleted", "session_restored",
                     "turn_completed", "turn_failed", "turn_interrupted"}:
            from .logbook import write_logbook
            try:
                write_logbook(self.path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                import warnings
                warnings.warn(f"Logbook edition failed ({type(exc).__name__}); source artifacts remain saved. "
                              "Generate with: trip-agent logbook --session <session-id>", stacklevel=2)

    def save(self, kind: str, data: Any, *, sources: list[str] | None = None) -> str:
        if kind not in self.KINDS:
            raise AppError(f"Unsupported artifact kind: {kind}")
        artifact_id = str(uuid.uuid4())
        record = self.redact({"schema_version": 1, "artifact_id": artifact_id, "kind": kind,
                              "session_id": self.session_id, "turn_id": self.turn_id,
                              "created_at": now(), "source_artifact_ids": sources or [], "data": data})
        target = self.path / "artifacts" / kind / f"{artifact_id}.json"
        # UUID filenames are never reused. The index is derived and can be rebuilt.
        atomic_json(target, record, replace=False)
        self.reindex()
        self.event("artifact_saved", artifact_id=artifact_id, kind=kind)
        return artifact_id

    def reindex(self) -> list[dict]:
        entries = []
        for file in (self.path / "artifacts").glob("*/*.json"):
            if file.is_symlink():
                continue
            record = json.loads(file.read_text())
            entries.append({k: record[k] for k in ("artifact_id", "kind", "turn_id", "created_at")})
        entries.sort(key=lambda entry: (entry["created_at"], entry["artifact_id"]))
        atomic_json(self.path / "artifact_index.json", entries)
        return entries

    def list(self, kind: str | None = None, turn_id: str | None = None) -> list[dict]:
        entries = self.reindex()
        return [entry for entry in entries if (not kind or entry["kind"] == kind)
                and (not turn_id or entry["turn_id"] == turn_id)]

    def read(self, artifact_id: str) -> dict:
        try:
            if str(uuid.UUID(artifact_id)) != artifact_id:
                raise ValueError()
        except (ValueError, AttributeError):
            raise AppError("Artifact IDs must be canonical UUIDs") from None
        for kind in self.KINDS:
            path = self.path / "artifacts" / kind / f"{artifact_id}.json"
            if path.is_file() and not path.is_symlink():
                record = json.loads(path.read_text())
                if record["session_id"] != self.session_id:
                    raise AppError("Artifact does not belong to this session")
                return record
        raise AppError(f"Artifact {artifact_id} was not found in this session")

    def validate_state(self, state) -> None:
        facts = [state.origin, state.destination, state.dates, state.duration, state.travelers,
                 state.budget, *state.preferences, *state.exclusions]
        for fact in facts:
            for artifact_id in fact.source_artifact_ids:
                source = self.read(artifact_id)
                if fact.status == "user_stated" and source["kind"] != "requests":
                    raise AppError("User-stated facts must cite original user request artifacts")

    def save_state(self, state) -> str:
        self.validate_state(state)
        previous = self.path / "current_trip.json"
        sources = [json.loads(previous.read_text())["artifact_id"]] if previous.exists() else []
        artifact_id = self.save("trip_states", state.model_dump(mode="json"), sources=sources)
        atomic_json(previous, {"artifact_id": artifact_id, "state": state.model_dump(mode="json")})
        return artifact_id
