import io
import json

import pytest

from trip_agent.agent import run_turn
from trip_agent.config import AppError
from trip_agent.persistence import ArtifactStore
from conftest import ScriptedModel, clarification


def test_real_strands_loop_tools_artifacts_and_memory_restore(sessions, session):
    stream = io.StringIO()
    first_model = ScriptedModel([("search_destinations", {"destination_id": "porto"}), clarification])
    first = run_turn(sessions, "Test trip", "I am considering Porto", model=first_model, output=stream)
    assert first["response"]["status"] == "needs_clarification"
    assert stream.getvalue().index("[Tool] search_destinations") < stream.getvalue().index("[Result] search_destinations")
    path = sessions.resolve("Test trip")
    store = ArtifactStore(path)
    assert len(store.list("model_inputs")) == 2
    assert len(store.list("tool_results")) == 2  # Lookup and structured-output tool.
    assert len(store.list("final_responses")) == 1
    second_model = ScriptedModel([clarification])
    second = run_turn(sessions, "Test trip", "Leaving JFK", model=second_model, output=io.StringIO())
    assert first["session_id"] == second["session_id"]
    assert first["turn_id"] != second["turn_id"]
    assert "I am considering Porto" in json.dumps(second_model.seen_messages[0])
    assert len(store.list("requests")) == 2
    assert len(store.list("final_responses")) == 2
    other = sessions.create("Fresh", "openai", __import__("trip_agent.config", fromlist=["Profile"]).Profile(
        provider="openai", model_id="gpt-6.1-sol"))
    clean = ScriptedModel([clarification])
    run_turn(sessions, other["session_id"], "Cheap", model=clean, output=io.StringIO())
    assert "I am considering Porto" not in json.dumps(clean.seen_messages[0])


def test_provider_failure_saved_and_session_can_be_resumed(sessions, session):
    with pytest.raises(AppError, match="connection refused"):
        run_turn(sessions, "Test trip", "Beach", model=ScriptedModel([RuntimeError("connection refused")]), output=io.StringIO())
    path = sessions.resolve("Test trip")
    assert sessions.metadata(path)["status"] == "failed"
    assert ArtifactStore(path).list("errors")
    result = run_turn(sessions, "Test trip", "Try again", model=ScriptedModel([clarification]), output=io.StringIO())
    assert result["response"]["status"] == "needs_clarification"


def test_model_call_budget_stops_loop(sessions, session):
    path = sessions.resolve("Test trip")
    profile = sessions.metadata(path)["model_config"]
    profile["max_model_calls"] = 1
    sessions.update(path, model_config=profile)
    with pytest.raises(AppError, match="limit reached"):
        run_turn(sessions, "Test trip", "Explore", model=ScriptedModel([
            ("search_destinations", {}), clarification]), output=io.StringIO())


def test_openrouter_unavailable_model_explains_recovery_and_preserves_error(sessions, session):
    import httpx
    from openai import NotFoundError
    path = sessions.resolve("Test trip")
    profile = sessions.metadata(path)["model_config"]
    profile.update(provider="openrouter", model_id="unavailable-model:free")
    sessions.update(path, model_config=profile)
    error = NotFoundError("This model is unavailable for free", response=httpx.Response(
        404, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")),
        body={"error": {"message": "This model is unavailable for free"}})
    with pytest.raises(AppError, match="No paid fallback was attempted") as caught:
        run_turn(sessions, "Test trip", "Porto", model=ScriptedModel([error]), output=io.StringIO())
    assert "openrouter/free" in str(caught.value)
    assert "existing sessions retain" in str(caught.value)
    store = ArtifactStore(path)
    assert any("unavailable for free" in store.read(a["artifact_id"])["data"]["message"]
               for a in store.list("errors"))
    assert sessions.metadata(path)["model_config"]["model_id"] == "unavailable-model:free"


def test_grounded_suggestion_budget_and_explicit_state_update(sessions, session):
    store = ArtifactStore(sessions.resolve("Test trip"))
    stream = io.StringIO()

    def latest(tool):
        return next(item["artifact_id"] for item in reversed(store.list("tool_results"))
                    if store.read(item["artifact_id"])["data"]["tool_name"] == tool)

    def state(messages):
        request_id = store.list("requests")[0]["artifact_id"]
        return {"destination": {"value": "Tokyo", "status": "user_stated",
                                "source_artifact_ids": [request_id]}}

    def budget(messages):
        # The lookup announcement has already been flushed and its evidence saved.
        assert "[Tool] search_accommodations" in stream.getvalue()
        return "calculate_trip_budget", {"destination_id": "tokyo", "accommodation_id": "tokyo-stay",
            "accommodation_artifact_id": latest("search_accommodations"), "travelers": 2,
            "nights": 7, "days": 8, "flights_excluded": True, "budget_usd": 6000}

    def final(messages):
        return "TripResponse", {"status": "suggestions", "message": "Consider Tokyo.",
            "trip_state": state(messages), "suggestions": [{"destination_id": "tokyo",
            "reasoning": "Food and city interests.", "accommodation_id": "tokyo-stay",
            "budget_artifact_id": latest("calculate_trip_budget"),
            "rough_budget": "USD 2220–3420 excluding flights and activities.",
            "evidence_artifact_ids": [latest("search_accommodations")]}]}

    result = run_turn(sessions, "Test trip", "Tokyo, two adults, 7 nights and 8 days, USD 6000 excluding flights",
        model=ScriptedModel([lambda m: ("update_trip_state", {"state": state(m)}),
                             ("search_accommodations", {"destination_id": "tokyo"}), budget, final]), output=stream)
    assert result["response"]["status"] == "suggestions"
    assert len(store.list("trip_states")) == 2
    from trip_agent.tools.context import payload
    assert payload(store.read(latest("calculate_trip_budget")))["total_range_usd"] == [2220, 3420]
