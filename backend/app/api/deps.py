"""What every route shares: the error shape, the signed-in user, a database connection, the
audit log, and case ownership."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request

from .. import config, db


class ApiError(Exception):
    """Rendered as {"error": {"code", "message"}} with this status."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn=Depends(get_conn)) -> dict:
    """No anonymous endpoint: every route but login depends on this."""
    uid = request.session.get("uid")
    user = db.one(conn, "SELECT id, email, role FROM users WHERE id = ?", (uid,)) if uid else None
    if not user:
        raise ApiError(401, "not_signed_in", "Sign in to continue.")
    return user


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def audit(conn, request: Request, user: dict | None, case_id: str | None, action: str, detail: str | None = None) -> None:
    db.audit(conn, user["id"] if user else None, case_id, action, detail, client_ip(request))


def get_case(conn, user: dict, case_id: str) -> dict:
    """The case, if it exists and is the user's (admins see all). Someone else's case is
    reported as missing, not as forbidden."""
    case = db.one(conn, "SELECT * FROM cases WHERE id = ?", (case_id,))
    if not case or (user["role"] != "admin" and case["created_by"] != user["id"]):
        raise ApiError(404, "case_not_found", "No such case.")
    return case


def rate_limit(conn, user: dict, action: str, what: str) -> None:
    """Per user, per hour, counted from the audit log so a restart does not reset it."""
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE user_id = ? AND action = ? AND ts > ?", (user["id"], action, since)).fetchone()[0]
    if n >= config.rate_per_hour(what):
        raise ApiError(429, "rate_limited", f"Too many {what} in the last hour. Try again later.")
