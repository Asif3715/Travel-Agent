from __future__ import annotations

import random


INTEREST_ACTIVITIES: dict[str, list[str]] = {
    "food": [
        "Breakfast at a local cafe",
        "Food market tasting tour",
        "Dinner at a well-reviewed local restaurant",
        "Street food exploration",
    ],
    "sightseeing": [
        "Guided walking tour of the historic center",
        "Visit the main city viewpoint",
        "Explore the central plaza and surrounding streets",
        "Photo walk through iconic neighborhoods",
    ],
    "art": [
        "Visit the principal art museum",
        "Gallery hopping in the arts district",
        "See a temporary exhibition",
        "Architecture and design walk",
    ],
    "history": [
        "Tour a historic monument or palace",
        "Visit a heritage museum",
        "Walk through the old town",
        "Learn about local history at a cultural center",
    ],
    "nightlife": [
        "Evening drinks in a lively district",
        "Live music or local performance",
        "Late-night food crawl",
        "Sunset-to-evening neighborhood walk",
    ],
    "nature": [
        "Morning walk in the city park",
        "Day trip to nearby green space",
        "Scenic riverside or coastal path",
        "Botanical garden visit",
    ],
    "shopping": [
        "Browse local markets and boutiques",
        "Visit a famous shopping street",
        "Pick up regional specialties",
        "Explore artisan workshops",
    ],
    "beach": [
        "Relax at the waterfront",
        "Coastal promenade walk",
        "Beachside lunch",
        "Sunset by the water",
    ],
}


def _pick_activities(interests: list[str], count: int, rng: random.Random) -> list[str]:
    pool: list[str] = []
    normalized = [i.lower().strip() for i in interests if i.strip()]
    for interest in normalized:
        pool.extend(INTEREST_ACTIVITIES.get(interest, [f"Explore {interest} spots"]))
    if not pool:
        pool = INTEREST_ACTIVITIES["sightseeing"] + INTEREST_ACTIVITIES["food"]
    rng.shuffle(pool)
    return pool[:count]


def _poi_items(pois: list[dict], count: int) -> list[str]:
    items: list[str] = []
    for poi in pois[:count]:
        name = poi.get("name", "")
        poi_type = poi.get("type", "place")
        if name:
            items.append(f"Visit {name} ({poi_type})")
    return items


def build_itinerary(
    destination: str,
    interests: list[str],
    days: int = 2,
    *,
    pois: list[dict] | None = None,
    wikipedia_summary: str = "",
) -> list[dict]:
    """Build a day-by-day itinerary using interests and real POI data when available."""
    seed = hash((destination, tuple(interests), days, wikipedia_summary[:80])) & 0xFFFFFFFF
    rng = random.Random(seed)

    interest_text = ", ".join(interests) if interests else "general sightseeing"
    poi_pool = list(pois or [])
    rng.shuffle(poi_pool)

    result: list[dict] = []
    activity_pool = _pick_activities(interests, days * 4, rng)
    activity_idx = 0
    poi_idx = 0

    for day in range(1, max(days, 1) + 1):
        if day == 1:
            title = f"Arrival in {destination.split(',')[0]}"
            items = [
                f"Arrive in {destination} and check in",
                "Short orientation walk near your accommodation",
            ]
            if wikipedia_summary:
                items.append(f"Context: {wikipedia_summary[:120].rstrip()}...")
            items.append(f"Light planning around {interest_text}")
        elif day == days:
            title = "Departure day"
            items = [
                "Pack and check out",
                "Last-minute souvenir stop or favorite revisit",
                "Head to airport/station",
            ]
        else:
            title = f"Explore {destination.split(',')[0]} — day {day}"
            items = []

        # Mix real POIs and interest-based activities
        while len(items) < 4 and poi_idx < len(poi_pool):
            poi = poi_pool[poi_idx]
            poi_idx += 1
            name = poi.get("name", "")
            if name:
                items.append(f"Visit {name}")

        while len(items) < 4 and activity_idx < len(activity_pool):
            items.append(f"{activity_pool[activity_idx]} in {destination.split(',')[0]}")
            activity_idx += 1

        if day > 1 and day < days:
            items.append("Evening: local dinner and neighborhood stroll")

        result.append({"day": day, "title": title, "items": items[:5]})

    return result
