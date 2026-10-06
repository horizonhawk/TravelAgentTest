"""Missing-detail regressions from the failed clean-clone acceptance run."""

import io
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from strands_evals.types.evaluation import EvaluationData

from conftest import ScriptedModel
from evals.evaluators import ContractEvaluator, ConstraintEvaluator
from trip_agent.agent import run_turn
from trip_agent.persistence import ArtifactStore
from trip_agent.schemas import TripState


@pytest.mark.parametrize("placeholder", ["Undecided", "Not yet decided", "TBD"])
def test_explicit_uncertainty_is_not_a_known_origin_or_duration(placeholder):
    fact = {"value": placeholder, "status": "user_stated", "source_artifact_ids": ["request"]}
    with pytest.raises(ValidationError, match="status='unknown' and value=null"):
        TripState.model_validate({"origin": fact, "duration": fact})


def test_partial_information_and_flexibility_are_not_erased():
    state = TripState.model_validate({
        "dates": {"value": "May; year undecided", "status": "user_stated", "source_artifact_ids": ["request"]},
        "budget": {"value": "Flexible; flag over USD 4000", "status": "user_stated", "source_artifact_ids": ["request"]},
        "origin": {"value": None, "status": "unknown", "source_artifact_ids": ["request"]},
        "duration": {"value": "About a week; exact nights undecided", "status": "user_stated", "source_artifact_ids": ["request"]},
    })
    assert state.dates.value == "May; year undecided"
    assert state.budget.status == state.duration.status == "user_stated"
    assert state.origin.value is None and state.origin.source_artifact_ids == ["request"]


@pytest.mark.parametrize("field,value", [("origin", "JFK"), ("duration", "7 nights")])
def test_real_fabrications_still_fail_the_unknown_field_check(field, value):
    case = EvaluationData(input="We have not decided where to depart from or how long to go.",
        actual_output={"response": {"status": "needs_clarification", "trip_state": {
            field: {"value": value, "status": "user_stated", "source_artifact_ids": ["request"]}}}},
        metadata={"statuses": ["needs_clarification"], "unknown": [field]})
    verdict = ConstraintEvaluator().evaluate(case)[0]
    assert not verdict.test_pass
    assert f"{field} is marked user_stated" in verdict.reason


def test_model_can_correct_uncertainty_without_losing_the_failed_attempt(sessions, session):
    store = ArtifactStore(sessions.resolve("Test trip"))

    def final(corrected):
        def action(messages):
            request_id = store.list("requests")[-1]["artifact_id"]
            fact = {"value": None if corrected else "Undecided",
                    "status": "unknown" if corrected else "user_stated",
                    "source_artifact_ids": [request_id]}
            if corrected:
                assert "status='unknown' and value=null" in json.dumps(messages)
            return "TripResponse", {
                "status": "needs_clarification", "message": "Your departure point and duration are still open.",
                "trip_state": {"origin": fact, "duration": fact,
                               "open_questions": ["The user has not decided departure point or duration."]},
                "questions": ["Would you prefer a short break or a longer trip?"],
            }
        return action

    result = run_turn(sessions, "Test trip", "We have not decided where to depart from or how long to go.",
        model=ScriptedModel([final(False), final(True)]), output=io.StringIO())
    request = store.read(store.list("requests")[0]["artifact_id"])
    for field in ["origin", "duration"]:
        assert result["response"]["trip_state"][field] == {
            "value": None, "status": "unknown", "source_artifact_ids": [request["artifact_id"]]}
    calls = [store.read(r["artifact_id"])["data"] for r in store.list("tool_calls")]
    results = [store.read(r["artifact_id"])["data"]["result"] for r in store.list("tool_results")]
    assert len(calls) == len(results) == 2
    assert calls[0]["input"]["trip_state"]["origin"]["value"] == "Undecided"
    assert [r["status"] for r in results] == ["error", "success"]
    assert len(store.list("final_responses")) == 1
    assert "not decided" in request["data"]["text"]


def test_historical_failed_output_is_not_rewritten_into_a_pass(tmp_path, monkeypatch):
    from evals.run import main

    bundle = Path(__file__).parents[1] / "submission/evidence/openai-20261006T170847905864Z"
    original = (bundle / "outputs.json").read_bytes()
    output = json.loads(original)["explicit-exclusion"]
    spec = next(c for c in json.loads((bundle / "cases.json").read_text()) if c["name"] == "explicit-exclusion")
    case = EvaluationData(input=spec["input"], metadata=spec["metadata"], actual_output=output)
    for field in ["origin", "duration"]:
        assert output["response"]["trip_state"][field]["value"] == "Undecided"
    assert not ContractEvaluator().evaluate(case)[0].test_pass
    verdict = ConstraintEvaluator().evaluate(case)[0]
    assert not verdict.test_pass and "Invented" not in verdict.reason
    monkeypatch.setattr(sys, "argv", ["evals.run", "--replay", str(bundle / "outputs.json"),
        "--only", "explicit-exclusion", "--output", str(tmp_path / "reports")])
    assert main() == 1
    report = json.loads(next((tmp_path / "reports").glob("*/summary.json")).read_text())
    assert report["evaluation_version"] == 4
    assert report["case_outcomes"]["explicit-exclusion"]["has_final_response"]
    assert report["counts"]["valid_final_responses"] == 0
    assert report["counts"]["failed_cases"] == 1
    assert (bundle / "outputs.json").read_bytes() == original
