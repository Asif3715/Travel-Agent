"""Budget & Visa agent — estimates budget and produces visa guidance."""

from __future__ import annotations

from ..memory import SharedMemory
from ..tools.registry import ToolContext, get_tool_result
from .base import BaseAgent


class BudgetVisaAgent(BaseAgent):
    name = "budget_visa"
    purpose = "Estimate trip budget and produce visa guidance"
    allowed_tools = ["estimate_budget", "visa_notes"]
    system_prompt = (
        "You are a travel budget and visa agent.\n"
        "1. Use `estimate_budget` with the correct travelers, nights, and budget from context.\n"
        "2. Use `visa_notes` for the origin→destination route.\n"
        "Summarize the budget breakdown and visa situation clearly."
    )

    def _store_results(self, memory: SharedMemory, text: str, ctx: ToolContext) -> None:
        memory.store("budget_visa_summary", text, agent=self.name)
        budget = get_tool_result(ctx, "estimate_budget")
        if budget:
            memory.store("budget_data", budget, agent=self.name)
        visa = get_tool_result(ctx, "visa_notes")
        if visa:
            memory.store("visa_data", visa, agent=self.name)

    async def _ensure_tools(self, ctx: ToolContext, memory: SharedMemory) -> None:
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        origin = request.get("origin", "the origin")
        nights = memory.get("trip_nights", 3)

        if not get_tool_result(ctx, "estimate_budget"):
            await self.tools.run(
                ctx, "estimate_budget",
                budget_usd=request.get("budget_usd", 1500),
                travelers=request.get("travelers", 1),
                nights=nights,
            )
        if not get_tool_result(ctx, "visa_notes"):
            await self.tools.run(ctx, "visa_notes", origin=origin, destination=dest)

    async def _fallback_run(self, ctx: ToolContext, memory: SharedMemory) -> str:
        request = memory.get("request", {})
        dest = request.get("destination", "the destination")
        origin = request.get("origin", "the origin")
        nights = memory.get("trip_nights", 3)

        budget = await self.tools.run(
            ctx, "estimate_budget",
            budget_usd=request.get("budget_usd", 1500),
            travelers=request.get("travelers", 1),
            nights=nights,
        )
        memory.store("budget_data", budget, agent=self.name)

        visa = await self.tools.run(ctx, "visa_notes", origin=origin, destination=dest)
        memory.store("visa_data", visa, agent=self.name)

        summary = f"Budget target ${budget['target']} USD (est. ${budget['estimated_total']}); visa notes prepared."
        memory.store("budget_visa_summary", summary, agent=self.name)
        return summary
