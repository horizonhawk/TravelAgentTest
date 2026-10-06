import json

import pytest
from strands.models.model import Model

from trip_agent.config import Profile
from trip_agent.session import Sessions


@pytest.fixture
def sessions(tmp_path):
    return Sessions(tmp_path / "data")


@pytest.fixture
def session(sessions):
    return sessions.create("Test trip", "openai", Profile(provider="openai", model_id="gpt-6.1-sol"))


class ScriptedModel(Model):
    """Offline SDK integration double, not an evaluation of LLM quality."""

    def __init__(self, actions):
        self.actions = iter(actions)
        self.seen_messages = []
        self.seen_choices = []
        self.seen_specs = []

    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {"model_id": "scripted-test-double"}

    async def structured_output(self, *args, **kwargs):
        raise AssertionError("Structured output should use the normal tool loop")
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.seen_messages.append(json.loads(json.dumps(messages)))
        self.seen_choices.append(kwargs.get('tool_choice'))
        self.seen_specs.append(json.loads(json.dumps(tool_specs)))
        action = next(self.actions)
        if callable(action):
            action = action(messages)
        if isinstance(action, Exception):
            raise action
        name, inputs = action
        yield {"messageStart": {"role": "assistant"}}
        if name == '__text__':
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": inputs}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                                "metrics": {"latencyMs": 1}}}
            return
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"call-{len(self.seen_messages)}", "name": name}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(inputs)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                            "metrics": {"latencyMs": 1}}}


def clarification(messages):
    return "TripResponse", {"status": "needs_clarification", "message": "Let's narrow this down.",
                            "trip_state": {}, "questions": ["Where are you leaving from?"]}
