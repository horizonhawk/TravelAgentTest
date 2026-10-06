"""Valid conflict questions must not depend on the model choosing one keyword."""

import json
import sys
from pathlib import Path

import pytest
from strands_evals.types.evaluation import EvaluationData

from evals.evaluators import ConstraintEvaluator


BUNDLE = Path(__file__).parents[1] / "submission/evidence/openai-20261006T172433615442Z"


def contradiction_case():
    spec = next(c for c in json.loads((BUNDLE / "cases.json").read_text()) if c["name"] == "contradiction")
    output = json.loads((BUNDLE / "outputs.json").read_text())["contradiction"]
    # Remove the real message's additional resolution question to isolate the
    # substituted question in these positive/negative fixtures.
    output["response"]["message"] = "Tokyo is in Japan, so the requirements conflict and cannot both be satisfied."
    return EvaluationData(input=spec["input"], metadata=spec["metadata"], actual_output=output)


@pytest.mark.parametrize("question", [
    "Would you allow visiting Japan to go to Tokyo, or keep Japan excluded and consider another destination?",
    "Which requirement would you like to revise?",
    "Could you relax the restriction on visiting Japan?",
    "Are you willing to visit Japan to reach Tokyo?",
    "Would you consider a different destination outside Japan?",
    "Is either constraint negotiable?",
    "Would you keep Japan excluded and choose another destination?",
    "Which requirement takes priority: Tokyo or avoiding Japan?",
])
def test_resolution_paraphrases_pass(question):
    case = contradiction_case()
    case.actual_output["response"]["questions"] = [question]
    result = ConstraintEvaluator().evaluate(case)[0]
    assert result.test_pass, result.reason


@pytest.mark.parametrize("questions", [
    ["What is your budget?"],
    ["Which hotel would you prefer in Tokyo?"],
    ["Which travel dates would you choose for Japan?"],
    ["Would you change your budget for Tokyo?"],
    ["Is Tokyo in Japan?", "Which hotel should we choose?"],
    [],
    ["Would you consider Tokyo hotels or Japan tours?"],
    ["What would you change about Japanese meals?"],
])
def test_unrelated_or_missing_questions_still_fail(questions):
    case = contradiction_case()
    case.actual_output["response"]["questions"] = questions
    result = ConstraintEvaluator().evaluate(case)[0]
    assert not result.test_pass
    assert "Clarification does not address resolving the conflict" in result.reason


def test_resolution_question_does_not_excuse_false_geography():
    case = contradiction_case()
    case.actual_output["response"]["message"] = "Tokyo is outside Japan, so the requirements do not conflict."
    result = ConstraintEvaluator().evaluate(case)[0]
    assert not result.test_pass
    assert "Reply contradicts the known destination/country relationship" in result.reason


def test_actual_run_passes_rescore_without_modifying_generated_answers(tmp_path, monkeypatch):
    from evals.run import main

    originals = {p: p.read_bytes() for p in BUNDLE.iterdir() if p.is_file()}
    monkeypatch.setattr(sys, "argv", ["evals.run", "--replay", str(BUNDLE / "outputs.json"),
                                     "--output", str(tmp_path / "reports")])
    assert main() == 0
    report = json.loads(next((tmp_path / "reports").glob("*/summary.json")).read_text())
    assert report["evaluation_version"] == 5
    assert report["counts"]["passed_cases"] == 10
    assert report["counts"]["passed_applicable_checks"] == 34
    assert all(p.read_bytes() == original for p, original in originals.items())
