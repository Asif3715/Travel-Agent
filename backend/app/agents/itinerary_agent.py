"""Itinerary agent — builds a day-by-day travel plan."""

from __future__ import annotations

from ..memory import SharedMemory
from ..tools.registry import ToolContext, get_tool_result
from .base import BaseAgent


class ItineraryAgent(BaseAgent):
    name = "itinerary"
    purpose = "Build a day-by-day travel itinerary"
    allowed_tools = ["build_itinerary"]
    system_prompt = (
        "You are a travel itinerary agent. Build a detailed day-by-day plan.\n"
        "Always call `build_itinerary` with the correct number of days from the trip context.\n"
        "Use the research context (weather, Wikipedia, recommendations) to personalize your summary.\n"
        "Mention specific places from the tool results when possible."
    )

    def _store_results(self, memory: SharedMemory, text: str, ctx: ToolContext) -> None:
        memory.store("itinerary_summary", text, agent=self.name)
        days_data = get_tool_result(ctx, "build_itinerary")
        if days_data:
            memory.store("itinerary_data", days_data, agent=self.name)

    async def _ensure_tools(self, ctx: ToolContext, memory: SharedMemory) -> None:
        if get_tool_result(ctx, "build_itinerary"):
            return
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        interests = request.get("interests", [])
        nights = memory.get("trip_nights", 3)
        await self.tools.run(
            ctx, "build_itinerary",
            destination=dest,
            interests=interests,
            days=nights,
        )

    async def _fallback_run(self, ctx: ToolContext, memory: SharedMemory) -> str:
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        interests = request.get("interests", [])
        nights = memory.get("trip_nights", 3)
        days_data = await self.tools.run(
            ctx, "build_itinerary",
            destination=dest,
            interests=interests,
            days=nights,
        )
        memory.store("itinerary_data", days_data, agent=self.name)
        summary = f"Built {len(days_data)}-day itinerary for {dest} using live POI data."
        memory.store("itinerary_summary", summary, agent=self.name)
        return summary
