"""Small explicit fixtures; no real travel services or implicit user defaults."""

import json
import math
from importlib.resources import files

from ..tool_schema import schema_tool as tool


def catalog():
    return json.loads(files("trip_agent").joinpath("data/mock_catalog.json").read_text())


def result(status, **data):
    return {"status": status, "source": "mock", "catalog_version": "1", "currency": "USD",
            "caveat": catalog()["disclaimer"], **data}


@tool
def search_destinations(tags: list[str] | None = None, region: str | None = None,
                        month: int | None = None, near: str | None = None,
                        exclude: list[str] | None = None, destination_id: str | None = None) -> dict:
    """Explore mock destinations, including when the user has not chosen one.

    Args:
        tags: Required fixture tags, e.g. beach, food, walkable, romantic, family, warm.
        region: Optional region: Europe, Japan, Mexico.
        month: Travel month 1–12 if known. Warm-season filter applies only with the warm tag.
        near: Optional nearby city; the small catalog supports Lisbon.
        exclude: Destination names/IDs the user excludes.
        destination_id: Optional exact destination ID to inspect.
    """
    if month is not None and not 1 <= month <= 12:
        return result("invalid_input", message="month must be 1–12")
    tags = [tag.lower() for tag in tags or []]
    excluded = {item.lower() for item in exclude or []}
    matches = []
    for d in catalog()["destinations"]:
        if d["id"] in excluded or d["name"].lower() in excluded:
            continue
        if destination_id and destination_id.lower() != d["id"]:
            continue
        if region and region.lower() != d["region"].lower():
            continue
        if near and near.lower() not in d["near"]:
            continue
        if not set(tags) - {"warm"} <= set(d["tags"]):
            continue
        if "warm" in tags and month is not None and month not in d["warm_months"]:
            continue
        matches.append(d)
    return result("ok" if matches else "no_match", destinations=matches,
                  missing_inputs=["travel month to assess warmth"] if "warm" in tags and month is None else [])


@tool
def search_flights(destination_id: str, origin: str | None = None, month: int | None = None) -> dict:
    """Look up mock round-trip airfare per person; never assume a missing origin.

    Args:
        destination_id: ID from search_destinations.
        origin: User's departure airport (JFK, SFO, LIS in this catalog), if known.
        month: Month 1–12 if known; fixture rates are not date-specific.
    """
    if not origin:
        return result("missing_input", missing_inputs=["origin"], flights=[])
    if month is not None and not 1 <= month <= 12:
        return result("invalid_input", message="month must be 1–12", flights=[])
    flights = [flight for flight in catalog()["flights"]
               if flight["origin"] == origin.upper() and flight["destination_id"] == destination_id]
    return result("ok" if flights else "no_match", flights=flights, month=month,
                  assumptions=["Round trip per person; same illustrative fare for adults and children.",
                               "Dates do not change these fixtures; this is not a quote."])


@tool
def search_accommodations(destination_id: str, amenities: list[str] | None = None,
                          max_nightly_usd: float | None = None) -> dict:
    """Find mock stays; prices are per room per night, not per traveler or entire trip.

    Args:
        destination_id: ID from search_destinations.
        amenities: Required fixture amenities, such as pool, boutique, family, nice.
        max_nightly_usd: Optional upper limit per room per night in USD; omit or pass null if not stated, never zero.
    """
    if max_nightly_usd is not None and (not math.isfinite(max_nightly_usd) or max_nightly_usd <= 0):
        return result("invalid_input", message="Nightly limit must be finite and positive when supplied. Omit max_nightly_usd or pass null when no nightly limit was stated.", accommodations=[])
    required = {item.lower() for item in amenities or []}
    stays = [stay for stay in catalog()["accommodations"] if stay["destination_id"] == destination_id
             and required <= set(stay["amenities"])
             and (max_nightly_usd is None or stay["nightly_room_usd"][1] <= max_nightly_usd)]
    return result("ok" if stays else "no_match", accommodations=stays)
