import json

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services import footage_research as research
from agent.services import youtube_footage


def test_fallback_plan_has_ordered_timeline_and_keywords():
    shots = research._fallback_plan(
        "Khách làm thủ tục tại sân bay. Đoàn tham quan thành phố và thưởng thức ẩm thực.", 45)
    assert shots[0]["timeline_start_seconds"] == 0
    assert shots[-1]["timeline_end_seconds"] == 45
    assert all(a["timeline_end_seconds"] <= b["timeline_start_seconds"] for a, b in zip(shots, shots[1:]))
    assert all(shot["keywords_vi"] for shot in shots)


def test_internal_candidate_uses_only_evidenced_timestamp(monkeypatch):
    monkeypatch.setattr(research.config, "FOOTAGE_SEARCH_MAX_RESULTS", 5)
    shot = {"keywords_vi_json": json.dumps(["sân bay"]), "keywords_en_json": "[]",
            "visual_description": "Khách tại sân bay"}
    assets = [{"id": "a1", "external_id": None, "file_name": "airport.mp4", "uri": "file:///airport.mp4",
               "status": "READY", "summary": "Khách check-in tại sân bay", "category": "travel",
               "tags_json": json.dumps(["sân bay"]), "usable_ranges_json": json.dumps([{"start": 2, "end": 6, "description": "check-in"}]),
               "quality_score": 8, "duration_s": 10, "width": 1080, "height": 1920}]
    result = research._asset_candidates(shot, assets)[0]
    assert result["source_start_s"] == 2
    assert result["source_end_s"] == 6
    assert result["timestamp_status"] == "VERIFIED"


def test_internal_candidate_selects_later_range_matching_scene(monkeypatch):
    monkeypatch.setattr(research.config, "FOOTAGE_SEARCH_MAX_RESULTS", 5)
    shot = {"keywords_vi_json": json.dumps(["ký kết", "sân khấu"]), "keywords_en_json": "[]",
            "visual_description": "Đại diện ký kết trên sân khấu"}
    assets = [{"id": "a1", "external_id": "drive-1", "file_name": "event.mp4",
               "uri": "gdrive://drive-1", "status": "READY",
               "summary": "Sự kiện có khách đến và lễ ký kết trên sân khấu", "category": "event",
               "tags_json": json.dumps(["sự kiện", "ký kết", "sân khấu"]),
               "usable_ranges_json": json.dumps([
                   {"start": 0, "end": 8, "description": "Khách đi vào sảnh"},
                   {"start": 42, "end": 55, "description": "Đại diện ký kết trên sân khấu"},
               ]), "quality_score": 8, "duration_s": 60}]

    result = research._asset_candidates(shot, assets)[0]

    assert result["source_start_s"] == 42
    assert result["source_end_s"] == 55


def test_internal_candidate_skips_center_text_range(monkeypatch):
    monkeypatch.setattr(research.config, "FOOTAGE_SEARCH_MAX_RESULTS", 5)
    shot = {"keywords_vi_json": json.dumps(["ký kết"]), "keywords_en_json": "[]",
            "visual_description": "Đại diện ký kết"}
    assets = [{"id": "a1", "file_name": "event.mp4", "uri": "file:///event.mp4",
               "status": "READY", "summary": "Lễ ký kết", "category": "event",
               "tags_json": json.dumps(["ký kết"]), "quality_score": 8, "duration_s": 60,
               "usable_ranges_json": json.dumps([
                   {"start": 5, "end": 12, "description": "Ký kết với tiêu đề lớn giữa màn hình",
                    "has_center_text": True},
                   {"start": 30, "end": 40, "description": "Đại diện ký kết không có chữ",
                    "has_center_text": False},
               ])}]

    result = research._asset_candidates(shot, assets)[0]

    assert result["source_start_s"] == 30
    assert result["source_end_s"] == 40


def test_internal_candidate_rejects_clip_when_all_ranges_have_center_text(monkeypatch):
    monkeypatch.setattr(research.config, "FOOTAGE_SEARCH_MAX_RESULTS", 5)
    shot = {"keywords_vi_json": json.dumps(["sự kiện"]), "keywords_en_json": "[]",
            "visual_description": "Sự kiện"}
    assets = [{"id": "a1", "file_name": "event.mp4", "uri": "file:///event.mp4",
               "status": "READY", "summary": "Sự kiện", "category": "event",
               "tags_json": "[]", "quality_score": 8,
               "usable_ranges_json": json.dumps([
                   {"start": 0, "end": 10, "description": "Banner giữa khung", "has_center_text": True}
               ])}]

    assert research._asset_candidates(shot, assets) == []


def test_unknown_timestamp_is_not_invented():
    shot = {"keywords_vi_json": json.dumps(["biển"]), "keywords_en_json": "[]", "visual_description": "Biển"}
    asset = {"id": "a", "file_name": "bien.mp4", "uri": "file:///bien.mp4", "status": "READY",
             "summary": "biển", "category": "travel", "tags_json": "[]", "usable_ranges_json": "[]",
             "quality_score": 5, "duration_s": 10}
    result = research._asset_candidates(shot, [asset])[0]
    assert result["source_start_s"] is None
    assert result["source_end_s"] is None
    assert result["timestamp_status"] == "UNVERIFIED"


