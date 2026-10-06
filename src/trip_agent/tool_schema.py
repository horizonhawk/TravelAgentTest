"""Keep advertised tool schemas consistent with Python/Pydantic validation."""

import inspect
from typing import get_type_hints

from pydantic import create_model
from strands import tool

from .schemas import TripResponse


def schema_tool(function):
    """Use Strands execution and docstrings, preserving the original argument types."""
    decorated = tool(function)
    hints = get_type_hints(function)
    fields = {
        name: (hints[name], ... if parameter.default is inspect.Parameter.empty else parameter.default)
        for name, parameter in inspect.signature(function).parameters.items()
    }
    schema = create_model(function.__name__ + "Arguments", **fields).model_json_schema()
    generated = decorated.tool_spec["inputSchema"]["json"]
    for name, prop in schema["properties"].items():
        description = generated.get("properties", {}).get(name, {}).get("description")
        if description:
            prop["description"] = description
    decorated.tool_spec = {**decorated.tool_spec, "inputSchema": {"json": schema}}
    return decorated


def align_final_schema(agent):
    # The SDK registers this dynamic tool at invocation time. Its generated schema
    # wrongly makes defaulted, non-nullable lists nullable in Strands 1.57.2.
    # Update its public spec before it is collected for the model call.
    final_tool = agent.tool_registry.dynamic_tools.get("TripResponse")
    if final_tool is not None:
        final_tool.tool_spec["inputSchema"] = {"json": TripResponse.model_json_schema()}
