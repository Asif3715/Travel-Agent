"""Planner service — thin wrapper over the orchestrator."""

from __future__ import annotations

from typing import AsyncGenerator

from ..agents.orchestrator import TripOrchestrator
from ..schemas import TripPlan, TripRequest

_orchestrator: TripOrchestrator | None = None


def _get_orchestrator() -> TripOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TripOrchestrator()
    return _orchestrator


async def plan_trip(request: TripRequest) -> TripPlan:
    return await _get_orchestrator().run(request)


async def stream_plan(request: TripRequest) -> AsyncGenerator[dict, None]:
    async for event in _get_orchestrator().stream(request):
        yield event
