import time

import pytest

from agent.services import google_oauth


def configure(monkeypatch):
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", "client")
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(google_oauth, "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8100/api/oauth/google/callback")
    monkeypatch.setattr(google_oauth, "TOKEN_ENCRYPTION_KEY", "ab" * 32)


def test_token_encryption_round_trip(monkeypatch):
    configure(monkeypatch)
    tokens = {"access_token": "access", "refresh_token": "refresh", "expires_at": 123}
    encrypted = google_oauth.encrypt_tokens(tokens)
    assert "access" not in encrypted
    assert google_oauth.decrypt_tokens(encrypted) == tokens


def test_config_rejects_invalid_key(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(google_oauth, "TOKEN_ENCRYPTION_KEY", "short")
    with pytest.raises(google_oauth.GoogleAuthError, match="64 hexadecimal"):
        google_oauth.validate_google_config()


@pytest.mark.asyncio
async def test_oauth_state_is_one_time(test_db, monkeypatch):
    configure(monkeypatch)
    url = await google_oauth.create_authorization_url()
    state = url.split("state=", 1)[1].split("&", 1)[0]
    user_id, redirect_uri = await google_oauth._consume_state(state)
    assert user_id == "local"
    assert redirect_uri == google_oauth.GOOGLE_REDIRECT_URI
    with pytest.raises(google_oauth.GoogleAuthError, match="invalid or expired"):
        await google_oauth._consume_state(state)


@pytest.mark.asyncio
async def test_valid_unexpired_token_does_not_refresh(test_db, monkeypatch):
    configure(monkeypatch)
    from agent.db.schema import get_db
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    encrypted = google_oauth.encrypt_tokens({
        "access_token": "still-valid", "refresh_token": "refresh",
        "expires_at": int(time.time() * 1000) + 600_000,
    })
    db = await get_db()
    await db.execute(
        """INSERT INTO connections(id,provider,user_id,encrypted_tokens,scopes,status,created_at,updated_at)
           VALUES('id','google','local',?,'[]','active',?,?)""", (encrypted, now, now)
    )
    await db.commit()
    assert await google_oauth.get_valid_access_token() == "still-valid"
