import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.content_planning import create_rule
from agent.services.production_progress import get_production_progress, update_production_progress
from agent.services.video_planning import _insert_scenes, create_production_job, parse_video_tab
from agent.services import production_orchestrator as runner


SHEET = [
    ["VIDEO"], ["Format 9:16"],
    ["Phần", "Shot", "Timecode", "Hình ảnh đề xuất", "Text on screen",
     "Voice-over (VI)", "Cách dựng", "Tư liệu tham khảo", "Âm thanh", "Ghi chú"],
    ["Hook", "01", "00:00-00:03", "misty mountain", "MOUNTAIN", "Hello", "cut", "mountain", "", ""],
]


def _stub_internet_footage(monkeypatch, queries=None):
    from agent.services import rea_video_adapter, youtube_footage

    def fake_search(query, limit):
        if queries is not None: queries.append(query)
        return [{"id": "aaaaaaaaaaa", "duration": 180, "title": "Misty mountain 4K", "channel": "Cam"}]
    async def fake_download(url, output): output.write_bytes(b"video"); return {"license_status": "CREATIVE_COMMONS"}
    async def fake_analyze(source, needed, limit):
        return [{"start": 12.15, "end": 17.85, "shot_index": 4, "method": "live_action", "confidence": .7, "score": .9}]

    monkeypatch.setattr(youtube_footage, "available", lambda: True)
    monkeypatch.setattr(youtube_footage, "_search_sync", fake_search)
    monkeypatch.setattr(youtube_footage, "download", fake_download)
    monkeypatch.setattr(rea_video_adapter, "analyze_broll_clip", fake_analyze)


