"""AI footage research API."""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from agent import config
from agent.db import crud
from agent.services import footage_research as service
from agent.services import youtube_footage

router = APIRouter(prefix="/footage-research", tags=["footage-research"])
_tasks: set[asyncio.Task] = set()


class JobCreate(BaseModel):
    profile_id: str | None = None
    script_text: str = Field(min_length=1, max_length=100_000)
    target_duration_seconds: float = Field(60, ge=5, le=600)
    aspect_ratio: str = Field("9:16", pattern=r"^(9:16|16:9|1:1)$")
    source_preference: str = Field("internal_first", pattern=r"^(internal_first|mixed|external_only)$")


class ShotUpdate(BaseModel):
    script_excerpt: str | None = None
    visual_description: str | None = None
    keywords_vi: list[str] | None = None
    keywords_en: list[str] | None = None
    notes: str | None = None


class SelectionUpdate(BaseModel):
    candidate_id: str
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    editor_note: str | None = None


@router.get("/status")
async def provider_status():
    return {"enabled": config.FOOTAGE_SEARCH_ENABLED,
            "internal": "READY" if config.FOOTAGE_INTERNAL_ENABLED else "DISABLED",
            "pexels": "READY" if config.FOOTAGE_EXTERNAL_ENABLED and config.PEXELS_API_KEY else "NOT_CONFIGURED",
            "youtube": "READY" if youtube_footage.available() else "DISABLED",
            "youtube_cc_only": config.YOUTUBE_CC_ONLY}


@router.post("/jobs", status_code=201)
async def create_job(body: JobCreate):
    if body.profile_id and not await crud.get_production_profile(body.profile_id):
        raise HTTPException(404, "Production profile not found")
    try:
        return await service.create_job(body.profile_id, body.script_text, body.target_duration_seconds,
                                        body.aspect_ratio, body.source_preference)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    try: return await service.get_job(job_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc


@router.post("/jobs/{job_id}/analyze")
async def analyze(job_id: str):
    try: return await service.analyze_job(job_id)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Script analysis failed: {exc}") from exc


@router.patch("/shots/{shot_id}")
async def update_shot(shot_id: str, body: ShotUpdate):
    data = body.model_dump(exclude_unset=True); assignments = []; values = []
    mapping = {"keywords_vi": "keywords_vi_json", "keywords_en": "keywords_en_json"}
    import json
    for key, value in data.items():
        column = mapping.get(key, key); assignments.append(f"{column}=?")
        values.append(json.dumps(value, ensure_ascii=False) if key in mapping else value)
    if not assignments: raise HTTPException(400, "No changes supplied")
    db = await service.get_db(); values.append(shot_id)
    cur = await db.execute(f"UPDATE footage_research_shots SET {','.join(assignments)} WHERE id=?", values); await db.commit()
    if not cur.rowcount: raise HTTPException(404, "Shot not found")
    return {"ok": True, "shot_id": shot_id}


@router.post("/jobs/{job_id}/search", status_code=202)
async def search(job_id: str):
    try: await service.get_job(job_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    task = asyncio.create_task(service.search_job(job_id), name=f"footage-search-{job_id}")
    _tasks.add(task); task.add_done_callback(_tasks.discard)
    return {"job_id": job_id, "status": "SEARCHING"}


@router.get("/shots/{shot_id}/candidates")
async def candidates(shot_id: str):
    return await service._rows("SELECT * FROM footage_research_candidates WHERE shot_id=? ORDER BY selected DESC,fit_score DESC", (shot_id,))


@router.patch("/shots/{shot_id}/selection")
async def select(shot_id: str, body: SelectionUpdate):
    try: return await service.select_candidate(shot_id, body.candidate_id, body.source_start_seconds,
                                               body.source_end_seconds, body.editor_note)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/jobs/{job_id}/export")
async def export(job_id: str, format: str = "json"):
    if format not in {"json", "csv"}: raise HTTPException(400, "format must be csv or json")
    try: content, media_type = await service.export_shotlist(job_id, format)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="shotlist.{format}"'})


@router.get("/jobs/{job_id}/export-media")
@router.post("/jobs/{job_id}/export-media")
async def export_media(job_id: str):
    try: archive = await service.export_media_package(job_id)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Media export failed: {exc}") from exc
    return FileResponse(archive, filename=f"TheHBG_Footage_{job_id[:8]}.zip", media_type="application/zip")
