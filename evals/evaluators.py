"""Transparent checks with per-dimension reasons; no judge model or extra API key."""

import json

from strands_evals.evaluators import Evaluator, ToolCalled
from strands_evals.types.evaluation import EvaluationOutput, NOT_APPLICABLE

from trip_agent.events import validate_response
from trip_agent.config import AppError
from trip_agent.schemas import TripResponse
from trip_agent.tools.context import payload
from trip_agent.failures import output_failure
from .claims import budget_claim_checks, conflict_checks
from .evidence import evidence_store


def provider_blocked(case):
    failure = output_failure(case.actual_output)
    if failure and failure["provider_blocked"]:
        return [EvaluationOutput(score=0, test_pass=True, label=NOT_APPLICABLE,
            reason=f"PROVIDER BLOCKED: {failure['category']}; no agent-quality verdict. See case outcomes.")]
    return None


def score(checks):
    failures = [name for name, passed in checks if not passed]
    return [EvaluationOutput(score=sum(passed for _, passed in checks) / len(checks),
                             test_pass=not failures, reason="; ".join(failures) if failures else "All checks passed")]


class ContractEvaluator(Evaluator):
    def evaluate(self, case):
        if skipped := provider_blocked(case):
            return skipped
        try:
            TripResponse.model_validate(case.actual_output["response"])
            return score([("schema", True)])
        except (ValueError, KeyError, TypeError):
            return score([("Missing or invalid structured response", False)])


class ConstraintEvaluator(Evaluator):
    def evaluate(self, case):
        if skipped := provider_blocked(case):
            return skipped
        output = case.actual_output or {}
        response = output.get("response", {})
        metadata = case.metadata or {}
        state = response.get("trip_state", {})
        checks = [("Unexpected response status", response.get("status") in metadata.get("statuses", []))]
        if metadata.get('conflict'):
            checks.extend(conflict_checks(response, metadata['conflict']))
        for field in metadata.get("unknown", []):
            checks.append((f"Invented user-stated {field}", state.get(field, {}).get("status") != "user_stated"))
        if metadata.get("requires_clarification"):
            checks.append(("Missing clarifying questions", bool(response.get("questions"))))
        if metadata.get("unpriced_preliminary_suggestions"):
            checks.append(("Unjustified budget estimate before clarification", all(
                s.get("budget_artifact_id") is None for s in response.get("suggestions", []))))
        if "origin" in metadata:
            checks.append(("Origin was not preserved", metadata["origin"].lower() in str(state.get("origin", {}).get("value", "")).lower()))
        if "destination" in metadata:
            checks.append(("Destination was not preserved", metadata["destination"] in str(state.get("destination", {}).get("value", "")).lower()))
        for excluded in metadata.get("excluded", []):
            checks.append(("Excluded destination recommended", all(excluded != s.get("destination_id") for s in response.get("suggestions", []))))
            checks.append(("Exclusion not retained", excluded in json.dumps(state.get("exclusions", [])).lower()))
        tools = output.get("tool_results", [])
        if metadata.get("flights_excluded"):
            checks.append(("Flights exclusion not retained", "exclud" in str(state.get("budget", {}).get("value", "")).lower()))
        if metadata.get("already_booked_flight"):
            facts = json.dumps(state).lower()
            checks.append(("Already-booked Lisbon flight not retained", "lisbon" in facts and
                           any(word in facts for word in ["already", "booked", "existing"])))
            for record in tools:
                if record["data"]["tool_name"] == "search_flights":
                    args = record["data"].get("arguments", {})
                    checks.append(("Searched an invented long-haul origin for an extension", args.get("origin", "").upper() in {"LIS", "LISBON"}))
        if metadata.get("pool"):
            checks.append(("Pool preference not retained", "pool" in json.dumps(state.get("preferences", [])).lower()))
        if "nightly_limit" in metadata:
            limit = metadata["nightly_limit"]
            checks.append(("Nightly hotel limit not retained", str(limit) in json.dumps(state).lower()))
            for record in tools:
                if record["data"]["tool_name"] == "search_accommodations":
                    try:
                        stays = payload(record).get("accommodations", [])
                    except (ValueError, TypeError, KeyError, AppError):
                        continue
                    chosen = {s.get("accommodation_id") for s in response.get("suggestions", [])}
                    checks.append(("Selected hotel exceeds nightly limit", all(
                        stay["nightly_room_usd"][1] <= limit for stay in stays if stay["id"] in chosen)))
        for record in tools:
            if record["data"]["tool_name"] != "calculate_trip_budget":
                continue
            try:
                budget = payload(record)
            except Exception:
                continue
            if budget.get("status") != "ok":
                continue
            if metadata.get("flights_excluded"):
                checks.append(("Flights incorrectly included in total", "flights" not in budget["line_items"] and "flights" in budget["exclusions"]))
            if "nightly_limit" in metadata:
                checks.append(("Invented a total budget when none was stated", budget.get("budget_usd") is None))
        return score(checks)


