"""Case outcomes separate operational failures from agent-quality measurements."""

from trip_agent.failures import output_failure
from rich.console import Console
from rich.table import Table


def display_outcomes(outcomes, counts):
    """Show case-level results without rendering skipped checks as green passes."""
    console = Console()
    table = Table(title="Travel-agent evaluation: case outcomes")
    table.add_column("Case")
    table.add_column("Outcome")
    for name in ("Contract", "Constraints", "Evidence", "Tools"):
        table.add_column(name)
    for name, entry in outcomes.items():
        style = {"passed": "green", "failed": "red", "provider_blocked": "yellow"}[entry["status"]]
        checks = ["[dim]N/A[/dim]" if not check["applicable"] else
                  "[green]PASS[/green]" if check["passed"] else "[red]FAIL[/red]" for check in entry["checks"]]
        table.add_row(name, f"[{style}]{entry['status']}[/{style}]", *checks)
    console.print(table)
    console.print(f"Cases: {counts['passed_cases']} passed, {counts['failed_cases']} failed, "
                  f"{counts['provider_blocked_cases']} provider-blocked. "
                  f"Valid final responses: {counts['valid_final_responses']}/{counts['total_cases']}.")
    console.print(f"Applicable quality checks: {counts['passed_applicable_checks']}/{counts['applicable_checks']}. "
                  "N/A checks are excluded; provider-blocked cases are not passes.")


def case_outcomes(report, outputs):
    outcomes = {}
    for case, passed, reason, details in zip(report.cases, report.test_passes, report.reasons, report.detailed_results):
        output = outputs.get(case['name'], {})
        failure = output_failure(output)
        entry = outcomes.setdefault(case['name'], {
            "status": "provider_blocked" if failure and failure["provider_blocked"] else "passed",
            "failure": failure, "has_final_response": bool(output.get("response")),
            "session_id": output.get("session_id"), "checks": [],
            "configured_model": output.get("model_config"),
            "provider_responses": output.get("provider_responses", []),
        })
        applicable = not all(detail.not_applicable for detail in details)
        entry["checks"].append({"evaluator": case['evaluator'], "passed": passed,
                                 "applicable": applicable, "reason": reason})
        if applicable and not passed and entry["status"] != "provider_blocked":
            entry["status"] = "failed"
    checks = [check for entry in outcomes.values() for check in entry["checks"] if check["applicable"]]
    return outcomes, {
        "total_cases": len(outcomes),
        "passed_cases": sum(e["status"] == "passed" for e in outcomes.values()),
        "failed_cases": sum(e["status"] == "failed" for e in outcomes.values()),
        "provider_blocked_cases": sum(e["status"] == "provider_blocked" for e in outcomes.values()),
        "valid_final_responses": sum(e["has_final_response"] and any(
            c["evaluator"] == "ContractEvaluator" and c["applicable"] and c["passed"]
            for c in e["checks"]) for e in outcomes.values()),
        "applicable_checks": len(checks), "passed_applicable_checks": sum(c["passed"] for c in checks),
    }
