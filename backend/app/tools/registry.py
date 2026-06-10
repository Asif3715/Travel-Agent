"""Async tool registry with permission enforcement and run logging."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from ..config import Settings
from .catalog import (
    TOOL_SCHEMAS,
    tool_build_itinerary,
    tool_destination_overview,
    tool_estimate_budget,
    tool_local_recommendations,
    tool_search_flights,
    tool_search_hotels,
    tool_visa_notes,
)

AsyncToolFn = Callable[..., Coroutine[Any, Any, Any]]

TOOLS_NEEDING_HTTP_DEFAULTS = {
    "destination_overview",
    "build_itinerary",
    "local_recommendations",
    "visa_notes",
}


@dataclass
class ToolRunRecord:
    agent: str
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result_summary: str
    result: Any = None


@dataclass
class ToolContext:
    agent: str
    allowed_tools: set[str]
    settings: Settings
    runs: list[ToolRunRecord] = field(default_factory=list)


def get_tool_result(ctx: ToolContext, tool_name: str) -> Any | None:
    """Return the most recent successful result for a tool in this context."""
    for run in reversed(ctx.runs):
        if run.tool == tool_name and run.ok:
            return run.result
    return None


class ToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tools: dict[str, AsyncToolFn] = {
            "destination_overview": tool_destination_overview,
            "search_flights": tool_search_flights,
            "search_hotels": tool_search_hotels,
            "build_itinerary": tool_build_itinerary,
            "estimate_budget": tool_estimate_budget,
            "visa_notes": tool_visa_notes,
            "local_recommendations": tool_local_recommendations,
        }

    def create_context(self, agent: str, allowed_tools: list[str]) -> ToolContext:
        return ToolContext(agent=agent, allowed_tools=set(allowed_tools), settings=self.settings)

    def get_schemas(self, tool_names: list[str]) -> list[dict]:
        """Return JSON schemas for the requested tools (for LLM function calling)."""
        return [TOOL_SCHEMAS[name] for name in tool_names if name in TOOL_SCHEMAS]

    async def run(self, context: ToolContext, tool_name: str, **kwargs: Any) -> Any:
        if tool_name not in context.allowed_tools:
            raise PermissionError(f"Agent '{context.agent}' cannot use tool '{tool_name}'")
        if tool_name not in self._tools:
            raise KeyError(f"Unknown tool '{tool_name}'")

        if tool_name in TOOLS_NEEDING_HTTP_DEFAULTS:
            kwargs.setdefault("timeout_s", self.settings.request_timeout_s)
            kwargs.setdefault("user_agent", self.settings.nominatim_user_agent)

        try:
            result = await self._tools[tool_name](**kwargs)
            context.runs.append(ToolRunRecord(
                agent=context.agent, tool=tool_name, arguments=kwargs,
                ok=True, result_summary=_summarize(result), result=result,
            ))
            return result
        except Exception as exc:
            context.runs.append(ToolRunRecord(
                agent=context.agent, tool=tool_name, arguments=kwargs,
                ok=False, result_summary=str(exc), result=None,
            ))
            raise

    async def run_from_tool_call(self, context: ToolContext, tool_name: str, arguments: dict) -> str:
        """Execute a tool from an LLM tool_call and return JSON string for the message."""
        result = await self.run(context, tool_name, **arguments)
        return json.dumps(result, default=str)


def _summarize(result: Any) -> str:
    if isinstance(result, dict):
        keys = ", ".join(list(result.keys())[:4])
        return f"dict({keys})"
    if isinstance(result, list):
        return f"list[{len(result)}]"
    return str(result)[:120]
