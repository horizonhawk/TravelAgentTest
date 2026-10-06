"""Stable session identity, explicit lifecycle, and process-safe local locks."""

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import AppError, Profile
from .persistence import ArtifactStore, atomic_json, now


class Sessions:
    def __init__(self, root: Path):
        self.root = root.resolve()
        for name in ("sessions", "trash", "locks"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self, key: str):
        # Lock filenames are internal UUIDs or the fixed registry key, never user paths.
        if key != "registry":
            key = str(uuid.UUID(key))
        with (self.root / "locks" / f"{key}.lock").open("a+b") as file:
            try:
                if os.name == "nt":
                    import msvcrt
                    file.seek(0)
                    if not file.read(1):
                        file.write(b"0")
                        file.flush()
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise AppError("Session or registry is busy in another process; try again after it finishes.") from None
            try:
                yield
            finally:
                if os.name == "nt":
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def list(self, deleted: bool = False) -> list[dict]:
        parent = self.root / ("trash" if deleted else "sessions")
        records = []
        for directory in parent.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            path = directory / "session.json"
            if path.exists():
                records.append(json.loads(path.read_text()))
        return sorted(records, key=lambda record: record["created_at"])

    def resolve(self, reference: str, deleted: bool = False) -> Path:
        records = self.list(deleted)
        matches = [r for r in records if r["session_id"] == reference]
        if not matches:
            matches = [r for r in records if r["name"].casefold() == reference.casefold()]
        if len(matches) != 1:
            reason = "Unknown" if not matches else "Ambiguous"
            raise AppError(f"{reason} session '{reference}'. Use session list and the full ID.")
        return self.root / ("trash" if deleted else "sessions") / matches[0]["session_id"]

    @staticmethod
    def metadata(path: Path) -> dict:
        file = path / "session.json"
        if not file.exists():
            raise AppError("Session was moved or deleted; list sessions again")
        return json.loads(file.read_text())

    @staticmethod
    def update(path: Path, **changes) -> dict:
        metadata = Sessions.metadata(path)
        metadata.update(changes, updated_at=now())
        atomic_json(path / "session.json", metadata)
        return metadata

    def create(self, name: str, profile_name: str, profile: Profile) -> dict:
        if not name.strip() or len(name) > 100:
            raise AppError("Session name must contain 1–100 characters")
        name = name.strip()
        with self.lock("registry"):
            if any(r["name"].casefold() == name.casefold() for r in self.list()):
                raise AppError(f"A session named '{name}' already exists; resume it or choose another name.")
            session_id = str(uuid.uuid4())
            path = self.root / "sessions" / session_id
            path.mkdir()
            record = {"schema_version": 1, "session_id": session_id, "name": name,
                      "created_at": now(), "updated_at": now(), "status": "ready",
                      "active_profile": profile_name, "model_config": profile.model_dump(mode="json"),
                      "latest_turn_id": None}
            atomic_json(path / "session.json", record)
            ArtifactStore(path).event("session_created", profile=profile_name, model_config=record["model_config"])
            return record

    def rename(self, reference: str, name: str) -> dict:
        if not name.strip() or len(name) > 100:
            raise AppError("Session name must contain 1–100 characters")
        with self.lock("registry"):
            path = self.resolve(reference)
            with self.lock(path.name):
                if any(r["name"].casefold() == name.strip().casefold() and r["session_id"] != path.name for r in self.list()):
                    raise AppError("That session name is already in use")
                old_name = self.metadata(path)["name"]
                record = self.update(path, name=name.strip())
                ArtifactStore(path).event("session_renamed", old_name=old_name, name=name.strip())
                return record

    def move(self, reference: str, restore: bool = False) -> dict:
        with self.lock("registry"):
            path = self.resolve(reference, deleted=restore)
            with self.lock(path.name):
                metadata = self.metadata(path)
                if restore and any(r["name"].casefold() == metadata["name"].casefold() for r in self.list()):
                    raise AppError("An active session has this name; rename it before restoring")
                target = self.root / ("sessions" if restore else "trash") / path.name
                if target.exists():
                    raise AppError("Destination session already exists")
                if restore:
                    metadata = self.update(path, status=metadata.get("status_before_delete", "ready"))
                else:
                    metadata = self.update(path, status="deleted", status_before_delete=metadata["status"])
                ArtifactStore(path).event("session_restored" if restore else "session_deleted")
                path.rename(target)
                return metadata
