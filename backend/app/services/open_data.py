"""Async open-data helpers: geocoding, weather, Wikipedia, POIs, search links."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, quote_plus

import httpx

INTEREST_SEARCH_TERMS: dict[str, list[str]] = {
    "food": ["restaurant", "food market", "cafe"],
    "sightseeing": ["tourist attraction", "landmark", "viewpoint"],
    "art": ["art museum", "gallery"],
    "history": ["historic site", "monument", "castle"],
    "nightlife": ["bar", "nightclub"],
    "nature": ["park", "garden", "nature reserve"],
    "shopping": ["market", "shopping district"],
    "beach": ["beach", "coastal walk"],
    "music": ["concert hall", "live music venue"],
    "architecture": ["cathedral", "architecture landmark"],
}


@dataclass
class PlaceSummary:
    name: str
    latitude: float | None = None
    longitude: float | None = None
    source: str = ""
    country: str = ""
    place_type: str = ""


@dataclass
class PlaceRecommendation:
    name: str
    type: str
    reason: str
    latitude: float | None = None
    longitude: float | None = None


def _wikipedia_title(name: str) -> str:
    # Use the city/place portion before the first comma for Wikipedia lookup.
    primary = name.split(",")[0].strip()
    return quote(primary.replace(" ", "_"), safe="")


async def build_flight_search_link(origin: str, destination: str) -> str:
    query = quote_plus(f"flights from {origin} to {destination}")
    return f"https://www.google.com/travel/flights?q={query}"


async def build_hotel_search_link(destination: str) -> str:
    query = quote_plus(f"hotels in {destination}")
    return f"https://www.google.com/travel/hotels/{destination.replace(' ', '%20')}?q={query}"


async def geocode_place(
    query: str, timeout_s: float = 30.0, user_agent: str = "travel-agent/0.1"
) -> PlaceSummary | None:
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    headers = {"User-Agent": user_agent}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            items = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not items:
        return None
    item = items[0]
    address = item.get("address", {})
    return PlaceSummary(
        name=item.get("display_name", query),
        latitude=float(item["lat"]),
        longitude=float(item["lon"]),
        source="nominatim",
        country=address.get("country", ""),
        place_type=item.get("type", ""),
    )


async def fetch_wikipedia_summary(
    place_name: str, timeout_s: float = 30.0
) -> dict | None:
    title = _wikipedia_title(place_name)
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, headers={"User-Agent": "travel-agent/0.1"})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    extract = data.get("extract", "")
    if not extract:
        return None
    return {
        "title": data.get("title", place_name),
        "summary": extract[:800],
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
    }


async def search_places(
    query: str,
    *,
    limit: int = 5,
    timeout_s: float = 30.0,
    user_agent: str = "travel-agent/0.1",
    near_lat: float | None = None,
    near_lon: float | None = None,
) -> list[dict]:
    url = "https://nominatim.openstreetmap.org/search"
    params: dict = {"q": query, "format": "jsonv2", "limit": limit}
    if near_lat is not None and near_lon is not None:
        delta = 0.4
        params["viewbox"] = f"{near_lon - delta},{near_lat + delta},{near_lon + delta},{near_lat - delta}"
        params["bounded"] = 1
    headers = {"User-Agent": user_agent}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        return []


async def fetch_local_recommendations(
    destination: str,
    interests: list[str],
    *,
    timeout_s: float = 30.0,
    user_agent: str = "travel-agent/0.1",
) -> list[PlaceRecommendation]:
    """Fetch real POIs from OpenStreetMap via Nominatim."""
    geocoded = await geocode_place(destination, timeout_s=timeout_s, user_agent=user_agent)
    near_lat = geocoded.latitude if geocoded else None
    near_lon = geocoded.longitude if geocoded else None
    city_name = destination.split(",")[0].strip()

    queries: list[tuple[str, str]] = []
    for interest in interests[:4]:
        terms = INTEREST_SEARCH_TERMS.get(interest.lower().strip(), [interest])
        for term in terms[:2]:
            queries.append((interest, f"{term}, {city_name}"))

    if not queries:
        queries = [
            ("sightseeing", f"tourist attraction, {city_name}"),
            ("food", f"restaurant, {city_name}"),
            ("culture", f"museum, {city_name}"),
        ]

    recommendations: list[PlaceRecommendation] = []
    seen_names: set[str] = set()

    for interest_type, query in queries:
        items = await search_places(
            query,
            limit=4,
            timeout_s=timeout_s,
            user_agent=user_agent,
            near_lat=near_lat,
            near_lon=near_lon,
        )
        for item in items:
            name = item.get("name") or item.get("display_name", "").split(",")[0]
            if not name:
                continue
            key = name.lower().strip()
            if key in seen_names:
                continue
            seen_names.add(key)
            place_type = item.get("type", interest_type)
            recommendations.append(
                PlaceRecommendation(
                    name=name,
                    type=place_type,
                    reason=f"OpenStreetMap match for '{interest_type}' near {destination}",
                    latitude=float(item["lat"]) if item.get("lat") else None,
                    longitude=float(item["lon"]) if item.get("lon") else None,
                )
            )
            if len(recommendations) >= 10:
                break
        if len(recommendations) >= 10:
            break

    if not recommendations:
        if geocoded:
            recommendations.append(
                PlaceRecommendation(
                    name=geocoded.name.split(",")[0],
                    type="destination",
                    reason="Primary destination from geocoding",
                    latitude=geocoded.latitude,
                    longitude=geocoded.longitude,
                )
            )

    return recommendations


def _weather_code_label(code: int | None) -> str:
    labels = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "depositing rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        61: "slight rain",
        63: "moderate rain",
        65: "heavy rain",
        71: "slight snow",
        73: "moderate snow",
        75: "heavy snow",
        80: "rain showers",
        95: "thunderstorm",
    }
    return labels.get(code, "variable conditions") if code is not None else "unknown"


async def fetch_open_meteo_summary(
    latitude: float,
    longitude: float,
    timeout_s: float = 30.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params: dict = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "auto",
    }
    if start_date and end_date:
        params["start_date"] = start_date
        params["end_date"] = end_date

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        return {}


def summarize_weather(weather: dict, *, start_date: str | None = None, end_date: str | None = None) -> str:
    if not weather:
        return ""
    parts: list[str] = []
    current = weather.get("current", {})
    if current:
        temp = current.get("temperature_2m")
        code = current.get("weather_code")
        if temp is not None:
            parts.append(f"Currently {temp}°C, {_weather_code_label(code)}")
    daily = weather.get("daily", {})
    dates = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_probability_max", [])
    codes = daily.get("weather_code", [])

    trip_days = [d for d in dates if (not start_date or d >= start_date) and (not end_date or d <= end_date)]
    if not trip_days and start_date and end_date:
        parts.append(
            f"Detailed forecast unavailable for {start_date} to {end_date} "
            "(dates may be beyond the 16-day forecast window). Showing nearest available forecast:"
        )
        trip_days = dates[:5]

    for day in trip_days[:7]:
        i = dates.index(day) if day in dates else -1
        if i < 0:
            continue
        hi = highs[i] if i < len(highs) else None
        lo = lows[i] if i < len(lows) else None
        rain = precip[i] if i < len(precip) else None
        code = codes[i] if i < len(codes) else None
        line = f"{day}: "
        if hi is not None and lo is not None:
            line += f"{lo:.0f}–{hi:.0f}°C"
        line += f", {_weather_code_label(code)}"
        if rain is not None:
            line += f", {rain}% rain chance"
        parts.append(line)
    return "; ".join(parts)


async def destination_overview(
    destination: str,
    timeout_s: float = 30.0,
    user_agent: str = "travel-agent/0.1",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    geocoded = await geocode_place(destination, timeout_s=timeout_s, user_agent=user_agent)
    weather: dict = {}
    weather_summary = ""
    wikipedia = None

    if geocoded and geocoded.latitude is not None and geocoded.longitude is not None:
        weather = await fetch_open_meteo_summary(
            geocoded.latitude,
            geocoded.longitude,
            timeout_s=timeout_s,
            start_date=start_date,
            end_date=end_date,
        )
        weather_summary = summarize_weather(weather, start_date=start_date, end_date=end_date)
        wiki_query = geocoded.name.split(",")[0]
        wikipedia = await fetch_wikipedia_summary(wiki_query, timeout_s=timeout_s)
    else:
        wikipedia = await fetch_wikipedia_summary(destination, timeout_s=timeout_s)

    return {
        "destination": destination,
        "geocoded": geocoded.__dict__ if geocoded else None,
        "wikipedia": wikipedia,
        "weather": weather,
        "weather_summary": weather_summary,
    }
