"""Production profiles and footage library API."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from agent.db import crud
from agent.models.production import (
    FootageAsset, FootageSource, FootageSourceCreate,
    ProductionProfile, ProductionProfileCreate, ProductionProfileUpdate,
)
from agent.services.footage_scanner import scan_source
from agent.services.footage_analyzer import analyze_footage

router = APIRouter(tags=["production"])


def _profile(row: dict) -> ProductionProfile:
    data = dict(row)
    data["rules"] = json.loads(data.pop("rules_json") or "{}")
    data["active"] = bool(data.get("active", 1))
    data["retain_removed_posts"] = bool(data.get("retain_removed_posts", 1))
    return ProductionProfile.model_validate(data)


def _source(row: dict) -> FootageSource:
    data = dict(row)
    data["recursive"] = bool(data["recursive"])
    data["enabled"] = bool(data["enabled"])
    return FootageSource.model_validate(data)


def _asset(row: dict) -> FootageAsset:
    data = dict(row)
    data["tags"] = json.loads(data.pop("tags_json") or "[]")
    data["usable_ranges"] = json.loads(data.pop("usable_ranges_json") or "[]")
    raw_analysis = data.pop("analysis_json")
    data["analysis"] = json.loads(raw_analysis) if raw_analysis else None
    if data.get("has_dialogue") is not None:
        data["has_dialogue"] = bool(data["has_dialogue"])
    return FootageAsset.model_validate(data)


@router.post("/profiles", response_model=ProductionProfile, status_code=201)
async def create_profile(body: ProductionProfileCreate):
    data = body.model_dump(exclude={"rules"})
    data["rules_json"] = body.rules.model_dump_json()
    data["active"] = int(body.active)
    data["retain_removed_posts"] = int(body.retain_removed_posts)
    return _profile(await crud.create_production_profile(**data))


@router.get("/profiles", response_model=list[ProductionProfile])
async def list_profiles():
    return [_profile(row) for row in await crud.list_production_profiles()]


@router.get("/profiles/{profile_id}", response_model=ProductionProfile)
async def get_profile(profile_id: str):
    row = await crud.get_production_profile(profile_id)
    if not row:
        raise HTTPException(404, "Production profile not found")
    return _profile(row)


@router.patch("/profiles/{profile_id}", response_model=ProductionProfile)
async def update_profile(profile_id: str, body: ProductionProfileUpdate):
    if not await crud.get_production_profile(profile_id):
        raise HTTPException(404, "Production profile not found")
    data = body.model_dump(exclude_unset=True, exclude={"rules"})
    for key in ("active", "retain_removed_posts"):
        if key in data:
            data[key] = int(data[key])
    if body.rules is not None:
        data["rules_json"] = body.rules.model_dump_json()
    return _profile(await crud.update_production_profile(profile_id, **data))


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    if not await crud.delete_production_profile(profile_id):
        raise HTTPException(404, "Production profile not found")
    return {"ok": True}


@router.post("/profiles/{profile_id}/footage-sources", response_model=FootageSource, status_code=201)
async def add_source(profile_id: str, body: FootageSourceCreate):
    if not await crud.get_production_profile(profile_id):
        raise HTTPException(404, "Production profile not found")
    return _source(await crud.create_footage_source(profile_id, **body.model_dump()))


@router.get("/profiles/{profile_id}/footage-sources", response_model=list[FootageSource])
async def list_sources(profile_id: str):
    return [_source(row) for row in await crud.list_footage_sources(profile_id)]


@router.delete("/footage-sources/{source_id}")
async def delete_source(source_id: str):
    if not await crud.delete_footage_source(source_id):
        raise HTTPException(404, "Footage source not found")
    return {"ok": True}


@router.post("/footage-sources/{source_id}/scan")
async def scan(source_id: str):
    source = await crud.get_footage_source(source_id)
    if not source:
        raise HTTPException(404, "Footage source not found")
    try:
        assets = await scan_source(source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Footage scan failed: {exc}") from exc
    await crud.update_footage_source(
        source_id, last_scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {"source_id": source_id, "discovered": len(assets), "assets": [_asset(row) for row in assets]}


@router.get("/profiles/{profile_id}/footage", response_model=list[FootageAsset])
async def list_footage(profile_id: str, status: str | None = Query(None)):
    return [_asset(row) for row in await crud.list_footage_assets(profile_id, status)]


@router.post("/footage/{asset_id}/analyze", response_model=FootageAsset)
async def analyze(asset_id: str):
    asset = await crud.get_footage_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Footage asset not found")
    profile = await crud.get_production_profile(asset["profile_id"])
    try:
        return _asset(await analyze_footage(asset_id, profile))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"OpenAI footage analysis failed: {exc}") from exc
