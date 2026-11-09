"""Discover footage from local folders and Google Drive folders."""
import asyncio
import json
import os
import re
from pathlib import Path

from agent.db import crud

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def _fraction(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        left, right = value.split("/", 1)
        return float(left) / float(right)
    except (ValueError, ZeroDivisionError):
        return None


async def probe_video(path: Path) -> dict:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "ffprobe failed")
    payload = json.loads(stdout)
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), {})
    format_data = payload.get("format", {})
    return {
        "duration_s": float(format_data["duration"]) if format_data.get("duration") else None,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": _fraction(stream.get("avg_frame_rate")),
        "size_bytes": int(format_data["size"]) if format_data.get("size") else path.stat().st_size,
        "mime_type": f"video/{path.suffix.lower().lstrip('.')}",
    }


async def scan_local(source: dict) -> list[dict]:
    root = Path(source["location"]).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Local footage folder does not exist: {root}")
    iterator = root.rglob("*") if source["recursive"] else root.glob("*")
    assets = []
    for path in iterator:
        if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        try:
            metadata = await probe_video(path)
            asset = await crud.upsert_footage_asset(
                source["profile_id"], source["id"], path.name, path.as_uri(), **metadata)
        except Exception as exc:
            asset = await crud.upsert_footage_asset(
                source["profile_id"], source["id"], path.name, path.as_uri(),
                status="FAILED", error_message=str(exc), size_bytes=path.stat().st_size)
        assets.append(asset)
    return assets


def drive_folder_id(location: str) -> str:
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", location)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]+", location):
        return location
    raise ValueError("Google Drive location must be a folder URL or folder ID")


async def scan_google_drive(source: dict) -> list[dict]:
    credentials_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if not credentials_file:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_FILE is required for Google Drive sources")

    def _list_files():
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=["https://www.googleapis.com/auth/drive.readonly"])
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        folder_id = drive_folder_id(source["location"])
        query = f"'{folder_id}' in parents and trashed=false and mimeType contains 'video/'"
        result, token = [], None
        while True:
            response = service.files().list(
                q=query, pageToken=token, pageSize=1000,
                fields="nextPageToken,files(id,name,mimeType,size,modifiedTime,webContentLink)").execute()
            result.extend(response.get("files", []))
            token = response.get("nextPageToken")
            if not token:
                return result

    files = await asyncio.to_thread(_list_files)
    assets = []
    for item in files:
        uri = f"gdrive://{item['id']}"
        assets.append(await crud.upsert_footage_asset(
            source["profile_id"], source["id"], item["name"], uri,
            external_id=item["id"], mime_type=item.get("mimeType"),
            size_bytes=int(item["size"]) if item.get("size") else None))
    return assets


async def scan_source(source: dict) -> list[dict]:
    if source["source_type"] == "local":
        return await scan_local(source)
    if source["source_type"] == "google_drive":
        return await scan_google_drive(source)
    raise ValueError(f"Unsupported footage source type: {source['source_type']}")
