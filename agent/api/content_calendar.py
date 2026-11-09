"""Production profiles, video scripts, jobs, and production calendar API."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.db import crud
from agent.services.content_planning import (
    create_rule, list_rules, sync_rules,
)
from agent.services.video_planning import (
    create_production_job, list_video_topics, production_calendar, sync_spreadsheet,
)
from agent.services.drive_output_export import (
    DriveExportError, approve_production_job, export_production_job,
)
from agent.services.video_footage_pipeline import (
    classification_status, classify_video_footage, start_video_footage_classification,
)

router = APIRouter(tags=["content-calendar"])


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


class ProductionJobApprove(BaseModel):
    output_path: str | None = None


async def _profile(profile_id: str) -> dict:
    profile = await crud.get_production_profile(profile_id)
    if not profile: raise HTTPException(404, "Production profile not found")
    return profile


async def _prepare_topic_footage(video_topic_id: str) -> None:
    from agent.services.video_planning import _rows
    topics = await _rows("SELECT footage_folder_url,footage_status FROM video_topics WHERE id=?", (video_topic_id,))
    if topics and topics[0].get("footage_folder_url") and topics[0].get("footage_status") != "READY":
        await classify_video_footage(video_topic_id)


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
                            "rule": await sync_rules(profile), "videos": await sync_spreadsheet(profile)})
        except Exception as exc:
            results.append({"profile_id": profile["id"], "ok": False, "error": str(exc)})
    return {"results": results}


@router.get("/topics")
async def get_topics(all: bool = False):
    return await list_video_topics(all)


@router.get("/video-topics")
async def get_video_topics(all: bool = False):
    return await list_video_topics(all)


@router.post("/video-topics/{video_topic_id}/classify-footage")
async def classify_topic_footage(video_topic_id: str):
    try:
        return await start_video_footage_classification(video_topic_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Footage classification failed: {exc}") from exc


@router.get("/video-topics/{video_topic_id}/classification-status")
async def get_topic_classification_status(video_topic_id: str):
    return classification_status(video_topic_id)


@router.post("/posts", status_code=201)
async def add_post(body: PostCreate):
    profile = await _profile(body.profile_id)
    if not body.topic_id: raise HTTPException(400, "video_topic_id is required")
    try:
        await _prepare_topic_footage(body.topic_id)
        return await create_production_job(profile, body.topic_id, body.date, body.time)
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
        await _prepare_topic_footage(body.video_topic_id)
        return await create_production_job(profile, body.video_topic_id, body.production_date, body.scheduled_time)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Footage preparation failed: {exc}") from exc


@router.get("/production-jobs")
async def get_production_jobs():
    return await get_posts()


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
