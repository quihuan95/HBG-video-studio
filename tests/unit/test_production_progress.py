import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.production_progress import (
    cancel_production_progress, get_production_progress, initialize_production_progress,
    update_production_progress,
)


@pytest.mark.asyncio
async def test_production_progress_is_persistent_and_stage_based(test_db):
    profile = await crud.create_production_profile(name="HBG", rules_json="{}")
    db = await get_db(); now = "2026-11-09T00:00:00+00:00"
    await db.execute("INSERT INTO production_jobs(id,profile_id,title,status,created_at,updated_at) VALUES(?,?,?,'DRAFT',?,?)",
                     ("job-progress", profile["id"], "Video", now, now))
    await db.commit()
    initial = await initialize_production_progress("job-progress")
    assert initial["stage"] == "VOICE" and initial["percent"] == 12
    running = await update_production_progress("job-progress", "VOICE", "PROCESSING", "Đang tạo voice", 20)
    assert running["status"] == "RUNNING"
    assert running["stages"][1]["status"] == "PROCESSING"
    restored = await get_production_progress("job-progress")
    assert restored["message"] == "Đang tạo voice"
    assert restored["logs"][-1]["stage"] == "VOICE"
    cancelled = await cancel_production_progress("job-progress")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["stages"][1]["status"] == "CANCELLED"
    assert cancelled["logs"][-1]["message"] == "Người dùng đã hủy làm video"
