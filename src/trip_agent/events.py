"""Capture evidence at SDK lifecycle boundaries and announce every execution."""

import copy
import json
import re
import sys

from strands.hooks import (AfterModelCallEvent, AfterToolCallEvent, BeforeModelCallEvent,
                           BeforeToolCallEvent, HookProvider, HookRegistry)

from .config import AppError
from .compatibility import normalize_containers
from .schemas import TripResponse
from .tool_schema import align_final_schema
from .terminal import Terminal, readable_tool_result
from .tools.context import payload, quote
from .tools.travel import catalog


def validate_response(store, response):
    store.validate_state(response.trip_state)
    destinations = {d["id"] for d in catalog()["destinations"]}
    for suggestion in response.suggestions:
        if suggestion.destination_id not in destinations:
            raise AppError("Suggested destination is not supported by the mock catalog")
        if not suggestion.evidence_artifact_ids:
            raise AppError("Suggestions must cite tool-result artifacts")
        evidence = []
        for artifact_id in suggestion.evidence_artifact_ids:
            artifact = store.read(artifact_id)
            if artifact["kind"] != "tool_results":
                raise AppError("Suggestion evidence must cite tool results")
            try:
                evidence.append(payload(artifact))
            except AppError:
                pass
        supported = any(any(d["id"] == suggestion.destination_id for d in item.get("destinations", []))
                        or any(s["destination_id"] == suggestion.destination_id for s in item.get("accommodations", []))
                        for item in evidence)
        if not supported:
            raise AppError("Destination must appear in cited lookup evidence")
        if suggestion.accommodation_id and not any(
            any(s["id"] == suggestion.accommodation_id and s["destination_id"] == suggestion.destination_id
                for s in item.get("accommodations", [])) for item in evidence
        ):
            raise AppError("Accommodation must appear in cited lookup evidence")
        if suggestion.budget_artifact_id:
            budget = quote(store, suggestion.budget_artifact_id, "calculate_trip_budget")
            if budget["destination_id"] != suggestion.destination_id:
                raise AppError("Budget evidence belongs to a different destination")
            if suggestion.accommodation_id and budget["accommodation_id"] != suggestion.accommodation_id:
                raise AppError("Budget evidence belongs to a different accommodation")


