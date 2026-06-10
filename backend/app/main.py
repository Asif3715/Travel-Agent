"""FastAPI application with SSE streaming, conversations, and trip persistence."""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import get_settings
from .database import Database
from .schemas import (
    ConversationCreate,
    ConversationOut,
    MessageCreate,
    TripPlan,
    TripRequest,
)
from .services.planner import plan_trip, stream_plan

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Travel Agent API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database(settings.db_path)


# ── Health ───────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.2.0"}


# ── Trip planning ────────────────────────────────────────────────────

@app.post("/trip/plan", response_model=TripPlan)
async def plan_trip_endpoint(request: TripRequest) -> TripPlan:
    """Non-streaming trip planning endpoint."""
    try:
        plan = await plan_trip(request)
        # Auto-save trip
        plan_dict = plan.model_dump()
        plan_dict["origin"] = request.origin
        plan_dict["destination"] = request.destination
        plan_dict["start_date"] = request.start_date
        plan_dict["end_date"] = request.end_date
        await db.save_trip(plan_dict, conversation_id=request.conversation_id)
        return plan
    except Exception as exc:
        logger.exception("Trip planning failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/trip/plan/stream")
async def plan_trip_stream(request: TripRequest):
    """SSE streaming endpoint — sends agent events in real time."""
    async def event_generator():
        try:
            async for event in stream_plan(request):
                event_type = event.get("event", "message")
                data = event.get("data", event)
                yield f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"

                # Auto-save when plan is ready
                if event_type == "plan_ready":
                    plan_dict = data.copy()
                    plan_dict["origin"] = request.origin
                    plan_dict["destination"] = request.destination
                    plan_dict["start_date"] = request.start_date
                    plan_dict["end_date"] = request.end_date
                    await db.save_trip(plan_dict, conversation_id=request.conversation_id)

        except Exception as exc:
            logger.exception("Streaming failed")
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── Conversations ────────────────────────────────────────────────────

@app.post("/conversations")
async def create_conversation(body: ConversationCreate):
    return await db.create_conversation(body.title)


@app.get("/conversations")
async def list_conversations():
    return await db.list_conversations()


@app.get("/conversations/{cid}")
async def get_conversation(cid: str):
    conv = await db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@app.delete("/conversations/{cid}")
async def delete_conversation(cid: str):
    ok = await db.delete_conversation(cid)
    if not ok:
        raise HTTPException(404, "Conversation not found")
    return {"deleted": True}


@app.post("/conversations/{cid}/message")
async def add_message(cid: str, body: MessageCreate):
    """Add a user message and optionally trigger planning."""
    conv = await db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    # Save user message
    user_msg = await db.add_message(cid, "user", body.content)

    if body.trip_request:
        # Plan and save assistant response
        body.trip_request.conversation_id = cid
        plan = await plan_trip(body.trip_request)
        plan_json = json.dumps(plan.model_dump(), default=str)
        assistant_msg = await db.add_message(cid, "assistant", plan.summary, plan_json=plan_json)
        return {"user_message": user_msg, "assistant_message": assistant_msg}

    return {"user_message": user_msg}


@app.post("/conversations/{cid}/plan/stream")
async def stream_conversation_plan(cid: str, request: TripRequest):
    """Stream a trip plan within a conversation context."""
    conv = await db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    request.conversation_id = cid
    await db.add_message(cid, "user", f"Plan trip: {request.origin} → {request.destination}")

    async def event_generator():
        final_plan = None
        try:
            async for event in stream_plan(request):
                event_type = event.get("event", "message")
                data = event.get("data", event)
                yield f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
                if event_type == "plan_ready":
                    final_plan = data
        except Exception as exc:
            logger.exception("Streaming failed")
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

        if final_plan:
            plan_json = json.dumps(final_plan, default=str)
            await db.add_message(cid, "assistant", final_plan.get("summary", ""), plan_json=plan_json)
            save_dict = final_plan.copy()
            save_dict["origin"] = request.origin
            save_dict["destination"] = request.destination
            await db.save_trip(save_dict, conversation_id=cid)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── Trips ────────────────────────────────────────────────────────────

@app.get("/trips")
async def list_trips():
    return await db.list_trips()


@app.get("/trips/{tid}")
async def get_trip(tid: str):
    trip = await db.get_trip(tid)
    if not trip:
        raise HTTPException(404, "Trip not found")
    return trip
