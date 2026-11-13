"""Production profiles, video scripts, jobs, and production calendar API."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from agent.db import crud
from agent import config
from agent.db.schema import get_db
from agent.services.content_planning import (
    create_rule, list_rules, sync_rules,
)
from agent.services.video_planning import (
    create_production_job, delete_production_job, list_video_topics, production_calendar, sync_spreadsheet,
)
from agent.services.drive_output_export import (
    DriveExportError, approve_production_job, export_production_job,
)
from agent.services.video_footage_pipeline import (
    classification_status, classify_video_footage, start_video_footage_classification,
)

router = APIRouter(tags=["content-calendar"])
_capcut_regenerating: set[str] = set()


class RuleCreate(BaseModel):
    content: str = Field(min_length=1)
    publish_config: dict = Field(default_factory=dict)


class PostCreate(BaseModel):
    profile_id: str
    topic_id: str | None = None
    date: str | None = None
    time: str | None = None
    creation_source: str = "manual"


class ProductionJobCreate(BaseModel):
    profile_id: str
    video_topic_id: str
    production_date: str | None = None
    scheduled_time: str | None = None
    footage_mode: Literal["DRIVE_ONLY", "INTERNET_ONLY", "HYBRID"] = "HYBRID"


class ProductionJobApprove(BaseModel):
    output_path: str | None = None


class ScheduleUpdate(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")


class ReferenceAnalysisLink(BaseModel):
    analysis_id: str | None = None


async def _profile(profile_id: str) -> dict:
    profile = await crud.get_production_profile(profile_id)
    if not profile: raise HTTPException(404, "Production profile not found")
    return profile


async def _prepare_topic_footage(video_topic_id: str) -> None:
    """Refresh the topic Drive folder; Internet is only the fallback source."""
    from agent.services import youtube_footage
    from agent.services.video_footage_pipeline import classify_video_footage
    from agent.services.video_planning import _rows
    topics = await _rows("SELECT * FROM video_topics WHERE id=?", (video_topic_id,))
    if not topics:
        raise ValueError("Video Topic not found")
    if topics[0].get("footage_folder_url"):
        await classify_video_footage(video_topic_id)
        return
    if not (youtube_footage.available() or (config.FOOTAGE_EXTERNAL_ENABLED and config.PEXELS_API_KEY)):
        raise ValueError("Chưa có nguồn footage Internet: bật YOUTUBE_FOOTAGE_ENABLED hoặc cấu hình PEXELS_API_KEY")


@router.get("/profiles/{profile_id}/rules")
async def get_rules(profile_id: str):
    await _profile(profile_id)
    return await list_rules(profile_id)


@router.post("/profiles/{profile_id}/rules", status_code=201)
async def add_rule(profile_id: str, body: RuleCreate):
    await _profile(profile_id)
    try: return await create_rule(profile_id, body.content, body.publish_config)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.post("/profiles/{profile_id}/sync-sheet")
async def sync_profile(profile_id: str):
    profile = await _profile(profile_id)
    try:
        rule = await sync_rules(profile)
        videos = await sync_spreadsheet(profile)
        return {"profile_id": profile_id, "rule": rule, "videos": videos}
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Google sync failed: {exc}") from exc


@router.post("/profiles/sync-all")
async def sync_all_profiles():
    results = []
    for profile in await crud.list_production_profiles():
        if not profile.get("active") or not (profile.get("sheet_id_topics") or profile.get("sheet_url")): continue
        try:
            results.append({"profile_id": profile["id"], "ok": True,
                            "rule": await sync_rules(profile),
                            "videos": await sync_spreadsheet(profile)})
        except Exception as exc:
            results.append({"profile_id": profile["id"], "ok": False, "error": str(exc)})
    return {"results": results}


@router.get("/topics")
async def get_topics(all: bool = False):
    return await list_video_topics(all)


@router.get("/video-topics")
async def get_video_topics(all: bool = False):
    return await list_video_topics(all)


@router.patch("/video-topics/{video_topic_id}/schedule")
async def schedule_video_topic(video_topic_id: str, body: ScheduleUpdate):
    from agent.services.video_planning import _rows
    db = await get_db()
    cursor = await db.execute("UPDATE video_topics SET production_date=?,scheduled_time=?,updated_at=? WHERE id=?",
                              (body.date, body.time, datetime.now(timezone.utc).isoformat(), video_topic_id))
    await db.commit()
    if not cursor.rowcount: raise HTTPException(404, "Video Topic not found")
    return (await _rows("SELECT * FROM video_topics WHERE id=?", (video_topic_id,)))[0]


@router.patch("/video-topics/{video_topic_id}/reference-analysis")
async def link_reference_analysis(video_topic_id: str, body: ReferenceAnalysisLink):
    from agent.services.video_planning import _rows
    topics = await _rows("SELECT profile_id FROM video_topics WHERE id=?", (video_topic_id,))
    if not topics:
        raise HTTPException(404, "Video Topic not found")
    if body.analysis_id:
        analyses = await _rows("SELECT profile_id,status FROM video_analyses WHERE id=?", (body.analysis_id,))
        if not analyses:
            raise HTTPException(404, "Reference analysis not found")
        if analyses[0]["status"] != "COMPLETED":
            raise HTTPException(409, "Reference analysis is not completed")
        if analyses[0].get("profile_id") and analyses[0]["profile_id"] != topics[0]["profile_id"]:
            raise HTTPException(400, "Reference analysis belongs to another profile")
    db = await get_db()
    await db.execute("UPDATE video_topics SET reference_analysis_id=?,updated_at=? WHERE id=?",
                     (body.analysis_id, datetime.now(timezone.utc).isoformat(), video_topic_id))
    await db.commit()
    return (await _rows("SELECT * FROM video_topics WHERE id=?", (video_topic_id,)))[0]


@router.post("/video-topics/{video_topic_id}/classify-footage")
async def classify_topic_footage(video_topic_id: str, force: bool = False):
    try:
        return await start_video_footage_classification(video_topic_id, force=force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Footage classification failed: {exc}") from exc


@router.get("/video-topics/{video_topic_id}/classification-status")
async def get_topic_classification_status(video_topic_id: str):
    return await classification_status(video_topic_id)


@router.post("/posts", status_code=201)
async def add_post(body: PostCreate):
    profile = await _profile(body.profile_id)
    if not body.topic_id: raise HTTPException(400, "video_topic_id is required")
    try:
        job = await create_production_job(profile, body.topic_id, body.date, body.time)
        from agent.services.production_orchestrator import start_production_job
        await start_production_job(job["id"])
        return job
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Footage preparation failed: {exc}") from exc


@router.get("/posts")
async def get_posts():
    from agent.services.video_planning import _rows
    return await _rows("SELECT j.*,p.name profile_name,p.color FROM production_jobs j JOIN production_profile p ON p.id=j.profile_id ORDER BY production_date,scheduled_time")


@router.post("/production-jobs", status_code=201)
async def add_production_job(body: ProductionJobCreate):
    profile = await _profile(body.profile_id)
    try:
        job = await create_production_job(
            profile, body.video_topic_id, body.production_date, body.scheduled_time,
            footage_mode=body.footage_mode)
        from agent.services.production_orchestrator import start_production_job
        await start_production_job(job["id"])
        return job
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Footage preparation failed: {exc}") from exc


@router.get("/production-jobs")
async def get_production_jobs():
    return await get_posts()


@router.get("/production-jobs/{job_id}/progress")
async def get_job_progress(job_id: str):
    from agent.services.production_progress import get_production_progress
    progress = await get_production_progress(job_id)
    if not progress:
        raise HTTPException(404, "Production progress not found")
    return progress


@router.post("/production-jobs/{job_id}/regenerate", status_code=202)
async def regenerate_job(job_id: str):
    from agent.services.video_planning import _rows
    jobs = await _rows("SELECT * FROM production_jobs WHERE id=?", (job_id,))
    if not jobs:
        raise HTTPException(404, "Production Job not found")
    job = jobs[0]
    if not job.get("video_topic_id"):
        raise HTTPException(400, "Production Job has no source video topic")
    profile = await _profile(job["profile_id"])
    try:
        regenerated = await create_production_job(
            profile, job["video_topic_id"], job.get("production_date"),
            job.get("scheduled_time"), force=True,
            footage_mode=job.get("footage_mode") or "HYBRID",
        )
        from agent.services.production_orchestrator import start_production_job
        await start_production_job(regenerated["id"])
        return regenerated
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/production-jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    from agent.services.drive_output_export import export_in_progress
    from agent.services.production_progress import cancel_production_progress
    from agent.services.video_planning import _rows
    if export_in_progress(job_id):
        raise HTTPException(409, "Không thể hủy khi video đang upload Google Drive")
    jobs = await _rows("SELECT * FROM production_jobs WHERE id=?", (job_id,))
    if not jobs: raise HTTPException(404, "Production Job not found")
    if jobs[0]["status"] in {"COMPLETED", "READY_FOR_MANUAL_UPLOAD", "MANUALLY_UPLOADED", "ARCHIVED", "CANCELLED"}:
        raise HTTPException(409, f"Không thể hủy Job ở trạng thái {jobs[0]['status']}")
    now = datetime.now(timezone.utc).isoformat(); db = await get_db()
    await db.execute("UPDATE production_jobs SET status='CANCELLED',error_stage=NULL,error_message=NULL,updated_at=? WHERE id=?",
                     (now, job_id))
    await db.execute("INSERT INTO production_audit_events(id,production_job_id,revision_id,action,detail_json,created_at) VALUES(?,?,?,?,?,?)",
                     (str(uuid.uuid4()), job_id, jobs[0].get("current_revision_id"), "CANCEL_PRODUCTION", "{}", now))
    await db.commit()
    from agent.services.production_orchestrator import cancel_running_production
    await cancel_running_production(job_id)
    progress = await cancel_production_progress(job_id)
    return {"success": True, "job_id": job_id, "status": "CANCELLED", "progress": progress}


@router.delete("/production-jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a finished job; the source topic then returns to the create-video list."""
    from agent.services.drive_output_export import export_in_progress
    if export_in_progress(job_id):
        raise HTTPException(409, "Không thể xóa khi video đang upload Google Drive")
    try:
        return await delete_production_job(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/production-jobs/{job_id}/open-capcut")
async def open_job_in_capcut(job_id: str):
    from agent.services.video_planning import _rows
    jobs = await _rows("SELECT capcut_draft_path FROM production_jobs WHERE id=?", (job_id,))
    if not jobs:
        raise HTTPException(404, "Production Job not found")
    draft = Path(jobs[0].get("capcut_draft_path") or "")
    if not draft.is_dir():
        raise HTTPException(404, "CapCut draft chưa được tạo hoặc không còn tồn tại")
    if os.name != "nt":
        raise HTTPException(400, "Mở CapCut tự động hiện chỉ hỗ trợ Windows")
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    capcut = local_app_data / "CapCut" / "Apps" / "CapCut.exe"
    if not capcut.is_file():
        raise HTTPException(404, "Không tìm thấy CapCut Desktop")
    subprocess.Popen([str(capcut)], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    os.startfile(str(draft))
    return {"success": True, "draft_path": str(draft)}


@router.post("/production-jobs/{job_id}/regenerate-capcut")
async def regenerate_capcut_draft(job_id: str):
    from agent.services.capcut_export import export_capcut_draft
    from agent.services.production_progress import update_production_progress
    from agent.services.video_planning import _rows
    rows = await _rows(
        """SELECT j.id,j.title,j.status,j.current_revision_id,r.scenes_json,r.assets_json,
                  p.music_path,p.rules_json,vt.orientation
           FROM production_jobs j JOIN production_revisions r ON r.id=j.current_revision_id
           JOIN production_profile p ON p.id=j.profile_id
           LEFT JOIN video_topics vt ON vt.id=j.video_topic_id WHERE j.id=?""", (job_id,))
    if not rows:
        raise HTTPException(404, "Production Job not found")
    data = rows[0]
    if data["status"] not in {"COMPLETED", "APPROVED", "READY_FOR_MANUAL_UPLOAD", "MANUALLY_UPLOADED"}:
        raise HTTPException(409, f"Chỉ tạo lại draft cho video đã hoàn thành; trạng thái hiện tại: {data['status']}")
    work = config.OUTPUT_DIR / "production_jobs" / job_id / data["current_revision_id"]
    if not work.is_dir():
        raise HTTPException(404, "Không còn file scene/voice cục bộ để tạo lại draft CapCut")
    if job_id in _capcut_regenerating:
        raise HTTPException(409, "Draft CapCut của video này đang được tạo lại")
    _capcut_regenerating.add(job_id)
    try:
        await update_production_progress(job_id, "CAPCUT_EXPORT", "PROCESSING",
                                         "Đang tạo lại draft CapCut", 92)
        scenes = json.loads(data["scenes_json"] or "[]")
        rules = json.loads(data.get("rules_json") or "{}")
        draft = await export_capcut_draft(
            job_id, data.get("title") or "Video", work, scenes, data.get("orientation") or "HORIZONTAL",
            data.get("music_path"), float(rules.get("music_volume", .106)), replace=True,
        )
        assets = json.loads(data.get("assets_json") or "{}")
        assets["capcut_draft_path"] = str(draft)
        db = await get_db()
        await db.execute("UPDATE production_revisions SET assets_json=? WHERE id=?",
                         (json.dumps(assets, ensure_ascii=False), data["current_revision_id"]))
        await db.execute("UPDATE production_jobs SET capcut_draft_path=?,capcut_error=NULL,updated_at=? WHERE id=?",
                         (str(draft), datetime.now(timezone.utc).isoformat(), job_id))
        await db.commit()
        await update_production_progress(job_id, "CAPCUT_EXPORT", "COMPLETED",
                                         "Đã tạo lại draft CapCut", 100)
        return {"success": True, "job_id": job_id, "draft_path": str(draft)}
    except Exception as exc:
        db = await get_db()
        await db.execute("UPDATE production_jobs SET capcut_error=? WHERE id=?", (str(exc)[:2000], job_id))
        await db.commit()
        await update_production_progress(job_id, "CAPCUT_EXPORT", "FAILED",
                                         f"Tạo lại draft CapCut thất bại: {exc}", 100,
                                         error=str(exc))
        raise HTTPException(502, f"Tạo lại draft CapCut thất bại: {exc}") from exc
    finally:
        _capcut_regenerating.discard(job_id)


@router.patch("/production-jobs/{job_id}/schedule")
async def schedule_job(job_id: str, body: ScheduleUpdate):
    from agent.services.video_planning import _rows
    db = await get_db()
    cursor = await db.execute("UPDATE production_jobs SET production_date=?,scheduled_time=?,updated_at=? WHERE id=?",
                              (body.date, body.time, datetime.now(timezone.utc).isoformat(), job_id))
    await db.commit()
    if not cursor.rowcount: raise HTTPException(404, "Production Job not found")
    return (await _rows("SELECT * FROM production_jobs WHERE id=?", (job_id,)))[0]


def _export_http_error(exc: DriveExportError) -> HTTPException:
    if exc.code in {"EXPORT_IN_PROGRESS", "EXPORT_REVISION_CONFLICT"}:
        status = 409
    elif exc.code in {"JOB_NOT_FOUND", "REVISION_NOT_FOUND"}:
        status = 404
    elif exc.code in {"JOB_NOT_APPROVED", "VIDEO_FILE_MISSING", "ASSETS_INVALID"}:
        status = 400
    else:
        status = 502
    return HTTPException(status, detail={"code": exc.code, "message": str(exc)})


@router.post("/production-jobs/{job_id}/approve")
async def approve_job(job_id: str, body: ProductionJobApprove):
    try:
        job = await approve_production_job(job_id, body.output_path)
        exported = await export_production_job(job_id)
        return {"job": job, "export": exported}
    except DriveExportError as exc:
        raise _export_http_error(exc) from exc
    except Exception as exc:
        raise HTTPException(502, f"Google Drive export failed: {exc}") from exc


@router.post("/production-jobs/{job_id}/export")
async def export_job(job_id: str):
    try:
        return await export_production_job(job_id)
    except DriveExportError as exc:
        raise _export_http_error(exc) from exc
    except Exception as exc:
        raise HTTPException(502, f"Google Drive export failed: {exc}") from exc


@router.get("/production-jobs/{job_id}/exports")
async def get_job_exports(job_id: str):
    from agent.services.video_planning import _rows
    return await _rows("SELECT * FROM production_exports WHERE production_job_id=? ORDER BY exported_at DESC", (job_id,))


@router.get("/calendar")
async def get_calendar():
    return await production_calendar()


@router.get("/production-calendar")
async def get_production_calendar():
    return await production_calendar()
