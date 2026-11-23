"""The event stream: server-sent events tailed from the job_events table.

`id:` is the row id, so the browser's Last-Event-ID resumes after a reconnect, and because
nothing is held in memory a restart of the api or the worker loses nothing."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .. import db
from .deps import current_user, get_case, get_conn

router = APIRouter(prefix="/api")
POLL_S = 0.3
HEARTBEAT_S = 15.0


@router.get("/cases/{case_id}/stream")
async def stream(case_id: str, request: Request, after: int | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    get_case(conn, user, case_id)
    last = request.headers.get("last-event-id")
    start = int(last) if last and last.isdigit() else (after or 0)

    async def gen():
        c = db.connect()
        last_id, idle = start, 0.0
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                rows = c.execute("SELECT id, type, payload FROM job_events WHERE case_id = ? AND id > ? ORDER BY id LIMIT 200",
                                 (case_id, last_id)).fetchall()
                for r in rows:
                    last_id = r["id"]
                    yield f"id: {r['id']}\nevent: {r['type']}\ndata: {r['payload']}\n\n"
                if rows:
                    idle = 0.0
                    continue
                await asyncio.sleep(POLL_S)
                idle += POLL_S
                if idle >= HEARTBEAT_S:
                    idle = 0.0
                    yield ": keep-alive\n\n"
        finally:
            c.close()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
