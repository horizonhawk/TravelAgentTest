"""Run isolated live cases or rescore saved live outputs; never pretend fixtures are a live eval."""

import argparse
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from strands_evals import Case, Experiment

from trip_agent.agent import run_turn
from trip_agent.config import AppError, check_profile, load_settings
from trip_agent.persistence import ArtifactStore, atomic_json
from trip_agent.session import Sessions
from trip_agent.failures import classify_failure
from .reporting import case_outcomes, display_outcomes

from .evaluators import ContractEvaluator, ConstraintEvaluator, EvidenceEvaluator, ToolUsageEvaluator, tool_trajectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("trip-agent.toml"))
    parser.add_argument("--profile")
    parser.add_argument("--only", nargs="+", help="Run or replay only these case names")
    parser.add_argument("--cases", type=Path, help="Case file; defaults to bundle cases on portable replay, otherwise built-in cases")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--data-dir", type=Path, default=Path(".trip-agent/evaluations"))
    parser.add_argument("--replay", type=Path, help="Rescore saved outputs.json without LLM calls; portable bundles embed their evidence")
    args = parser.parse_args()
    bundled_cases = None
    if args.replay and (args.replay.parent / 'manifest.json').exists():
        manifest = json.loads((args.replay.parent / 'manifest.json').read_text())
        if manifest.get('bundle_version') != 1:
            raise AppError('Unsupported evidence bundle version')
        for name in ['outputs.json', 'cases.json']:
            expected = manifest['files_sha256'][name]
            if hashlib.sha256((args.replay.parent / name).read_bytes()).hexdigest() != expected:
                raise AppError(f'Bundle integrity check failed: {name}')
        bundled_cases = args.replay.parent / 'cases.json'
    case_file = args.cases or bundled_cases or Path(__file__).with_name('cases.json')
    cases = [Case(**case) for case in json.loads(case_file.read_text())]
    if args.only:
        unknown = set(args.only) - {case.name for case in cases}
        if unknown:
            raise AppError("Unknown evaluation cases: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case.name in args.only]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    outputs = json.loads(args.replay.read_text()) if args.replay else {}
    if not args.replay:
        name, profile = load_settings(args.config).select(args.profile)
        problems = check_profile(profile)
        if problems:
            raise AppError(" ".join(problems))
        sessions = Sessions(args.data_dir / run_id)

    def task(case):
        if args.replay:
            output = outputs.get(case.name, {"error": "No saved output for case"})
            return {"output": output, "trajectory": tool_trajectory(output)}
        session = sessions.create(case.name, name, profile)
        path = sessions.resolve(session["session_id"])
        try:
            output = run_turn(sessions, path.name, case.input)
        except AppError as exc:
            output = {"error": str(exc), "failure": classify_failure(exc), "session_id": path.name}
        store = ArtifactStore(path)
        output["session_path"] = str(path)
        output["tool_calls"] = [store.read(item["artifact_id"]) for item in store.list("tool_calls")]
        output["tool_results"] = [store.read(item["artifact_id"]) for item in store.list("tool_results")]
        output["model_config"] = profile.model_dump(mode="json")
        output["provider_responses"] = [identity for item in store.list("model_responses")
                                       for identity in store.read(item["artifact_id"])["data"].get("provider_responses", [])]
        outputs[case.name] = output
        atomic_json(args.output / run_id / "cases" / f"{path.name}.json", {"case": case.name, "output": output}, replace=False)
        return {"output": output, "trajectory": tool_trajectory(output)}

    experiment = Experiment(cases=cases, evaluators=[ContractEvaluator(), ConstraintEvaluator(), EvidenceEvaluator(), ToolUsageEvaluator()])
    report = experiment.run_evaluations(task)
    if not args.replay:
        atomic_json(args.output / run_id / "outputs.json", outputs, replace=False)
    outcomes, counts = case_outcomes(report, outputs)
    artifact = {"mode": "replay" if args.replay else "live", "run_id": run_id,
                "evaluation_version": 3, "source_outputs": str(args.replay) if args.replay else None,
                "case_outcomes": outcomes, "counts": counts, **report.model_dump(mode="json")}
    atomic_json(args.output / run_id / "summary.json", artifact, replace=False)
    display_outcomes(outcomes, counts)
    for name, outcome in outcomes.items():
        if outcome['status'] != 'passed':
            reasons = [check['reason'] for check in outcome['checks'] if not check['passed']]
            category = outcome['failure']['category'] if outcome['failure'] else 'quality_checks'
            print(f"{name}: {outcome['status']} ({category})" + (" — " + "; ".join(dict.fromkeys(reasons)) if reasons else ""))
    print(f"Report: {args.output / run_id / 'summary.json'}")
    return 0 if all(outcome['status'] == 'passed' for outcome in outcomes.values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AppError as exc:
        print(f"Evaluation setup error: {exc}")
        raise SystemExit(1)
