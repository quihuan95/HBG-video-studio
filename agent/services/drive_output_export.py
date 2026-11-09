"""Idempotent export of an approved production revision to Google Drive OUTPUT."""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from agent.db.schema import get_db
from agent.services.google_oauth import get_valid_access_token

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
EXPORTABLE_STATUSES = {"APPROVED", "READY_FOR_MANUAL_UPLOAD"}
_active_exports: set[str] = set()
_active_lock = asyncio.Lock()


class DriveExportError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drive_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"/folders/([\w-]+)", value)
    result = match.group(1) if match else value.strip()
    return result if re.fullmatch(r"[\w-]+", result) else None


def _safe_name(value: str) -> str:
    value = re.sub(r"[/\\]+", " - ", value)
    value = re.sub(r"[\x00-\x1f\x7f]", "", value)
    return re.sub(r"\s+", " ", value).strip(" .")[:120] or "Untitled video"


def _date_folder(value: str | None) -> str:
    try:
        parsed = datetime.strptime(value or "", "%Y-%m-%d")
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return parsed.strftime("%d-%m-%Y")


def _local_path(value: str | None) -> Path | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme == "file":
        raw = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
        candidate = Path(raw)
    elif parsed.scheme and not re.match(r"^[A-Za-z]:[\\/]", value):
        return None
    else:
        candidate = Path(value)
    return candidate.resolve() if candidate.is_file() else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


async def _find_child(client: httpx.AsyncClient, parent_id: str, name: str,
                      mime_type: str | None = None) -> dict | None:
    clauses = [f"'{_escape_query(parent_id)}' in parents", f"name='{_escape_query(name)}'", "trashed=false"]
    if mime_type:
        clauses.append(f"mimeType='{_escape_query(mime_type)}'")
    response = await client.get(f"{DRIVE_API}/files", params={
        "q": " and ".join(clauses), "fields": "files(id,name,mimeType,webViewLink)",
        "pageSize": 10, "spaces": "drive", "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    })
    response.raise_for_status()
    files = response.json().get("files", [])
    return files[0] if files else None


async def _create_folder(client: httpx.AsyncClient, parent_id: str, name: str) -> dict:
    existing = await _find_child(client, parent_id, name, FOLDER_MIME)
    if existing:
        return existing
    response = await client.post(f"{DRIVE_API}/files", params={"supportsAllDrives": "true"},
        json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]})
    response.raise_for_status()
    return response.json()


async def _resolve_output_folder(client: httpx.AsyncClient, profile: dict) -> str:
    configured = _drive_id(profile.get("folder_id_output") or profile.get("output_drive_url"))
    if configured:
        return configured
    profile_folder = await _find_child(client, "root", profile["id"], FOLDER_MIME)
    if profile_folder:
        output = await _find_child(client, profile_folder["id"], "OUTPUT", FOLDER_MIME)
        if output:
            return output["id"]
    raise DriveExportError("OUTPUT_FOLDER_MISSING", "Profile has no writable Google Drive OUTPUT folder")


async def _upsert_file(client: httpx.AsyncClient, parent_id: str, name: str,
                       content: bytes | Path, mime_type: str) -> str:
    existing = await _find_child(client, parent_id, name)
    if existing:
        file_id = existing["id"]
    else:
        response = await client.post(f"{DRIVE_API}/files", params={"supportsAllDrives": "true"},
            json={"name": name, "mimeType": mime_type, "parents": [parent_id]})
        response.raise_for_status()
        file_id = response.json()["id"]
    headers = {"Content-Type": mime_type}
    if isinstance(content, Path):
        headers["Content-Length"] = str(content.stat().st_size)
        response = await client.patch(f"{DRIVE_UPLOAD_API}/files/{file_id}",
            params={"uploadType": "media", "supportsAllDrives": "true"}, headers=headers,
            content=_file_chunks(content))
    else:
        response = await client.patch(f"{DRIVE_UPLOAD_API}/files/{file_id}",
            params={"uploadType": "media", "supportsAllDrives": "true"}, headers=headers, content=content)
    response.raise_for_status()
    return file_id


