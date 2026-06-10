"""Recommendation agent — suggests local places, food, and neighborhoods."""

from __future__ import annotations

from ..memory import SharedMemory
from ..tools.registry import ToolContext, get_tool_result
from .base import BaseAgent


class RecommendationAgent(BaseAgent):
    name = "recommendation"
    purpose = "Suggest local places, food, and useful neighborhoods"
    allowed_tools = ["local_recommendations"]
    system_prompt = (
        "You are a local recommendations agent. Suggest places, food spots, "
        "and neighborhoods a traveler should know about.\n"
        "Always call `local_recommendations` first — it returns real OpenStreetMap places.\n"
        "Then write a summary highlighting the best picks for the traveler's interests."
    )

    def _store_results(self, memory: SharedMemory, text: str, ctx: ToolContext) -> None:
        memory.store("recommendation_summary", text, agent=self.name)
        recs = get_tool_result(ctx, "local_recommendations")
        if recs:
            memory.store("recommendations_data", recs, agent=self.name)

    async def _ensure_tools(self, ctx: ToolContext, memory: SharedMemory) -> None:
        if get_tool_result(ctx, "local_recommendations"):
            return
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        interests = request.get("interests", [])
        await self.tools.run(ctx, "local_recommendations", destination=dest, interests=interests)

    async def _fallback_run(self, ctx: ToolContext, memory: SharedMemory) -> str:
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        interests = request.get("interests", [])
        recs = await self.tools.run(ctx, "local_recommendations", destination=dest, interests=interests)
        memory.store("recommendations_data", recs, agent=self.name)
        names = ", ".join(r.get("name", "") for r in recs[:4])
        summary = f"Found {len(recs)} live recommendations for {dest}: {names}."
        memory.store("recommendation_summary", summary, agent=self.name)
        return summary
