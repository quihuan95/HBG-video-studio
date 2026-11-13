"""Export a completed production revision as an editable CapCut draft."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from agent import config


def _draft_name(title: str, job_id: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", title or "Video").strip().rstrip(".")
    safe = re.sub(r"\s+", " ", safe)[:80] or "Video"
    return f"{safe} - {job_id[:8]}"


def _scene_path(work: Path, index: int) -> Path:
    visual = work / f"scene-{index:03}-visual.mp4"
    return visual if visual.is_file() else work / f"scene-{index:03}.mp4"


def _backup_path(backup_root: Path, job_id: str) -> Path:
    """Return a short archival path that does not repeat the project title."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return backup_root / f"{job_id[:8]}-{stamp}"


def _apply_caption_style(draft: Path, canvas_height: int) -> None:
    """Apply the configured CapCut text style to every editable caption segment."""
    font_path = Path(config.CAPCUT_TEXT_FONT_PATH)
    if not font_path.is_file():
        raise RuntimeError(f"CapCut subtitle font not found: {font_path}")
    normalized_y = config.CAPCUT_TEXT_Y / canvas_height
    targets = [draft / "draft_content.json", draft / "template-2.tmp"]
    targets.extend((draft / "Timelines").glob("*/draft_content.json"))
    targets.extend((draft / "Timelines").glob("*/template*.tmp"))
    for target in targets:
        if not target.is_file():
            continue
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        text_ids = {item.get("id") for item in payload.get("materials", {}).get("texts", [])}
        for material in payload.get("materials", {}).get("texts", []):
            material.update({
                "font_name": config.CAPCUT_TEXT_FONT_NAME,
                "font_title": config.CAPCUT_TEXT_FONT_NAME,
                "font_path": str(font_path).replace("\\", "/"),
                "font_size": config.CAPCUT_TEXT_FONT_SIZE,
                "text_size": config.CAPCUT_TEXT_FONT_SIZE,
            })
            try:
                content = json.loads(material.get("content") or "{}")
                for style in content.get("styles", []):
                    style["size"] = config.CAPCUT_TEXT_FONT_SIZE
                    style["font"] = {"path": str(font_path).replace("\\", "/"), "id": ""}
                material["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            except ValueError:
                pass
        for track in payload.get("tracks", []):
            if track.get("type") != "text":
                continue
            for segment in track.get("segments", []):
                if segment.get("material_id") not in text_ids:
                    continue
                transform = (segment.get("clip") or {}).setdefault("transform", {})
                transform.update({"x": config.CAPCUT_TEXT_X, "y": normalized_y})
        target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


async def export_capcut_draft(job_id: str, title: str, work: Path, scenes: list[dict],
                              orientation: str, music_path: str | None,
                              music_volume: float = .15, replace: bool = False) -> Path:
    if not config.CAPCUT_EXPORT_ENABLED:
        raise RuntimeError("CapCut export is disabled")
    draft_root = config.CAPCUT_DRAFT_ROOT.resolve()
    if not draft_root.is_dir():
        raise RuntimeError(f"CapCut draft root not found: {draft_root}")
    if not scenes:
        raise RuntimeError("No scenes available for CapCut export")

    video_items, voice_items = [], []
    for index, scene in enumerate(scenes, 1):
        start = float(scene.get("start_time_s") or 0)
        duration = float(scene.get("duration_s") or 0)
        video = _scene_path(work, index)
        if not video.is_file():
            raise RuntimeError(f"Missing CapCut scene media: {video.name}")
        video_items.append({"path": str(video), "start": start, "duration": duration,
                            "ref": f"scene-{index:03}"})
        voice = work / f"voice-{index:03}.wav"
        voice_duration = float(scene.get("voice_duration_s") or 0)
        if voice.is_file() and voice_duration > 0:
            voice_items.append({"path": str(voice), "start": start, "duration": voice_duration,
                                "volume": 1, "ref": f"voice-{index:03}"})

    tracks: list[dict] = [{"type": "video", "name": "Phân cảnh", "items": video_items}]
    if voice_items:
        tracks.append({"type": "audio", "name": "Voice", "items": voice_items})
    total = max(float(scene.get("end_time_s") or 0) for scene in scenes)
    music = Path(music_path).expanduser() if music_path else None
    if music and music.is_file():
        tracks.append({"type": "audio", "name": "Nhạc nền", "items": [
            {"path": str(music), "start": 0, "duration": total, "volume": music_volume}]})
    spec = {
        "name": _draft_name(title, job_id),
        "width": 1080 if orientation == "VERTICAL" else 1920,
        "height": 1920 if orientation == "VERTICAL" else 1080,
        "fps": 30,
        "ratio": "9:16" if orientation == "VERTICAL" else "16:9",
        "tracks": tracks,
        "operations": ([{"op": "captions", "path": str(work / "subtitles.srt"),
                         "trackName": "Phụ đề"}]
                       if (work / "subtitles.srt").is_file() else []),
    }
    spec_path = work / "capcut-spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    cli = config.BASE_DIR / "node_modules" / "capcut-cli" / "dist" / "index.js"
    if not cli.is_file():
        raise RuntimeError("capcut-cli is not installed; run npm install")
    draft = draft_root / spec["name"]
    backup = None
    if draft.exists():
        if not replace:
            raise RuntimeError(f"CapCut draft already exists: {draft}")
        backup_root = config.OUTPUT_DIR / "capcut_draft_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        # Never repeat the long draft title or full UUID in the destination;
        # descendants in Timelines/ otherwise exceed MAX_PATH on Windows.
        backup = _backup_path(backup_root, job_id)
        await asyncio.to_thread(shutil.move, str(draft), str(backup))
    try:
        process = await asyncio.create_subprocess_exec(
            "node", str(cli), "compile", str(spec_path), "--drafts", str(draft_root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace")
            raise RuntimeError(f"CapCut draft export failed: {detail[-1500:].strip()}")
    except Exception:
        if backup and backup.exists() and not draft.exists():
            await asyncio.to_thread(shutil.move, str(backup), str(draft))
        raise
    if not (draft / "draft_content.json").is_file():
        raise RuntimeError("CapCut export completed but draft_content.json was not created")
    _apply_caption_style(draft, spec["height"])
    return draft
