"""Tools are exposed to the LLM; no application-level travel workflow."""

from .travel import search_accommodations, search_destinations, search_flights
from .context import context_tools


def build_tools(store):
    return [search_destinations, search_flights, search_accommodations, *context_tools(store)]
