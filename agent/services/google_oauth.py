"""Google OAuth and encrypted token storage for the local Electron user."""
from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent.config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_LOCAL_USER_ID,
    GOOGLE_REDIRECT_URI, GOOGLE_SCOPES, TOKEN_ENCRYPTION_KEY,
)
from agent.db.schema import get_db

TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
TOKEN_BUFFER_MS = 5 * 60 * 1000


class GoogleAuthError(RuntimeError):
    pass


def validate_google_config() -> None:
    missing = [name for name, value in (
        ("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID),
        ("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET),
        ("GOOGLE_REDIRECT_URI", GOOGLE_REDIRECT_URI),
        ("TOKEN_ENCRYPTION_KEY", TOKEN_ENCRYPTION_KEY),
    ) if not value]
    if missing:
        raise GoogleAuthError("Missing Google OAuth configuration: " + ", ".join(missing))
    try:
        key = bytes.fromhex(TOKEN_ENCRYPTION_KEY)
    except ValueError as exc:
        raise GoogleAuthError("TOKEN_ENCRYPTION_KEY must be 64 hexadecimal characters") from exc
    if len(key) != 32:
        raise GoogleAuthError("TOKEN_ENCRYPTION_KEY must be 64 hexadecimal characters")


def _key() -> bytes:
    validate_google_config()
    return bytes.fromhex(TOKEN_ENCRYPTION_KEY)


def encrypt_tokens(tokens: dict) -> str:
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(_key()).encrypt(nonce, json.dumps(tokens).encode(), b"google-oauth")
    return f"{nonce.hex()}:{encrypted.hex()}"


def decrypt_tokens(payload: str) -> dict:
    nonce_hex, encrypted_hex = payload.split(":", 1)
    plaintext = AESGCM(_key()).decrypt(
        bytes.fromhex(nonce_hex), bytes.fromhex(encrypted_hex), b"google-oauth"
    )
    return json.loads(plaintext)


async def create_authorization_url(user_id: str = GOOGLE_LOCAL_USER_ID) -> str:
    validate_google_config()
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db = await get_db()
    await db.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now.isoformat(),))
    await db.execute(
        "INSERT INTO oauth_states(state,user_id,redirect_uri,expires_at,created_at) VALUES(?,?,?,?,?)",
        (state, user_id, GOOGLE_REDIRECT_URI, (now + timedelta(minutes=15)).isoformat(), now.isoformat()),
    )
    await db.commit()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })


async def _consume_state(state: str) -> tuple[str, str]:
    db = await get_db()
    cursor = await db.execute("SELECT user_id,redirect_uri,expires_at FROM oauth_states WHERE state=?", (state,))
    row = await cursor.fetchone()
    if row:
        await db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
        await db.commit()
    if not row or datetime.fromisoformat(row[2]) <= datetime.now(timezone.utc):
        raise GoogleAuthError("OAuth state is invalid or expired")
    if row[1] != GOOGLE_REDIRECT_URI:
        raise GoogleAuthError("OAuth redirect URI does not match the stored request")
    return row[0], row[1]


async def complete_authorization(code: str, state: str) -> dict:
    user_id, redirect_uri = await _consume_state(state)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data={
            "code": code, "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        if response.is_error:
            raise GoogleAuthError("Google rejected the authorization code")
        data = response.json()
        profile_response = await client.get(USERINFO_URL, headers={
            "Authorization": f"Bearer {data['access_token']}"
        })
        profile_response.raise_for_status()
        profile = profile_response.json()

    db = await get_db()
    cursor = await db.execute(
        "SELECT encrypted_tokens FROM connections WHERE provider='google' AND user_id=?", (user_id,)
    )
    previous = await cursor.fetchone()
    if not data.get("refresh_token") and previous:
        try:
            data["refresh_token"] = decrypt_tokens(previous[0]).get("refresh_token")
        except Exception:
            pass
    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": int(time.time() * 1000) + int(data.get("expires_in", 3600)) * 1000,
    }
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO connections(id,provider,user_id,encrypted_tokens,scopes,account_email,
               account_name,status,last_health_check,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(provider,user_id) DO UPDATE SET encrypted_tokens=excluded.encrypted_tokens,
               scopes=excluded.scopes,account_email=excluded.account_email,account_name=excluded.account_name,
               status='active',last_health_check=excluded.last_health_check,updated_at=excluded.updated_at""",
        (str(uuid.uuid4()), "google", user_id, encrypt_tokens(tokens), json.dumps(GOOGLE_SCOPES),
         profile.get("email"), profile.get("name"), "active", now, now, now),
    )
    await db.commit()
    return await connection_status(user_id)


async def connection_status(user_id: str = GOOGLE_LOCAL_USER_ID) -> dict:
    db = await get_db()
    cursor = await db.execute(
        """SELECT account_email,account_name,status,last_health_check,updated_at FROM connections
           WHERE provider='google' AND user_id=?""", (user_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return {"provider": "google", "status": "not_connected", "accountEmail": None,
                "accountName": None, "lastHealthCheck": None, "updatedAt": None}
    return {"provider": "google", "accountEmail": row[0], "accountName": row[1],
            "status": row[2], "lastHealthCheck": row[3], "updatedAt": row[4]}


async def _mark_reconnect(user_id: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE connections SET status='needs_reconnect',updated_at=? WHERE provider='google' AND user_id=?",
        (datetime.now(timezone.utc).isoformat(), user_id),
    )
    await db.commit()


async def get_valid_access_token(user_id: str = GOOGLE_LOCAL_USER_ID) -> str:
    validate_google_config()
    db = await get_db()
    cursor = await db.execute(
        "SELECT encrypted_tokens FROM connections WHERE provider='google' AND user_id=? AND status='active'",
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise GoogleAuthError("Google account is not connected")
    try:
        tokens = decrypt_tokens(row[0])
    except Exception as exc:
        await _mark_reconnect(user_id)
        raise GoogleAuthError("Stored Google token cannot be decrypted; reconnect required") from exc
    if tokens.get("access_token") and int(tokens.get("expires_at", 0)) > int(time.time() * 1000) + TOKEN_BUFFER_MS:
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        await _mark_reconnect(user_id)
        raise GoogleAuthError("Google refresh token is missing; reconnect required")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token",
        })
    if response.is_error:
        await _mark_reconnect(user_id)
        raise GoogleAuthError("Google token refresh failed; reconnect required")
    data = response.json()
    tokens["access_token"] = data["access_token"]
    tokens["expires_at"] = int(time.time() * 1000) + int(data.get("expires_in", 3600)) * 1000
    if data.get("refresh_token"):
        tokens["refresh_token"] = data["refresh_token"]
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE connections SET encrypted_tokens=?,last_health_check=?,updated_at=? WHERE provider='google' AND user_id=?",
        (encrypt_tokens(tokens), now, now, user_id),
    )
    await db.commit()
    return tokens["access_token"]


async def disconnect(user_id: str = GOOGLE_LOCAL_USER_ID) -> None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT encrypted_tokens FROM connections WHERE provider='google' AND user_id=?", (user_id,)
    )
    row = await cursor.fetchone()
    if row:
        try:
            token = decrypt_tokens(row[0]).get("refresh_token")
            if token:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(REVOKE_URL, data={"token": token})
        except Exception:
            pass
    await db.execute("DELETE FROM connections WHERE provider='google' AND user_id=?", (user_id,))
    await db.commit()
