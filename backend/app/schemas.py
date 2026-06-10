"""Pydantic schemas for API requests, responses and streaming events."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request ──────────────────────────────────────────────────────────

class TripRequest(BaseModel):
    origin: str = Field(..., examples=["New York"])
    destination: str = Field(..., examples=["Paris"])
    start_date: str = Field(..., examples=["2026-07-10"])
    end_date: str = Field(..., examples=["2026-07-18"])
    travelers: int = Field(1, ge=1, le=20)
    budget_usd: int = Field(1500, ge=0)
    interests: list[str] = Field(default_factory=list)
    conversation_id: str | None = Field(None, description="Attach to an existing conversation")


# ── Plan sub-models ──────────────────────────────────────────────────

class SearchLink(BaseModel):
    label: str
    url: str


class ItineraryDay(BaseModel):
    day: int
    title: str
    items: list[str]


class Recommendation(BaseModel):
    name: str
    type: str
    reason: str


class AgentRun(BaseModel):
    name: str
    purpose: str
    summary: str
    status: str = "ok"


class ToolRun(BaseModel):
    agent: str
    tool: str
    arguments: dict
    ok: bool
    result_summary: str


class ReviewNote(BaseModel):
    category: str
    note: str
    severity: str = "info"  # info | warning | suggestion


class TripPlan(BaseModel):
    summary: str
    agents: list[AgentRun]
    tool_runs: list[ToolRun]
    flights: list[SearchLink]
    hotels: list[SearchLink]
    itinerary: list[ItineraryDay]
    budget: dict
    visa: list[str]
    recommendations: list[Recommendation]
    review: list[ReviewNote] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)
    destination_info: dict = Field(default_factory=dict)
    llm_enabled: bool = True


# ── SSE streaming events ────────────────────────────────────────────

class StreamEvent(BaseModel):
    """One SSE event sent during planning."""
    event: str
    data: dict

    def to_sse(self) -> str:
        import json
        return f"event: {self.event}\ndata: {json.dumps(self.data)}\n\n"


# ── Conversation ─────────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    title: str = ""


class MessageCreate(BaseModel):
    content: str
    trip_request: TripRequest | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    plan: dict | None = None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[MessageOut] = Field(default_factory=list)
