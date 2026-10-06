import json

import pytest

from trip_agent.config import AppError
from trip_agent.persistence import ArtifactStore
from trip_agent.tools.context import context_tools
from trip_agent.tools.travel import search_accommodations, search_destinations, search_flights


def recorded(store, name, value):
    return store.save("tool_results", {"tool_name": name, "result": {"status": "success",
                       "content": [{"text": json.dumps(value)}]}})


def test_destination_constraints_and_missing_origin():
    warm = search_destinations(tags=["warm", "beach"], month=2)
    assert [d["id"] for d in warm["destinations"]] == ["cancun"]
    assert not search_destinations(tags=["beach"], exclude=["cancun", "algarve"])["destinations"]
    assert search_flights("tokyo")["status"] == "missing_input"
    assert search_flights("tokyo", "XYZ")["status"] == "no_match"
    assert search_accommodations("porto", amenities=["pool"])["status"] == "no_match"
    assert search_accommodations("porto", max_nightly_usd=150)["status"] == "no_match"


def test_budget_party_units_and_excluded_flights(sessions, session):
    store = ArtifactStore(sessions.resolve("Test trip"))
    accommodation = recorded(store, "search_accommodations", search_accommodations("cancun"))
    flights = recorded(store, "search_flights", search_flights("cancun", "JFK"))
    budget = context_tools(store)[0]
    output = budget("cancun", accommodation, "cancun-garden", 4, 7, 8, flights)
    assert output["rooms"] == 2
    assert output["line_items"]["lodging"] == [1540, 2100]
    assert output["line_items"]["flights"] == [1200, 1800]
    assert output["total_range_usd"] == [3860, 5980]
    excluded = budget("cancun", accommodation, "cancun-garden", 4, 7, 8, flights_excluded=True)
    assert "flights" not in excluded["line_items"]
    assert "flights" in excluded["exclusions"]
    unknown = budget("cancun", accommodation, "cancun-garden", 4, 7, 8, budget_usd=99999)
    assert unknown["unknown_costs"] == ["flights"]
    assert unknown["budget_assessment"] == "unknown"
    with pytest.raises(AppError, match="does not belong"):
        budget("porto", accommodation, "cancun-garden", 2, 7, 8)


def test_invalid_budget_inputs(sessions, session):
    budget = context_tools(ArtifactStore(sessions.resolve("Test trip")))[0]
    assert budget("tokyo", "unused", "unused", -1, 7, 8)["status"] == "invalid_input"
