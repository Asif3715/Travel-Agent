"""Research agent — gathers destination data, weather, and search links."""

from __future__ import annotations

from ..memory import SharedMemory
from ..tools.registry import ToolContext, get_tool_result
from .base import BaseAgent


class ResearchAgent(BaseAgent):
    name = "research"
    purpose = "Gather destination facts, weather, and search links"
    allowed_tools = ["destination_overview", "search_flights", "search_hotels"]
    system_prompt = (
        "You are a travel research agent. Your job is to gather factual information "
        "about a travel destination using your tools.\n"
        "1. Call `destination_overview` with the destination AND the trip start/end dates "
        "to get geocoding, Wikipedia summary, and a date-specific weather forecast.\n"
        "2. Call `search_flights` for the origin→destination route.\n"
        "3. Call `search_hotels` for the destination.\n\n"
        "After calling all tools, write a detailed research summary covering "
        "location context, Wikipedia highlights, weather during the trip dates, "
        "and practical travel notes. Be specific to this destination — do not use generic filler."
    )

    def _store_results(self, memory: SharedMemory, text: str, ctx: ToolContext) -> None:
        memory.store("research_summary", text, agent=self.name)

        overview = get_tool_result(ctx, "destination_overview")
        if overview:
            memory.store("destination_overview", overview, agent=self.name)

        flight = get_tool_result(ctx, "search_flights")
        if flight:
            memory.store("flight_link", flight, agent=self.name)

        hotel = get_tool_result(ctx, "search_hotels")
        if hotel:
            memory.store("hotel_link", hotel, agent=self.name)

    async def _ensure_tools(self, ctx: ToolContext, memory: SharedMemory) -> None:
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        origin = request.get("origin", "the origin")

        if not get_tool_result(ctx, "destination_overview"):
            await self.tools.run(
                ctx, "destination_overview",
                destination=dest,
                start_date=request.get("start_date"),
                end_date=request.get("end_date"),
            )
        if not get_tool_result(ctx, "search_flights"):
            await self.tools.run(ctx, "search_flights", origin=origin, destination=dest)
        if not get_tool_result(ctx, "search_hotels"):
            await self.tools.run(ctx, "search_hotels", destination=dest)

    async def _fallback_run(self, ctx: ToolContext, memory: SharedMemory) -> str:
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        origin = request.get("origin", "the origin")

        overview = await self.tools.run(
            ctx, "destination_overview",
            destination=dest,
            start_date=request.get("start_date"),
            end_date=request.get("end_date"),
        )
        memory.store("destination_overview", overview, agent=self.name)

        flight = await self.tools.run(ctx, "search_flights", origin=origin, destination=dest)
        memory.store("flight_link", flight, agent=self.name)

        hotel = await self.tools.run(ctx, "search_hotels", destination=dest)
        memory.store("hotel_link", hotel, agent=self.name)

        parts = [f"Collected live data for {dest}."]
        wiki = overview.get("wikipedia") or {}
        if wiki.get("summary"):
            parts.append(wiki["summary"][:300])
        if overview.get("weather_summary"):
            parts.append(f"Weather: {overview['weather_summary'][:200]}")

        summary = " ".join(parts)
        memory.store("research_summary", summary, agent=self.name)
        return summary
