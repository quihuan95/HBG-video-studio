import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.video_footage_pipeline import _category_folder, classify_video_footage
from agent.api.content_calendar import _prepare_topic_footage


def test_category_folder_is_drive_safe():
    assert _category_folder("  City / Street\\Night  ") == "City - Street - Night"


@pytest.mark.asyncio
async def test_per_video_footage_is_scanned_analyzed_and_organized(monkeypatch, test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    topic_id = "topic-footage"
    folder_url = "https://drive.google.com/drive/folders/folder_12345678901234567890"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,footage_folder_url,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        (topic_id, profile["id"], "sheet", 10, "Video tab", "Video", "Brief", folder_url,
         "VERTICAL", 10, "hash", now, now))
    await db.commit()

    async def fake_scan(source):
        return [await crud.upsert_footage_asset(
            profile["id"], source["id"], "clip.mp4", "gdrive://clip-id",
            external_id="clip-id", mime_type="video/mp4")]

    analyzed_ids = []
    async def fake_analyze(asset_id, selected_profile):
        analyzed_ids.append(asset_id)
        return await crud.update_footage_asset(asset_id, status="READY", category="City / Street")

    organized = {}
    def fake_organize(root, items, token):
        organized.update(root=root, items=items, token=token)
        return {"clip-id": "City - Street"}

    async def fake_token(): return "token"
    monkeypatch.setattr("agent.services.video_footage_pipeline.scan_google_drive", fake_scan)
    monkeypatch.setattr("agent.services.video_footage_pipeline.analyze_footage", fake_analyze)
    monkeypatch.setattr("agent.services.video_footage_pipeline._organize_files_sync", fake_organize)
    monkeypatch.setattr("agent.services.video_footage_pipeline.get_valid_access_token", fake_token)

    result = await classify_video_footage(topic_id)
    assert result["status"] == "READY"
    assert result["classified"] == 1
    assert organized["root"] == "folder_12345678901234567890"
    source = (await crud.list_footage_sources(profile["id"]))[0]
    assert source["video_topic_id"] == topic_id
    assert len(analyzed_ids) == 1

    # A normal create flow reuses READY analysis; only an explicit force reruns OpenAI.
    await classify_video_footage(topic_id)
    assert len(analyzed_ids) == 1
    await classify_video_footage(topic_id, force=True)
    assert len(analyzed_ids) == 2


@pytest.mark.asyncio
async def test_job_creation_gate_requires_ready_footage(monkeypatch, test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        ("no-folder", profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 1, "h", now, now))
    await db.commit()
    with pytest.raises(ValueError, match="folder footage"):
        await _prepare_topic_footage("no-folder")

    await db.execute("UPDATE video_topics SET footage_folder_url=?,footage_status='PARTIAL',footage_error='one clip failed' WHERE id=?",
                     ("https://drive.google.com/drive/folders/folder_12345678901234567890", "no-folder"))
    await db.commit()

    async def remains_partial(topic_id):
        return {"status": "PARTIAL"}

    monkeypatch.setattr("agent.api.content_calendar.classify_video_footage", remains_partial)
    with pytest.raises(ValueError, match="PARTIAL"):
        await _prepare_topic_footage("no-folder")
