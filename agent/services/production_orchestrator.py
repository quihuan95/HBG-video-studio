"""Background production pipeline: Drive-first footage with Internet/REA fallback."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from agent import config
from agent.db.schema import get_db
from agent.services.footage_analyzer import _download_drive, _local_path
from agent.services.post_process import _ffmpeg_bin, add_music, merge_videos, probe_duration
from agent.services.production_progress import update_production_progress

_tasks: dict[str, asyncio.Task] = {}


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


async def _tts(text: str, output: Path, provider: str, voice: str, instructions: str | None) -> None:
    if not text.strip():
        return
    provider = (provider or "openai").lower()
    if provider == "vbee":
        from agent.services.vbee_tts import synthesize_vbee
        await synthesize_vbee(text, output, voice)
        return
    if provider != "openai":
        raise RuntimeError(f"Unsupported voice provider: {provider}")
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


async def _download_https(uri: str, output: Path) -> Path:
    from agent.services.footage_research import _safe_download_url
    if not _safe_download_url(uri):
        raise RuntimeError("Online footage is not authorized for download")
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(uri)
        response.raise_for_status()
        if len(response.content) > 500 * 1024 * 1024:
            raise RuntimeError("Online footage exceeds 500 MB")
        output.write_bytes(response.content)
    return output


async def _materialize_asset(asset: dict, output: Path, token: str) -> Path:
    if asset.get("local_path") and Path(asset["local_path"]).is_file():
        return Path(asset["local_path"])
    if output.is_file():
        return output
    uri = asset.get("uri") or asset.get("download_url") or ""
    if uri.startswith("file:"):
        source = _local_path(uri)
        if not source.is_file():
            raise FileNotFoundError(source)
        return source
    if uri.startswith("https://"):
        if not asset.get("download_allowed"):
            raise RuntimeError("Online footage is not authorized for download")
        if asset.get("provider") == "youtube":
            from agent.services import youtube_footage
            await youtube_footage.download(uri, output)
            return output
        return await _download_https(uri, output)
    if not asset.get("external_id"):
        raise RuntimeError(f"Footage has no Drive file ID: {asset.get('file_name')}")
    await asyncio.to_thread(_download_drive, asset["external_id"], output, token)
    return output


def _online_candidate_usable(candidate: dict) -> bool:
    if not candidate.get("download_allowed") or not candidate.get("download_url"):
        return False
    if candidate.get("provider") == "pexels":
        return candidate.get("license_status") == "PEXELS_LICENSE"
    return candidate.get("provider") == "youtube"


async def _online_segments(candidate: dict, work: Path, needed_s: float, limit: int,
                           downloads: dict[str, dict]) -> tuple[list[dict], str | None]:
    """Download one online candidate, let rea-video pick its usable shots.

    Returns timeline-ready asset dicts plus a warning when REA could not verify
    the clip and the fallback range was used instead.
    """
    from agent.services import rea_video_adapter
    provider = candidate["provider"]
    file_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(candidate.get("provider_file_id") or candidate["id"]))
    path = work / f"online-{provider}-{file_id}.mp4"
    meta = downloads.get(str(path))
    if meta is None:
        if not path.is_file():
            if provider == "youtube":
                from agent.services import youtube_footage
                meta = await youtube_footage.download(candidate["download_url"], path)
            else:
                await _download_https(candidate["download_url"], path)
                meta = {"license_status": candidate.get("license_status")}
        downloads[str(path)] = meta = meta or {"license_status": candidate.get("license_status")}
    warning = None
    try:
        segments = await rea_video_adapter.analyze_broll_clip(path, needed_s, limit)
        evidence = "rea-video"
    except Exception as exc:
        duration = await asyncio.to_thread(probe_duration, str(path)) or needed_s
        start = min(5.0, duration * .1)
        segments = [{"start": start, "end": min(duration, start + needed_s), "shot_index": None,
                     "method": "unknown", "confidence": None, "score": 0}]
        evidence = "fallback"
        warning = f"REA không phân tích được {candidate.get('title')}: {exc}"
    license_status = meta.get("license_status") or candidate.get("license_status")
    assets = []
    for segment in segments:
        assets.append({
            "id": f"{provider}:{file_id}:{segment['shot_index'] or 0}",
            "candidate_id": candidate["id"], "provider": provider, "external_id": candidate.get("provider_file_id"),
            "file_name": path.name, "uri": candidate["download_url"], "download_url": candidate["download_url"],
            "download_allowed": True, "license_status": license_status, "local_path": str(path),
            "source_url": candidate.get("source_url"), "title": candidate.get("title"),
            "usable_ranges_json": json.dumps([{"start": segment["start"], "end": segment["end"]}]),
            "source_start_s": segment["start"], "source_end_s": segment["end"],
            "timestamp_evidence": (f"{evidence} shot {segment['shot_index']} ({segment['method']}, "
                                   f"confidence {segment['confidence']}, score {segment['score']})"
                                   if evidence == "rea-video" else "Fallback range; rea-video unavailable"),
        })
    return assets, warning


def _usable_start(asset: dict) -> float:
    try:
        explicit = asset.get("source_start_s")
        if explicit is not None:
            return max(0.0, float(explicit))
    except (ValueError, TypeError):
        pass
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
        audio = ["-map", "0:v", "-map", "1:a", "-af", "volume=1.188,apad", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio = ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30"
    cmd += ["-t", str(duration), "-vf", vf, *audio, "-c:v", "libx264", "-preset", "fast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    await _run_process(*cmd)


async def _make_scene_montage(sources: list[tuple[Path, float]], voice: Path | None,
                              output: Path, duration: float, vertical: bool,
                              work: Path) -> None:
    """Cut several visual shots, then lay one uninterrupted voice track over them."""
    shot_duration = duration / max(1, len(sources))
    shots = []
    for index, (source, start) in enumerate(sources, 1):
        shot = work / f"{output.stem}-shot-{index:02}.mp4"
        await _make_scene_clip(source, None, shot, shot_duration, start, vertical)
        shots.append(str(shot))
    visual = work / f"{output.stem}-visual.mp4"
    if not await asyncio.to_thread(merge_videos, shots, str(visual)):
        raise RuntimeError("FFmpeg could not merge scene B-roll")
    if not voice or not voice.is_file():
        shutil.copy2(visual, output); return
    await _run_process(
        _ffmpeg_bin(), "-y", "-i", str(visual), "-i", str(voice), "-t", str(duration),
        "-map", "0:v", "-map", "1:a", "-af", "volume=1.188,apad", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    )


def _srt_time(seconds: float) -> str:
    millis = round(seconds * 1000); hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000); secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


async def _burn_subtitles(video: Path, scenes: list[dict], output: Path, work: Path) -> Path:
    srt = work / "subtitles.srt"; blocks = []
    for index, scene in enumerate(scenes, 1):
        text = (scene.get("narration_text") or scene.get("on_screen_text") or "").strip()
        if text:
            lines = textwrap.wrap(text, width=30, break_long_words=False, break_on_hyphens=False)
            text = "\n".join(lines[:2])
            blocks.append(f"{index}\n{_srt_time(float(scene['start_time_s']))} --> {_srt_time(float(scene['end_time_s']))}\n{text}\n")
    if not blocks:
        shutil.copy2(video, output); return output
    srt.write_text("\n".join(blocks), encoding="utf-8")
    escaped = srt.as_posix().replace(":", "\\:").replace("'", "\\'")
    font = Path(config.HBG_TEXT_FONT_PATH).as_posix().replace(":", "\\:").replace("'", "\\'")
    hotline = config.HBG_HOTLINE.replace("'", "\\'").replace(":", "\\:")
    # libass uses its default 288px-tall script space for SRT styles. At
    # 1080x1920, FontSize=6 and MarginV=65 render at roughly 40px with the
    # first subtitle line starting around y=1405.
    subtitle_style = "FontName=Arial,FontSize=6,Bold=-1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,Alignment=2,MarginV=65"
    vf = (f"subtitles='{escaped}':force_style='{subtitle_style}',"
          f"drawtext=fontfile='{font}':text='{hotline}':fontcolor=#d9a65a:fontsize=30:"
          "box=1:boxcolor=#253E89@0.92:boxborderw=10:x=(w-text_w)/2:y=1360-text_h/2")
    await _run_process(_ffmpeg_bin(), "-y", "-i", str(video), "-vf", vf,
                       "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-preset", "slow",
                       "-b:v", config.HBG_VIDEO_BITRATE, "-maxrate", config.HBG_VIDEO_MAXRATE,
                       "-bufsize", "40M", "-pix_fmt", "yuv420p", "-r", "30",
                       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output))
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
        """SELECT j.*,r.scenes_json,r.assets_json,r.rule_version_id,r.rule_hash,
                  rv.content AS rule_content,rv.content_hash AS stored_rule_hash,
                  p.name AS profile_name,p.brand,p.profile_type,p.language,
                  p.voice_provider,p.voice_id,p.tone,p.logo_path,p.logo_position,
                  vt.title AS topic_title,vt.brief,vt.orientation,vt.reference_analysis_id,
                  vt.footage_folder_url,vt.source_tab_name,
                  p.music_path,p.rules_json
           FROM production_jobs j JOIN production_revisions r ON r.id=j.current_revision_id
           JOIN rule_versions rv ON rv.id=r.rule_version_id
           JOIN production_profile p ON p.id=j.profile_id
           JOIN video_topics vt ON vt.id=j.video_topic_id WHERE j.id=?""", (job_id,))).fetchone()
    if not row or row["status"] == "CANCELLED": return
    data = dict(row); scenes = json.loads(data["scenes_json"]); rules = json.loads(data.get("rules_json") or "{}")
    footage_mode = data.get("footage_mode") or "HYBRID"
    from agent.services import youtube_footage
    online_available = (config.FOOTAGE_INTERNAL_ENABLED or
                        (config.FOOTAGE_EXTERNAL_ENABLED and bool(config.PEXELS_API_KEY)) or
                        youtube_footage.available())
    if not online_available:
        message = "Chưa có nguồn footage Internet (YouTube/Pexels)"
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
        await update_production_progress(job_id, "VOICE", "PROCESSING",
                                         "Đang hiệu chỉnh kịch bản theo Profile Rule", 13)
        from agent.services.production_rule_compliance import apply_profile_rule, verify_rule_snapshot
        verified_rule_hash = verify_rule_snapshot(
            data.get("rule_content"), data.get("rule_hash"), data.get("stored_rule_hash"))
        scenes, compliance = await apply_profile_rule(
            scenes, data["rule_content"], verified_rule_hash, {
                "profile_name": data.get("profile_name"),
                "brand": data.get("brand"),
                "profile_type": data.get("profile_type"),
                "language": data.get("language"),
                "topic_title": data.get("topic_title") or data.get("title"),
                "brief": data.get("brief"),
                "source_tab_name": data.get("source_tab_name"),
                "orientation": data.get("orientation"),
                "voice_provider": data.get("voice_provider"),
                "voice_id": data.get("voice_id"),
                "has_footage_folder": bool(data.get("footage_folder_url")),
                "has_logo": bool(data.get("logo_path")),
                "has_music": bool(data.get("music_path")),
            })
        revision_assets = json.loads(data.get("assets_json") or "{}")
        revision_assets["profile_rule_compliance"] = {
            "rule_version_id": data["rule_version_id"],
            "rule_hash": verified_rule_hash,
            "approved": True,
            "summary": compliance.get("summary") or "",
            "warnings": compliance.get("warnings") or [],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.execute(
            "UPDATE production_revisions SET scenes_json=?,assets_json=? WHERE id=?",
            (json.dumps(scenes, ensure_ascii=False), json.dumps(revision_assets, ensure_ascii=False),
             data["current_revision_id"]),
        )
        await db.execute(
            "INSERT INTO production_audit_events(id,production_job_id,revision_id,action,detail_json,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), job_id, data["current_revision_id"], "PROFILE_RULE_APPROVED",
             json.dumps(revision_assets["profile_rule_compliance"], ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
        await update_production_progress(job_id, "VOICE", "PROCESSING",
                                         "Profile Rule đã duyệt và hiệu chỉnh kịch bản", 14)
        voice_provider = (data.get("voice_provider") or "openai").lower()
        await update_production_progress(job_id, "VOICE", "PROCESSING", f"Đang tạo voice-over bằng {voice_provider}", 15)
        voices = []
        for index, scene in enumerate(scenes, 1):
            path = work / f"voice-{index:03}.wav"; text = scene.get("narration_text") or ""
            if not path.is_file() and text.strip():
                await _tts(text, path, voice_provider, data.get("voice_id") or "marin", data.get("tone"))
            voices.append(path if path.is_file() else None)
            await update_production_progress(job_id, "VOICE", "PROCESSING", f"Voice {index}/{len(scenes)}", 15 + round(index / len(scenes) * 10))
            await _check_cancelled(job_id)
        # Approved The HBG reel cadence: VO stays at x1 with 0.15-0.4s pauses.
        pause_s = max(0.15, min(0.4, float(rules.get("scene_pause_s", .4))))
        cursor = 0.0
        for scene, voice in zip(scenes, voices):
            measured = await asyncio.to_thread(probe_duration, str(voice)) if voice else None
            duration = (measured + pause_s) if measured else float(scene["duration_s"])
            scene.update({"start_time_s": cursor, "duration_s": duration,
                          "end_time_s": cursor + duration, "voice_duration_s": measured or 0,
                          "voice_pause_s": pause_s if measured else 0})
            cursor += duration
        await db.execute("UPDATE production_revisions SET scenes_json=? WHERE id=?",
                         (json.dumps(scenes, ensure_ascii=False), data["current_revision_id"])); await db.commit()
        # Script and measured voice timing are ready. Refresh/classify Drive
        # now so footage selection follows the actual narration.
        internal_source_ids = []
        if footage_mode in {"DRIVE_ONLY", "HYBRID"} and data.get("footage_folder_url"):
            await update_production_progress(job_id, "FOOTAGE", "PROCESSING",
                                             "Refreshing and classifying Drive footage", 26)
            try:
                from agent.services.video_footage_pipeline import classify_video_footage, _source_for_topic
                await asyncio.wait_for(
                    classify_video_footage(data["video_topic_id"]),
                    timeout=config.DRIVE_FOOTAGE_TIMEOUT_S + 5,
                )
                source = await _source_for_topic({
                    "id": data["video_topic_id"], "profile_id": data["profile_id"],
                    "source_tab_name": data.get("source_tab_name") or data["title"],
                    "footage_folder_url": data["footage_folder_url"],
                })
                internal_source_ids = [source["id"]]
            except Exception as drive_exc:
                if footage_mode == "DRIVE_ONLY":
                    raise
                await update_production_progress(job_id, "FOOTAGE", "PROCESSING",
                                                 f"Drive unavailable; using Internet fallback: {drive_exc}", 27)
        elif footage_mode == "DRIVE_ONLY":
            raise RuntimeError("100% Drive mode requires a footage folder in the video tab")
        await update_production_progress(job_id, "VOICE", "COMPLETED", "Đã tạo voice-over", 25)

        mode_label = {"DRIVE_ONLY": "100% Drive", "INTERNET_ONLY": "100% Internet"}.get(
            footage_mode, "Drive + Internet")
        await update_production_progress(job_id, "FOOTAGE", "PROCESSING",
                                         f"Đang tìm footage theo voice ({mode_label})", 28)
        reference_shots = []
        if data.get("reference_analysis_id"):
            reference_shots = [dict(item) for item in await (await db.execute(
                """SELECT * FROM reference_video_shots WHERE analysis_id=?
                   AND reviewer_status<>'REJECTED' ORDER BY order_index""",
                (data["reference_analysis_id"],))).fetchall()]
        from agent.services.footage_research import research_production_scenes
        preference = {"DRIVE_ONLY": "internal_only", "INTERNET_ONLY": "external_only"}.get(
            footage_mode, "internal_first")
        if footage_mode == "HYBRID" and not internal_source_ids:
            preference = "external_only"
        research = await research_production_scenes(
            data["profile_id"], scenes,
            "9:16" if data.get("orientation") == "VERTICAL" else "16:9",
            reference_shots, preference=preference,
            internal_source_ids=internal_source_ids or None,
        )
        research_by_order = {shot["order_index"]: shot.get("candidates") or []
                             for shot in research.get("shots", [])}
        asset_ids = {item["asset_id"] for candidates in research_by_order.values()
                     for item in candidates if item.get("asset_id")}
        internal_assets = {}
        if asset_ids:
            rows = await (await db.execute(
                f"SELECT * FROM footage_asset WHERE id IN ({','.join('?' for _ in asset_ids)}) "
                "AND status IN ('READY','DISCOVERED')", tuple(asset_ids))).fetchall()
            internal_assets = {row["id"]: dict(row) for row in rows}
        chosen = []; chosen_candidate_ids = []; used = set(); downloads: dict[str, dict] = {}
        for scene_index, scene in enumerate(scenes, 1):
            scene_order = int(scene.get("scene_order") or len(chosen) + 1)
            shot_count = max(1, min(4, round(float(scene["duration_s"]) / 3.5)))
            candidates = research_by_order.get(scene_order, [])
            internal_candidates = [item for item in candidates
                                   if item.get("asset_id") in internal_assets]
            internal_scene_assets = []
            for candidate in internal_candidates:
                asset = dict(internal_assets[candidate["asset_id"]])
                if asset["id"] in used:
                    continue
                asset["candidate_id"] = candidate["id"]
                asset["source_start_s"] = candidate.get("source_start_s")
                asset["source_end_s"] = candidate.get("source_end_s")
                asset["timestamp_evidence"] = candidate.get("timestamp_evidence")
                if candidate.get("source_start_s") is not None and candidate.get("source_end_s") is not None:
                    asset["usable_ranges_json"] = json.dumps([{
                        "start": candidate["source_start_s"],
                        "end": candidate["source_end_s"],
                        "description": candidate.get("description") or "Selected scene-matched range",
                    }], ensure_ascii=False)
                internal_scene_assets.append(asset)
                chosen_candidate_ids.append(candidate["id"])
                if len(internal_scene_assets) >= shot_count:
                    break
            online_assets = []
            online_candidates = [item for item in candidates if not item.get("asset_id") and _online_candidate_usable(item)]
            tried = 0
            for candidate in online_candidates if not internal_scene_assets else []:
                missing = shot_count - len(online_assets)
                # Past the per-scene budget, keep trying only while the scene has nothing at all.
                if missing <= 0 or (tried >= config.ONLINE_CLIPS_PER_SCENE and online_assets):
                    break
                tried += 1
                await update_production_progress(
                    job_id, "FOOTAGE", "PROCESSING",
                    f"Cảnh {scene_index}/{len(scenes)}: tải {candidate['provider']} và phân tích REA — {candidate.get('title')}",
                    28 + round((scene_index - 1) / len(scenes) * 10))
                try:
                    segments, warning = await _online_segments(
                        candidate, work, float(scene["duration_s"]) / shot_count, missing + 1, downloads)
                except asyncio.CancelledError:
                    raise
                except Exception as online_exc:
                    await update_production_progress(job_id, "FOOTAGE", "PROCESSING",
                                                     f"Bỏ qua {candidate.get('title')}: {online_exc}")
                    continue
                if warning:
                    await update_production_progress(job_id, "FOOTAGE", "PROCESSING", warning)
                fresh = [item for item in segments if item["id"] not in used][:missing]
                if fresh:
                    online_assets.extend(fresh)
                    chosen_candidate_ids.append(candidate["id"])
                    first = fresh[0]
                    await db.execute(
                        """UPDATE footage_research_candidates SET source_start_s=?,source_end_s=?,timestamp_status=?,
                           timestamp_evidence=?,license_status=? WHERE id=?""",
                        (first["source_start_s"], first["source_end_s"],
                         "VERIFIED" if first["timestamp_evidence"].startswith("rea-video") else "UNVERIFIED",
                         first["timestamp_evidence"], first["license_status"], candidate["id"]))
                    await db.commit()
                await _check_cancelled(job_id)
            scene_assets = internal_scene_assets or online_assets[:shot_count]
            if not scene_assets:
                status = research.get("provider_status") or {}
                raise RuntimeError(f"Không tìm được footage dùng được cho cảnh {scene_index} "
                                   f"({len(online_candidates)} kết quả, nguồn: {status})")
            chosen.append(scene_assets); used.update(asset["id"] for asset in scene_assets)
        if research and chosen_candidate_ids:
            await db.execute(
                f"UPDATE footage_research_candidates SET selected=1 WHERE id IN ({','.join('?' for _ in chosen_candidate_ids)})",
                chosen_candidate_ids)
            await db.commit()
        await update_production_progress(
            job_id, "FOOTAGE", "COMPLETED", f"Đã chọn footage ({mode_label}) cho {len(scenes)} cảnh", 38)

        # Internet footage is already on disk; the Drive token is only needed for Drive assets.
        needs_drive = any(asset.get("uri", "").startswith("gdrive://") for assets in chosen for asset in assets)
        if needs_drive:
            from agent.services.google_oauth import get_valid_access_token
            token = await get_valid_access_token()
        else:
            token = ""
        clips = []
        await update_production_progress(job_id, "TIMELINE", "PROCESSING", "Đang tải, cắt và dựng timeline", 40)
        for index, (scene, scene_assets, voice) in enumerate(zip(scenes, chosen, voices), 1):
            sources = []
            for asset in scene_assets:
                suffix = Path(asset["file_name"]).suffix or ".mp4"
                safe_source_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(asset.get("external_id") or asset["id"]))
                source = work / f"source-{safe_source_id}{suffix}"
                source = await _materialize_asset(asset, source, token); sources.append((source, _usable_start(asset)))
            clip = work / f"scene-{index:03}.mp4"
            await _make_scene_montage(sources, voice, clip, float(scene["duration_s"]),
                                      data.get("orientation") == "VERTICAL", work)
            clips.append(str(clip)); await update_production_progress(job_id, "TIMELINE", "PROCESSING", f"Đã dựng cảnh {index}/{len(scenes)}", 40 + round(index / len(scenes) * 20)); await _check_cancelled(job_id)
        merged = work / "timeline.mp4"
        if not await asyncio.to_thread(merge_videos, clips, str(merged)): raise RuntimeError("FFmpeg could not merge scene timeline")
        await update_production_progress(job_id, "TIMELINE", "COMPLETED", "Đã ghép timeline", 62)

        await update_production_progress(job_id, "BRANDING", "PROCESSING", "Đang chèn logo và nhạc", 65)
        branded = await _overlay_logo(merged, data.get("logo_path"), data.get("logo_position") or "top-right", work / "branded.mp4")
        music = data.get("music_path")
        if music and Path(music).is_file():
            mixed = work / "branded-music.mp4"
            if not await asyncio.to_thread(add_music, str(branded), music, str(mixed), float(rules.get("music_volume", .106))): raise RuntimeError("Could not mix background music")
            branded = mixed
        await update_production_progress(job_id, "BRANDING", "COMPLETED", "Đã xử lý logo và nhạc", 72)

        await update_production_progress(job_id, "SUBTITLES", "PROCESSING", "Đang tạo và chèn phụ đề", 75)
        subtitled = await _burn_subtitles(branded, scenes, work / "subtitled.mp4", work)
        await update_production_progress(job_id, "SUBTITLES", "COMPLETED", "Đã chèn phụ đề", 82)
        await _check_cancelled(job_id)

        await update_production_progress(job_id, "RENDER", "PROCESSING", "Đang render video thành phẩm", 85)
        final = work / "final.mp4"; shutil.copy2(subtitled, final)
        outro = Path(config.HBG_OUTRO_PATH).expanduser() if config.HBG_OUTRO_PATH else None
        if outro and outro.is_file():
            with_outro = work / "final-with-outro.mp4"
            if not await asyncio.to_thread(merge_videos, [str(final), str(outro)], str(with_outro)):
                raise RuntimeError("Could not append HBG outro")
            shutil.copy2(with_outro, final)
        revision_assets["final_video_path"] = str(final)
        revision_assets["footage_research_job_id"] = (research or {}).get("id")
        revision_assets["reference_analysis_id"] = data.get("reference_analysis_id")
        revision_assets["scene_footage"] = [{"scene_order": scene["scene_order"], "assets":
            [{"asset_id": asset["id"], "file_id": asset.get("external_id"),
              **({"provider": asset["provider"], "source_url": asset.get("source_url"),
                  "source_start_s": asset.get("source_start_s"), "source_end_s": asset.get("source_end_s"),
                  "license_status": asset.get("license_status"), "evidence": asset.get("timestamp_evidence")}
                 if asset.get("provider") else {})} for asset in scene_assets]}
            for scene, scene_assets in zip(scenes, chosen)]
        await db.execute("UPDATE production_revisions SET assets_json=? WHERE id=?", (json.dumps(revision_assets, ensure_ascii=False), data["current_revision_id"])); await db.commit()
        await update_production_progress(job_id, "CAPCUT_EXPORT", "PROCESSING", "Đang tạo project CapCut có thể chỉnh sửa", 88)
        try:
            from agent.services.capcut_export import export_capcut_draft
            capcut_draft = await export_capcut_draft(
                job_id, data.get("title") or "Video", work, scenes, data.get("orientation") or "HORIZONTAL",
                data.get("music_path"), float(rules.get("music_volume", .106)),
            )
            revision_assets["capcut_draft_path"] = str(capcut_draft)
            await db.execute("UPDATE production_revisions SET assets_json=? WHERE id=?",
                             (json.dumps(revision_assets, ensure_ascii=False), data["current_revision_id"]))
            await db.execute("UPDATE production_jobs SET capcut_draft_path=?,capcut_error=NULL WHERE id=?",
                             (str(capcut_draft), job_id)); await db.commit()
            await update_production_progress(job_id, "CAPCUT_EXPORT", "COMPLETED", "Đã tạo draft CapCut", 92)
        except Exception as capcut_exc:
            await db.execute("UPDATE production_jobs SET capcut_error=? WHERE id=?", (str(capcut_exc)[:2000], job_id)); await db.commit()
            await update_production_progress(job_id, "CAPCUT_EXPORT", "FAILED",
                                             f"Không thể tạo draft CapCut: {capcut_exc}", 92,
                                             error=str(capcut_exc))
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
