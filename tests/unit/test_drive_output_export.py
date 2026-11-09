import json

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.content_planning import create_rule
from agent.services.drive_output_export import (
    DriveExportError, _date_folder, _safe_name, approve_production_job,
    export_production_job,
)
from agent.services.video_planning import create_production_job


async def _job_with_video(tmp_path):
    profile = await crud.create_production_profile(
        name="HBG", rules_json="{}", folder_id_output="output-folder")
    rule = await create_rule(profile["id"], "Video rule")
    db = await get_db()
    now = "2026-11-09T00:00:00+00:00"
    await db.execute(
        "INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        ("topic-export", profile["id"], "sheet", 123, "Tab", "Tour / Trung Quốc", "Brief",
         "VERTICAL", 30, "hash", now, now))
    await db.commit()
    job = await create_production_job(profile, "topic-export", "2026-11-12", "09:00")
    video = tmp_path / "result.mp4"
    video.write_bytes(b"fake-video-output")
    await approve_production_job(job["id"], str(video))
    return profile, job, rule, video


def test_output_names_are_safe_and_date_is_local_format():
    assert _safe_name("  Tour / Trung\\Quốc\x00  ") == "Tour - Trung - Quốc"
    assert _date_folder("2026-11-12") == "12-11-2026"


@pytest.mark.asyncio
async def test_approval_requires_a_real_final_video(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    await create_rule(profile["id"], "Rule")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?,?,?)",
        ("missing-topic", profile["id"], "sheet", 1, "Tab", "Video", "", "VERTICAL", 1, "h", now, now))
    await db.commit()
    job = await create_production_job(profile, "missing-topic")
    with pytest.raises(DriveExportError, match="does not exist"):
        await approve_production_job(job["id"], "Z:/missing/final.mp4")


@pytest.mark.asyncio
async def test_export_is_idempotent_and_records_manifest(monkeypatch, test_db, tmp_path):
    _, job, rule, video = await _job_with_video(tmp_path)
    monkeypatch.setattr("agent.services.drive_output_export.get_valid_access_token", _async_value("token"))
    monkeypatch.setattr("agent.services.drive_output_export._resolve_output_folder", _async_value("output-folder"))
    folder_ids = iter(["day-folder", "title-folder", "revision-folder"] * 2)

    async def fake_folder(client, parent, name):
        return {"id": next(folder_ids), "name": name}

    uploads = []

    async def fake_upload(client, parent, name, content, mime):
        if isinstance(content, bytes):
            uploads.append((name, content.decode()))
        else:
            uploads.append((name, str(content)))
        return {"final.mp4": "video-id", "video.json": "manifest-id", "REVIEW.md": "review-id"}[name]

    monkeypatch.setattr("agent.services.drive_output_export._create_folder", fake_folder)
    monkeypatch.setattr("agent.services.drive_output_export._upsert_file", fake_upload)

    first = await export_production_job(job["id"])
    second = await export_production_job(job["id"])
    assert first == second
    assert first["driveFolderUrl"].endswith("/revision-folder")
    assert any(name == "final.mp4" and value == str(video) for name, value in uploads)
    manifests = [json.loads(value) for name, value in uploads if name == "video.json"]
    assert manifests[-1]["rule_version_id"] == rule["id"]
    assert manifests[-1]["drive"]["video_file_id"] == "video-id"

    db = await get_db()
    status = await (await db.execute("SELECT status,output_url FROM production_jobs WHERE id=?", (job["id"],))).fetchone()
    assert status[0] == "READY_FOR_MANUAL_UPLOAD"
    assert status[1].endswith("/revision-folder")
    count = await (await db.execute("SELECT COUNT(*) FROM production_exports WHERE production_job_id=?", (job["id"],))).fetchone()
    assert count[0] == 1
    audit = await (await db.execute("SELECT action FROM production_audit_events WHERE production_job_id=? ORDER BY created_at", (job["id"],))).fetchall()
    assert [row[0] for row in audit].count("EXPORT_TO_DRIVE") == 2


@pytest.mark.asyncio
async def test_drive_failure_keeps_approved_job_for_retry(monkeypatch, test_db, tmp_path):
    _, job, _, _ = await _job_with_video(tmp_path)

    async def oauth_failure():
        raise RuntimeError("Google unavailable")

    monkeypatch.setattr("agent.services.drive_output_export.get_valid_access_token", oauth_failure)
    with pytest.raises(RuntimeError, match="Google unavailable"):
        await export_production_job(job["id"])
    db = await get_db()
    row = await (await db.execute("SELECT status,error_stage,error_message FROM production_jobs WHERE id=?", (job["id"],))).fetchone()
    assert row[0] == "APPROVED"
    assert row[1] == "drive_export"
    assert "Google unavailable" in row[2]


def _async_value(value):
    async def result(*args, **kwargs):
        return value
    return result
