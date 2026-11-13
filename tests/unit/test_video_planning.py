import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.content_planning import create_rule
from agent.services.video_planning import (
    _footage_link, _footage_link_from_cell, _insert_scenes, create_production_job, delete_production_job,
    parse_video_tab, production_calendar,
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


@pytest.mark.parametrize(("cell", "expected"), [
    ("https://drive.google.com/drive/folders/folder_12345678901234567890?usp=sharing",
     "https://drive.google.com/drive/folders/folder_12345678901234567890?usp=sharing"),
    ('=HYPERLINK("https://drive.google.com/drive/folders/folder_12345678901234567890?usp=sharing","Footage")',
     "https://drive.google.com/drive/folders/folder_12345678901234567890?usp=sharing"),
    ("folder_12345678901234567890", "folder_12345678901234567890"),
])
def test_footage_link_supports_a3_drive_url_formula_and_id(cell, expected):
    assert _footage_link([cell]) == expected


def test_footage_link_reads_rich_text_link_from_a3_cell_metadata():
    cell = {"effectiveValue": {"stringValue": "Footage"}, "textFormatRuns": [
        {"startIndex": 0, "format": {"link": {"uri": "https://drive.google.com/drive/folders/folder_12345678901234567890"}}}
    ]}
    assert _footage_link_from_cell(cell).endswith("folder_12345678901234567890")


def test_footage_link_reads_drive_smart_chip_from_a3_cell_metadata():
    cell = {"chipRuns": [{"chip": {"richLinkProperties": {
        "uri": "https://drive.google.com/drive/folders/folder_12345678901234567890"
    }}}]}
    assert _footage_link_from_cell(cell).endswith("folder_12345678901234567890")


def test_parse_accepts_outline_without_narration_or_footage_columns():
    values = [
        ["Video outline"], ["Brief"],
        ["Phần", "Shot", "Timecode", "Ghi chú"],
        ["Hook", "01", "00:00-00:05", "Mở đầu gây tò mò"],
    ]
    parsed = parse_video_tab(values, "Outline")
    assert parsed["scenes"][0]["narration_text"] == ""
    assert parsed["scenes"][0]["visual_intent"] == ""


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


def test_parse_four_column_sheet_with_second_durations():
    data = [
        ["CHUYẾN BAY TRỄ"], ["Format 9:16"],
        ["Footage", "https://drive.google.com/drive/folders/folder_12345678901234567890"],
        ["THỜI LƯỢNG", "VOICE", "TEXT TRÊN VIDEO", "HÌNH ẢNH / GỢI Ý DỰNG"],
        ["0–6s", "Một đoàn khách quốc tế đến Việt Nam dự hội nghị.", "CHUYẾN BAY TRỄ. GIỜ G KHÔNG ĐỔI.",
         "Dựng nhịp nhanh: bảng giờ bay → xe đón → đồng hồ đếm ngược → sân khấu đang chuẩn bị."],
        ["6–16s", "A: Điều chỉnh xe đón. B: Báo ngay cho ban tổ chức.", "A / ĐỔI XE\nB / BÁO BTC\nC / RÀ SOÁT TOÀN HÀNH TRÌNH",
         "Chia ba ô A/B/C, mỗi ô một cảnh."],
        ["54–64s", "Nếu là người điều phối, bạn chọn A, B hay C?", "BẠN CHỌN A, B HAY C?", "End-card The HBG."],
    ]
    result = parse_video_tab(data, "Chuyến bay trễ")
    scenes = result["scenes"]
    assert [(s["start_time_s"], s["end_time_s"]) for s in scenes] == [(0, 6), (6, 16), (54, 64)]
    assert result["target_duration_s"] == 64 and result["orientation"] == "VERTICAL"
    assert scenes[0]["narration_text"].startswith("Một đoàn khách")
    assert scenes[1]["on_screen_text"].splitlines()[2] == "C / RÀ SOÁT TOÀN HÀNH TRÌNH"
    assert scenes[0]["visual_intent"].startswith("Dựng nhịp nhanh")
    assert [s["shot_code"] for s in scenes] == ["01", "02", "03"]


@pytest.mark.parametrize(("value", "expected"), [("6", 6), ("6s", 6), ("6,5 giây", 6.5), ("01:05", 65)])
def test_duration_cells_accept_seconds_and_clock_time(value, expected):
    from agent.services.video_planning import _seconds
    assert _seconds(value) == expected


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


@pytest.mark.asyncio
async def test_video_job_requires_published_profile_rule(test_db):
    profile = await crud.create_production_profile(name="No Drive Rule", rules_json="{}")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        ("no-rule-topic", profile["id"], "sheet", 1, "Tab", "Video", "Brief", "VERTICAL", 10, "hash", now, now))
    await db.commit()

    with pytest.raises(ValueError, match="published Profile Rule"):
        await create_production_job(profile, "no-rule-topic", footage_mode="INTERNET_ONLY")


