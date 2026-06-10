"""Reviewer agent — critiques the plan and surfaces clarification questions."""

from __future__ import annotations

import asyncio
import json
import logging

from ..config import Settings
from ..memory import SharedMemory
from ..services.groq_client import GroqClient
from ..tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ReviewerAgent:
    """Phase 4: self-critique agent.

    After all other agents finish, the reviewer reads shared memory and
    produces structured feedback:
      - **review notes** (warnings, suggestions, info)
      - **clarification questions** the user could answer to improve the plan
    """

    name = "reviewer"
    purpose = "Review the plan for gaps, inconsistencies, and suggest improvements"

    SYSTEM_PROMPT = (
        "You are a critical travel plan reviewer. You receive a trip plan built by "
        "other agents and must evaluate it.\n\n"
        "Respond ONLY with valid JSON in this exact format:\n"
        "```json\n"
        "{\n"
        '  "review": [\n'
        '    {"category": "budget", "note": "...", "severity": "warning"},\n'
        '    {"category": "itinerary", "note": "...", "severity": "suggestion"}\n'
        "  ],\n"
        '  "clarifications": [\n'
        '    "Would you prefer a central or suburban hotel?",\n'
        '    "Do you have dietary restrictions?"\n'
        "  ],\n"
        '  "overall": "A one-sentence overall assessment."\n'
        "}\n"
        "```\n\n"
        "Rules:\n"
        "- severity must be one of: info, warning, suggestion\n"
        "- category must be one of: budget, itinerary, visa, logistics, safety, general\n"
        "- Keep clarifications practical — only ask what would genuinely improve the plan\n"
        "- Limit to 3-5 review notes and 1-3 clarifications\n"
        "- Do NOT invent facts; base your review on what the agents produced"
    )

    def __init__(self, settings: Settings, tools: ToolRegistry) -> None:
        self.settings = settings
        self.groq = GroqClient(settings)

    async def run(
        self,
        memory: SharedMemory,
        queue: asyncio.Queue | None = None,
    ) -> dict:
        """Review the plan in shared memory. Returns {review, clarifications, overall}."""
        if queue:
            await queue.put({"event": "agent_start", "data": {"agent": self.name, "purpose": self.purpose}})

        if not self.groq.enabled:
            result = self._fallback_review(memory)
        else:
            context = memory.context_summary(max_chars=3000)
            request = memory.get("request", {})
            user_prompt = (
                f"Review this trip plan:\n\n"
                f"Trip: {request.get('origin', '?')} → {request.get('destination', '?')}, "
                f"{request.get('start_date', '?')} to {request.get('end_date', '?')}, "
                f"{request.get('travelers', 1)} travelers, ${request.get('budget_usd', '?')} budget\n\n"
                f"Agent outputs:\n{context}"
            )

            text = await self.groq.chat(self.SYSTEM_PROMPT, user_prompt)
            result = self._parse_review(text)

        memory.store("review", result.get("review", []), agent=self.name)
        memory.store("clarifications", result.get("clarifications", []), agent=self.name)
        memory.store("review_overall", result.get("overall", ""), agent=self.name)

        if queue:
            await queue.put({"event": "agent_done", "data": {
                "agent": self.name,
                "summary": result.get("overall", "Review complete."),
                "tool_runs": [],
            }})

        return result

    def _parse_review(self, text: str | None) -> dict:
        if not text:
            return self._empty_review()
        # Try to extract JSON from the response
        try:
            # Handle markdown code blocks
            clean = text.strip()
            if "```json" in clean:
                clean = clean.split("```json", 1)[1]
                clean = clean.split("```", 1)[0]
            elif "```" in clean:
                clean = clean.split("```", 1)[1]
                clean = clean.split("```", 1)[0]
            data = json.loads(clean.strip())
            return {
                "review": data.get("review", []),
                "clarifications": data.get("clarifications", []),
                "overall": data.get("overall", "Review complete."),
            }
        except (json.JSONDecodeError, IndexError):
            logger.warning("Reviewer returned non-JSON: %s", text[:200])
            return {"review": [], "clarifications": [], "overall": text[:200]}

    def _fallback_review(self, memory: SharedMemory) -> dict:
        notes = []
        request = memory.get("request", {})
        budget = request.get("budget_usd", 0)
        nights = memory.get("trip_nights", 1)
        travelers = request.get("travelers", 1)
        if budget and nights and travelers:
            daily = budget / (nights * travelers)
            if daily < 50:
                notes.append({"category": "budget", "note": f"${daily:.0f}/person/day is very tight for international travel.", "severity": "warning"})
        notes.append({"category": "general", "note": "Review generated without LLM — configure GROQ_API_KEY for detailed analysis.", "severity": "info"})
        return {"review": notes, "clarifications": [], "overall": "Basic review completed (no LLM)."}

    def _empty_review(self) -> dict:
        return {"review": [], "clarifications": [], "overall": "No review generated."}
