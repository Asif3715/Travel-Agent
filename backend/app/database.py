"""SQLite persistence for conversations and trips."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite

_CREATE = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    plan_json       TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trips (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT,
    origin          TEXT,
    destination     TEXT,
    start_date      TEXT,
    end_date        TEXT,
    plan_json       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_CREATE)
            await db.commit()
        self._ready = True

    # ── conversations ────────────────────────────────────────────────
    async def create_conversation(self, title: str = "") -> dict:
        await self._ensure()
        cid = uuid.uuid4().hex[:12]
        now = _now()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
                (cid, title, now, now),
            )
            await db.commit()
        return {"id": cid, "title": title, "created_at": now, "updated_at": now, "messages": []}

    async def list_conversations(self) -> list[dict]:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            )
            return [dict(r) for r in rows]

    async def get_conversation(self, cid: str) -> dict | None:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchall("SELECT * FROM conversations WHERE id=?", (cid,))
            if not row:
                return None
            conv = dict(row[0])
            msgs = await db.execute_fetchall(
                "SELECT id, role, content, plan_json, created_at FROM messages WHERE conversation_id=? ORDER BY created_at",
                (cid,),
            )
            conv["messages"] = [_msg_row(m) for m in msgs]
            return conv

    async def delete_conversation(self, cid: str) -> bool:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM conversations WHERE id=?", (cid,))
            await db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            await db.commit()
            return cur.rowcount > 0

    # ── messages ─────────────────────────────────────────────────────
    async def add_message(self, conversation_id: str, role: str, content: str, plan_json: str | None = None) -> dict:
        await self._ensure()
        mid = uuid.uuid4().hex[:12]
        now = _now()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, plan_json, created_at) VALUES (?,?,?,?,?,?)",
                (mid, conversation_id, role, content, plan_json, now),
            )
            await db.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
            )
            await db.commit()
        return {"id": mid, "role": role, "content": content, "plan_json": json.loads(plan_json) if plan_json else None, "created_at": now}

    async def get_messages(self, conversation_id: str) -> list[dict]:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT id, role, content, plan_json, created_at FROM messages WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            )
            return [_msg_row(r) for r in rows]

    # ── trips ────────────────────────────────────────────────────────
    async def save_trip(self, plan_dict: dict, conversation_id: str | None = None) -> dict:
        await self._ensure()
        tid = uuid.uuid4().hex[:12]
        now = _now()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO trips (id, conversation_id, origin, destination, start_date, end_date, plan_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (tid, conversation_id, plan_dict.get("origin"), plan_dict.get("destination"),
                 plan_dict.get("start_date"), plan_dict.get("end_date"),
                 json.dumps(plan_dict), now),
            )
            await db.commit()
        return {"id": tid, "created_at": now}

    async def list_trips(self) -> list[dict]:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT id, origin, destination, start_date, end_date, created_at FROM trips ORDER BY created_at DESC")
            return [dict(r) for r in rows]

    async def get_trip(self, tid: str) -> dict | None:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT * FROM trips WHERE id=?", (tid,))
            if not rows:
                return None
            row = dict(rows[0])
            row["plan"] = json.loads(row.pop("plan_json", "{}"))
            return row


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg_row(row) -> dict:
    d = dict(row)
    pj = d.get("plan_json")
    d["plan"] = json.loads(pj) if pj else None
    d.pop("plan_json", None)
    return d
