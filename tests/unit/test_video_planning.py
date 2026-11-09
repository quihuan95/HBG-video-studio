import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.content_planning import create_rule
from agent.services.video_planning import (
    create_production_job, parse_video_tab, production_calendar,
)


SHEET = [
    ["KỊCH BẢN REEL TEST"],
    ["Format 9:16 | Hook 3 giây đầu"],
    ["Phần", "Shot", "Timecode", "Hình ảnh đề xuất", "Text on screen",
     "Voice-over (VI) – lời đọc tiếng Việt", "Cách dựng", "Tư liệu tham khảo", "Âm thanh", "Ghi chú"],
    ["Hook", "OF", "00:00–00:03", "Cắt nhanh cảnh đẹp", "Bạn chọn đâu?",
     "Bạn muốn đi đâu?", "Cắt theo beat", "hero shots", "Nhạc vào beat", "Logo xuyên suốt"],
    ["Body", "01", "00:03-00:09", "Cảnh thiên nhiên", "THIÊN NHIÊN",
     "Hãy chọn thiên nhiên.", "Giữ khung rộng", "forest mountain", "Nhạc cinematic", ""],
]


def test_parse_one_tab_as_one_video():
    result = parse_video_tab(SHEET, "Video tab")
    assert result["title"] == "KỊCH BẢN REEL TEST"
    assert result["orientation"] == "VERTICAL"
    assert result["target_duration_s"] == 9
    assert result["scenes"][0]["shot_code"] == "OF"
    assert result["scenes"][1]["narration_text"] == "Hãy chọn thiên nhiên."


def test_overlapping_timecodes_are_rejected():
    data = [row[:] for row in SHEET]
    data[4] = data[4][:]
    data[4][2] = "00:02-00:09"
    with pytest.raises(ValueError, match="overlaps"):
        parse_video_tab(data, "Bad")


def test_parse_new_row_three_footage_folder_and_row_four_headers():
    data = [SHEET[0], SHEET[1], ["Footage folder", "https://drive.google.com/drive/folders/folder_12345678901234567890"], *SHEET[2:]]
    result = parse_video_tab(data, "Video with footage")
    assert result["footage_folder_url"].endswith("folder_12345678901234567890")
    assert len(result["scenes"]) == 2


def test_inbound_headers_accept_english_voice_and_optional_audio_notes():
    data = [
        ["INBOUND VIDEO"], ["Format 9:16 | English only"],
        ["Phần", "Shot", "Timecode", "Hình ảnh đề xuất", "Text on screen (EN) – hiển thị",
         "Dịch tiếng Việt – nội bộ", "Voice-over (EN) – lời đọc",
         "Dịch Voice-over (VI) – nội bộ", "Cách dựng", "Tư liệu tham khảo"],
        ["Hook", "OF", "00:00–00:03", "Hanoi", "HANOI", "HÀ NỘI", "Welcome to Hanoi",
         "Chào mừng đến Hà Nội", "Fast cut", "Hanoi footage"],
    ]
    result = parse_video_tab(data, "Inbound")
    assert result["scenes"][0]["narration_text"] == "Welcome to Hanoi"
    assert result["scenes"][0]["audio_instruction"] == ""
    assert result["scenes"][0]["notes"] == ""


@pytest.mark.asyncio
async def test_job_snapshots_tab_scenes_and_replaces_topic(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}", color="#123456")
    await create_rule(profile["id"], "Video rule")
    parsed = parse_video_tab(SHEET, "Tab")
    db = await get_db(); topic_id = "topic-1"; now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        (topic_id, profile["id"], "spreadsheet", 379799720, "Tab", parsed["title"], parsed["brief"], parsed["orientation"], parsed["target_duration_s"], "hash", now, now))
    from agent.services.video_planning import _insert_scenes
    await _insert_scenes(db, topic_id, parsed["scenes"]); await db.commit()
    job = await create_production_job(profile, topic_id)
    assert job["status"] == "DRAFT"
    items = await production_calendar()
    assert len(items) == 1 and items[0]["kind"] == "job"
    revision = (await db.execute("SELECT * FROM production_revisions WHERE production_job_id=?", (job["id"],)))
    row = await revision.fetchone()
    assert "voice_missing" in row["blockers_json"]
    from agent.services.production_progress import get_production_progress
    progress = await get_production_progress(job["id"])
    assert progress["stage"] == "VOICE"
    assert progress["percent"] == 12
    assert progress["stages"][0]["status"] == "COMPLETED"
