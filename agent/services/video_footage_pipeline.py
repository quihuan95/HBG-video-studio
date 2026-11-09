"""Per-video Drive footage discovery, OpenAI classification, and organization."""
from __future__ import annotations

import asyncio
import io
import json
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


def _organize_files_sync(root_folder_id: str, items: list[dict], access_token: str) -> dict:
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

    def parsed(value: str | None, fallback):
        try:
            return json.loads(value) if value else fallback
        except ValueError:
            return fallback

    catalog = {
        "schema_version": 1,
        "generated_at": _now(),
        "source_folder_id": root_folder_id,
        "classified_folder_id": classified_id,
        "total_files": len(items),
        "files": [{
            "file_id": item.get("external_id"), "file_name": item.get("file_name"),
            "category": _category_folder(item.get("category")), "summary": item.get("summary"),
            "tags": parsed(item.get("tags_json"), []), "quality_score": item.get("quality_score"),
            "has_dialogue": bool(item.get("has_dialogue")) if item.get("has_dialogue") is not None else None,
            "usable_ranges": parsed(item.get("usable_ranges_json"), []),
            "analysis": parsed(item.get("analysis_json"), {}),
            "drive_url": f"https://drive.google.com/file/d/{item.get('external_id')}/view",
        } for item in items],
    }
    report_lines = [
        "# AI FOOTAGE CLASSIFICATION", "", f"Generated: {catalog['generated_at']}",
        f"Total clips: {len(items)}", "",
    ]
    for entry in catalog["files"]:
        report_lines.extend([
            f"## {entry['file_name']}", "", f"- Category: {entry['category']}",
            f"- Quality: {entry['quality_score'] if entry['quality_score'] is not None else 'N/A'}/10",
            f"- Dialogue: {'Yes' if entry['has_dialogue'] else 'No'}",
            f"- Tags: {', '.join(entry['tags']) or 'None'}", f"- Summary: {entry['summary'] or 'N/A'}",
            f"- Drive: {entry['drive_url']}", "",
        ])

    def upsert(name: str, payload: bytes, mime_type: str) -> str:
        escaped_name = name.replace("'", "\\'")
        response = service.files().list(
            q=f"'{classified_id}' in parents and name='{escaped_name}' and trashed=false",
            fields="files(id)", pageSize=10, supportsAllDrives=True,
            includeItemsFromAllDrives=True).execute()
        media = MediaIoBaseUpload(io.BytesIO(payload), mimetype=mime_type, resumable=False)
        if response.get("files"):
            return service.files().update(fileId=response["files"][0]["id"], media_body=media,
                                          fields="id", supportsAllDrives=True).execute()["id"]
        return service.files().create(
            body={"name": name, "parents": [classified_id]}, media_body=media,
            fields="id", supportsAllDrives=True).execute()["id"]

    from googleapiclient.http import MediaIoBaseUpload
    catalog_id = upsert("FOOTAGE_CATALOG.json", json.dumps(catalog, ensure_ascii=False, indent=2).encode(), "application/json")
    report_id = upsert("FOOTAGE_REPORT.md", "\n".join(report_lines).encode(), "text/markdown")
    return {"moved": moved, "classified_folder_id": classified_id,
            "classified_folder_url": f"https://drive.google.com/drive/folders/{classified_id}",
            "catalog_file_id": catalog_id, "report_file_id": report_id}


async def classify_video_footage(video_topic_id: str, force: bool = False) -> dict:
    return await _classify_video_footage(video_topic_id, force=force)


async def _classify_video_footage(video_topic_id: str, progress: ProgressCallback | None = None,
                                  force: bool = False) -> dict:
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
                result = asset if asset["status"] == "READY" and not force else await analyze_footage(asset["id"], profile)
                analyzed.append(result)
                await emit("ANALYZING", f"Đã phân loại {asset['file_name']} → {_category_folder(result.get('category'))}", index, len(assets))
            except Exception as exc:
                errors.append({"asset_id": asset["id"], "file_name": asset["file_name"], "error": str(exc)})
                await emit("ANALYZING", f"Lỗi {asset['file_name']}: {exc}", index, len(assets))
        organization = None
        if analyzed:
            await emit("ORGANIZING", f"Đang chuyển {len(analyzed)} clip vào {CLASSIFIED_FOLDER}", len(analyzed), len(assets))
            token = await get_valid_access_token()
            organization = await asyncio.to_thread(_organize_files_sync, folder_id, analyzed, token)
            await emit("SAVING", "Đã lưu FOOTAGE_CATALOG.json và FOOTAGE_REPORT.md trên Drive", len(analyzed), len(assets))
        status = "READY" if not errors else ("PARTIAL" if analyzed else "FAILED")
        await db.execute("UPDATE video_topics SET footage_status=?,footage_error=?,footage_result_json=?,updated_at=? WHERE id=?",
                         (status, None if not errors else str(errors)[:4000],
                          json.dumps(organization or {}, ensure_ascii=False), _now(), video_topic_id))
        await crud.update_footage_source(source["id"], last_scanned_at=_now())
        await db.commit()
        await emit("COMPLETED", f"Hoàn tất: {len(analyzed)}/{len(assets)} clip đã phân loại", len(analyzed), len(assets))
        return {"video_topic_id": video_topic_id, "folder_id": folder_id,
                "discovered": len(assets), "classified": len(analyzed), "status": status,
                "organization": organization, "errors": errors}
    except Exception as exc:
        await db.execute("UPDATE video_topics SET footage_status='FAILED',footage_error=?,updated_at=? WHERE id=?",
                         (str(exc)[:4000], _now(), video_topic_id))
        await db.commit()
        await emit("FAILED", f"Phân loại thất bại: {exc}")
        raise


