"""Per-video Drive footage discovery, OpenAI classification, and organization."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

from agent.db import crud
from agent.db.schema import get_db
from agent.services.footage_analyzer import analyze_footage
from agent.services.footage_scanner import drive_folder_id, scan_google_drive
from agent.services.google_oauth import get_valid_access_token

CLASSIFIED_FOLDER = "_AI_CLASSIFIED"
ProgressCallback = Callable[[str, str, int, int], Awaitable[None]]
_classification_runs: dict[str, dict] = {}
_classification_tasks: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _category_folder(value: str | None) -> str:
    value = re.sub(r"[/\\\x00-\x1f]+", " - ", (value or "uncategorized").strip())
    return re.sub(r"\s+", " ", value).strip(" .")[:80] or "uncategorized"


async def _source_for_topic(topic: dict) -> dict:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM footage_source WHERE video_topic_id=?", (topic["id"],))
    row = await cursor.fetchone()
    if row:
        source = dict(row)
        if source["location"] != topic["footage_folder_url"]:
            source = await crud.update_footage_source(source["id"], location=topic["footage_folder_url"])
        return source
    return await crud.create_footage_source(
        topic["profile_id"], "google_drive", f"Footage - {topic['source_tab_name']}",
        topic["footage_folder_url"], recursive=False, video_topic_id=topic["id"])


def _organize_files_sync(root_folder_id: str, items: list[dict], access_token: str) -> dict[str, str]:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=Credentials(token=access_token), cache_discovery=False)

    def folder(parent: str, name: str) -> str:
        escaped_name = name.replace("'", "\\'")
        escaped_parent = parent.replace("'", "\\'")
        response = service.files().list(
            q=f"'{escaped_parent}' in parents and name='{escaped_name}' and "
              "mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id)", pageSize=10, supportsAllDrives=True,
            includeItemsFromAllDrives=True).execute()
        if response.get("files"):
            return response["files"][0]["id"]
        return service.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]},
            fields="id", supportsAllDrives=True).execute()["id"]

    classified_id = folder(root_folder_id, CLASSIFIED_FOLDER)
    category_ids: dict[str, str] = {}
    moved: dict[str, str] = {}
    for item in items:
        category = _category_folder(item.get("category"))
        if category not in category_ids:
            category_ids[category] = folder(classified_id, category)
        category_id = category_ids[category]
        metadata = service.files().get(fileId=item["external_id"], fields="parents", supportsAllDrives=True).execute()
        parents = metadata.get("parents", [])
        if category_id not in parents:
            service.files().update(
                fileId=item["external_id"], addParents=category_id,
                removeParents=",".join(parents), fields="id,parents", supportsAllDrives=True).execute()
        moved[item["external_id"]] = category
    return moved


async def classify_video_footage(video_topic_id: str) -> dict:
    return await _classify_video_footage(video_topic_id)


async def _classify_video_footage(video_topic_id: str, progress: ProgressCallback | None = None) -> dict:
    async def emit(stage: str, message: str, current: int = 0, total: int = 0):
        if progress:
            await progress(stage, message, current, total)

    await emit("INITIALIZING", "Đang đọc cấu hình video và folder footage")
    db = await get_db()
    cursor = await db.execute("SELECT * FROM video_topics WHERE id=?", (video_topic_id,))
    row = await cursor.fetchone()
    if not row:
        raise ValueError("Video Topic not found")
    topic = dict(row)
    if not topic.get("footage_folder_url"):
        raise ValueError("Video tab has no footage folder URL in row 3")
    profile = await crud.get_production_profile(topic["profile_id"])
    folder_id = drive_folder_id(topic["footage_folder_url"])
    await db.execute("UPDATE video_topics SET footage_folder_id=?,footage_status='ANALYZING',footage_error=NULL,updated_at=? WHERE id=?",
                     (folder_id, _now(), video_topic_id))
    await db.commit()
    try:
        source = await _source_for_topic(topic)
        await emit("SCANNING", "Đang quét các file video trong Google Drive")
        await scan_google_drive(source)
        assets = await crud.list_footage_assets(topic["profile_id"])
        assets = [item for item in assets if item["source_id"] == source["id"]]
        await emit("ANALYZING", f"Tìm thấy {len(assets)} clip footage", 0, len(assets))
        errors = []
        analyzed = []
        for index, asset in enumerate(assets, start=1):
            try:
                await emit("ANALYZING", f"Đang phân tích {asset['file_name']}", index - 1, len(assets))
                result = asset if asset["status"] == "READY" else await analyze_footage(asset["id"], profile)
                analyzed.append(result)
                await emit("ANALYZING", f"Đã phân loại {asset['file_name']} → {_category_folder(result.get('category'))}", index, len(assets))
            except Exception as exc:
                errors.append({"asset_id": asset["id"], "file_name": asset["file_name"], "error": str(exc)})
                await emit("ANALYZING", f"Lỗi {asset['file_name']}: {exc}", index, len(assets))
        if analyzed:
            await emit("ORGANIZING", f"Đang chuyển {len(analyzed)} clip vào {CLASSIFIED_FOLDER}", len(analyzed), len(assets))
            token = await get_valid_access_token()
            await asyncio.to_thread(_organize_files_sync, folder_id, analyzed, token)
        status = "READY" if not errors else ("PARTIAL" if analyzed else "FAILED")
        await db.execute("UPDATE video_topics SET footage_status=?,footage_error=?,updated_at=? WHERE id=?",
                         (status, None if not errors else str(errors)[:4000], _now(), video_topic_id))
        await crud.update_footage_source(source["id"], last_scanned_at=_now())
        await db.commit()
        await emit("COMPLETED", f"Hoàn tất: {len(analyzed)}/{len(assets)} clip đã phân loại", len(analyzed), len(assets))
        return {"video_topic_id": video_topic_id, "folder_id": folder_id,
                "discovered": len(assets), "classified": len(analyzed), "status": status, "errors": errors}
    except Exception as exc:
        await db.execute("UPDATE video_topics SET footage_status='FAILED',footage_error=?,updated_at=? WHERE id=?",
                         (str(exc)[:4000], _now(), video_topic_id))
        await db.commit()
        await emit("FAILED", f"Phân loại thất bại: {exc}")
        raise


def classification_status(video_topic_id: str) -> dict:
    return _classification_runs.get(video_topic_id, {
        "video_topic_id": video_topic_id, "status": "IDLE", "stage": "IDLE",
        "message": "Chưa chạy phân loại", "current": 0, "total": 0, "logs": [],
    })


async def start_video_footage_classification(video_topic_id: str) -> dict:
    task = _classification_tasks.get(video_topic_id)
    if task and not task.done():
        return classification_status(video_topic_id)
    started_at = _now()
    state = {"video_topic_id": video_topic_id, "status": "RUNNING", "stage": "QUEUED",
             "message": "Đã xếp hàng phân loại footage", "current": 0, "total": 0,
             "started_at": started_at, "updated_at": started_at, "logs": []}
    _classification_runs[video_topic_id] = state

    async def progress(stage: str, message: str, current: int, total: int):
        now = _now()
        state.update({"stage": stage, "message": message, "current": current,
                      "total": total, "updated_at": now})
        state["logs"].append({"time": now, "stage": stage, "message": message})
        state["logs"] = state["logs"][-100:]

    async def run():
        try:
            result = await _classify_video_footage(video_topic_id, progress)
            state.update({"status": "COMPLETED", "result": result, "updated_at": _now()})
        except Exception as exc:
            state.update({"status": "FAILED", "stage": "FAILED", "message": str(exc),
                          "error": str(exc), "updated_at": _now()})

    _classification_tasks[video_topic_id] = asyncio.create_task(run())
    return state
