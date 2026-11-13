"""YouTube search and download for online B-roll candidates (yt-dlp)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from agent import config

_WATCH_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def available() -> bool:
    if not (config.FOOTAGE_EXTERNAL_ENABLED and config.YOUTUBE_FOOTAGE_ENABLED):
        return False
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def watch_url(video_id: str) -> str:
    if not _WATCH_ID.match(video_id or ""):
        raise ValueError(f"Invalid YouTube video id: {video_id}")
    return f"https://www.youtube.com/watch?v={video_id}"


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname in {"www.youtube.com", "youtube.com", "youtu.be"}


def _search_sync(query: str, limit: int) -> list[dict]:
    import yt_dlp
    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "extract_flat": "in_playlist", "noplaylist": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    return list(info.get("entries") or [])


async def search_candidates(query: str, limit: int) -> list[dict]:
    """Return footage_research candidate dicts. Timestamps stay UNVERIFIED until REA runs."""
    query = " ".join(query.split())[:200]
    if not query:
        return []
    entries = await asyncio.to_thread(_search_sync, query, max(limit * 2, limit + 3))
    result = []
    for item in entries:
        video_id = item.get("id") or ""
        duration = item.get("duration")
        if not _WATCH_ID.match(video_id) or item.get("live_status") in {"is_live", "is_upcoming"}:
            continue
        if duration is not None and not (config.YOUTUBE_MIN_DURATION_S <= float(duration) <= config.YOUTUBE_MAX_DURATION_S):
            continue
        url = watch_url(video_id)
        result.append({"provider": "youtube", "provider_file_id": video_id,
            "title": (item.get("title") or f"YouTube {video_id}")[:300],
            "description": f"YouTube result for: {query}", "source_url": url, "preview_url": url,
            "thumbnail_url": ((item.get("thumbnails") or [{}])[-1]).get("url"),
            "duration_s": duration, "creator": item.get("channel") or item.get("uploader"),
            "source_start_s": None, "source_end_s": None, "timestamp_status": "UNVERIFIED",
            "timestamp_evidence": None, "fit_score": 45.0, "verification_status": "NEEDS_REVIEW",
            "license_status": "YOUTUBE_UNVERIFIED",
            "attribution": f"{item.get('channel') or 'YouTube creator'} — {url}",
            "download_allowed": True, "download_url": url,
            "metadata_json": json.dumps({"query": query, "channel_id": item.get("channel_id")}, ensure_ascii=False)})
        if len(result) >= limit:
            break
    return result


def _license_status(info: dict) -> str:
    return "CREATIVE_COMMONS" if "creative commons" in str(info.get("license") or "").lower() else "YOUTUBE_STANDARD"


def _download_sync(url: str, output: Path) -> dict:
    import yt_dlp
    rejected: list[str] = []

    def guard(info, *, incomplete):
        duration = info.get("duration")
        if duration and float(duration) > config.YOUTUBE_MAX_DURATION_S:
            rejected.append(f"Video dài {duration}s vượt YOUTUBE_MAX_DURATION_S")
        elif config.YOUTUBE_CC_ONLY and _license_status(info) != "CREATIVE_COMMONS":
            rejected.append("Video không dùng giấy phép Creative Commons")
        return rejected[-1] if rejected else None

    height = config.YOUTUBE_MAX_HEIGHT
    options = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
               "outtmpl": str(output), "overwrites": True, "match_filter": guard,
               "max_filesize": config.YOUTUBE_MAX_FILESIZE_MB * 1024 * 1024,
               # Audio is replaced by voice-over, so a video-only stream avoids a merge step.
               "format": f"bv*[height<={height}][ext=mp4]/bv*[height<={height}]/b[height<={height}]",
               "js_runtimes": {"node": {}}}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
    if not output.is_file():
        raise RuntimeError(rejected[-1] if rejected else "yt-dlp không tải được video")
    return {"license_status": _license_status(info or {}), "duration_s": (info or {}).get("duration"),
            "height": (info or {}).get("height")}


async def download(url: str, output: Path) -> dict:
    if not is_youtube_url(url):
        raise ValueError("Only YouTube watch URLs can be downloaded")
    output.parent.mkdir(parents=True, exist_ok=True)
    return await asyncio.wait_for(asyncio.to_thread(_download_sync, url, output),
                                  timeout=config.YOUTUBE_DOWNLOAD_TIMEOUT_S)
