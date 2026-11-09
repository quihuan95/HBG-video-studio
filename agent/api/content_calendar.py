"""Profile rules, TOPICS plan, posts and merged content calendar API."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.db import crud
from agent.services.content_planning import (
    calendar_items, create_post, create_rule, fetch_and_sync_topics,
    list_rules, sync_rules,
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


async def _profile(profile_id: str) -> dict:
    profile = await crud.get_production_profile(profile_id)
    if not profile: raise HTTPException(404, "Production profile not found")
    return profile


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
        topics = await fetch_and_sync_topics(profile)
        return {"profile_id": profile_id, "rule": rule, "topics": topics}
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Google sync failed: {exc}") from exc


@router.post("/profiles/sync-all")
async def sync_all_profiles():
    results = []
    for profile in await crud.list_production_profiles():
        if not profile.get("active") or not (profile.get("sheet_id_topics") or profile.get("sheet_url")): continue
        try:
            results.append({"profile_id": profile["id"], "ok": True,
                            "rule": await sync_rules(profile), "topics": await fetch_and_sync_topics(profile)})
        except Exception as exc:
            results.append({"profile_id": profile["id"], "ok": False, "error": str(exc)})
    return {"results": results}


@router.get("/topics")
async def get_topics(all: bool = False):
    from agent.services.content_planning import _rows
    where = "" if all else " WHERE t.status='READY'"
    return await _rows("SELECT t.*,p.name profile_name,p.color FROM topics t JOIN production_profile p ON p.id=t.profile_id" + where + " ORDER BY content_date,publish_time")


@router.post("/posts", status_code=201)
async def add_post(body: PostCreate):
    profile = await _profile(body.profile_id)
    try: return await create_post(profile, body.topic_id, body.date, body.time, body.creation_source)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/posts")
async def get_posts():
    from agent.services.content_planning import _rows
    return await _rows("SELECT p.*,pr.name profile_name,pr.color FROM posts p JOIN production_profile pr ON pr.id=p.profile_id ORDER BY content_date,scheduled_time")


@router.get("/calendar")
async def get_calendar():
    return await calendar_items()
