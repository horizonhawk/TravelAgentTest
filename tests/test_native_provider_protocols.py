"""Real provider adapters and Strands loop, with transport fixtures instead of model calls.

These tests deliberately do not import the OpenAI SDK. They also run in isolated
Anthropic-only / Bedrock-only environments during the dependency audit.
"""

import json

from trip_agent.cli import main
from trip_agent.session import Sessions


def prepare(tmp_path, monkeypatch, capsys, provider):
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    if provider == "anthropic":
        monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-anthropic-key")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "offline-aws-id")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "offline-aws-secret")
    assert main(["config", "init", "--provider", provider, "--model", "offline-model-id"]) == 0
    assert main(["config", "check"]) == 0
    assert main(["session", "create", "--name", "Native provider check"]) == 0
    capsys.readouterr()


def action(call_number):
    if call_number == 1:
        return "search_destinations", {"destination_id": "porto"}
    return "TripResponse", {
        "status": "needs_clarification", "message": "Porto is in the mock catalog.", "trip_state": {},
        "questions": ["Where are you departing from?"], "caveats": ["Mock data only."],
    }


def run_and_resume(tmp_path, capsys, calls):
    assert main(["run", "--session", "Native provider check", "--json", "Look up Porto and ask where I depart from."]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["response"]["status"] == "needs_clarification"
    assert len(calls) == 2
    assert main(["run", "--session", "Native provider check", "--json", "Continue this saved conversation."]) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["session_id"] == second["session_id"] and first["artifact_id"] != second["artifact_id"]
    assert len(calls) == 3
    session = Sessions(tmp_path / ".trip-agent").resolve(first["session_id"])
    for kind in ("requests", "tool_calls", "tool_results", "trip_states", "final_responses"):
        assert list((session / "artifacts" / kind).glob("*.json")), kind
    assert len(list((session / "artifacts/final_responses").glob("*.json"))) == 2
    assert list((session / "logbooks").glob("*.html"))


def test_anthropic_cli_tools_structured_output_and_resume(tmp_path, monkeypatch, capsys):
    import anthropic
    import httpx

    prepare(tmp_path, monkeypatch, capsys, "anthropic")
    calls = []

    def respond(request):
        assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "offline-anthropic-key"
        data = json.loads(request.content)
        calls.append(data)
        assert data["model"] == "offline-model-id" and data["stream"] is True
        assert {"search_destinations", "TripResponse"} <= {t["name"] for t in data["tools"]}
        if len(calls) > 1:
            results = [b for m in data["messages"] for b in m["content"] if b["type"] == "tool_result"]
            assert "porto" in json.dumps(results).lower() and "Evidence artifact ID:" in json.dumps(results)
        name, inputs = action(len(calls))
        events = [
            {"type": "message_start", "message": {"id": f"msg-{len(calls)}", "type": "message", "role": "assistant",
                "model": "offline-model-id", "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {
                "type": "tool_use", "id": f"call-{len(calls)}", "name": name, "input": {}}},
            {"type": "content_block_delta", "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(inputs)}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 20}},
            {"type": "message_stop"},
        ]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
            "event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events))

    original = anthropic.AsyncAnthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: original(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    run_and_resume(tmp_path, capsys, calls)


def test_bedrock_cli_tools_structured_output_and_resume(tmp_path, monkeypatch, capsys):
    from botocore.client import BaseClient
    from botocore.validate import validate_parameters

    prepare(tmp_path, monkeypatch, capsys, "bedrock")
    calls = []

    def respond(client, operation_name, params):
        assert operation_name == "ConverseStream"
        # Validate with the actual botocore operation shape before returning synthetic events.
        validate_parameters(params, client.meta.service_model.operation_model(operation_name).input_shape)
        assert client.meta.region_name == "us-west-2"
        assert params["modelId"] == "offline-model-id"
        calls.append(params)
        assert {"search_destinations", "TripResponse"} <= {t["toolSpec"]["name"] for t in params["toolConfig"]["tools"]}
        if len(calls) > 1:
            results = [b["toolResult"] for m in params["messages"] for b in m["content"] if "toolResult" in b]
            assert "porto" in json.dumps(results).lower() and "Evidence artifact ID:" in json.dumps(results)
        name, inputs = action(len(calls))
        return {"stream": iter([
            {"messageStart": {"role": "assistant"}},
            {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"name": name, "toolUseId": f"call-{len(calls)}"}}}},
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": json.dumps(inputs)}}}},
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"messageStop": {"stopReason": "tool_use"}},
            {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30}, "metrics": {"latencyMs": 1}}},
        ])}

    monkeypatch.setattr(BaseClient, "_make_api_call", respond)
    run_and_resume(tmp_path, capsys, calls)
