"""Local-only OpenAI settings API. Never returns the stored API key."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from agent import config

router = APIRouter(prefix="/settings/openai", tags=["settings"])
_ENV_FILE = Path(os.environ.get("APP_ENV_PATH", config.BASE_DIR / ".env"))
_MODEL_FIELDS = {
    "vision_model": "OPENAI_VISION_MODEL",
    "review_model": "OPENAI_REVIEW_MODEL",
    "script_model": "OPENAI_SCRIPT_MODEL",
    "tts_model": "OPENAI_TTS_MODEL",
}


class OpenAISettingsUpdate(BaseModel):
    api_key: str | None = Field(default=None, repr=False)
    vision_model: str
    review_model: str
    script_model: str
    tts_model: str

    @field_validator("vision_model", "review_model", "script_model", "tts_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value or value.startswith("-"):
            raise ValueError("Model name is invalid")
        return value

    @field_validator("api_key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None  # blank means preserve the existing secret
        if "\n" in value or "\r" in value:
            raise ValueError("API key is invalid")
        return value


def _safe_status() -> dict:
    return {
        "has_api_key": bool(config.OPENAI_API_KEY),
        "vision_model": config.OPENAI_VISION_MODEL,
        "review_model": config.OPENAI_REVIEW_MODEL,
        "script_model": config.OPENAI_SCRIPT_MODEL,
        "tts_model": config.OPENAI_TTS_MODEL,
        "restart_required": False,
    }


def _update_env(values: dict[str, str]) -> None:
    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines() if _ENV_FILE.exists() else []
    remaining = dict(values)
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    if remaining:
        if output and output[-1]:
            output.append("")
        output.extend(f"{key}={value}" for key, value in remaining.items())
    tmp = _ENV_FILE.with_suffix(_ENV_FILE.suffix + ".tmp")
    tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(tmp, _ENV_FILE)


@router.get("")
async def get_openai_settings():
    return _safe_status()


@router.patch("")
async def update_openai_settings(body: OpenAISettingsUpdate):
    values = {
        env_name: getattr(body, field_name)
        for field_name, env_name in _MODEL_FIELDS.items()
    }
    if body.api_key:
        values["OPENAI_API_KEY"] = body.api_key
    try:
        _update_env(values)
    except OSError as exc:
        raise HTTPException(500, "Could not save OpenAI settings") from exc

    for field_name, env_name in _MODEL_FIELDS.items():
        value = getattr(body, field_name)
        os.environ[env_name] = value
        setattr(config, env_name, value)
    if body.api_key:
        os.environ["OPENAI_API_KEY"] = body.api_key
        config.OPENAI_API_KEY = body.api_key
    result = _safe_status()
    # Some services import constants at process start, so make this explicit.
    result["restart_required"] = True
    return result
