import json

import pytest

from trip_agent.config import AppError, Profile
from trip_agent.persistence import ArtifactStore
from trip_agent.schemas import Fact, TripState


def test_create_resume_name_and_isolation(sessions, session):
    path = sessions.resolve("Test trip")
    assert path.name == session["session_id"]
    first = ArtifactStore(path, "turn-1")
    artifact = first.save("requests", {"text": "Leaving JFK"})
    second = ArtifactStore(sessions.resolve(session["session_id"]), "turn-2")
    assert second.read(artifact)["data"]["text"] == "Leaving JFK"
    other = sessions.create("Other trip", "openai", Profile(provider="openai", model_id="other-model"))
    with pytest.raises(AppError, match="not found"):
        ArtifactStore(sessions.resolve(other["session_id"])).read(artifact)
    with pytest.raises(AppError, match="UUID"):
        second.read("../../session.json")
    with pytest.raises(AppError, match="Unknown"):
        sessions.resolve("mistyped-session")
    assert len(sessions.list()) == 2


def test_rename_delete_restore_preserve_artifacts(sessions, session):
    path = sessions.resolve("Test trip")
    artifact = ArtifactStore(path).save("requests", {"text": "Original"})
    sessions.rename("Test trip", "New name")
    assert sessions.resolve("New name") == path
    sessions.move("New name")
    assert not sessions.list()
    assert sessions.list(deleted=True)[0]["session_id"] == path.name
    sessions.move(path.name, restore=True)
    assert ArtifactStore(path).read(artifact)["data"]["text"] == "Original"


def test_busy_session_rejects_delete(sessions, session):
    with sessions.lock(session["session_id"]):
        with pytest.raises(AppError, match="busy"):
            sessions.move(session["session_id"])


def test_duplicate_names_rejected(sessions, session):
    with pytest.raises(AppError, match="already exists"):
        sessions.create("test TRIP", "openai", Profile(provider="openai", model_id="model"))


def test_corrections_preserve_sources_and_old_state(sessions, session):
    store = ArtifactStore(sessions.resolve("Test trip"), "turn-1")
    request = store.save("requests", {"text": "Leaving JFK"})
    original = store.save_state(TripState(origin=Fact(value="JFK", status="user_stated", source_artifact_ids=[request])))
    correction = store.save("requests", {"text": "Actually SFO"})
    latest = store.save_state(TripState(origin=Fact(value="SFO", status="user_stated", source_artifact_ids=[correction])))
    assert store.read(original)["data"]["origin"]["value"] == "JFK"
    assert store.read(latest)["source_artifact_ids"] == [original]
    assert json.loads((store.path / "current_trip.json").read_text())["state"]["origin"]["value"] == "SFO"
    with pytest.raises(AppError, match="original user request"):
        store.save_state(TripState(origin=Fact(value="LAX", status="user_stated", source_artifact_ids=[latest])))


def test_secret_redaction_and_rebuild_index(sessions, session):
    store = ArtifactStore(sessions.resolve("Test trip"), secrets=["test-secret-value"])
    artifact = store.save("errors", {"message": "key=test-secret-value"})
    assert store.read(artifact)["data"]["message"] == "key=[REDACTED]"
    (store.path / "artifact_index.json").unlink()
    assert store.list()[0]["artifact_id"] == artifact