async def _file_chunks(path: Path, chunk_size: int = 8 * 1024 * 1024):
    """Stream a local video without loading it all into memory."""
    with path.open("rb") as handle:
        while True:
            chunk = await asyncio.to_thread(handle.read, chunk_size)
            if not chunk:
                break
            yield chunk


async def _load_export(job_id: str) -> tuple[dict, dict, dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT j.*,p.name profile_name,p.folder_id_output,p.output_drive_url "
        "FROM production_jobs j JOIN production_profile p ON p.id=j.profile_id WHERE j.id=?", (job_id,))
    job_row = await cursor.fetchone()
    if not job_row:
        raise DriveExportError("JOB_NOT_FOUND", "Production Job not found")
    job = dict(job_row)
    if job["status"] not in EXPORTABLE_STATUSES:
        raise DriveExportError("JOB_NOT_APPROVED", "Production Job must be APPROVED before export")
    cursor = await db.execute("SELECT * FROM production_revisions WHERE id=? AND production_job_id=?",
                              (job.get("current_revision_id"), job_id))
    revision_row = await cursor.fetchone()
    if not revision_row:
        raise DriveExportError("REVISION_NOT_FOUND", "Current production revision was not found")
    revision = dict(revision_row)
    try:
        assets = json.loads(revision.get("assets_json") or "{}")
    except ValueError as exc:
        raise DriveExportError("ASSETS_INVALID", "Revision assets_json is invalid") from exc
    path = _local_path(assets.get("final_video_path") or assets.get("video_path") or job.get("output_url"))
    if not path:
        raise DriveExportError("VIDEO_FILE_MISSING", "Final video file is missing from the current revision")
    assets["resolved_video_path"] = str(path)
    return job, revision, assets


async def approve_production_job(job_id: str, output_path: str | None = None) -> dict:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM production_jobs WHERE id=?", (job_id,))
    job = await cursor.fetchone()
    if not job:
        raise DriveExportError("JOB_NOT_FOUND", "Production Job not found")
    revision_id = job["current_revision_id"]
    cursor = await db.execute("SELECT assets_json FROM production_revisions WHERE id=? AND production_job_id=?",
                              (revision_id, job_id))
    revision = await cursor.fetchone()
    if not revision:
        raise DriveExportError("REVISION_NOT_FOUND", "Current production revision was not found")
    assets = json.loads(revision[0] or "{}")
    if output_path:
        path = _local_path(output_path)
        if not path:
            raise DriveExportError("VIDEO_FILE_MISSING", "The supplied final video file does not exist")
        assets["final_video_path"] = str(path)
        await db.execute("UPDATE production_revisions SET assets_json=? WHERE id=?",
                         (json.dumps(assets, ensure_ascii=False), revision_id))
    if not _local_path(assets.get("final_video_path") or assets.get("video_path") or job["output_url"]):
        raise DriveExportError("VIDEO_FILE_MISSING", "A final video path is required before approval")
    now = _now()
    await db.execute("UPDATE production_jobs SET status='APPROVED',error_stage=NULL,error_message=NULL,updated_at=? WHERE id=?",
                     (now, job_id))
    await db.execute("INSERT INTO production_audit_events(id,production_job_id,revision_id,action,detail_json,created_at) VALUES(?,?,?,?,?,?)",
                     (str(uuid.uuid4()), job_id, revision_id, "APPROVE", "{}", now))
    await db.commit()
    return dict((await (await db.execute("SELECT * FROM production_jobs WHERE id=?", (job_id,))).fetchone()))


