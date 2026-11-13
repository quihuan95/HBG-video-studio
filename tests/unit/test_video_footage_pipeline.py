import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.video_footage_pipeline import _category_folder, _source_for_topic, classify_video_footage
from agent.services import video_footage_pipeline as pipeline
from agent.api.content_calendar import _prepare_topic_footage
from agent.services.footage_scanner import _reconcile_drive_assets


def test_category_folder_is_drive_safe():
    assert _category_folder("  City / Street\\Night  ") == "City - Street - Night"


@pytest.mark.asyncio
async def test_drive_scan_marks_deleted_cached_assets_unavailable(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    source = await crud.create_footage_source(
        profile["id"], "google_drive", "Drive", "folder")
    kept = await crud.upsert_footage_asset(
        profile["id"], source["id"], "kept.mp4", "gdrive://kept",
        external_id="kept", status="READY")
    removed = await crud.upsert_footage_asset(
        profile["id"], source["id"], "removed.mp4", "gdrive://removed",
        external_id="removed", status="READY")

    await _reconcile_drive_assets(source, {"kept"})

    assert (await crud.get_footage_asset(kept["id"]))["status"] == "READY"
    stale = await crud.get_footage_asset(removed["id"])
    assert stale["status"] == "FAILED"
    assert stale["error_message"] == "Missing from Google Drive"


@pytest.mark.asyncio
async def test_topics_with_same_folder_reuse_source_with_ready_assets(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    folder = "https://drive.google.com/drive/folders/shared_folder_123456789"
    first = await crud.create_footage_source(profile["id"], "google_drive", "First", folder)
    second = await crud.create_footage_source(profile["id"], "google_drive", "Second", folder)
    await crud.upsert_footage_asset(profile["id"], first["id"], "ready.mp4", "gdrive://ready",
                                    external_id="ready", status="READY")
    selected = await _source_for_topic({"id": "topic-three", "profile_id": profile["id"],
                                        "source_tab_name": "Third", "footage_folder_url": folder})
    assert selected["id"] == first["id"]
    assert selected["id"] != second["id"]


@pytest.mark.asyncio
async def test_per_video_footage_is_inspected_without_organizing_drive(monkeypatch, test_db):
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

    organized = {"called": False}
    def fake_organize(root, items, token):
        organized["called"] = True
        return {"clip-id": "City - Street"}

    async def fake_token(): return "token"
    def fake_restore(root, token): return 0
    monkeypatch.setattr("agent.services.video_footage_pipeline.scan_google_drive", fake_scan)
    monkeypatch.setattr("agent.services.video_footage_pipeline.analyze_footage", fake_analyze)
    monkeypatch.setattr("agent.services.video_footage_pipeline._organize_files_sync", fake_organize)
    monkeypatch.setattr("agent.services.video_footage_pipeline.get_valid_access_token", fake_token)
    monkeypatch.setattr("agent.services.video_footage_pipeline._restore_legacy_moved_files_sync", fake_restore)

    result = await classify_video_footage(topic_id)
    assert result["status"] == "READY"
    assert result["classified"] == 1
    assert organized["called"] is False
    assert result["organization"]["mode"] == "inspect_in_place"
    assert result["organization"]["files_moved"] == 0
    assert result["organization"]["classified_folder_id"] is None
    source = (await crud.list_footage_sources(profile["id"]))[0]
    assert source["video_topic_id"] == topic_id
    assert len(analyzed_ids) == 1

    # A normal create flow reuses READY analysis; only an explicit force reruns OpenAI.
    await classify_video_footage(topic_id)
    assert len(analyzed_ids) == 1
    await classify_video_footage(topic_id, force=True)
    assert len(analyzed_ids) == 2


@pytest.mark.asyncio
async def test_job_creation_needs_only_an_internet_footage_provider(monkeypatch, test_db):
    from agent.services import youtube_footage
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        ("no-folder", profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 1, "h", now, now))
    await db.commit()
    monkeypatch.setattr(youtube_footage, "available", lambda: False)
    with pytest.raises(ValueError, match="nguồn footage Internet"):
        await _prepare_topic_footage("no-folder")

    monkeypatch.setattr(youtube_footage, "available", lambda: True)
    await _prepare_topic_footage("no-folder")


@pytest.mark.asyncio
async def test_background_progress_survives_memory_reset(monkeypatch, test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"; topic_id = "persist-progress"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,footage_folder_url,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        (topic_id, profile["id"], "sheet", 2, "Tab", "Video", "",
         "https://drive.google.com/drive/folders/folder_12345678901234567890",
         "VERTICAL", 1, "h", now, now))
    await db.commit()

    async def fake_classify(selected_id, progress=None, force=False):
        await progress("ANALYZING", "Đã xử lý clip 1", 1, 2)
        return {"status": "READY", "classified": 2}

    monkeypatch.setattr(pipeline, "_classify_video_footage", fake_classify)
    await pipeline.start_video_footage_classification(topic_id)
    await pipeline._classification_tasks[topic_id]
    pipeline._classification_runs.pop(topic_id, None)
    pipeline._classification_tasks.pop(topic_id, None)
    restored = await pipeline.classification_status(topic_id)
    assert restored["status"] == "COMPLETED"
    assert restored["current"] == 1
    assert restored["logs"][-1]["message"] == "Đã xử lý clip 1"