async def _persist_run(state: dict) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO footage_classification_runs(video_topic_id,status,stage,message,current,total,force,logs_json,result_json,error,started_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(video_topic_id) DO UPDATE SET status=excluded.status,stage=excluded.stage,
           message=excluded.message,current=excluded.current,total=excluded.total,force=excluded.force,
           logs_json=excluded.logs_json,result_json=excluded.result_json,error=excluded.error,
           started_at=excluded.started_at,updated_at=excluded.updated_at""",
        (state["video_topic_id"], state["status"], state["stage"], state["message"],
         state.get("current", 0), state.get("total", 0), int(state.get("force", False)),
         json.dumps(state.get("logs", []), ensure_ascii=False),
         json.dumps(state.get("result"), ensure_ascii=False) if state.get("result") is not None else None,
         state.get("error"), state["started_at"], state["updated_at"]),
    )
    await db.commit()


async def classification_status(video_topic_id: str) -> dict:
    active = _classification_runs.get(video_topic_id)
    if active:
        return active
    db = await get_db()
    row = await (await db.execute("SELECT * FROM footage_classification_runs WHERE video_topic_id=?",
                                  (video_topic_id,))).fetchone()
    if not row:
        return {"video_topic_id": video_topic_id, "status": "IDLE", "stage": "IDLE",
                "message": "Chưa chạy phân loại", "current": 0, "total": 0, "logs": []}
    data = dict(row)
    data["logs"] = json.loads(data.pop("logs_json") or "[]")
    raw_result = data.pop("result_json")
    data["result"] = json.loads(raw_result) if raw_result else None
    data["force"] = bool(data["force"])
    # A RUNNING row without an in-process task came from an app shutdown.
    if data["status"] == "RUNNING":
        data.update({"status": "INTERRUPTED", "stage": "INTERRUPTED",
                     "message": "Ứng dụng đã dừng; có thể tiếp tục từ clip chưa hoàn tất",
                     "updated_at": _now()})
        await _persist_run(data)
    return data


async def start_video_footage_classification(video_topic_id: str, force: bool = False) -> dict:
    task = _classification_tasks.get(video_topic_id)
    if task and not task.done():
        return await classification_status(video_topic_id)
    started_at = _now()
    state = {"video_topic_id": video_topic_id, "status": "RUNNING", "stage": "QUEUED",
             "message": "Đã xếp hàng phân loại footage", "current": 0, "total": 0,
             "force": force, "started_at": started_at, "updated_at": started_at, "logs": []}
    _classification_runs[video_topic_id] = state
    await _persist_run(state)

    async def progress(stage: str, message: str, current: int, total: int):
        now = _now()
        state.update({"stage": stage, "message": message, "current": current,
                      "total": total, "updated_at": now})
        state["logs"].append({"time": now, "stage": stage, "message": message})
        state["logs"] = state["logs"][-100:]
        await _persist_run(state)

    async def run():
        try:
            result = await _classify_video_footage(video_topic_id, progress, force=force)
            state.update({"status": "COMPLETED", "result": result, "updated_at": _now()})
            await _persist_run(state)
        except Exception as exc:
            state.update({"status": "FAILED", "stage": "FAILED", "message": str(exc),
                          "error": str(exc), "updated_at": _now()})
            await _persist_run(state)

    _classification_tasks[video_topic_id] = asyncio.create_task(run())
    return state


async def resume_interrupted_classifications() -> list[str]:
    """Resume topics left ANALYZING by an earlier app shutdown."""
    db = await get_db()
    rows = await (await db.execute(
        """SELECT vt.id,COALESCE(r.force,0) force FROM video_topics vt
           LEFT JOIN footage_classification_runs r ON r.video_topic_id=vt.id
           WHERE vt.footage_status='ANALYZING'""")).fetchall()
    resumed = []
    for row in rows:
        await start_video_footage_classification(row[0], force=bool(row[1]))
        resumed.append(row[0])
    return resumed