@pytest.mark.asyncio
async def test_pipeline_advances_to_drive_export(monkeypatch, test_db, tmp_path):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}", voice_id="marin")
    await create_rule(profile["id"], "Rule")
    parsed = parse_video_tab(SHEET, "Tab"); db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    topic_id = "pipeline-topic"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,footage_status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY','READY',?,?,?)",
        (topic_id, profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 3, "hash", now, now))
    await db.execute("UPDATE video_topics SET footage_folder_url='folder' WHERE id=?", (topic_id,))
    await _insert_scenes(db, topic_id, parsed["scenes"]); await db.commit()
    source = await crud.create_footage_source(profile["id"], "google_drive", "Footage", "folder", video_topic_id=topic_id)
    await crud.upsert_footage_asset(profile["id"], source["id"], "mountain.mp4", "gdrive://file-1",
                                    external_id="file-1", status="READY", category="mountain", quality_score=9)
    job = await create_production_job(profile, topic_id, footage_mode="DRIVE_ONLY")

    _stub_internet_footage(monkeypatch)
    async def fake_tts(text, output, provider, voice, instructions): output.write_bytes(b"wav")
    async def fake_materialize(asset, output, token): output.write_bytes(b"video"); return output
    async def fake_scene(source_path, voice, output, duration, start, vertical): output.write_bytes(b"clip")
    async def fake_montage(sources, voice, output, duration, vertical, work): output.write_bytes(b"clip")
    def fake_merge(paths, output): Path(output).write_bytes(b"merged"); return True
    async def fake_logo(video, logo, position, output): shutil.copy2(video, output); return output
    async def fake_subtitles(video, scenes, output, work): shutil.copy2(video, output); return output
    async def fake_approve(job_id, output_path):
        await db.execute("UPDATE production_jobs SET status='APPROVED' WHERE id=?", (job_id,)); await db.commit()
    async def fake_export(job_id):
        await db.execute("UPDATE production_jobs SET status='READY_FOR_MANUAL_UPLOAD' WHERE id=?", (job_id,)); await db.commit()
        await update_production_progress(job_id, "DRIVE_EXPORT", "COMPLETED", "Uploaded", 100)

    monkeypatch.setattr(runner.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(runner.config, "CAPCUT_EXPORT_ENABLED", False)
    monkeypatch.setattr(runner, "_tts", fake_tts)
    monkeypatch.setattr(runner, "_materialize_asset", fake_materialize)
    monkeypatch.setattr(runner, "_make_scene_clip", fake_scene)
    monkeypatch.setattr(runner, "_make_scene_montage", fake_montage)
    monkeypatch.setattr(runner, "probe_duration", lambda path: 2.6)
    monkeypatch.setattr(runner, "merge_videos", fake_merge)
    monkeypatch.setattr(runner, "_overlay_logo", fake_logo)
    monkeypatch.setattr(runner, "_burn_subtitles", fake_subtitles)
    monkeypatch.setattr("agent.services.video_footage_pipeline.classify_video_footage", AsyncMock(return_value={"status": "READY"}))
    monkeypatch.setattr("agent.services.google_oauth.get_valid_access_token", AsyncMock(return_value="token"))
    monkeypatch.setattr("agent.services.drive_output_export.approve_production_job", fake_approve)
    monkeypatch.setattr("agent.services.drive_output_export.export_production_job", fake_export)

    await runner.run_production_job(job["id"])
    updated = await (await db.execute("SELECT status FROM production_jobs WHERE id=?", (job["id"],))).fetchone()
    assert updated[0] == "READY_FOR_MANUAL_UPLOAD"
    progress = await get_production_progress(job["id"])
    assert progress["percent"] == 100 and progress["stage"] == "DRIVE_EXPORT"
    revision = await (await db.execute("SELECT assets_json FROM production_revisions WHERE id=?", (job["current_revision_id"],))).fetchone()
    saved = json.loads(revision[0])
    assert saved["final_video_path"].endswith("final.mp4")
    # Matching Drive footage is authoritative; Internet is only a fallback.
    assert saved["scene_footage"][0]["assets"][0]["file_id"] == "file-1"
    assert saved["footage_research_job_id"]
    research = await (await db.execute(
        "SELECT status FROM footage_research_jobs WHERE id=?", (saved["footage_research_job_id"],))).fetchone()
    assert research[0] == "READY"


@pytest.mark.asyncio
async def test_online_footage_is_cut_to_rea_selected_shot(monkeypatch, test_db, tmp_path):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}", voice_id="marin")
    await create_rule(profile["id"], "Rule")
    parsed = parse_video_tab(SHEET, "Tab"); db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    topic_id = "online-topic"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,footage_status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY','READY',?,?,?)",
        (topic_id, profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 3, "hash", now, now))
    await _insert_scenes(db, topic_id, parsed["scenes"]); await db.commit()
    job = await create_production_job(profile, topic_id)

    queries, montages = [], []
    _stub_internet_footage(monkeypatch, queries)
    async def fake_tts(text, output, provider, voice, instructions): output.write_bytes(b"wav")
    async def fake_montage(sources, voice, output, duration, vertical, work):
        montages.append(sources); output.write_bytes(b"clip")
    def fake_merge(paths, output): Path(output).write_bytes(b"merged"); return True
    async def fake_logo(video, logo, position, output): shutil.copy2(video, output); return output
    async def fake_subtitles(video, scenes, output, work): shutil.copy2(video, output); return output
    async def fake_approve(job_id, output_path): pass
    async def fake_export(job_id): pass

    monkeypatch.setattr(runner.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(runner.config, "CAPCUT_EXPORT_ENABLED", False)
    monkeypatch.setattr(runner, "_tts", fake_tts)
    monkeypatch.setattr(runner, "_make_scene_montage", fake_montage)
    monkeypatch.setattr(runner, "probe_duration", lambda path: 2.6)
    monkeypatch.setattr(runner, "merge_videos", fake_merge)
    monkeypatch.setattr(runner, "_overlay_logo", fake_logo)
    monkeypatch.setattr(runner, "_burn_subtitles", fake_subtitles)
    monkeypatch.setattr("agent.services.drive_output_export.approve_production_job", fake_approve)
    monkeypatch.setattr("agent.services.drive_output_export.export_production_job", fake_export)

    await runner.run_production_job(job["id"])
    status = await (await db.execute("SELECT status,error_message FROM production_jobs WHERE id=?", (job["id"],))).fetchone()
    assert status[0] != "FAILED", status[1]
    assert queries and "misty" in queries[0] and "mountain" in queries[0]
    source, start = montages[0][0]
    assert source.name == "online-youtube-aaaaaaaaaaa.mp4" and start == pytest.approx(12.15)
    revision = await (await db.execute("SELECT assets_json FROM production_revisions WHERE id=?", (job["current_revision_id"],))).fetchone()
    footage = json.loads(revision[0])["scene_footage"][0]["assets"][0]
    assert footage["provider"] == "youtube" and footage["license_status"] == "CREATIVE_COMMONS"
    assert footage["source_start_s"] == pytest.approx(12.15)
    candidate = await (await db.execute(
        "SELECT selected,timestamp_status,source_start_s FROM footage_research_candidates WHERE provider='youtube'")).fetchone()
    assert candidate[0] == 1 and candidate[1] == "VERIFIED" and candidate[2] == pytest.approx(12.15)
