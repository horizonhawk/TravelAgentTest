"""One model-directed Strands invocation, restored from a named local session."""

import json
import os
import uuid
from importlib.metadata import version

from strands import Agent
from strands.session import SnapshotSessionManager
from strands.storage import LocalFileStorage
from strands.tools.executors.sequential import SequentialToolExecutor
from strands.types.exceptions import StructuredOutputException

from .config import AppError, Profile
from .events import EvidenceHooks, validate_response
from .models import build_model
from .failures import classify_failure
from .persistence import ArtifactStore, now
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, STRUCTURED_OUTPUT_PROMPT
from .schemas import TripResponse
from .tools import build_tools


def run_turn(sessions, reference, request, *, model=None, output=None, debug=False):
    if not request.strip():
        raise AppError("Please provide a non-empty travel request")
    path = sessions.resolve(reference)
    with sessions.lock(path.name):
        metadata = sessions.metadata(path)
        profile = Profile.model_validate(metadata["model_config"])
        turn_id = str(uuid.uuid4())
        secrets = [os.environ.get(name, "") for name in
                   {profile.credential_env, "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK"}]
        store = ArtifactStore(path, turn_id, secrets)
        if metadata["status"] == "running":
            store.event("previous_turn_interrupted", turn=metadata["latest_turn_id"])
        sessions.update(path, status="running", latest_turn_id=turn_id)
        store.event("turn_started", profile=metadata["active_profile"])
        request_id = store.save("requests", {"text": request})
        try:
            selected_model = model if model is not None else build_model(profile)
            hooks = EvidenceHooks(store, profile, output, debug=debug)
            memory = SnapshotSessionManager(path.name, storage=LocalFileStorage(str(path / "memory")))
            agent = Agent(model=selected_model, system_prompt=SYSTEM_PROMPT,
                          tools=build_tools(store), structured_output_model=TripResponse,
                          structured_output_prompt=STRUCTURED_OUTPUT_PROMPT,
                          session_manager=memory, hooks=[hooks], callback_handler=None,
                          tool_executor=SequentialToolExecutor(), retry_strategy=None,
                          agent_id="trip-agent")
            store.save("prompt_configs", {"prompt_version": PROMPT_VERSION, "system_prompt": SYSTEM_PROMPT,
                       "structured_output_prompt": STRUCTURED_OUTPUT_PROMPT,
                       "model_config": profile.model_dump(mode="json"), "strands_version": version("strands-agents"),
                       "tools": agent.tool_registry.get_all_tools_config(),
                       "output_schema": TripResponse.model_json_schema()})
            current_path = path / "current_trip.json"
            current = json.loads(current_path.read_text()) if current_path.exists() else None
            envelope = {"user_request": request, "request_artifact_id": request_id,
                        "reference_time_utc": now(), "current_trip": current,
                        "recent_artifacts": store.list()[-15:]}
            result = agent(json.dumps(envelope, ensure_ascii=False))
            response = result.structured_output
            if not isinstance(response, TripResponse):
                raise AppError("Model did not return a valid TripResponse")
            validate_response(store, response)
            state_id = store.save_state(response.trip_state)
            final_id = store.save("final_responses", response.model_dump(mode="json"), sources=[request_id, state_id])
            status = "awaiting_clarification" if response.status == "needs_clarification" else "ready"
            sessions.update(path, status=status)
            store.event("turn_completed", final_artifact_id=final_id)
            return {"session_id": path.name, "turn_id": turn_id, "artifact_id": final_id,
                    "response": response.model_dump(mode="json")}
        except BaseException as exc:
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            failure = classify_failure(exc)
            store.save("errors", {"stage": "turn", "type": type(exc).__name__, "message": str(exc), **failure})
            sessions.update(path, status=status)
            store.event("turn_" + status)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, AppError):
                raise
            if profile.provider == "openrouter" and getattr(exc, "status_code", None) == 404:
                raise AppError(store.redact(
                    f"OpenRouter cannot serve '{profile.model_id}' with this request (HTTP 404). "
                    "The model/free variant may be unavailable, or no endpoint supports the requested features. "
                    "For a free connectivity check, configure model_id = 'openrouter/free'. "
                    "After changing the profile, rerun config check --live or create a fresh test session; "
                    "existing sessions retain their saved model. No paid fallback was attempted. "
                    "The provider error and session evidence are saved."
                )) from exc
            if failure["provider_blocked"]:
                advice = {
                    "provider_quota": "The provider quota is exhausted. Wait for its reset or explicitly change your account/model configuration.",
                    "provider_rate_limit": "The provider rate-limited this request. Retry later after the limit resets.",
                    "provider_connection": "The provider could not be reached. Check network access and retry.",
                    "provider_access": "The provider rejected access to this model. Check the configured model, credentials and endpoint availability.",
                    "provider_unavailable": "The provider service is unavailable. Retry later.",
                }[failure["category"]]
                raise AppError(f"Provider blocked ({failure['category']}): {advice} "
                               "This is not a travel-agent quality result. Evidence is saved; no provider or model was switched.") from exc
            if failure["category"] in {"model_call_limit", "repeated_invalid_tool_input"}:
                raise AppError(f"Agent stopped ({failure['category']}): {exc}") from exc
            if isinstance(exc, StructuredOutputException):
                raise AppError(store.redact(
                    f"Model '{profile.model_id}' did not return a valid native TripResponse tool call, "
                    "even after Strands requested it explicitly. This is a model/tool-protocol failure. "
                    "No valid final response was saved for this turn; completed tools, intermediate state, "
                    "and raw responses remain in the logbook. You can retry in this session. "
                    "If it repeats, test an explicit tool-capable model in a separate session. "
                    "No model or provider was switched automatically."
                )) from exc
            raise AppError(store.redact(f"Agent call failed ({type(exc).__name__}): {exc}. "
                                      "Inspect the saved session logbook for the failure evidence.")) from exc
