"""Sign-in. Accounts only; passwords hashed with argon2; a signed, HTTP-only session cookie."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import config, db
from .deps import ApiError, audit, client_ip, current_user, get_conn

router = APIRouter(prefix="/api/auth")
_hasher = PasswordHasher()
# verified against when the email is unknown, so both failures take the same time
_DUMMY = _hasher.hash("not a real password")


class Login(BaseModel):
    email: str
    password: str


def create_user(conn, email: str, password: str, role: str = "analyst") -> int:
    with conn:
        cur = conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                           (email.strip().lower(), _hasher.hash(password), role, db.now()))
    return cur.lastrowid


def ensure_admin(conn) -> None:
    """The first user, from ADMIN_EMAIL and ADMIN_PASSWORD, created at startup if missing."""
    email, password = config.admin_login()
    if email and password and not db.one(conn, "SELECT id FROM users WHERE email = ?", (email.strip().lower(),)):
        create_user(conn, email, password, role="admin")


MIN_PASSWORD = 10


class WeakPassword(ValueError):
    pass


def strong_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise WeakPassword(f"A password needs at least {MIN_PASSWORD} characters.")
    return password


def check_password(conn, email: str, password: str) -> dict | None:
    """The user, when the email and password match. Both failures take the same time."""
    user = db.one(conn, "SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    try:
        ok = _hasher.verify(user["password_hash"] if user else _DUMMY, password) and user is not None
    except (Argon2Error, InvalidHashError):
        ok = False
    return user if ok else None


def set_password(conn, email: str, password: str) -> bool:
    """False when there is no such user. Sessions already open stay open until they expire."""
    with conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (_hasher.hash(strong_password(password)), email.strip().lower()))
    return cur.rowcount == 1


def too_many_failures(conn, ip: str | None) -> bool:
    """Counted from the audit log, so a restart does not reset it."""
    if not ip:
        return False
    since = (datetime.now(timezone.utc) - timedelta(seconds=config.login_failures_window_s())).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'login.failed' AND ip = ? AND ts > ?", (ip, since)).fetchone()[0]
    return n >= config.login_failures_max()


@router.post("/login")
def login(body: Login, request: Request, conn=Depends(get_conn)):
    ip = client_ip(request)
    if too_many_failures(conn, ip):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-ins from this address. Wait a few minutes and try again.")
    user = check_password(conn, body.email, body.password)
    if not user:
        db.audit(conn, None, None, "login.failed", body.email.strip().lower()[:120], ip)
        raise ApiError(401, "bad_credentials", "The email or password is wrong.")
    request.session.clear()
    request.session["uid"] = user["id"]
    audit(conn, request, user, None, "login")
    return {"user": {"id": user["id"], "email": user["email"], "role": user["role"]}}


@router.post("/logout")
def logout(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    request.session.clear()
    audit(conn, request, user, None, "logout")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": user}
