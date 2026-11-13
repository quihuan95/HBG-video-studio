"""Reference video breakdown API backed by the pinned rea-video sidecar."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.services import rea_video_adapter as service

router = APIRouter(prefix="/video-analyses", tags=["video-analyses"])
_tasks: dict[str, asyncio.Task] = {}


class AnalysisCreate(BaseModel):
    source_asset_id: str
    title: str | None = Field(None, max_length=300)
    purpose: str = Field("complete", pattern=r"^(editing_style|shot_structure|captions|music|complete)$")
    language: str = Field("vi", pattern=r"^(vi|en|zh)$")
    use_vlm: bool = False


class ReviewUpdate(BaseModel):
    reviewer_status: str = Field(pattern=r"^(ACCEPTED|NEEDS_REVIEW|REJECTED)$")
    reviewer_notes: str | None = Field(None, max_length=4000)
    production_method: str | None = None
    reference_start_seconds: float | None = None
    reference_end_seconds: float | None = None


def _start(analysis_id: str):
    existing = _tasks.get(analysis_id)
    if existing and not existing.done(): return
    task = asyncio.create_task(service.run_analysis(analysis_id), name=f"rea-video-{analysis_id}")
    _tasks[analysis_id] = task
    task.add_done_callback(lambda _: _tasks.pop(analysis_id, None))


@router.get("/status")
async def status(): return service.runtime_status()


@router.post("", status_code=202)
async def create(body: AnalysisCreate):
    try: analysis = await service.create_analysis(**body.model_dump())
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    _start(analysis["id"]); return analysis


@router.get("/{analysis_id}")
async def detail(analysis_id: str):
    try: return await service.get_analysis(analysis_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc


@router.post("/{analysis_id}/retry", status_code=202)
async def retry(analysis_id: str):
    try: analysis = await service.get_analysis(analysis_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    if analysis["status"] == "PROCESSING": raise HTTPException(409, "Analysis is already processing")
    db = await service.get_db(); await db.execute("UPDATE video_analyses SET status='QUEUED',progress=0 WHERE id=?", (analysis_id,)); await db.commit()
    _start(analysis_id); return {"id": analysis_id, "status": "QUEUED"}


@router.patch("/{analysis_id}/shots/{shot_id}/review")
async def review(analysis_id: str, shot_id: str, body: ReviewUpdate):
    try: return await service.review_shot(analysis_id, shot_id, body.reviewer_status, body.reviewer_notes,
                                          body.production_method, body.reference_start_seconds, body.reference_end_seconds)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.post("/{analysis_id}/shots/{shot_id}/search-brief", status_code=201)
async def search_brief(analysis_id: str, shot_id: str):
    try: return await service.create_search_brief(analysis_id, shot_id)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/{analysis_id}/artifacts/{kind}")
async def artifact(analysis_id: str, kind: str):
    analysis = await detail(analysis_id)
    mapping = {"report": analysis.get("report_html_path"), "storyboard": analysis.get("storyboard_path"),
               "breakdown": analysis.get("breakdown_path")}
    value = mapping.get(kind)
    if not value or not Path(value).is_file(): raise HTTPException(404, "Artifact not found")
    media = {"report": "text/html", "storyboard": "image/jpeg", "breakdown": "application/json"}[kind]
    # HTML is served as an attachment, never embedded into the privileged app origin.
    disposition = "attachment" if kind == "report" else "inline"
    return FileResponse(value, media_type=media, headers={"Content-Disposition": f'{disposition}; filename="{Path(value).name}"'})


@router.get("/{analysis_id}/shots/{shot_id}/thumbnail")
async def thumbnail(analysis_id: str, shot_id: str):
    shots = await service._rows("SELECT thumbnail_path FROM reference_video_shots WHERE id=? AND analysis_id=?", (shot_id, analysis_id))
    if not shots or not shots[0].get("thumbnail_path") or not Path(shots[0]["thumbnail_path"]).is_file():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(shots[0]["thumbnail_path"], media_type="image/jpeg")


@router.get("/{analysis_id}/export")
async def export(analysis_id: str):
    try: archive = await service.export_analysis(analysis_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    return FileResponse(archive, media_type="application/zip", filename=f"REA_Analysis_{analysis_id[:8]}.zip")
