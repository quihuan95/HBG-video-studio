"""Background production pipeline for script + classified footage jobs."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import unicodedata
from pathlib import Path

from agent import config
from agent.db.schema import get_db
from agent.services.footage_analyzer import _download_drive
from agent.services.google_oauth import get_valid_access_token
from agent.services.post_process import _ffmpeg_bin, add_music, merge_videos
from agent.services.production_progress import update_production_progress

_tasks: dict[str, asyncio.Task] = {}


def _words(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return {word for word in re.findall(r"[a-z0-9]+", normalized) if len(word) > 2}


def _asset_score(scene: dict, asset: dict) -> int:
    desired = _words(" ".join(str(scene.get(key) or "") for key in
                              ("section", "visual_intent", "footage_references", "notes")))
    actual = _words(" ".join(str(asset.get(key) or "") for key in
                             ("file_name", "summary", "category", "tags_json", "analysis_json")))
    return len(desired & actual) * 10 + int(float(asset.get("quality_score") or 0))


async def _check_cancelled(job_id: str) -> None:
    db = await get_db()
    row = await (await db.execute("SELECT status FROM production_jobs WHERE id=?", (job_id,))).fetchone()
    if not row or row[0] == "CANCELLED":
        raise asyncio.CancelledError("Production Job was cancelled")


async def _run_process(*args: str, timeout: int = 900) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        process.kill(); await process.communicate()
        raise
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-1200:] or "FFmpeg failed")


async def _tts(text: str, output: Path, voice: str, instructions: str | None) -> None:
    if not text.strip():
        return
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for voice-over")
    from openai import AsyncOpenAI
    configured = config.OPENAI_TTS_MODEL
    models = [configured]
    if "realtime" in configured.lower():
        models.append("gpt-4o-mini-tts")
    last_error = None
    for model in dict.fromkeys(models):
        try:
            response = await AsyncOpenAI(api_key=config.OPENAI_API_KEY).audio.speech.create(
                model=model, voice=voice or "marin", input=text,
                instructions=instructions or "Speak naturally for a professional travel video.",
                response_format="wav")
            await asyncio.to_thread(response.write_to_file, output)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"OpenAI TTS failed: {last_error}")


async def _materialize_asset(asset: dict, output: Path, token: str) -> Path:
    if output.is_file():
        return output
    if not asset.get("external_id"):
        raise RuntimeError(f"Footage has no Drive file ID: {asset.get('file_name')}")
    await asyncio.to_thread(_download_drive, asset["external_id"], output, token)
    return output


def _usable_start(asset: dict) -> float:
    try:
        ranges = json.loads(asset.get("usable_ranges_json") or "[]")
        return max(0.0, float(ranges[0].get("start", 0))) if ranges else 0.0
    except (ValueError, TypeError, IndexError):
        return 0.0


async def _make_scene_clip(source: Path, voice: Path | None, output: Path,
                           duration: float, start: float, vertical: bool) -> None:
    width, height = (1080, 1920) if vertical else (1920, 1080)
    cmd = [_ffmpeg_bin(), "-y", "-stream_loop", "-1", "-ss", str(start), "-i", str(source)]
    if voice and voice.is_file():
        cmd += ["-i", str(voice)]
        audio = ["-map", "0:v", "-map", "1:a", "-af", "apad", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio = ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30"
    cmd += ["-t", str(duration), "-vf", vf, *audio, "-c:v", "libx264", "-preset", "fast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    await _run_process(*cmd)


def _srt_time(seconds: float) -> str:
    millis = round(seconds * 1000); hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000); secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


async def _burn_subtitles(video: Path, scenes: list[dict], output: Path, work: Path) -> Path:
    srt = work / "subtitles.srt"; blocks = []
    for index, scene in enumerate(scenes, 1):
        text = (scene.get("on_screen_text") or scene.get("narration_text") or "").strip()
        if text:
            blocks.append(f"{index}\n{_srt_time(float(scene['start_time_s']))} --> {_srt_time(float(scene['end_time_s']))}\n{text}\n")
    if not blocks:
        shutil.copy2(video, output); return output
    srt.write_text("\n".join(blocks), encoding="utf-8")
    escaped = srt.as_posix().replace(":", "\\:").replace("'", "\\'")
    await _run_process(_ffmpeg_bin(), "-y", "-i", str(video), "-vf",
                       f"subtitles='{escaped}'", "-c:v", "libx264", "-preset", "fast",
                       "-crf", "19", "-c:a", "copy", str(output))
    return output


async def _overlay_logo(video: Path, logo: str | None, position: str, output: Path) -> Path:
    logo_path = Path(logo).expanduser() if logo else None
    if not logo_path or not logo_path.is_file():
        shutil.copy2(video, output); return output
    positions = {"top-left": "20:20", "top-right": "W-w-20:20", "bottom-left": "20:H-h-20",
                 "bottom-right": "W-w-20:H-h-20", "center": "(W-w)/2:(H-h)/2"}
    await _run_process(_ffmpeg_bin(), "-y", "-i", str(video), "-i", str(logo_path),
        "-filter_complex", f"[1:v]scale=220:-1[logo];[0:v][logo]overlay={positions.get(position, positions['top-right'])}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-c:a", "copy", str(output))
    return output


async def run_production_job(job_id: str) -> None:
    db = await get_db()
    row = await (await db.execute(
        """SELECT j.*,r.scenes_json,r.assets_json,p.voice_id,p.tone,p.logo_path,p.logo_position,vt.orientation,
                  p.music_path,p.rules_json
           FROM production_jobs j JOIN production_revisions r ON r.id=j.current_revision_id
           JOIN production_profile p ON p.id=j.profile_id
           JOIN video_topics vt ON vt.id=j.video_topic_id WHERE j.id=?""", (job_id,))).fetchone()
    if not row or row["status"] == "CANCELLED": return
    data = dict(row); scenes = json.loads(data["scenes_json"]); rules = json.loads(data.get("rules_json") or "{}")
    assets = [dict(item) for item in await (await db.execute(
        """SELECT a.* FROM footage_asset a JOIN footage_source s ON s.id=a.source_id
           WHERE s.video_topic_id=? AND a.status='READY' ORDER BY a.quality_score DESC""",
        (data["video_topic_id"],))).fetchall()]
    if not assets:
        message = "Chưa có footage READY đã được phân loại"
        await db.execute(
            "UPDATE production_jobs SET status='FAILED',error_stage='FOOTAGE',error_message=?,updated_at=datetime('now') WHERE id=?",
            (message, job_id),
        )
        await db.commit()
        await update_production_progress(job_id, "FOOTAGE", "FAILED", message, error=message)
        return
    work = config.OUTPUT_DIR / "production_jobs" / job_id / data["current_revision_id"]
    work.mkdir(parents=True, exist_ok=True)
    try:
        await db.execute("UPDATE production_jobs SET status='PROCESSING',updated_at=datetime('now') WHERE id=?", (job_id,)); await db.commit()
        await _check_cancelled(job_id)
        await update_production_progress(job_id, "VOICE", "PROCESSING", "Đang tạo voice-over bằng OpenAI", 15)
        voices = []
        for index, scene in enumerate(scenes, 1):
            path = work / f"voice-{index:03}.wav"; text = scene.get("narration_text") or ""
            if not path.is_file() and text.strip(): await _tts(text, path, data.get("voice_id") or "marin", data.get("tone"))
            voices.append(path if path.is_file() else None)
            await update_production_progress(job_id, "VOICE", "PROCESSING", f"Voice {index}/{len(scenes)}", 15 + round(index / len(scenes) * 10))
            await _check_cancelled(job_id)
        await update_production_progress(job_id, "VOICE", "COMPLETED", "Đã tạo voice-over", 25)

        await update_production_progress(job_id, "FOOTAGE", "PROCESSING", "Đang ghép footage đã phân loại vào từng cảnh", 28)
        chosen = []; used = set()
        for scene in scenes:
            ranked = sorted(assets, key=lambda item: (_asset_score(scene, item), item["id"] not in used), reverse=True)
            asset = ranked[0]; chosen.append(asset); used.add(asset["id"])
        await update_production_progress(job_id, "FOOTAGE", "COMPLETED", f"Đã chọn footage cho {len(scenes)} cảnh", 38)

        token = await get_valid_access_token(); clips = []
        await update_production_progress(job_id, "TIMELINE", "PROCESSING", "Đang tải, cắt và dựng timeline", 40)
        for index, (scene, asset, voice) in enumerate(zip(scenes, chosen, voices), 1):
            suffix = Path(asset["file_name"]).suffix or ".mp4"; source = work / f"source-{asset['external_id']}{suffix}"
            await _materialize_asset(asset, source, token)
            clip = work / f"scene-{index:03}.mp4"
            await _make_scene_clip(source, voice, clip, float(scene["duration_s"]), _usable_start(asset), data.get("orientation") == "VERTICAL")
            clips.append(str(clip)); await update_production_progress(job_id, "TIMELINE", "PROCESSING", f"Đã dựng cảnh {index}/{len(scenes)}", 40 + round(index / len(scenes) * 20)); await _check_cancelled(job_id)
        merged = work / "timeline.mp4"
        if not await asyncio.to_thread(merge_videos, clips, str(merged)): raise RuntimeError("FFmpeg could not merge scene timeline")
        await update_production_progress(job_id, "TIMELINE", "COMPLETED", "Đã ghép timeline", 62)

        await update_production_progress(job_id, "BRANDING", "PROCESSING", "Đang chèn logo và nhạc", 65)
        branded = await _overlay_logo(merged, data.get("logo_path"), data.get("logo_position") or "top-right", work / "branded.mp4")
        music = data.get("music_path")
        if music and Path(music).is_file():
            mixed = work / "branded-music.mp4"
            if not await asyncio.to_thread(add_music, str(branded), music, str(mixed), float(rules.get("music_volume", .15))): raise RuntimeError("Could not mix background music")
            branded = mixed
        await update_production_progress(job_id, "BRANDING", "COMPLETED", "Đã xử lý logo và nhạc", 72)

        await update_production_progress(job_id, "SUBTITLES", "PROCESSING", "Đang tạo và chèn phụ đề", 75)
        subtitled = await _burn_subtitles(branded, scenes, work / "subtitled.mp4", work)
        await update_production_progress(job_id, "SUBTITLES", "COMPLETED", "Đã chèn phụ đề", 82)
        await _check_cancelled(job_id)

        await update_production_progress(job_id, "RENDER", "PROCESSING", "Đang render video thành phẩm", 85)
        final = work / "final.mp4"; shutil.copy2(subtitled, final)
        revision_assets = json.loads(data.get("assets_json") or "{}"); revision_assets["final_video_path"] = str(final)
        revision_assets["scene_footage"] = [{"scene_order": scene["scene_order"], "asset_id": asset["id"], "file_id": asset["external_id"]} for scene, asset in zip(scenes, chosen)]
        await db.execute("UPDATE production_revisions SET assets_json=? WHERE id=?", (json.dumps(revision_assets, ensure_ascii=False), data["current_revision_id"])); await db.commit()
        from agent.services.drive_output_export import approve_production_job, export_production_job
        await approve_production_job(job_id, str(final))
        try:
            await export_production_job(job_id)
        except Exception:
            # Drive export errors are retryable and already recorded by the exporter.
            return
    except asyncio.CancelledError:
        return
    except Exception as exc:
        progress = await (await db.execute("SELECT stage FROM production_job_progress WHERE production_job_id=?", (job_id,))).fetchone()
        stage = progress[0] if progress else "VOICE"
        await db.execute("UPDATE production_jobs SET status='FAILED',error_stage=?,error_message=?,updated_at=datetime('now') WHERE id=?",
                         (stage, str(exc)[:2000], job_id)); await db.commit()
        await update_production_progress(job_id, stage, "FAILED", f"Sản xuất thất bại: {exc}", error=str(exc))


async def start_production_job(job_id: str) -> None:
    task = _tasks.get(job_id)
    if task and not task.done(): return
    _tasks[job_id] = asyncio.create_task(run_production_job(job_id))


async def cancel_running_production(job_id: str) -> None:
    task = _tasks.get(job_id)
    if task and not task.done():
        task.cancel()


async def resume_production_jobs() -> list[str]:
    db = await get_db()
    rows = await (await db.execute("SELECT id FROM production_jobs WHERE status IN ('DRAFT','PROCESSING')")).fetchall()
    for row in rows: await start_production_job(row[0])
    return [row[0] for row in rows]