def tool_trajectory(output):
    """Use recorded call attempts, never model prose. Support older saved runs with results only."""
    if 'tool_calls' in output:
        return [record['data']['name'] for record in output['tool_calls']]
    if 'tool_results' in output:
        return [record['data']['tool_name'] for record in output['tool_results']]
    return None


class ToolUsageEvaluator(Evaluator):
    """Case-specific requirements using Strands' deterministic ToolCalled evaluator."""

    def evaluate(self, case):
        if skipped := provider_blocked(case):
            return skipped
        metadata = case.metadata or {}
        required = list(dict.fromkeys(metadata.get('required_tools', [])))
        successful = list(dict.fromkeys(metadata.get('required_successful_tools', [])))
        forbidden = list(dict.fromkeys(metadata.get('forbidden_tools', [])))
        if not (required or successful or forbidden):
            return [EvaluationOutput(score=0, test_pass=True, label=NOT_APPLICABLE,
                reason='No tool requirements for this case; clarification may require no tools.')]
        output = case.actual_output or {}
        trajectory = case.actual_trajectory
        if trajectory is None:
            trajectory = tool_trajectory(output)
        if trajectory is None:
            return score([('No recorded tool trajectory available', False)])
        context = case.model_copy(update={'actual_trajectory': trajectory})
        checks = []
        for name in required:
            verdict = ToolCalled(tool_name=name).evaluate(context)[0]
            checks.append((f'Required tool not called: {name}', verdict.test_pass))
        for name in forbidden:
            verdict = ToolCalled(tool_name=name).evaluate(context)[0]
            checks.append((f'Forbidden tool called: {name}', not verdict.test_pass))
        completed = set()
        for record in output.get('tool_results', []):
            data = record['data']
            if data['result'].get('status') != 'success':
                continue
            try:
                result = payload(record)
            except (ValueError, TypeError, KeyError, AppError):
                continue
            if isinstance(result, dict) and result.get('status') in {'ok', 'no_match'}:
                completed.add(data['tool_name'])
        for name in successful:
            called = ToolCalled(tool_name=name).evaluate(context)[0].test_pass
            checks.append((f'No successful result for required tool: {name}', called and name in completed))
        return score(checks)


class EvidenceEvaluator(Evaluator):
    def evaluate(self, case):
        if skipped := provider_blocked(case):
            return skipped
        output = case.actual_output or {}
        try:
            store = evidence_store(output)
            response = TripResponse.model_validate(output["response"])
            validate_response(store, response)
        except Exception as exc:
            return score([(f"Invalid or missing evidence: {type(exc).__name__}", False)])
        checks = [("Evidence references", True)]
        try:
            checks.extend(budget_claim_checks(response, store))
        except (ValueError, TypeError, KeyError, AppError) as exc:
            checks.append((f'Cannot verify final budget claims: {type(exc).__name__}', False))
        for record in output.get("tool_results", []):
            if record["data"]["tool_name"] == "calculate_trip_budget":
                try:
                    budget = payload(record)
                except (ValueError, TypeError, KeyError, AppError):
                    continue  # Failed attempts have no budget to check; tool-success checks remain separate.
                if budget.get("status") == "ok":
                    expected = [sum(line[i] for line in budget["line_items"].values()) for i in (0, 1)]
                    checks.append(("Budget arithmetic mismatch", expected == budget["total_range_usd"]))
                    checks.append(("Unknown costs treated as affordable", not budget["unknown_costs"] or budget["budget_assessment"] != "within_estimated_scope"))
        return score(checks)
