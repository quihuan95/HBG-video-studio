import json

import pytest

from agent.db import crud
from agent.services.footage_scanner import drive_folder_id


@pytest.mark.asyncio
async def test_profile_supports_local_and_drive_sources(test_db, tmp_path):
    profile = await crud.create_production_profile(
        name="News", language="vi", tone="authoritative",
        rules_json=json.dumps({"target_resolution": "1920x1080"}),
        sheet_url="https://docs.google.com/spreadsheets/d/example",
        output_drive_url="https://drive.google.com/drive/folders/output",
    )
    local = await crud.create_footage_source(
        profile["id"], "local", "Local library", str(tmp_path))
    drive = await crud.create_footage_source(
        profile["id"], "google_drive", "Drive library",
        "https://drive.google.com/drive/folders/abc_123")

    sources = await crud.list_footage_sources(profile["id"])
    assert {item["source_type"] for item in sources} == {"local", "google_drive"}
    assert local["profile_id"] == drive["profile_id"] == profile["id"]


@pytest.mark.asyncio
async def test_footage_upsert_is_idempotent(test_db):
    profile = await crud.create_production_profile(name="Profile")
    source = await crud.create_footage_source(profile["id"], "local", "Local", "C:/footage")
    first = await crud.upsert_footage_asset(
        profile["id"], source["id"], "clip.mp4", "file:///C:/footage/clip.mp4", duration_s=10)
    second = await crud.upsert_footage_asset(
        profile["id"], source["id"], "clip.mp4", "file:///C:/footage/clip.mp4", duration_s=12)

    assert first["id"] == second["id"]
    assert second["duration_s"] == 12
    assert len(await crud.list_footage_assets(profile["id"])) == 1


def test_drive_folder_id_accepts_url_or_id():
    assert drive_folder_id("https://drive.google.com/drive/folders/abc_123?usp=sharing") == "abc_123"
    assert drive_folder_id("abc_123") == "abc_123"
