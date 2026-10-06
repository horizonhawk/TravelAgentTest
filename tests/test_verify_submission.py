"""Acceptance results must not turn fast failures or partial suites into passes."""

import json
import sys
import tomllib

import pytest

from scripts.verify_submission import (Check, configure_bedrock, evaluation_passed, load_credentials,
                                       options, redact, timing_results)


def test_timing_requires_a_successful_response_and_uses_strict_limits():
    result = timing_results(30, 90, 95, False)
    assert result["clean_clone_to_first_response"]["status"] == "not_completed"
    assert result["clone_start_to_first_response"]["status"] == "not_completed"
    result = timing_results(30, 120, 300, True)
    assert result["clean_clone_to_first_response"]["status"] == "failed"
    assert result["clone_start_to_first_response"]["status"] == "failed"
    result = timing_results(30, 119.9, 299.9, True)
    assert result["clean_clone_to_first_response"]["status"] == "passed"
    assert result["clone_start_to_first_response"]["status"] == "passed"
    result = timing_results(None, None, None, False)
    assert result["clean_clone_to_first_response"]["seconds"] is None


def test_full_evaluation_gate_rejects_missing_cases_and_provider_blocks():
    summary = {"case_outcomes": {"a": {"status": "passed", "has_final_response": True}}}
    assert evaluation_passed(summary, ["a"])
    assert not evaluation_passed(summary, ["a", "b"])
    assert not evaluation_passed(summary, [])
    summary["case_outcomes"]["b"] = {"status": "provider_blocked", "has_final_response": False}
    assert not evaluation_passed(summary, ["a", "b"])
    summary["case_outcomes"]["b"] = {"status": "passed", "has_final_response": False}
    assert not evaluation_passed(summary, ["a", "b"])


def test_failed_subprocess_retains_diagnostics_and_redacts_credentials(tmp_path):
    secret = "acceptance-test-fake-secret"
    check = Check(tmp_path, {"OPENAI_API_KEY": secret})
    with pytest.raises(RuntimeError, match="failed"):
        check.run("A real subprocess failure", [sys.executable, "-c",
                  "import os,sys; print(os.environ['OPENAI_API_KEY']); print('failure',file=sys.stderr); sys.exit(7)"])
    report = json.loads((tmp_path / "check.json").read_text())
    assert report["steps"][0]["exit_code"] == 7
    assert report["steps"][0]["stderr"].strip() == "failure"
    assert secret not in (tmp_path / "check.json").read_text()
    assert "[REDACTED_CREDENTIAL]" in report["steps"][0]["stdout"]


def test_redaction_handles_private_index_and_unexpected_api_key():
    assert redact("https://user:password@example.test/pkg", []) == "https://[REDACTED_CREDENTIAL]@example.test/pkg"
    assert redact("sk-example-fake-credential-123", []) == "[REDACTED_CREDENTIAL]"


@pytest.mark.parametrize("provider,key_name", [
    ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"),
])
def test_acceptance_loads_only_selected_credentials_without_openai_fallback(tmp_path, provider, key_name):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=fake-openai\nANTHROPIC_API_KEY=fake-claude\nOPENROUTER_API_KEY=fake-router\n")
    check = Check(tmp_path, {})
    load_credentials(check, sys.executable, env_file, tmp_path, provider)
    assert set(check.env) == {key_name}
    assert check.env[key_name] in check.secrets
    check.env[key_name] = "fake-shell-key"
    load_credentials(check, sys.executable, env_file, tmp_path, provider)
    assert check.env[key_name] == "fake-shell-key"


def test_acceptance_rejects_unrelated_keys_and_requires_explicit_non_openai_model(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-fake-key")
    with pytest.raises(SystemExit) as missing_key:
        options(["--provider", "anthropic", "--model", "configured-claude", "--env-file", str(tmp_path / "missing")])
    assert missing_key.value.code == 2
    with pytest.raises(SystemExit) as missing_model:
        options(["--provider", "openrouter"])
    assert missing_model.value.code == 2
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=unrelated-fake-key\n")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        load_credentials(Check(tmp_path, {}), sys.executable, env_file, tmp_path, "anthropic")


def test_bedrock_acceptance_uses_aws_chain_and_selected_region_without_api_keys(tmp_path, monkeypatch):
    from trip_agent.config import initialize_config

    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    args = options(["--provider", "bedrock", "--model", "configured-bedrock",
                    "--aws-region", "eu-west-1", "--aws-profile", "reviewer", "--env-file", str(tmp_path / "absent")])
    check = Check(tmp_path, {})
    load_credentials(check, sys.executable, args.env_file, tmp_path, "bedrock")
    assert not check.env  # No .env required for an existing AWS profile/role.
    env_file = tmp_path / ".env"
    env_file.write_text("AWS_PROFILE=file-profile\nAWS_REGION=us-east-1\nAWS_SESSION_TOKEN=fake-session\nOPENAI_API_KEY=unrelated\n")
    check.env["AWS_REGION"] = "eu-west-2"
    load_credentials(check, sys.executable, env_file, tmp_path, "bedrock")
    assert check.env == {"AWS_PROFILE": "file-profile", "AWS_REGION": "eu-west-2", "AWS_SESSION_TOKEN": "fake-session"}
    assert "fake-session" in check.secrets
    config = tmp_path / "trip-agent.toml"
    initialize_config(config, "bedrock", args.model)
    configure_bedrock(config, args.aws_region, args.aws_profile)
    profile = tomllib.loads(config.read_text())["profiles"]["bedrock"]
    assert profile["region"] == "eu-west-1" and profile["aws_profile"] == "reviewer"
    assert profile["model_id"] == args.model and profile["max_model_calls"] == 12
