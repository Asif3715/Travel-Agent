"""Base agent with LLM function-calling (ReAct) loop."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..config import Settings
from ..memory import SharedMemory
from ..services.groq_client import GroqClient
from ..tools.registry import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)


class BaseAgent:
    """Abstract base for all sub-agents.

    Subclasses set *name*, *purpose*, *system_prompt*, and *allowed_tools*.
    The ``run`` method implements a ReAct-style loop:
      1. Send context + tools to the LLM
      2. If the LLM returns tool_calls → execute them, feed results back
      3. Repeat until the LLM returns a text response (or max iterations)
    When no API key is configured the agent falls back to ``_fallback_run``.
    """

    name: str = "base"
    purpose: str = ""
    system_prompt: str = "You are a helpful travel planning assistant."
    allowed_tools: list[str] = []
    max_iterations: int = 6

    def __init__(self, settings: Settings, tools: ToolRegistry) -> None:
        self.settings = settings
        self.tools = tools
        self.groq = GroqClient(settings)

    async def run(
        self,
        user_prompt: str,
        memory: SharedMemory,
        queue: asyncio.Queue | None = None,
    ) -> str:
        """Execute the agent. Returns the LLM's final text answer."""
        await self._emit(queue, "agent_start", {"agent": self.name, "purpose": self.purpose})

        ctx = self.tools.create_context(self.name, self.allowed_tools)
        tool_schemas = self.tools.get_schemas(self.allowed_tools)
        used_llm = False
        llm_error: str | None = None

        if not self.groq.enabled:
            llm_error = "GROQ_API_KEY not configured"
            result = await self._fallback_run(ctx, memory)
            await self._finalize_agent(memory, queue, ctx, result, used_llm=False, llm_error=llm_error)
            return result

        messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt(memory)},
            {"role": "user", "content": user_prompt},
        ]

        final_text = ""
        for _iteration in range(self.max_iterations):
            chat = await self.groq.chat_with_tools(messages, tool_schemas or None)

            if chat.finish_reason in ("error", "no_key") and not chat.has_tool_calls:
                llm_error = chat.error_message or f"LLM unavailable (reason={chat.finish_reason})"
                logger.warning("%s: %s — using tool fallback.", self.name, llm_error)
                await self._emit(queue, "agent_warning", {
                    "agent": self.name,
                    "message": llm_error,
                })
                result = await self._fallback_run(ctx, memory)
                await self._finalize_agent(memory, queue, ctx, result, used_llm=False, llm_error=llm_error)
                return result

            used_llm = True

            if chat.has_tool_calls:
                assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": []}
                for tc in chat.tool_calls:
                    assistant_msg["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    })
                if chat.content:
                    assistant_msg["content"] = chat.content
                messages.append(assistant_msg)

                for tc in chat.tool_calls:
                    await self._emit(queue, "tool_call", {"agent": self.name, "tool": tc.name, "arguments": tc.arguments})
                    try:
                        result_json = await self.tools.run_from_tool_call(ctx, tc.name, tc.arguments)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_json})
                        await self._emit(queue, "tool_result", {"agent": self.name, "tool": tc.name, "ok": True, "summary": result_json[:200]})
                    except Exception as exc:
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": str(exc)})})
                        await self._emit(queue, "tool_result", {"agent": self.name, "tool": tc.name, "ok": False, "summary": str(exc)[:200]})
            else:
                final_text = chat.content or ""
                break

        await self._ensure_tools(ctx, memory)
        self._store_results(memory, final_text, ctx)
        await self._finalize_agent(memory, queue, ctx, final_text, used_llm=used_llm, llm_error=llm_error)
        return final_text

    # ── overrideable hooks ───────────────────────────────────────────

    def _build_system_prompt(self, memory: SharedMemory) -> str:
        base = self.system_prompt
        ctx = memory.context_summary()
        if ctx:
            base += f"\n\n## Context from other agents\n{ctx}"
        return base

    def _store_results(self, memory: SharedMemory, text: str, ctx: ToolContext) -> None:
        """Store agent outputs into shared memory. Override in subclasses."""
        memory.store(f"{self.name}_summary", text, agent=self.name)

    async def _ensure_tools(self, ctx: ToolContext, memory: SharedMemory) -> None:
        """Run any missing required tools after the LLM loop. Override in subclasses."""
        return None

    async def _fallback_run(self, ctx: ToolContext, memory: SharedMemory) -> str:
        """Fallback when no LLM is available. Override in subclasses."""
        return f"{self.name} completed (no LLM)."

    # ── helpers ──────────────────────────────────────────────────────

    async def _finalize_agent(
        self,
        memory: SharedMemory,
        queue: asyncio.Queue | None,
        ctx: ToolContext,
        result: str,
        *,
        used_llm: bool,
        llm_error: str | None,
    ) -> None:
        if not used_llm:
            memory.store("llm_enabled", False, agent=self.name)

        for run in ctx.runs:
            memory.append("all_tool_runs", {
                "agent": run.agent,
                "tool": run.tool,
                "arguments": run.arguments,
                "ok": run.ok,
                "result_summary": run.result_summary,
            }, agent=self.name)

        await self._emit(queue, "agent_done", {
            "agent": self.name,
            "summary": (result or "")[:200],
            "tool_runs": self._serialize_runs(ctx),
            "used_llm": used_llm,
            "llm_error": llm_error,
        })

    async def _emit(self, queue: asyncio.Queue | None, event: str, data: dict) -> None:
        if queue is not None:
            await queue.put({"event": event, "data": data})

    def _serialize_runs(self, ctx: ToolContext) -> list[dict]:
        return [
            {"agent": r.agent, "tool": r.tool, "arguments": r.arguments, "ok": r.ok, "result_summary": r.result_summary}
            for r in ctx.runs
        ]