@pytest.mark.asyncio
async def test_cancelled_job_releases_topic_and_can_restart_as_new_revision(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}", color="#123456")
    await create_rule(profile["id"], "Video rule")
    parsed = parse_video_tab(SHEET, "Tab")
    db = await get_db(); topic_id = "topic-restart"; now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        (topic_id, profile["id"], "spreadsheet", 99, "Tab", parsed["title"], parsed["brief"], parsed["orientation"], parsed["target_duration_s"], "hash", now, now))
    from agent.services.video_planning import _insert_scenes
    await _insert_scenes(db, topic_id, parsed["scenes"]); await db.commit()
    first = await create_production_job(profile, topic_id)
    await db.execute("UPDATE production_jobs SET status='CANCELLED' WHERE id=?", (first["id"],)); await db.commit()
    items = await production_calendar()
    assert {item["kind"] for item in items} == {"topic", "job"}
    assert next(item for item in items if item["kind"] == "job")["status"] == "CANCELLED"

    restarted = await create_production_job(profile, topic_id)
    assert restarted["id"] == first["id"]
    assert restarted["status"] == "DRAFT"
    revisions = await (await db.execute("SELECT revision FROM production_revisions WHERE production_job_id=? ORDER BY revision", (first["id"],))).fetchall()
    assert [row[0] for row in revisions] == [1, 2]
    assert len(await production_calendar()) == 1


@pytest.mark.asyncio
async def test_completed_job_can_be_forced_to_regenerate_as_new_revision(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}", color="#123456")
    await create_rule(profile["id"], "Rule")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"; topic_id = "topic-regenerate"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        (topic_id, profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 50, "hash", now, now))
    await _insert_scenes(db, topic_id, [{"scene_order": 1, "start_time_s": 0, "end_time_s": 50, "duration_s": 50}])
    await db.commit()
    first = await create_production_job(profile, topic_id)
    await db.execute("UPDATE production_jobs SET status='READY_FOR_MANUAL_UPLOAD',output_url='https://drive.google.com/old' WHERE id=?", (first["id"],))
    await db.commit()
    regenerated = await create_production_job(profile, topic_id, force=True)
    assert regenerated["id"] == first["id"]
    assert regenerated["status"] == "DRAFT"
    assert regenerated["output_url"] is None
    revisions = await (await db.execute("SELECT revision FROM production_revisions WHERE production_job_id=? ORDER BY revision", (first["id"],))).fetchall()
    assert [row[0] for row in revisions] == [1, 2]
    audit = await (await db.execute("SELECT action FROM production_audit_events WHERE production_job_id=? ORDER BY created_at DESC", (first["id"],))).fetchone()
    assert audit[0] == "REGENERATE_PRODUCTION"


@pytest.mark.asyncio
async def test_delete_completed_job_returns_topic_to_create_list(test_db, tmp_path, monkeypatch):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}", color="#123456")
    await create_rule(profile["id"], "Rule")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"; topic_id = "topic-delete"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        (topic_id, profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 50, "hash", now, now))
    await _insert_scenes(db, topic_id, [{"scene_order": 1, "start_time_s": 0, "end_time_s": 50, "duration_s": 50}])
    await db.commit()
    job = await create_production_job(profile, topic_id)
    await db.execute("UPDATE production_jobs SET status='COMPLETED' WHERE id=?", (job["id"],)); await db.commit()
    monkeypatch.setattr("agent.config.OUTPUT_DIR", tmp_path)
    workspace = tmp_path / "production_jobs" / job["id"]
    workspace.mkdir(parents=True); (workspace / "final.mp4").write_bytes(b"video")

    result = await delete_production_job(job["id"])

    assert result["video_topic_id"] == topic_id and not workspace.exists()
    items = await production_calendar()
    assert len(items) == 1 and items[0]["kind"] == "topic" and items[0]["id"] == topic_id
