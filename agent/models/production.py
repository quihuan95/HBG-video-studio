"""Production profiles and normalized footage library models."""
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProductionRules(BaseModel):
    intro_duration_s: float = 0
    outro_duration_s: float = 0
    subtitle_style: dict[str, Any] = Field(default_factory=dict)
    target_resolution: str = "1920x1080"
    target_fps: int = 30
    music_volume: float = Field(0.15, ge=0, le=1)
    voice_volume: float = Field(1.0, ge=0, le=2)
    extra: dict[str, Any] = Field(default_factory=dict)


class ProductionProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    language: str = "vi"
    tone: str | None = None
    rules: ProductionRules = Field(default_factory=ProductionRules)
    logo_path: str | None = None
    logo_position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"] = "top-right"
    voice_provider: str = "openai"
    voice_id: str = "marin"
    music_path: str | None = None
    sheet_url: str | None = None
    output_drive_url: str | None = None


class ProductionProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    language: str | None = None
    tone: str | None = None
    rules: ProductionRules | None = None
    logo_path: str | None = None
    logo_position: str | None = None
    voice_provider: str | None = None
    voice_id: str | None = None
    music_path: str | None = None
    sheet_url: str | None = None
    output_drive_url: str | None = None
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class ProductionProfile(ProductionProfileCreate):
    id: str
    status: str = "ACTIVE"
    created_at: str | None = None
    updated_at: str | None = None


class FootageSourceCreate(BaseModel):
    source_type: Literal["local", "google_drive"]
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1)
    recursive: bool = True
    enabled: bool = True


class FootageSource(FootageSourceCreate):
    id: str
    profile_id: str
    last_scanned_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class FootageAsset(BaseModel):
    id: str
    profile_id: str
    source_id: str
    external_id: str | None = None
    file_name: str
    uri: str
    mime_type: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    status: str = "DISCOVERED"
    summary: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    usable_ranges: list[dict[str, Any]] = Field(default_factory=list)
    quality_score: float | None = None
    has_dialogue: bool | None = None
    analysis: dict[str, Any] | None = None
    error_message: str | None = None
    analyzed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
