"""Authentication.

* Supabase Auth (email/password + Google OAuth) when SUPABASE_URL/ANON_KEY are set.
* Local email/password with signed JWTs otherwise, so the app is runnable offline.
"""
import functools
import time
from typing import Optional

import jwt
import requests
from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from . import config, db

TOKEN_TTL = 60 * 60 * 24 * 7  # 7 days


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------------ local JWT
def issue_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "name": user.get("full_name") or "",
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_TTL,
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")


def _decode_local(token: str) -> dict:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expired, please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid session token.") from exc


# --------------------------------------------------------------- Supabase Auth
def _supabase_auth(path: str, payload: dict) -> dict:
    url = f"{config.SUPABASE_URL}/auth/v1/{path}"
    resp = requests.post(
        url,
        headers={"apikey": config.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        raise AuthError(data.get("msg") or data.get("error_description")
                        or data.get("message") or "Authentication failed",
                        status=resp.status_code)
    return data


def _supabase_user(token: str) -> dict:
    resp = requests.get(
        f"{config.SUPABASE_URL}/auth/v1/user",
        headers={"apikey": config.SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise AuthError("Invalid Supabase session.")
    return resp.json()


# ------------------------------------------------------------------- public API
def signup(email: str, password: str, full_name: str = "") -> dict:
    email = (email or "").strip().lower()
    if "@" not in email or len(password or "") < 8:
        raise AuthError("Enter a valid email and a password of at least 8 characters.", 400)

    if config.USE_SUPABASE:
        data = _supabase_auth("signup", {
            "email": email, "password": password,
            "data": {"full_name": full_name},
        })
        user = data.get("user") or {}
        token = (data.get("access_token") or "")
        if not token:  # email confirmation required
            raise AuthError("Check your inbox to confirm your email, then sign in.", 202)
        db.upsert_external_user(user.get("id", ""), email, full_name)
        return {"token": token, "user": {"id": user.get("id"), "email": email,
                                         "name": full_name}}

    if db.get_user_by_email(email):
        raise AuthError("That email is already registered.", 409)
    user = db.create_user(email, generate_password_hash(password), full_name)
    return {"token": issue_token(user),
            "user": {"id": user["id"], "email": email, "name": full_name}}


def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    if config.USE_SUPABASE:
        data = _supabase_auth("token?grant_type=password",
                              {"email": email, "password": password})
        user = data.get("user") or {}
        meta = user.get("user_metadata") or {}
        db.upsert_external_user(user.get("id", ""), email, meta.get("full_name", ""))
        return {"token": data["access_token"],
                "user": {"id": user.get("id"), "email": email,
                         "name": meta.get("full_name", "")}}

    user = db.get_user_by_email(email)
    if not user or not user.get("password_hash") \
            or not check_password_hash(user["password_hash"], password or ""):
        raise AuthError("Incorrect email or password.")
    return {"token": issue_token(user),
            "user": {"id": user["id"], "email": user["email"],
                     "name": user.get("full_name") or ""}}


def user_from_token(token: str) -> dict:
    if not token:
        raise AuthError("Missing authentication token.")
    if config.USE_SUPABASE:
        u = _supabase_user(token)
        meta = u.get("user_metadata") or {}
        name = meta.get("full_name") or meta.get("name") or ""
        db.upsert_external_user(u["id"], u.get("email", ""), name)
        return {"id": u["id"], "email": u.get("email", ""), "name": name}
    claims = _decode_local(token)
    return {"id": claims["sub"], "email": claims.get("email", ""),
            "name": claims.get("name", "")}


def bearer_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            g.user = user_from_token(bearer_token() or "")
        except AuthError as exc:
            return jsonify({"error": exc.message}), exc.status
        return fn(*args, **kwargs)
    return wrapper
