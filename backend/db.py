"""Storage layer.

Uses Supabase (PostgREST) when SUPABASE_URL + service key are configured,
otherwise falls back to a local SQLite file so the app always runs.
"""
import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

import requests

from . import config

_lock = threading.Lock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    full_name TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS biographies (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    subtitle TEXT,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    stage TEXT,
    transcript TEXT,
    payload TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bio_user ON biographies(user_id);
"""


def _conn() -> sqlite3.Connection:
    if getattr(_local, "conn", None) is None:
        conn = sqlite3.connect(config.SQLITE_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _local.conn = conn
    return _local.conn


def init() -> None:
    _conn()


# --------------------------------------------------------------- Supabase REST
def _sb_headers() -> dict:
    key = config.SUPABASE_SERVICE_KEY or config.SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _sb(method: str, table: str, **kw) -> Any:
    url = f"{config.SUPABASE_URL}/rest/v1/{table}"
    resp = requests.request(method, url, headers=_sb_headers(), timeout=20, **kw)
    resp.raise_for_status()
    return resp.json() if resp.content else None


# --------------------------------------------------------------- Users (local auth)
def create_user(email: str, password_hash: Optional[str], full_name: str = "") -> dict:
    user = {
        "id": str(uuid.uuid4()),
        "email": email.lower().strip(),
        "password_hash": password_hash,
        "full_name": full_name,
        "created_at": time.time(),
    }
    with _lock:
        _conn().execute(
            "INSERT INTO users (id, email, password_hash, full_name, created_at)"
            " VALUES (:id, :email, :password_hash, :full_name, :created_at)",
            user,
        )
        _conn().commit()
    return user


def get_user_by_email(email: str) -> Optional[dict]:
    row = _conn().execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    return dict(row) if row else None


def get_user(user_id: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def upsert_external_user(user_id: str, email: str, full_name: str = "") -> dict:
    """Mirror a Supabase Auth user into local storage for joins."""
    existing = get_user(user_id)
    if existing:
        return existing
    with _lock:
        _conn().execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, full_name, created_at)"
            " VALUES (?, ?, NULL, ?, ?)",
            (user_id, (email or "").lower(), full_name, time.time()),
        )
        _conn().commit()
    return get_user(user_id) or {"id": user_id, "email": email, "full_name": full_name}


# --------------------------------------------------------------- Biographies
def create_biography(user_id: str, transcript: str, title: str = "Untitled Life") -> dict:
    now = time.time()
    bio = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": title,
        "subtitle": "",
        "status": "queued",
        "progress": 0.0,
        "stage": "Queued",
        "transcript": transcript,
        "payload": json.dumps({"chapters": []}),
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        _conn().execute(
            "INSERT INTO biographies (id, user_id, title, subtitle, status, progress, stage,"
            " transcript, payload, error, created_at, updated_at) VALUES (:id, :user_id, :title,"
            " :subtitle, :status, :progress, :stage, :transcript, :payload, :error, :created_at,"
            " :updated_at)",
            bio,
        )
        _conn().commit()
    if _sb_enabled():
        try:
            _sb("POST", "biographies", json={
                "id": bio["id"], "user_id": user_id, "title": title,
                "status": "queued", "transcript": transcript[:100000],
            })
        except Exception:
            pass  # Supabase mirroring is best-effort; SQLite is the source of truth.
    return bio


def update_biography(bio_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    if "payload" in fields and not isinstance(fields["payload"], str):
        fields["payload"] = json.dumps(fields["payload"])
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        _conn().execute(
            f"UPDATE biographies SET {sets} WHERE id = ?", (*fields.values(), bio_id)
        )
        _conn().commit()
    if _sb_enabled():
        try:
            mirror = {k: v for k, v in fields.items()
                      if k in ("title", "status", "progress", "stage")}
            if mirror:
                _sb("PATCH", "biographies", params={"id": f"eq.{bio_id}"}, json=mirror)
        except Exception:
            pass


def get_biography(bio_id: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM biographies WHERE id = ?", (bio_id,)).fetchone()
    if not row:
        return None
    bio = dict(row)
    try:
        bio["payload"] = json.loads(bio["payload"] or "{}")
    except json.JSONDecodeError:
        bio["payload"] = {}
    return bio


def list_biographies(user_id: str) -> list:
    rows = _conn().execute(
        "SELECT id, title, subtitle, status, progress, stage, created_at, updated_at"
        " FROM biographies WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_biography(bio_id: str, user_id: str) -> bool:
    with _lock:
        cur = _conn().execute(
            "DELETE FROM biographies WHERE id = ? AND user_id = ?", (bio_id, user_id)
        )
        _conn().commit()
    return cur.rowcount > 0
