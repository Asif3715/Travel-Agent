"""Shared memory store that agents read and write during a planning run."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEvent:
    """A single logged action inside the memory timeline."""
    timestamp: float
    agent: str
    action: str
    key: str
    summary: str = ""


class SharedMemory:
    """Thread-safe-ish dict-based memory that every agent can read/write.

    Each planning run gets its own SharedMemory instance so there is no
    cross-request contamination.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._timeline: list[MemoryEvent] = []

    # ── write ────────────────────────────────────────────────────────
    def store(self, key: str, value: Any, *, agent: str, summary: str = "") -> None:
        self._store[key] = value
        self._timeline.append(
            MemoryEvent(
                timestamp=time.time(),
                agent=agent,
                action="store",
                key=key,
                summary=summary or _auto_summary(value),
            )
        )

    def append(self, key: str, value: Any, *, agent: str, summary: str = "") -> None:
        """Append *value* to a list stored under *key*."""
        bucket = self._store.setdefault(key, [])
        if not isinstance(bucket, list):
            bucket = [bucket]
            self._store[key] = bucket
        bucket.append(value)
        self._timeline.append(
            MemoryEvent(
                timestamp=time.time(),
                agent=agent,
                action="append",
                key=key,
                summary=summary or _auto_summary(value),
            )
        )

    # ── read ─────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the full store."""
        return dict(self._store)

    def context_summary(self, *, max_chars: int = 4000) -> str:
        """Return a rich text summary of stored data for downstream LLM prompts."""
        parts: list[str] = []

        request = self._store.get("request")
        if isinstance(request, dict):
            parts.append(
                f"Trip: {request.get('origin', '?')} → {request.get('destination', '?')}, "
                f"{request.get('start_date', '?')} to {request.get('end_date', '?')}, "
                f"{request.get('travelers', 1)} travelers, ${request.get('budget_usd', '?')} budget, "
                f"interests: {', '.join(request.get('interests', [])) or 'general'}"
            )

        overview = self._store.get("destination_overview")
        if isinstance(overview, dict):
            geo = overview.get("geocoded") or {}
            if geo.get("name"):
                parts.append(f"Location: {geo['name']}")
            wiki = overview.get("wikipedia") or {}
            if wiki.get("summary"):
                parts.append(f"About destination: {wiki['summary'][:500]}")
            if overview.get("weather_summary"):
                parts.append(f"Weather forecast: {overview['weather_summary'][:600]}")

        research = self._store.get("research_summary")
        if isinstance(research, str) and research.strip():
            parts.append(f"Research notes: {research[:500]}")

        recs = self._store.get("recommendations_data")
        if isinstance(recs, list) and recs:
            rec_lines = [
                f"- {r.get('name', '?')} ({r.get('type', '?')}): {r.get('reason', '')[:80]}"
                for r in recs[:6]
                if isinstance(r, dict)
            ]
            parts.append("Recommendations:\n" + "\n".join(rec_lines))

        itinerary = self._store.get("itinerary_data")
        if isinstance(itinerary, list) and itinerary:
            day_lines = []
            for day in itinerary[:8]:
                if isinstance(day, dict):
                    items = "; ".join(day.get("items", [])[:3])
                    day_lines.append(f"Day {day.get('day', '?')} ({day.get('title', '')}): {items}")
            parts.append("Itinerary:\n" + "\n".join(day_lines))

        budget = self._store.get("budget_data")
        if isinstance(budget, dict):
            parts.append(
                f"Budget: target ${budget.get('target', '?')}, "
                f"estimated ${budget.get('estimated_total', '?')} "
                f"({budget.get('per_person_per_day', '?')}/person/day)"
            )

        visa = self._store.get("visa_data")
        if isinstance(visa, list) and visa:
            parts.append("Visa notes: " + " | ".join(str(v) for v in visa[:3]))

        text = "\n\n".join(parts)
        return text[:max_chars]

    @property
    def timeline(self) -> list[MemoryEvent]:
        return list(self._timeline)


def _auto_summary(value: Any) -> str:
    if isinstance(value, dict):
        if "summary" in value and isinstance(value["summary"], str):
            return value["summary"][:120]
        if "weather_summary" in value:
            return str(value["weather_summary"])[:120]
        keys = ", ".join(list(value.keys())[:5])
        return f"dict({keys})"
    if isinstance(value, list):
        if value and isinstance(value[0], dict) and "name" in value[0]:
            names = ", ".join(str(item.get("name", "")) for item in value[:3])
            return f"{len(value)} items: {names}"
        return f"list[{len(value)} items]"
    if isinstance(value, str):
        return value[:120]
    return str(value)[:120]
