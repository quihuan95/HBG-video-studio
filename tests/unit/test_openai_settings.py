from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import config
from agent.api import openai_settings


def make_client():
    app = FastAPI()
    app.include_router(openai_settings.router, prefix="/api")
    return TestClient(app)


def test_status_never_returns_api_key(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-super-secret")
    payload = make_client().get("/api/settings/openai").json()
    assert payload["has_api_key"] is True
    assert "api_key" not in payload
    assert "sk-super-secret" not in str(payload)


def test_update_preserves_blank_key_and_writes_models(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=existing-secret\nOPENAI_VISION_MODEL=old\n", encoding="utf-8")
    monkeypatch.setattr(openai_settings, "_ENV_FILE", env_file)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "existing-secret")
    for name in ("OPENAI_VISION_MODEL", "OPENAI_REVIEW_MODEL", "OPENAI_SCRIPT_MODEL", "OPENAI_TTS_MODEL"):
        monkeypatch.setattr(config, name, "old")

    response = make_client().patch("/api/settings/openai", json={
        "api_key": "",
        "vision_model": "vision-new",
        "review_model": "review-new",
        "script_model": "script-new",
        "tts_model": "tts-new",
    })
    assert response.status_code == 200
    saved = env_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=existing-secret" in saved
    assert "OPENAI_REVIEW_MODEL=review-new" in saved
    assert response.json()["restart_required"] is True


def test_update_replaces_key_without_returning_it(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(openai_settings, "_ENV_FILE", env_file)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    response = make_client().patch("/api/settings/openai", json={
        "api_key": "sk-new-secret",
        "vision_model": "vision",
        "review_model": "review",
        "script_model": "script",
        "tts_model": "tts",
    })
    assert response.status_code == 200
    assert "OPENAI_API_KEY=sk-new-secret" in env_file.read_text(encoding="utf-8")
    assert "sk-new-secret" not in response.text
