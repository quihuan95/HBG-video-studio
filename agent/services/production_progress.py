"""Persistent, stage-based progress for Production Jobs."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.db.schema import get_db

STAGES = [
    ("SCRIPT", "Đọc và chuẩn hóa kịch bản"),
    ("VOICE", "Tạo voice-over"),
    ("FOOTAGE", "Chọn footage cho từng cảnh"),
    ("TIMELINE", "Cắt và dựng timeline"),
    ("BRANDING", "Chèn nhạc và logo"),
    ("SUBTITLES", "Tạo và chèn phụ đề"),
    ("RENDER", "Render video thành phẩm"),
    ("CAPCUT_EXPORT", "Tạo draft CapCut chỉnh sửa"),
    ("DRIVE_EXPORT", "Upload Google Drive OUTPUT"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _initial_stages() -> list[dict]:
    return [{"key": key, "name": name, "status": "COMPLETED" if key == "SCRIPT" else "PENDING"}
            for key, name in STAGES]


async def initialize_production_progress(job_id: str) -> dict:
    now = _now(); stages = _initial_stages()
    state = {"production_job_id": job_id, "status": "QUEUED", "stage": "VOICE",
             "message": "Đã tạo Job và snapshot kịch bản; chờ tạo voice-over", "percent": 12,
             "stages": stages, "logs": [{"time": now, "stage": "SCRIPT",
             "message": "Đã snapshot kịch bản, scene và Video Rule"}],
             "error": None, "started_at": now, "updated_at": now}
    await _save(state)
    return state


async def _save(state: dict) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO production_job_progress(production_job_id,status,stage,message,percent,stages_json,logs_json,error,started_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(production_job_id) DO UPDATE SET
           status=excluded.status,stage=excluded.stage,message=excluded.message,percent=excluded.percent,
           stages_json=excluded.stages_json,logs_json=excluded.logs_json,error=excluded.error,
           started_at=excluded.started_at,updated_at=excluded.updated_at""",
        (state["production_job_id"], state["status"], state["stage"], state["message"],
         state["percent"], json.dumps(state["stages"], ensure_ascii=False),
         json.dumps(state["logs"][-200:], ensure_ascii=False), state.get("error"),
         state["started_at"], state["updated_at"]))
    await db.commit()


async def get_production_progress(job_id: str) -> dict | None:
    db = await get_db()
    row = await (await db.execute("SELECT * FROM production_job_progress WHERE production_job_id=?", (job_id,))).fetchone()
    if not row:
        return None
    result = dict(row)
    result["stages"] = json.loads(result.pop("stages_json") or "[]")
    result["logs"] = json.loads(result.pop("logs_json") or "[]")
    return result


async def update_production_progress(job_id: str, stage: str, status: str, message: str,
                                     percent: int | None = None, error: str | None = None) -> dict:
    state = await get_production_progress(job_id) or await initialize_production_progress(job_id)
    keys = [key for key, _ in STAGES]
    if stage not in keys:
        raise ValueError(f"Unknown production stage: {stage}")
    stage_index = keys.index(stage)
    for index, item in enumerate(state["stages"]):
        if index < stage_index and item["status"] == "PENDING": item["status"] = "COMPLETED"
        if item["key"] == stage: item["status"] = status
    completed = sum(item["status"] == "COMPLETED" for item in state["stages"])
    state.update({"stage": stage, "status": "FAILED" if status == "FAILED" else
                  ("COMPLETED" if completed == len(STAGES) else "RUNNING"),
                  "message": message, "percent": max(0, min(100, percent if percent is not None else round(completed / len(STAGES) * 100))),
                  "error": error, "updated_at": _now()})
    state["logs"].append({"time": state["updated_at"], "stage": stage, "message": message})
    await _save(state)
    return state


async def ensure_production_progress() -> int:
    """Backfill progress rows for Production Jobs created before this tracker."""
    db = await get_db()
    rows = await (await db.execute(
        """SELECT j.id FROM production_jobs j LEFT JOIN production_job_progress p
           ON p.production_job_id=j.id WHERE p.production_job_id IS NULL""")).fetchall()
    for row in rows:
        await initialize_production_progress(row[0])
    return len(rows)


async def cancel_production_progress(job_id: str, reason: str = "Người dùng đã hủy làm video") -> dict:
    state = await get_production_progress(job_id) or await initialize_production_progress(job_id)
    for item in state["stages"]:
        if item["key"] == state["stage"] and item["status"] in {"PENDING", "PROCESSING"}:
            item["status"] = "CANCELLED"
    now = _now()
    state.update({"status": "CANCELLED", "message": reason, "error": None, "updated_at": now})
    state["logs"].append({"time": now, "stage": state["stage"], "message": reason})
    await _save(state)
    return state