class EvidenceHooks(HookProvider):
    def __init__(self, store, profile, output=None, debug=False):
        self.store = store
        self.profile = profile
        self.output = output or sys.stderr
        self.terminal = Terminal(self.output)
        self.debug = debug
        self.model_calls = 0
        self.tool_calls = {}
        self.model_input_id = None
        self.reasoning_notice_shown = False
        self.invalid_attempts = {}

    def register_hooks(self, registry: HookRegistry):
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_model(self, event: BeforeModelCallEvent):
        align_final_schema(event.agent)
        self.model_calls += 1
        if self.model_calls > self.profile.max_model_calls:
            raise AppError("Model-call limit reached; evidence is saved. Refine the request and resume.")
        self.model_input_id = self.store.save("model_inputs", {
            "call_number": self.model_calls,
            "model_config": self.profile.model_dump(mode="json"),
            "system_prompt": event.agent.system_prompt,
            "messages": copy.deepcopy(event.agent.messages),
            "tools": event.agent.tool_registry.get_all_tools_config(),
            "output_schema": TripResponse.model_json_schema(),
            "capture_level": "Strands application-visible context, not provider HTTP wire payload",
            "reasoning_replay": "omitted by Chat Completions adapter; original blocks retained" if self.profile.provider == "openrouter" else "provider adapter default",
        })
        if self.profile.provider == "openrouter" and not self.reasoning_notice_shown and any(
            "reasoningContent" in block for message in event.agent.messages for block in message.get("content", [])
        ):
            self.terminal.debug("OpenRouter: reasoning blocks are retained in evidence but omitted from Chat Completions replay.")
            self.reasoning_notice_shown = True

    def after_model(self, event: AfterModelCallEvent):
        if event.stop_response:
            message = copy.deepcopy(event.stop_response.message)
            response_id = self.store.save("model_responses", {"call_number": self.model_calls, "message": message,
                            "provider_responses": copy.deepcopy(getattr(event.agent.model, "response_identities", [])),
                            "stop_reason": event.stop_response.stop_reason},
                            sources=[self.model_input_id] if self.model_input_id else [])
            for block in message.get("content", []):
                if block.get("text"):
                    if re.search(r"<(?:tool_call|arg_key|arg_value)\b", block["text"], re.IGNORECASE):
                        self.store.save("errors", {"stage": "model_protocol", "type": "UnstructuredToolMarkup",
                                        "message": "Tool-call markup appeared in ordinary text; it was not executed."},
                                        sources=[response_id])
                        self.terminal.debug("Model emitted tool-call markup as text; it was not executed. Raw response saved.")
                        if self.debug:
                            self.terminal.prose(self.store.redact(block["text"]), "muted")
                        continue
                    self.terminal.write("Agent · progress", "heading")
                    self.terminal.prose(self.store.redact(block["text"]))
        elif event.exception:
            self.store.save("errors", {"stage": "model", "type": type(event.exception).__name__,
                                       "message": str(event.exception)},
                            sources=[self.model_input_id] if self.model_input_id else [])

    def before_tool(self, event: BeforeToolCallEvent):
        use = copy.deepcopy(event.tool_use)
        artifact_id = self.store.save("tool_calls", use)
        self.tool_calls[use["toolUseId"]] = artifact_id
        label = "Format final response" if use["name"] == "TripResponse" else use["name"]
        self.terminal.debug(f"[Tool] {label}")
        if self.debug:
            self.terminal.debug(f"Call {use['toolUseId']} · input")
            self.terminal.json(self.store.redact(use["input"]))
        if self.profile.provider == "openrouter":
            schema = (TripResponse.model_json_schema() if use["name"] == "TripResponse" else
                      event.selected_tool.tool_spec.get("inputSchema", {}).get("json", {}) if event.selected_tool else {})
            normalized, changes = normalize_containers(use["input"], schema)
            if changes:
                self.store.save("normalizations", {"tool_name": use["name"], "tool_use_id": use["toolUseId"],
                                "changes": changes, "effective_input": normalized}, sources=[artifact_id])
                use["input"] = normalized
                event.tool_use = use
                self.terminal.debug("Decoded JSON containers at " + ", ".join(change["path"] for change in changes)
                                    + "; original input preserved in evidence.")
                if self.debug:
                    self.terminal.json(self.store.redact(normalized))
        if use["name"] == "TripResponse":
            try:
                validate_response(self.store, TripResponse.model_validate(use["input"]))
            except (ValueError, AppError) as exc:
                event.cancel_tool = (f"Fix final response evidence/schema: {exc}. "
                                     "Use native JSON arrays and objects, not quoted JSON. Empty lists must be [], not null. "
                                     "Supply required fields and valid original evidence IDs; do not invent them.")
        fingerprint = json.dumps([use["name"], use["input"]], sort_keys=True)
        if self.invalid_attempts.get(fingerprint, 0) >= 2:
            raise AppError("Repeated identical invalid tool input stopped after two failed executions. "
                           "Correct the arguments or clarify the missing information and resume; evidence is saved.")

    def after_tool(self, event: AfterToolCallEvent):
        use = event.tool_use
        raw = copy.deepcopy(event.result)
        if isinstance(raw, Exception):
            raw = {"status": "error", "content": [{"text": str(raw)}]}
        invalid = raw.get("status") == "error"
        business_status = None
        for block in raw.get("content", []):
            try:
                data = block.get("json") if "json" in block else json.loads(block.get("text", ""))
                if isinstance(data, dict):
                    business_status = data.get("status")
                    invalid |= business_status == "invalid_input"
            except (ValueError, TypeError):
                pass
        fingerprint = json.dumps([use["name"], use["input"]], sort_keys=True)
        if invalid:
            self.invalid_attempts[fingerprint] = self.invalid_attempts.get(fingerprint, 0) + 1
        else:
            self.invalid_attempts.pop(fingerprint, None)
        input_id = self.tool_calls.get(use["toolUseId"])
        artifact_id = self.store.save("tool_results", {"tool_name": use["name"],
                                     "tool_use_id": use["toolUseId"], "arguments": use["input"], "result": raw},
                                     sources=[input_id] if input_id else [])
        self.terminal.debug(f"[Result] {use['name']}: {business_status or raw.get('status', 'unknown')}")
        if self.debug:
            self.terminal.debug(f"Evidence {artifact_id} · result")
            self.terminal.json(self.store.redact(readable_tool_result(raw)))
        if isinstance(event.result, dict):
            event.result.setdefault("content", []).append({"text": f"Evidence artifact ID: {artifact_id}"})
