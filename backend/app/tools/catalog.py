"""Tool catalog: implementations + JSON schemas for LLM function calling."""

from __future__ import annotations

from ..services.budget import estimate_budget
from ..services.itinerary import build_itinerary
from ..services.open_data import (
    build_flight_search_link,
    build_hotel_search_link,
    destination_overview,
    fetch_local_recommendations,
    fetch_wikipedia_summary,
    geocode_place,
)
from ..services.visa import visa_notes


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations (async wrappers)
# ═══════════════════════════════════════════════════════════════════════

async def tool_destination_overview(
    *,
    destination: str,
    timeout_s: float,
    user_agent: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    return await destination_overview(
        destination,
        timeout_s=timeout_s,
        user_agent=user_agent,
        start_date=start_date,
        end_date=end_date,
    )


async def tool_search_flights(*, origin: str, destination: str) -> dict:
    url = await build_flight_search_link(origin, destination)
    return {"label": f"Flights: {origin} → {destination}", "url": url}


async def tool_search_hotels(*, destination: str) -> dict:
    url = await build_hotel_search_link(destination)
    return {"label": f"Hotels in {destination}", "url": url}


async def tool_build_itinerary(
    *,
    destination: str,
    interests: list[str],
    days: int,
    timeout_s: float,
    user_agent: str,
) -> list[dict]:
    pois_raw = await fetch_local_recommendations(
        destination, interests, timeout_s=timeout_s, user_agent=user_agent
    )
    pois = [{"name": p.name, "type": p.type} for p in pois_raw]
    wiki = await fetch_wikipedia_summary(destination.split(",")[0], timeout_s=timeout_s)
    wiki_text = wiki.get("summary", "") if wiki else ""
    return build_itinerary(
        destination,
        interests,
        days=days,
        pois=pois,
        wikipedia_summary=wiki_text,
    )


async def tool_estimate_budget(*, budget_usd: int, travelers: int, nights: int) -> dict:
    return estimate_budget(budget_usd, travelers, nights)


async def tool_visa_notes(
    *,
    origin: str,
    destination: str,
    timeout_s: float,
    user_agent: str,
) -> list[str]:
    geocoded = await geocode_place(destination, timeout_s=timeout_s, user_agent=user_agent)
    country = geocoded.country if geocoded else ""
    return await visa_notes(
        origin,
        destination,
        destination_country=country,
        timeout_s=timeout_s,
    )


async def tool_local_recommendations(
    *,
    destination: str,
    interests: list[str],
    timeout_s: float,
    user_agent: str,
) -> list[dict]:
    recs = await fetch_local_recommendations(
        destination, interests, timeout_s=timeout_s, user_agent=user_agent
    )
    return [
        {"name": r.name, "type": r.type, "reason": r.reason}
        for r in recs
    ]


# ═══════════════════════════════════════════════════════════════════════
# JSON schemas for LLM function calling
# ═══════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS: dict[str, dict] = {
    "destination_overview": {
        "type": "function",
        "function": {
            "name": "destination_overview",
            "description": "Get geocoding, Wikipedia summary, and weather forecast for a travel destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string", "description": "City or place name, e.g. 'Paris'"},
                    "start_date": {"type": "string", "description": "Trip start date YYYY-MM-DD (for weather forecast)"},
                    "end_date": {"type": "string", "description": "Trip end date YYYY-MM-DD (for weather forecast)"},
                },
                "required": ["destination"],
            },
        },
    },
    "search_flights": {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Generate a flight search link between two cities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Departure city"},
                    "destination": {"type": "string", "description": "Arrival city"},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    "search_hotels": {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Generate a hotel search link for a destination city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string", "description": "City to search hotels in"},
                },
                "required": ["destination"],
            },
        },
    },
    "build_itinerary": {
        "type": "function",
        "function": {
            "name": "build_itinerary",
            "description": "Build a day-by-day travel itinerary using real local POIs and traveler interests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "interests": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Traveler's interests like 'food', 'art', 'nightlife'",
                    },
                    "days": {"type": "integer", "description": "Number of days"},
                },
                "required": ["destination", "interests", "days"],
            },
        },
    },
    "estimate_budget": {
        "type": "function",
        "function": {
            "name": "estimate_budget",
            "description": "Estimate a trip budget with per-day breakdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "budget_usd": {"type": "integer", "description": "Total budget in USD"},
                    "travelers": {"type": "integer"},
                    "nights": {"type": "integer"},
                },
                "required": ["budget_usd", "travelers", "nights"],
            },
        },
    },
    "visa_notes": {
        "type": "function",
        "function": {
            "name": "visa_notes",
            "description": "Get visa and entry requirement notes for a route using open country data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    "local_recommendations": {
        "type": "function",
        "function": {
            "name": "local_recommendations",
            "description": "Get real local places from OpenStreetMap based on traveler interests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "interests": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["destination", "interests"],
            },
        },
    },
}
