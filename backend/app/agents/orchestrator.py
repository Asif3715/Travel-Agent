"""Orchestrator — runs sub-agents with parallel execution and streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import AsyncGenerator

from ..config import get_settings
from ..memory import SharedMemory
from ..schemas import (
    AgentRun, ItineraryDay, Recommendation, ReviewNote,
    SearchLink, ToolRun, TripPlan, TripRequest,
)
from ..tools.registry import ToolRegistry
from .budget_visa_agent import BudgetVisaAgent
from .itinerary_agent import ItineraryAgent
from .recommendation_agent import RecommendationAgent
from .research_agent import ResearchAgent
from .reviewer_agent import ReviewerAgent

logger = logging.getLogger(__name__)


def _trip_nights(start_date: str, end_date: str) -> int:
    try:
        return max((date.fromisoformat(end_date) - date.fromisoformat(start_date)).days, 1)
    except ValueError:
        return 2


class TripOrchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.tools = ToolRegistry(self.settings)
        self.research = ResearchAgent(self.settings, self.tools)
        self.itinerary = ItineraryAgent(self.settings, self.tools)
        self.budget_visa = BudgetVisaAgent(self.settings, self.tools)
        self.recommendation = RecommendationAgent(self.settings, self.tools)
        self.reviewer = ReviewerAgent(self.settings, self.tools)

    # ── streaming entry point ────────────────────────────────────────

    async def stream(self, request: TripRequest) -> AsyncGenerator[dict, None]:
        """Yield SSE-style dicts as agents work, final event is plan_ready."""
        queue: asyncio.Queue = asyncio.Queue()
        memory = SharedMemory()
        self._seed_memory(memory, request)

        yield {"event": "planning_start", "data": {"message": f"Planning trip to {request.destination}..."}}

        # Phase 1: independent agents in parallel
        yield {"event": "phase_start", "data": {"phase": 1, "label": "Research & Recommendations", "agents": ["research", "recommendation"]}}
        task = asyncio.create_task(self._run_phase_1(request, memory, queue))
        async for evt in _drain(queue, task):
            yield evt

        # Phase 2: dependent agents in parallel
        yield {"event": "phase_start", "data": {"phase": 2, "label": "Itinerary & Budget", "agents": ["itinerary", "budget_visa"]}}
        task = asyncio.create_task(self._run_phase_2(request, memory, queue))
        async for evt in _drain(queue, task):
            yield evt

        # Phase 3: reviewer (self-critique)
        yield {"event": "phase_start", "data": {"phase": 3, "label": "Review & Critique", "agents": ["reviewer"]}}
        task = asyncio.create_task(self._run_phase_3(memory, queue))
        async for evt in _drain(queue, task):
            yield evt

        # Build final plan
        plan = self._build_plan(request, memory)
        yield {"event": "plan_ready", "data": plan.model_dump()}

    # ── non-streaming entry point ────────────────────────────────────

    async def run(self, request: TripRequest) -> TripPlan:
        """Run all agents and return the final plan (no streaming)."""
        memory = SharedMemory()
        self._seed_memory(memory, request)

        await self._run_phase_1(request, memory, None)
        await self._run_phase_2(request, memory, None)
        await self._run_phase_3(memory, None)

        return self._build_plan(request, memory)

    # ── phases ───────────────────────────────────────────────────────

    async def _run_phase_1(self, request: TripRequest, memory: SharedMemory, queue: asyncio.Queue | None) -> None:
        """Research + Recommendation in parallel."""
        research_prompt = (
            f"Research the destination '{request.destination}' for a trip from "
            f"'{request.origin}'. Dates: {request.start_date} to {request.end_date}. "
            f"Travelers: {request.travelers}. Interests: {', '.join(request.interests) or 'general'}. "
            f"Get destination overview, flight search link, and hotel search link."
        )
        rec_prompt = (
            f"Suggest local recommendations for {request.destination}. "
            f"Interests: {', '.join(request.interests) or 'general sightseeing'}."
        )
        # Run sequentially to avoid Groq rate limits when multiple agents call the LLM at once.
        await self.research.run(research_prompt, memory, queue)
        await self.recommendation.run(rec_prompt, memory, queue)

    async def _run_phase_2(self, request: TripRequest, memory: SharedMemory, queue: asyncio.Queue | None) -> None:
        """Itinerary + Budget/Visa in parallel (depend on Phase 1 context)."""
        nights = memory.get("trip_nights", 3)
        itin_prompt = (
            f"Build a {nights}-day itinerary for {request.destination}. "
            f"Interests: {', '.join(request.interests) or 'general'}. "
            f"Use the research context available in shared memory."
        )
        bv_prompt = (
            f"Estimate budget for {request.travelers} traveler(s), {nights} nights, "
            f"${request.budget_usd} total budget. Also get visa notes for "
            f"{request.origin} → {request.destination}."
        )
        await self.itinerary.run(itin_prompt, memory, queue)
        await self.budget_visa.run(bv_prompt, memory, queue)

    async def _run_phase_3(self, memory: SharedMemory, queue: asyncio.Queue | None) -> None:
        """Reviewer critiques the plan."""
        await self.reviewer.run(memory, queue)

    # ── plan assembly ────────────────────────────────────────────────

    def _seed_memory(self, memory: SharedMemory, request: TripRequest) -> None:
        nights = _trip_nights(request.start_date, request.end_date)
        memory.store("request", request.model_dump(), agent="system")
        memory.store("trip_nights", nights, agent="system")
        memory.store("llm_enabled", True, agent="system")

    def _build_plan(self, request: TripRequest, memory: SharedMemory) -> TripPlan:
        # Collect agent runs from timeline
        agents = self._build_agent_runs(memory)
        tool_runs = self._build_tool_runs(memory)

        # Extract structured data
        flight_link = memory.get("flight_link")
        hotel_link = memory.get("hotel_link")
        flights = _parse_search_links(flight_link, "Search flights", request.origin, request.destination)
        hotels = _parse_search_links(hotel_link, "Search hotels", request.destination)

        itinerary = _parse_itinerary(memory.get("itinerary_data"))
        budget = memory.get("budget_data", _default_budget(request))
        visa = memory.get("visa_data", [])
        recommendations = _parse_recommendations(memory.get("recommendations_data"))

        review_data = memory.get("review", [])
        review = [ReviewNote(**n) if isinstance(n, dict) else n for n in review_data]
        clarifications = memory.get("clarifications", [])

        summary = memory.get("research_summary", f"Trip plan for {request.destination} from {request.origin}.")
        if isinstance(summary, str) and len(summary) > 300:
            summary = summary[:300] + "..."

        destination_info = memory.get("destination_overview", {})
        if not isinstance(destination_info, dict):
            destination_info = {}

        llm_enabled = memory.get("llm_enabled", True)

        return TripPlan(
            summary=summary,
            agents=agents,
            tool_runs=tool_runs,
            flights=flights,
            hotels=hotels,
            itinerary=itinerary,
            budget=budget,
            visa=visa if isinstance(visa, list) else [str(visa)],
            recommendations=recommendations,
            review=review,
            clarifications=clarifications,
            destination_info=destination_info,
            llm_enabled=llm_enabled,
        )

    def _build_agent_runs(self, memory: SharedMemory) -> list[AgentRun]:
        agent_names = {
            "research": self.research,
            "recommendation": self.recommendation,
            "itinerary": self.itinerary,
            "budget_visa": self.budget_visa,
            "reviewer": self.reviewer,
        }
        runs = []
        for name, agent in agent_names.items():
            summary_key = f"{name}_summary"
            if name == "reviewer":
                summary_key = "review_overall"
            s = memory.get(summary_key, "")
            if s:
                runs.append(AgentRun(
                    name=name,
                    purpose=getattr(agent, "purpose", ""),
                    summary=str(s)[:200],
                ))
        return runs

    def _build_tool_runs(self, memory: SharedMemory) -> list[ToolRun]:
        raw_runs = memory.get("all_tool_runs", [])
        runs: list[ToolRun] = []
        for item in raw_runs:
            if isinstance(item, dict):
                runs.append(ToolRun(
                    agent=item.get("agent", ""),
                    tool=item.get("tool", ""),
                    arguments=item.get("arguments", {}),
                    ok=item.get("ok", False),
                    result_summary=item.get("result_summary", ""),
                ))
        return runs


# ── helpers ──────────────────────────────────────────────────────────

def _parse_search_links(raw, label: str, *parts: str) -> list[SearchLink]:
    if isinstance(raw, dict):
        return [SearchLink(label=raw.get("label", label), url=raw.get("url", ""))]
    if isinstance(raw, str) and raw.startswith("dict("):
        # Fallback: generate link from parts
        from urllib.parse import quote_plus
        query = quote_plus(" ".join(parts))
        return [SearchLink(label=label, url=f"https://www.google.com/search?q={query}")]
    # Default
    from urllib.parse import quote_plus
    query = quote_plus(f"{label.lower()} {' '.join(parts)}")
    return [SearchLink(label=label, url=f"https://www.google.com/search?q={query}")]


def _parse_itinerary(raw) -> list[ItineraryDay]:
    if not raw:
        return []
    if isinstance(raw, list):
        result = []
        for item in raw:
            if isinstance(item, dict):
                result.append(ItineraryDay(**item))
            elif isinstance(item, ItineraryDay):
                result.append(item)
        return result
    return []


def _parse_recommendations(raw) -> list[Recommendation]:
    if not raw:
        return []
    if isinstance(raw, list):
        result = []
        for item in raw:
            if isinstance(item, dict):
                result.append(Recommendation(**item))
            elif isinstance(item, Recommendation):
                result.append(item)
        return result
    return []


def _default_budget(request: TripRequest) -> dict:
    return {"currency": "USD", "target": request.budget_usd, "estimated_total": 0, "breakdown": {}}


async def _drain(queue: asyncio.Queue, task: asyncio.Task):
    """Yield events from queue until the task completes."""
    while not task.done():
        try:
            evt = await asyncio.wait_for(queue.get(), timeout=0.1)
            yield evt
        except asyncio.TimeoutError:
            continue
    # Drain remaining
    while not queue.empty():
        yield await queue.get()
    # Re-raise any exception from the task
    task.result()
