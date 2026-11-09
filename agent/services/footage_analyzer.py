"""OpenAI Vision classification for sampled footage frames."""
import asyncio
import base64
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from agent.config import OPENAI_API_KEY, OPENAI_VISION_MODEL
from agent.db import crud

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "category": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "subjects": {"type": "array", "items": {"type": "string"}},
        "actions": {"type": "array", "items": {"type": "string"}},
        "locations": {"type": "array", "items": {"type": "string"}},
        "quality_score": {"type": "number", "minimum": 0, "maximum": 10},
        "has_dialogue": {"type": "boolean"},
        "usable_ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "description": {"type": "string"},
                },
                "required": ["start", "end", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "category", "tags", "subjects", "actions", "locations",
                 "quality_score", "has_dialogue", "usable_ranges"],
    "additionalProperties": False,
}


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    return Path(path)


def _download_drive(file_id: str, destination: Path) -> None:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    credentials_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if not credentials_file:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_FILE is required to analyze Drive footage")
    credentials = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    request = service.files().get_media(fileId=file_id)
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


async def _materialize(asset: dict, temp_dir: Path) -> Path:
    if asset["uri"].startswith("file:"):
        path = _local_path(asset["uri"])
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    if asset["uri"].startswith("gdrive://"):
        destination = temp_dir / asset["file_name"]
        await asyncio.to_thread(_download_drive, asset["external_id"] or asset["uri"][9:], destination)
        return destination
    raise ValueError(f"Unsupported footage URI: {asset['uri']}")


async def _extract_frames(video: Path, output: Path, duration_s: float | None) -> list[Path]:
    interval = max((duration_s or 24) / 8, 1)
    pattern = str(output / "frame-%03d.jpg")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", f"fps=1/{interval},scale='min(1280,iw)':-2", "-frames:v", "10", "-q:v", "3", pattern,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "ffmpeg frame extraction failed")
    frames = sorted(output.glob("frame-*.jpg"))
    if not frames:
        raise RuntimeError("No frames could be extracted")
    return frames


async def analyze_footage(asset_id: str, profile: dict) -> dict:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for footage analysis")
    asset = await crud.get_footage_asset(asset_id)
    if not asset:
        raise ValueError("Footage asset not found")
    await crud.update_footage_asset(asset_id, status="ANALYZING", error_message=None)
    temp_dir = Path(tempfile.mkdtemp(prefix="hbg-footage-"))
    try:
        video = await _materialize(asset, temp_dir)
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir()
        frames = await _extract_frames(video, frames_dir, asset.get("duration_s"))
        content = [{
            "type": "input_text",
            "text": (
                "Analyze these chronological frames from one footage clip for a professional video editor. "
                f"Profile tone: {profile.get('tone') or 'neutral'}. Language: {profile.get('language') or 'vi'}. "
                f"Clip duration: {asset.get('duration_s') or 'unknown'} seconds. "
                "Classify content, describe useful editorial ranges conservatively, and return only the schema."
            ),
        }]
        for frame in frames:
            encoded = base64.b64encode(frame.read_bytes()).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}", "detail": "low"})

        from openai import AsyncOpenAI
        response = await AsyncOpenAI(api_key=OPENAI_API_KEY).responses.create(
            model=OPENAI_VISION_MODEL,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": "footage_analysis",
                             "strict": True, "schema": ANALYSIS_SCHEMA}},
        )
        analysis = json.loads(response.output_text)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return await crud.update_footage_asset(
            asset_id, status="READY", summary=analysis["summary"], category=analysis["category"],
            tags_json=json.dumps(analysis["tags"], ensure_ascii=False),
            usable_ranges_json=json.dumps(analysis["usable_ranges"], ensure_ascii=False),
            quality_score=analysis["quality_score"], has_dialogue=int(analysis["has_dialogue"]),
            analysis_json=json.dumps(analysis, ensure_ascii=False), analyzed_at=now, error_message=None)
    except Exception as exc:
        await crud.update_footage_asset(asset_id, status="FAILED", error_message=str(exc))
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
