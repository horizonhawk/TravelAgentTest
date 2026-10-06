"""Time a fresh GitHub install, then run the complete submission checks.

Standard library only. Does not publish, resume an old install, or retry LLM calls.
Requires Python 3.11+, Git, network access, and credentials for the chosen provider.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib


REPOSITORY = "https://github.com/horizonhawk/TravelAgentTest.git"
PROVIDER_KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
AWS_ENV_NAMES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK",
                 "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE")
EXAMPLE = (
    "Two adults from SFO to Porto in May 2027, 3 nights and 4 days. "
    "Boutique hotel under USD 300 per room per night. No total trip budget. Give a mock estimate."
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timing_results(setup_seconds, first_response_seconds, end_to_end_seconds, example_ok):
    """Thresholds use unrounded durations; a failed response can never pass timing."""
    def gate(seconds, limit):
        return {
            "seconds": round(seconds, 3) if seconds is not None else None,
            "limit_seconds": limit,
            "status": "not_completed" if seconds is None or not example_ok
            else "passed" if seconds < limit else "failed",
        }

    return {
        "runtime_ready_after_clone_seconds": round(setup_seconds, 3) if setup_seconds is not None else None,
        "clean_clone_to_first_response": gate(first_response_seconds, 120),
        "clone_start_to_first_response": gate(end_to_end_seconds, 300),
        "interpretation": "Conservative: running means a validated Porto suggestion, including the README's "
        "live configuration probe. The 120s clock starts when cloning completes; the 300s clock includes cloning. "
        "Both include venv creation, runtime installation, credential loading, configuration and LLM latency. "
        "API-key acquisition, reading the README, eval/test installation and the later suite are not timed here.",
    }


def evaluation_passed(summary, expected_names):
    outcomes = summary.get("case_outcomes", {})
    return bool(expected_names) and set(outcomes) == set(expected_names) and all(
        entry.get("status") == "passed" and entry.get("has_final_response")
        for entry in outcomes.values()
    )


def redact(value, secrets):
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED_CREDENTIAL]")
    # Also protect credentials in an install/proxy URL or an unexpected provider diagnostic.
    value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED_CREDENTIAL]@", value)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED_CREDENTIAL]", value)


class Check:
    def __init__(self, output, env):
        self.output, self.env = output, env
        self.secrets = [v for k, v in env.items() if v and ("KEY" in k or "TOKEN" in k or "PASSWORD" in k)]
        self.report = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "running", "steps": []}

    def save(self):
        # Only this new run's working report changes; previous runs are never reused.
        (self.output / "check.json").write_text(redact(json.dumps(self.report, indent=2), self.secrets) + "\n")

    def run(self, label, command, cwd=None, required=True):
        print(label, flush=True)
        started = time.monotonic()
        process = subprocess.Popen([str(a) for a in command], cwd=cwd, env=self.env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    print(f"  still running ({time.monotonic() - started:.0f}s)", flush=True)
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
        seconds = time.monotonic() - started
        self.report["steps"].append({"label": label, "seconds": round(seconds, 3),
                                     "exit_code": process.returncode, "stdout": redact(stdout, self.secrets),
                                     "stderr": redact(stderr, self.secrets)})
        self.save()
        print(f"  exit={process.returncode}, {seconds:.2f}s", flush=True)
        if process.returncode:
            print(redact(stderr or stdout, self.secrets)[-2500:], flush=True)
            if required:
                raise RuntimeError(f"{label} failed; remaining dependent checks were not run")
        return process.returncode, stdout


def audit_logbook(check, cli, checkout, example):
    session = checkout / ".trip-agent" / "sessions" / example["session_id"]
    artifacts = list((session / "artifacts").glob("*/*.json"))
    kinds = {p.parent.name for p in artifacts}
    required = {"requests", "model_inputs", "model_responses", "tool_calls", "tool_results", "trip_states", "final_responses"}
    editions = list((session / "logbooks").glob("*.html"))
    if not required <= kinds or not editions:
        raise ValueError("The live example is missing source evidence or automatic logbook editions")
    before = {p: digest(p) for p in artifacts + editions}
    events = (session / "events.jsonl").read_bytes()
    check.run("Generate an additional integrated logbook (no LLM call)",
              [*cli, "logbook", "--session", example["session_id"]], checkout)
    after = set((session / "logbooks").glob("*.html"))
    preserved = all(p.exists() and digest(p) == sha for p, sha in before.items())
    preserved = preserved and (session / "events.jsonl").read_bytes().startswith(events)
    if not preserved or not after - set(editions):
        raise ValueError("Logbook generation did not preserve earlier artifacts/editions")
    latest = max(after - set(editions))
    (check.output / "live-example-logbook.html").write_bytes(latest.read_bytes())
    check.report["logbook_audit"] = {"passed": True, "artifact_count": len(artifacts),
                                       "preserved_artifact_and_edition_hashes": {str(p.relative_to(session)): sha for p, sha in before.items()},
                                       "note": "Checks preservation during an extra export; offline tests cover subsequent turns and lifecycle changes."}


def options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPOSITORY)
    parser.add_argument("--ref", default="main", help="Remote branch or tag to clone; exact resulting commit is recorded")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Existing credential file; never copied into the clone")
    parser.add_argument("--provider", choices=[*PROVIDER_KEYS, "bedrock"], default="openai")
    parser.add_argument("--model", help="Default gpt-6.1-sol for OpenAI; required for other providers")
    parser.add_argument("--aws-region", help="Bedrock region; defaults to AWS_REGION/AWS_DEFAULT_REGION, then us-west-2")
    parser.add_argument("--aws-profile", help="Bedrock AWS credential profile; otherwise use the existing AWS credential chain")
    parser.add_argument("--output", type=Path, default=Path("reports/acceptance"))
    parser.add_argument("--use-pip-cache", action="store_true", help="Opt in to pip's existing cache; default disables it")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Use Python 3.11 or later")
    if not args.model:
        if args.provider != "openai":
            parser.error("Pass --model with a tool-capable model ID for the selected provider")
        args.model = "gpt-6.1-sol"
    if args.provider != "bedrock" and (args.aws_region or args.aws_profile):
        parser.error("--aws-region and --aws-profile apply only to --provider bedrock")
    args.env_file = args.env_file.resolve()
    key_name = PROVIDER_KEYS.get(args.provider)
    if key_name and not os.environ.get(key_name) and not args.env_file.is_file():
        parser.error(f"Set {key_name} or pass --env-file pointing to your existing .env")
    return args


def load_credentials(check, python, env_file, checkout, provider):
    """Read only selected-provider settings. Shell values retain dotenv precedence."""
    names = AWS_ENV_NAMES if provider == "bedrock" else (PROVIDER_KEYS[provider],)
    if env_file.is_file() and any(name not in check.env for name in names):
        # No third-party dependencies for the driver: use dotenv in the newly installed runtime.
        # Never put this subprocess's private output in the report.
        loaded = subprocess.run([str(python), "-c", "from dotenv import dotenv_values; import json,sys; "
                                 "values=dotenv_values(sys.argv[1]); "
                                 "print(json.dumps({k: values[k] for k in sys.argv[2:] if values.get(k)}))",
                                 str(env_file), *names], cwd=checkout, env=check.env, capture_output=True, text=True)
        if loaded.returncode:
            raise RuntimeError("Could not read selected-provider credentials from the supplied .env")
        for name, value in json.loads(loaded.stdout).items():
            check.env.setdefault(name, value)
            if "KEY" in name or "TOKEN" in name:
                check.secrets.append(value)
    if provider != "bedrock" and not check.env.get(PROVIDER_KEYS[provider]):
        raise ValueError(f"{PROVIDER_KEYS[provider]} is missing or empty in the environment and supplied .env")


def configure_bedrock(path, region, aws_profile):
    """Customize only the fresh generated profile; never touch the reviewer's config."""
    settings = tomllib.loads(path.read_text())
    if settings["default_profile"] != "bedrock" or set(settings["profiles"]) != {"bedrock"}:
        raise ValueError("Expected a freshly initialized Bedrock-only config")
    profile = settings["profiles"]["bedrock"]
    profile["region"] = region
    if aws_profile:
        profile["aws_profile"] = aws_profile
    lines = ['default_profile = "bedrock"', "", "[profiles.bedrock]"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in profile.items()]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    args = options(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output.resolve() / (stamp + "-clean-clone")
    output.mkdir(parents=True, exist_ok=False)
    checkout = Path(tempfile.mkdtemp(prefix="travel-agent-acceptance-")) / "checkout"
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRIP_AGENT_")
           and k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "OPENAI_BASE_URL"}}
    env.update({"GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1", "PYTHONUNBUFFERED": "1"})
    check = Check(output, env)
    check.report.update({"repository": args.repo, "requested_ref": args.ref, "checkout": str(checkout),
                         "runner_sha256": digest(Path(__file__)), "python": sys.version,
                         "provider": args.provider, "model": args.model, "fresh_venv": True,
                         "pip_cache": "enabled" if args.use_pip_cache else "disabled",
                         "manual_review": "Automation cannot certify prose clarity, genuine authorship, or actual personal review. "
                         "Read PROCESS.md, annotated prompts and original transcript; inspect normal CLI and HTML presentation.",
                         "checks": {}})
    setup_seconds = first_seconds = end_to_end_seconds = None
    example_ok = False
    start = time.monotonic()
    try:
        check.run("Clone GitHub into a new directory", ["git", "clone", "--branch", args.ref, args.repo, checkout])
        cloned = time.monotonic()
        _, revision = check.run("Record the tested commit", ["git", "rev-parse", "HEAD"], checkout)
        check.report["cloned_commit"] = revision.strip()
        python = checkout / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = [python, "-m", "trip_agent"]
        check.run("Create a fresh virtual environment", [sys.executable, "-m", "venv", ".venv"], checkout)
        install = [python, "-m", "pip", "install", "--disable-pip-version-check"]
        if not args.use_pip_cache:
            install += ["--no-cache-dir"]
        extra = f".[{args.provider}]"
        check.run(f"Install runtime only: {extra}", [*install, "-e", extra], checkout)
        load_credentials(check, python, args.env_file, checkout, args.provider)
        check.run(f"Initialize fresh {args.provider} configuration",
                  [*cli, "config", "init", "--provider", args.provider, "--model", args.model], checkout)
        if args.provider == "bedrock":
            region = args.aws_region or env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-west-2"
            configure_bedrock(checkout / "trip-agent.toml", region, args.aws_profile or env.get("AWS_PROFILE"))
        _, configured = check.run("Record the non-secret model configuration", [*cli, "config", "show"], checkout)
        check.report["configured_profile"] = json.loads(configured)
        code, _ = check.run("Check local configuration", [*cli, "config", "check"], checkout)
        setup_seconds = time.monotonic() - cloned
        code, _ = check.run("Check real model/tool/structured output", [*cli, "config", "check", "--live"], checkout, required=False)
        check.report["checks"]["live_configuration"] = code == 0
        name = "Acceptance Porto " + stamp
        check.run("Create a fresh reviewer session", [*cli, "session", "create", "--name", name, "--profile", args.provider], checkout)
        code, stdout = check.run("Run the README example with real calls and debug JSON",
                                 [*cli, "run", "--session", name, "--json", "--debug", EXAMPLE], checkout, required=False)
        example = {}
        if code == 0:
            example = json.loads(stdout)
            response = example.get("response", {})
            example_ok = response.get("status") == "suggestions" and any(
                s.get("destination_id") == "porto" for s in response.get("suggestions", []))
            (output / "live-example.json").write_text(redact(json.dumps(example, indent=2), check.secrets) + "\n")
        if example_ok:
            first_seconds, end_to_end_seconds = time.monotonic() - cloned, time.monotonic() - start
        check.report["checks"]["live_example"] = example_ok
        check.report["timing"] = timing_results(setup_seconds, first_seconds, end_to_end_seconds, example_ok)
        check.save()
        for label in ("clean_clone_to_first_response", "clone_start_to_first_response"):
            metric = check.report["timing"][label]
            print(f"Timing: {label}: {metric['status']} ({metric['seconds']}s; under {metric['limit_seconds']}s)", flush=True)

        # Timing stops here. All subsequent checks are additional acceptance work.
        if example_ok:
            try:
                audit_logbook(check, cli, checkout, example)
                check.report["checks"]["logbook_preservation"] = True
            except (OSError, ValueError, RuntimeError) as error:
                check.report["checks"]["logbook_preservation"] = False
                check.report["logbook_error"] = str(error)
        else:
            check.report["checks"]["logbook_preservation"] = False
        required_files = ["README.md", "PROCESS.md", "transcripts/README.md", "evals/cases.json", "pyproject.toml"]
        missing = [p for p in required_files if not (checkout / p).is_file()]
        check.report["checks"]["submission_files_present"] = not missing
        check.report["missing_files"] = missing
        check.run("Install optional evaluation/test dependencies (outside setup timing)", [*install, "-e", ".[eval,test]"], checkout)
        code, _ = check.run("Run all offline tests from the cloned revision", [python, "-m", "pytest", "-q"], checkout, required=False)
        check.report["checks"]["offline_tests"] = code == 0
        bundle = checkout / "submission/evidence/openai-20261006T044810289114Z/outputs.json"
        code, _ = check.run("Replay the included portable evidence (no model calls)",
                            [python, "-m", "evals.run", "--replay", bundle, "--output", output / "included-replay"], checkout, required=False)
        check.report["checks"]["included_evidence_replay"] = code == 0
        expected = [case["name"] for case in json.loads((checkout / "evals/cases.json").read_text())]
        live_output = output / "live-evals"
        code, _ = check.run(f"Run ALL {len(expected)} evaluation cases with real model calls",
                            [python, "-m", "evals.run", "--profile", args.provider, "--output", live_output], checkout, required=False)
        summaries = list(live_output.glob("*/summary.json"))
        check.report["checks"]["all_live_evaluations"] = False
        check.report["checks"]["new_evidence_replay"] = False
        if len(summaries) == 1:
            summary = json.loads(summaries[0].read_text())
            check.report["live_evaluation_counts"] = summary["counts"]
            check.report["checks"]["all_live_evaluations"] = code == 0 and evaluation_passed(summary, expected)
            check.run("Export this run's portable evidence", [python, "-m", "evals.export", "--run", summaries[0].parent,
                                                             "--output", output / "portable-evidence"], checkout)
            replay_dir = output / "new-evidence-replay"
            code, _ = check.run("Replay the newly exported evidence (no model calls)",
                                [python, "-m", "evals.run", "--replay", output / "portable-evidence/outputs.json",
                                 "--output", replay_dir], checkout, required=False)
            replay_summaries = list(replay_dir.glob("*/summary.json"))
            check.report["checks"]["new_evidence_replay"] = code == 0 and len(replay_summaries) == 1 and evaluation_passed(
                json.loads(replay_summaries[0].read_text()), expected)
        _, dirty = check.run("Verify the checked-out source stayed unchanged", ["git", "status", "--porcelain"], checkout)
        check.report["checks"]["source_unchanged"] = not dirty.strip()
        timings = check.report["timing"]
        timed_pass = all(timings[k]["status"] == "passed" for k in ("clean_clone_to_first_response", "clone_start_to_first_response"))
        check.report["status"] = "passed" if all(check.report["checks"].values()) and timed_pass else "failed"
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        check.report.update(status="incomplete", error=str(error))
        print(redact(str(error), check.secrets), flush=True)
    except KeyboardInterrupt:
        check.report.update(status="interrupted", error="Interrupted by user; this attempt is retained")
    finally:
        check.report.setdefault("timing", timing_results(setup_seconds, first_seconds, end_to_end_seconds, example_ok))
        check.report["total_suite_seconds"] = round(time.monotonic() - start, 3)
        check.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        check.save()
        print(f"\nAcceptance: {check.report['status']}\nReport: {output / 'check.json'}\nClone retained: {checkout}", flush=True)
    return 0 if check.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
