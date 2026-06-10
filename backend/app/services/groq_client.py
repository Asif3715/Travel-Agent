"""Async Groq client with function-calling (tool use) support."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """A single tool call requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    """Result of a chat completion."""
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    error_message: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class GroqClient:
    """Async client for the Groq chat completions API."""

    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.groq_api_key)

    async def chat(self, system: str, user: str) -> str | None:
        """Simple text chat — no tools."""
        if not self.enabled:
            return None
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        result = await self._call(messages)
        return result.content

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResult:
        """Chat with optional function-calling tools.

        *messages* follows OpenAI format.  *tools* is a list of tool
        definitions in OpenAI format (type + function schema).
        """
        if not self.enabled:
            return ChatResult(content=None, finish_reason="no_key")
        return await self._call(messages, tools=tools)

    # ── internal ─────────────────────────────────────────────────────
    async def _call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.settings.groq_model,
            "messages": messages,
            "temperature": 0.6,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        max_retries = 5
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
                    resp = await client.post(self.BASE_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                choice = data["choices"][0]
                msg = choice["message"]

                tool_calls: list[ToolCall] = []
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        fn = tc["function"]
                        try:
                            args = json.loads(fn["arguments"])
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        tool_calls.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args))

                return ChatResult(
                    content=msg.get("content"),
                    tool_calls=tool_calls,
                    finish_reason=choice.get("finish_reason", ""),
                )
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:300]
                if exc.response.status_code == 429 and attempt < max_retries - 1:
                    wait_s = _retry_after_seconds(detail, attempt)
                    logger.info("Groq rate limited, retrying in %.1fs (attempt %d)", wait_s, attempt + 1)
                    await asyncio.sleep(wait_s)
                    continue
                logger.warning("Groq HTTP error %s: %s", exc.response.status_code, detail)
                return ChatResult(content=None, finish_reason="error", error_message=detail)
            except Exception as exc:
                logger.warning("Groq call failed: %s", exc)
                return ChatResult(content=None, finish_reason="error", error_message=str(exc))

        return ChatResult(content=None, finish_reason="error", error_message="Groq retries exhausted")


def _retry_after_seconds(detail: str, attempt: int) -> float:
    match = re.search(r"try again in ([\d.]+)s", detail)
    if match:
        return max(float(match.group(1)), 0.5)
    match = re.search(r"try again in (\d+)ms", detail)
    if match:
        return max(float(match.group(1)) / 1000.0, 0.5)
    return 2.0 * (attempt + 1)