async def export_production_job(job_id: str) -> dict:
    async with _active_lock:
        if job_id in _active_exports:
            raise DriveExportError("EXPORT_IN_PROGRESS", "This Production Job is already being exported")
        _active_exports.add(job_id)
    try:
        job, revision, assets = await _load_export(job_id)
        video_path = Path(assets["resolved_video_path"])
        token = await get_valid_access_token()
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=None) as client:
            root_id = await _resolve_output_folder(client, job)
            day = await _create_folder(client, root_id, _date_folder(job.get("production_date")))
            title = await _create_folder(client, day["id"], _safe_name(job["title"]))
            revision_folder = await _create_folder(client, title["id"], f"v{revision['revision']}")
            folder_id = revision_folder["id"]
            video_name = f"final{video_path.suffix.lower() or '.mp4'}"
            mime = mimetypes.guess_type(video_name)[0] or "video/mp4"
            video_id = await _upsert_file(client, folder_id, video_name, video_path, mime)
            exported_at = _now()
            manifest = {
                "schema_version": 1, "production_job_id": job_id, "revision_id": revision["id"],
                "revision": revision["revision"], "profile_id": job["profile_id"],
                "video_topic_id": job.get("video_topic_id"), "title": job["title"],
                "production_date": job.get("production_date"), "scheduled_time": job.get("scheduled_time"),
                "rule_version_id": revision.get("rule_version_id"), "rule_hash": revision.get("rule_hash"),
                "revision_hash": revision["revision_hash"], "video_sha256": _sha256(video_path),
                "video_size_bytes": video_path.stat().st_size, "exported_at": exported_at,
                "drive": {"folder_id": folder_id, "video_file_id": video_id},
            }
            manifest_id = await _upsert_file(client, folder_id, "video.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode(), "application/json")
            review = (f"# VIDEO EXPORT REVIEW\n\n- Profile: {job['profile_name']}\n- Video: {job['title']}\n"
                      f"- Production date: {job.get('production_date') or 'Not scheduled'}\n"
                      f"- Revision: v{revision['revision']}\n- Status: READY_FOR_MANUAL_UPLOAD\n"
                      f"- Exported at: {exported_at}\n\n## Files\n\n- `{video_name}`\n- `video.json`\n- `REVIEW.md`\n")
            review_id = await _upsert_file(client, folder_id, "REVIEW.md", review.encode(), "text/markdown")
            manifest["drive"].update({"manifest_file_id": manifest_id, "review_file_id": review_id})
            await _upsert_file(client, folder_id, "video.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode(), "application/json")

        db = await get_db()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT current_revision_id FROM production_jobs WHERE id=?", (job_id,))
            current = await cursor.fetchone()
            if not current or current[0] != revision["id"]:
                raise DriveExportError("EXPORT_REVISION_CONFLICT", "Current revision changed during Drive export")
            files = {"video": video_id, "manifest": manifest_id, "review": review_id}
            await db.execute("DELETE FROM production_exports WHERE production_job_id=? AND revision_id=?",
                             (job_id, revision["id"]))
            await db.execute("INSERT INTO production_exports(id,production_job_id,revision_id,status,drive_folder_id,drive_video_file_id,drive_manifest_file_id,drive_review_file_id,drive_folder_url,files_json,exported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), job_id, revision["id"], "EXPORTED", folder_id, video_id, manifest_id,
                 review_id, f"https://drive.google.com/drive/folders/{folder_id}", json.dumps(files), exported_at))
            await db.execute("UPDATE production_jobs SET status='READY_FOR_MANUAL_UPLOAD',output_drive_file_id=?,output_url=?,error_stage=NULL,error_message=NULL,updated_at=? WHERE id=?",
                (video_id, f"https://drive.google.com/drive/folders/{folder_id}", exported_at, job_id))
            await db.execute("INSERT INTO production_audit_events(id,production_job_id,revision_id,action,detail_json,created_at) VALUES(?,?,?,?,?,?)",
                (str(uuid.uuid4()), job_id, revision["id"], "EXPORT_TO_DRIVE", json.dumps({"folder_id": folder_id, "files": files}), exported_at))
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return {"success": True, "driveFolderId": folder_id,
                "driveFolderUrl": f"https://drive.google.com/drive/folders/{folder_id}", "files": files}
    except Exception as exc:
        db = await get_db()
        try:
            await db.execute("UPDATE production_jobs SET error_stage='drive_export',error_message=?,updated_at=? WHERE id=?",
                             (str(exc)[:2000], _now(), job_id))
            await db.commit()
        except Exception:
            await db.rollback()
        raise
    finally:
        async with _active_lock:
            _active_exports.discard(job_id)


def export_in_progress(job_id: str) -> bool:
    return job_id in _active_exports
