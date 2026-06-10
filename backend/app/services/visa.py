from __future__ import annotations

import httpx


async def fetch_country_info(country_name: str, timeout_s: float = 15.0) -> dict | None:
    if not country_name:
        return None
    url = f"https://restcountries.com/v3.1/name/{country_name}"
    params = {"fields": "name,capital,region,subregion,languages,cca2"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            items = resp.json()
            return items[0] if items else None
    except (httpx.HTTPError, ValueError):
        return None


async def visa_notes(
    origin: str,
    destination: str,
    *,
    destination_country: str = "",
    timeout_s: float = 15.0,
) -> list[str]:
    """Produce route-specific visa guidance using open country metadata."""
    notes: list[str] = [
        f"Verify official entry requirements for travel from {origin} to {destination}.",
    ]

    country_data = await fetch_country_info(destination_country or destination, timeout_s=timeout_s)
    if country_data:
        common_name = country_data.get("name", {}).get("common", destination)
        region = country_data.get("region", "")
        subregion = country_data.get("subregion", "")
        capital = (country_data.get("capital") or [""])[0]
        code = country_data.get("cca2", "")
        notes.append(
            f"{common_name} is in {region}{f' ({subregion})' if subregion else ''}. "
            f"Capital: {capital or 'N/A'}. Country code: {code}."
        )
        langs = country_data.get("languages", {})
        if langs:
            lang_list = ", ".join(list(langs.values())[:3])
            notes.append(f"Common languages: {lang_list}.")
    else:
        notes.append(
            f"Could not fetch live country metadata for {destination}; "
            "confirm passport validity and visa rules on official government sites."
        )

    notes.append(
        "Treat all guidance as informational until confirmed by your government's travel advisory "
        "and the destination's official immigration authority."
    )
    return notes