@pytest.mark.asyncio
async def test_youtube_candidates_filter_duration_and_live(monkeypatch):
    entries = [
        {"id": "aaaaaaaaaaa", "duration": 120, "title": "Da Lat drone", "channel": "Cam"},
        {"id": "bbbbbbbbbbb", "duration": 4000, "title": "Too long"},
        {"id": "ccccccccccc", "duration": 3, "title": "Too short"},
        {"id": "ddddddddddd", "duration": None, "title": "Live", "live_status": "is_live"},
        {"id": "not-an-id", "duration": 60, "title": "Bad id"},
    ]
    monkeypatch.setattr(youtube_footage, "_search_sync", lambda query, limit: entries)
    monkeypatch.setattr(youtube_footage.config, "YOUTUBE_MIN_DURATION_S", 10)
    monkeypatch.setattr(youtube_footage.config, "YOUTUBE_MAX_DURATION_S", 600)
    result = await youtube_footage.search_candidates("da lat  drone", 5)
    assert [item["provider_file_id"] for item in result] == ["aaaaaaaaaaa"]
    assert result[0]["download_url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert result[0]["timestamp_status"] == "UNVERIFIED"


def test_online_query_keeps_keyword_order():
    shot = {"keywords_en_json": json.dumps(research._ordered_words("misty mountain at sunrise, mountain")),
            "keywords_vi_json": "[]", "visual_description": "x"}
    assert research._online_query(shot) == "misty mountain at sunrise"


def test_youtube_download_rejects_non_youtube_urls():
    assert youtube_footage.is_youtube_url("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    assert not youtube_footage.is_youtube_url("https://example.com/watch?v=aaaaaaaaaaa")
    assert not youtube_footage.is_youtube_url("http://www.youtube.com/watch?v=aaaaaaaaaaa")


def test_online_download_allowlist_blocks_arbitrary_hosts():
    assert research._safe_download_url("https://videos.pexels.com/video.mp4")
    assert not research._safe_download_url("https://example.com/video.mp4")
    assert not research._safe_download_url("http://videos.pexels.com/video.mp4")


@pytest.mark.asyncio
async def test_internal_search_is_limited_to_current_drive_source(monkeypatch, test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    stale_source = await crud.create_footage_source(profile["id"], "google_drive", "Old", "old-folder")
    current_source = await crud.create_footage_source(profile["id"], "google_drive", "Current", "current-folder")
    await crud.upsert_footage_asset(profile["id"], stale_source["id"], "old-mountain.mp4", "gdrive://old",
                                    external_id="old", status="READY", summary="misty mountain")
    await crud.upsert_footage_asset(profile["id"], current_source["id"], "new-mountain.mp4", "gdrive://new",
                                    external_id="new", status="READY", summary="misty mountain")
    job = await research.create_job(profile["id"], "misty mountain", 5, "9:16", "internal_only")
    db = await get_db()
    await db.execute("""INSERT INTO footage_research_shots
        (id,job_id,order_index,script_excerpt,visual_description,visual_intent,keywords_vi_json,keywords_en_json,
         negative_keywords_json,timeline_start_s,timeline_end_s,requirement_type,priority,notes,status)
         VALUES('shot-source-filter',?,1,'mountain','misty mountain','', '[]','[\"misty\",\"mountain\"]',
                '[]',0,5,'ILLUSTRATIVE',1,'','PLANNED')""", (job["id"],))
    await db.commit()

    result = await research.search_job(job["id"], [current_source["id"]])

    candidates = result["shots"][0]["candidates"]
    assert [item["provider_file_id"] for item in candidates] == ["new"]


@pytest.mark.asyncio
async def test_hybrid_skips_internet_when_drive_has_a_usable_match(monkeypatch, test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    source = await crud.create_footage_source(profile["id"], "google_drive", "Drive", "folder")
    await crud.upsert_footage_asset(
        profile["id"], source["id"], "signing.mp4", "gdrive://signing",
        external_id="signing", status="READY", summary="representatives signing on stage",
        tags_json=json.dumps(["signing", "stage"]),
        usable_ranges_json=json.dumps([{
            "start": 20, "end": 30, "description": "representatives signing on stage",
            "has_center_text": False,
        }]),
    )
    job = await research.create_job(profile["id"], "signing", 5, "9:16", "internal_first")
    db = await get_db()
    await db.execute("""INSERT INTO footage_research_shots
        (id,job_id,order_index,script_excerpt,visual_description,visual_intent,keywords_vi_json,keywords_en_json,
         negative_keywords_json,timeline_start_s,timeline_end_s,requirement_type,priority,notes,status)
        VALUES('drive-first-shot',?,1,'signing','signing on stage','signing', '[]','[\"signing\",\"stage\"]',
               '[]',0,5,'ILLUSTRATIVE',1,'','PLANNED')""", (job["id"],))
    await db.commit()
    calls = []
    async def fake_pexels(shot, aspect_ratio):
        calls.append(shot["id"])
        return []
    monkeypatch.setattr(research, "_pexels_candidates", fake_pexels)
    monkeypatch.setattr(research.config, "FOOTAGE_EXTERNAL_ENABLED", True)
    monkeypatch.setattr(research.config, "PEXELS_API_KEY", "key")
    monkeypatch.setattr(youtube_footage, "available", lambda: False)

    result = await research.search_job(job["id"], [source["id"]])

    assert calls == []
    assert result["shots"][0]["candidates"][0]["asset_id"] is not None
