"""Isolated adapter for the pinned rea-video CLI and normalized artifacts."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from agent import config
from agent.db import crud
from agent.db.schema import get_db
from agent.services.footage_analyzer import _materialize
from agent.services.footage_scanner import probe_video

SCHEMA = "rea_video.breakdown.v1"
METHODS = {"live_action", "film_footage", "ai_video", "avatar", "cg_3d", "anim_2d",
           "stop_motion", "code_render", "screen_capture", "still_motion", "static_hold"}
_semaphore = asyncio.Semaphore(1)


def _id() -> str: return str(uuid.uuid4())
def _now() -> str: return datetime.now(timezone.utc).isoformat()


async def _rows(sql: str, args=()) -> list[dict]:
    db = await get_db(); cur = await db.execute(sql, args)
    return [dict(row) for row in await cur.fetchall()]


def runtime_status() -> dict:
    cli = config.REA_VIDEO_CLI
    return {"enabled": config.REA_VIDEO_ENABLED, "available": cli.is_file(), "cli": str(cli),
            "tool_version": config.REA_VIDEO_VERSION, "upstream_commit": config.REA_VIDEO_PINNED_COMMIT,
            "vlm_allowed": config.REA_VIDEO_ALLOW_VLM}


async def mark_interrupted_analyses() -> int:
    """Make crashed work explicitly retryable; never pretend it completed."""
    db = await get_db()
    cur = await db.execute("""UPDATE video_analyses SET status='FAILED',error_code='INTERRUPTED',
        error_message='Ứng dụng đã dừng trong lúc phân tích; hãy bấm Thử lại.',updated_at=?
        WHERE status IN ('QUEUED','PROCESSING')""", (_now(),))
    await db.commit(); return cur.rowcount


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024): digest.update(chunk)
    return digest.hexdigest()


def _nested(data: dict, *keys, default=None):
    value = data
    for key in keys:
        if not isinstance(value, dict): return default
        value = value.get(key)
    return default if value is None else value


def normalize_breakdown(data: dict, artifact_dir: Path, duration: float) -> list[dict]:
    if data.get("schema") != SCHEMA: raise ValueError(f"Unsupported rea-video schema: {data.get('schema')}")
    result = []
    previous = -1.0
    for position, raw in enumerate(data.get("shots") or [], 1):
        start = float(raw.get("start")); end = float(raw.get("end"))
        if start < 0 or end <= start or start < previous or end > duration + .25:
            raise ValueError(f"Invalid reference timecode in shot {position}: {start}-{end}")
        previous = end
        base = raw.get("base") or {}; method = base.get("label") or "unknown"
        if method not in METHODS: method = "unknown"
        vlm = raw.get("vlm") or {}; replication = raw.get("replication") or {}
        description = (vlm.get("description") or vlm.get("content") or replication.get("description") or
                       replication.get("prompt") or base.get("label_zh") or method)
        assets = raw.get("assets") or {}; thumbnail = assets.get("sheet") or assets.get("first_frame")
        thumb_path = str((artifact_dir / thumbnail).resolve()) if thumbnail else None
        result.append({"order_index": int(raw.get("index") or position), "reference_start_s": start,
            "reference_end_s": end, "visual_description": str(description)[:4000], "production_method": method,
            "confidence": float(base["confidence"]) if base.get("confidence") is not None else None,
            "evidence_json": json.dumps(base.get("evidence") or _nested(raw, "deterministic", "evidence", default=[]), ensure_ascii=False),
            "camera_json": json.dumps(_nested(raw, "aspects", "camera", default={}), ensure_ascii=False),
            "lighting_json": json.dumps(_nested(raw, "aspects", "lighting", default={}), ensure_ascii=False),
            "overlays_json": json.dumps({"overlay": raw.get("overlay"), "text": raw.get("text")}, ensure_ascii=False),
            "audio_notes_json": json.dumps(raw.get("audio") or {}, ensure_ascii=False), "thumbnail_path": thumb_path,
            "reviewer_status": "NEEDS_REVIEW" if (base.get("confidence") or 0) < .75 or base.get("disputed") else "UNREVIEWED",
            "raw_json": json.dumps(raw, ensure_ascii=False)})
    if not result: raise ValueError("rea-video returned no shots")
    return result


async def _decompose(source: Path, artifact_dir: Path, use_vlm: bool) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command = [str(config.REA_VIDEO_CLI)]
    if use_vlm and config.REA_VIDEO_ENV_FILE: command += ["--env-file", config.REA_VIDEO_ENV_FILE]
    command += ["decompose", str(source), "-o", str(artifact_dir), "--lang", "en",
                "--workers", str(config.REA_VIDEO_WORKERS)]
    command += ["--vlm"] if use_vlm else ["--no-vlm"]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "REA_VIDEO_HOME": str((config.OUTPUT_DIR / "_shared" / "rea-video-home").resolve())}
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE, env=env)
    try: stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=config.REA_VIDEO_TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        process.kill(); await process.wait()
        if isinstance(exc, asyncio.CancelledError): raise
        raise TimeoutError("REA Video analysis timed out")
    if process.returncode:
        message = (stderr or stdout).decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"REA Video exited with code {process.returncode}: {message}")


# B-roll suitability per rea-video production label. Labels outside this map
# (screen capture, code/template render, avatar, static hold...) are rejected.
# Without a VLM, real drone/landscape footage is often labelled ai_video, so it
# is down-weighted instead of rejected.
BROLL_METHOD_WEIGHT = {"live_action": 1.0, "film_footage": .9, "ai_video": .6, "cg_3d": .5,
                       "still_motion": .35, "unknown": .3}


def _overlay_area(raw: dict) -> float:
    area = 0.0
    for box in (raw.get("overlay") or {}).get("boxes") or []:
        bbox = box.get("bbox") or []
        if len(bbox) == 4: area += max(0.0, float(bbox[2])) * max(0.0, float(bbox[3]))
    return area


def score_broll_shot(raw: dict, needed_s: float) -> float | None:
    base = raw.get("base") or {}
    weight = BROLL_METHOD_WEIGHT.get(base.get("label") or "unknown")
    duration = float(raw["end"]) - float(raw["start"])
    if weight is None or duration < min(1.5, needed_s):
        return None
    text_coverage = float((raw.get("text") or {}).get("text_coverage") or 0)
    length_ratio = min(1.0, duration / max(needed_s, .1))
    score = (.45 * weight + .35 * length_ratio + .2 * float(base.get("confidence") or 0)
             - min(1.0, text_coverage * 6) - min(.4, _overlay_area(raw) * 4))
    return round(score, 4) if score > 0 else None


def pick_broll_segments(data: dict, needed_s: float, limit: int) -> list[dict]:
    """Best non-text, real-footage shots of a candidate clip, in score order."""
    if data.get("schema") != SCHEMA: raise ValueError(f"Unsupported rea-video schema: {data.get('schema')}")
    scored = []
    for raw in data.get("shots") or []:
        score = score_broll_shot(raw, needed_s)
        if score is None: continue
        start, end = float(raw["start"]), float(raw["end"])
        # Skip the frames nearest a cut so transitions do not leak into the clip.
        trim = .15 if end - start > 1.5 else 0
        base = raw.get("base") or {}
        scored.append({"start": round(start + trim, 3), "end": round(end - trim, 3), "score": score,
                       "shot_index": raw.get("index"), "method": base.get("label") or "unknown",
                       "confidence": base.get("confidence")})
    return sorted(scored, key=lambda item: item["score"], reverse=True)[:max(1, limit)]


async def analyze_broll_clip(source: Path, needed_s: float, limit: int) -> list[dict]:
    """Run rea-video on a downloaded candidate clip and return usable segments."""
    if not config.REA_VIDEO_ENABLED: raise RuntimeError("REA Video is disabled")
    if not config.REA_VIDEO_CLI.is_file(): raise FileNotFoundError(f"REA Video CLI not found: {config.REA_VIDEO_CLI}")
    digest = await asyncio.to_thread(_sha256, source)
    artifact_dir = (config.REA_VIDEO_OUTPUT_DIR / "broll" / digest[:32]).resolve()
    breakdown = artifact_dir / "breakdown.json"
    if not breakdown.is_file():
        async with _semaphore:
            if not breakdown.is_file():
                await _decompose(source, artifact_dir, False)
    data = json.loads(breakdown.read_text(encoding="utf-8"))
    return pick_broll_segments(data, needed_s, limit)


async def create_analysis(source_asset_id: str, title: str | None, purpose: str, language: str,
                          use_vlm: bool, force: bool = False) -> dict:
    if not config.REA_VIDEO_ENABLED: raise ValueError("REA Video is disabled")
    if use_vlm and not config.REA_VIDEO_ALLOW_VLM:
        raise ValueError("VLM transmission is not allowed; enable REA_VIDEO_ALLOW_VLM explicitly")
    asset = await crud.get_footage_asset(source_asset_id)
    if not asset: raise ValueError("Footage asset not found")
    if not (asset["uri"].startswith("file:") or asset["uri"].startswith("gdrive://")):
        raise ValueError("Only authorized local or Google Drive assets can be analyzed")
    config_data = {"purpose": purpose, "language": language, "use_vlm": use_vlm,
                   "workers": config.REA_VIDEO_WORKERS, "upstream_commit": config.REA_VIDEO_PINNED_COMMIT}
    now = _now(); analysis_id = _id(); db = await get_db()
    await db.execute("""INSERT INTO video_analyses
        (id,source_asset_id,profile_id,title,purpose,language,use_vlm,status,upstream_commit,tool_version,
         analysis_config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'QUEUED',?,?,?,?,?)""",
        (analysis_id, source_asset_id, asset["profile_id"], title or asset["file_name"], purpose, language,
         int(use_vlm), config.REA_VIDEO_PINNED_COMMIT, config.REA_VIDEO_VERSION,
         json.dumps(config_data), now, now))
    await db.commit(); return (await _rows("SELECT * FROM video_analyses WHERE id=?", (analysis_id,)))[0]


async def run_analysis(analysis_id: str) -> None:
    rows = await _rows("SELECT va.*,fa.uri,fa.file_name FROM video_analyses va JOIN footage_asset fa ON fa.id=va.source_asset_id WHERE va.id=?", (analysis_id,))
    if not rows: return
    row = rows[0]; db = await get_db(); now = _now()
    await db.execute("UPDATE video_analyses SET status='PROCESSING',progress=5,started_at=?,updated_at=?,error_code=NULL,error_message=NULL WHERE id=?", (now, now, analysis_id)); await db.commit()
    temp_dir = Path(tempfile.mkdtemp(prefix="hbg-rea-video-")); artifact_dir = (config.REA_VIDEO_OUTPUT_DIR / analysis_id).resolve()
    try:
        if not config.REA_VIDEO_CLI.is_file(): raise FileNotFoundError(f"REA Video CLI not found: {config.REA_VIDEO_CLI}")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): raise RuntimeError("FFmpeg/FFprobe is not available")
        async with _semaphore:
            asset = await crud.get_footage_asset(row["source_asset_id"]); source = await _materialize(asset, temp_dir)
            if source.stat().st_size > config.REA_VIDEO_MAX_INPUT_MB * 1024 * 1024: raise ValueError("Reference video exceeds configured size limit")
            metadata = await probe_video(source); duration = float(metadata.get("duration_s") or 0)
            if duration <= 0 or duration > config.REA_VIDEO_MAX_DURATION_S: raise ValueError("Reference video duration is invalid or exceeds configured limit")
            digest = await asyncio.to_thread(_sha256, source)
            cache_key = hashlib.sha256(f"{digest}:{row['analysis_config_json']}:{config.REA_VIDEO_PINNED_COMMIT}".encode()).hexdigest()
            cached = await _rows("SELECT * FROM video_analyses WHERE cache_key=? AND status='COMPLETED' AND id<>? ORDER BY completed_at DESC LIMIT 1", (cache_key, analysis_id))
            if cached and cached[0].get("artifact_dir") and Path(cached[0]["artifact_dir"]).is_dir():
                if artifact_dir.exists(): shutil.rmtree(artifact_dir)
                await asyncio.to_thread(shutil.copytree, cached[0]["artifact_dir"], artifact_dir)
            else:
                await _decompose(source, artifact_dir, bool(row["use_vlm"]))
            breakdown_path = artifact_dir / "breakdown.json"
            data = json.loads(breakdown_path.read_text(encoding="utf-8")); shots = normalize_breakdown(data, artifact_dir, duration)
            await db.execute("DELETE FROM reference_video_shots WHERE analysis_id=?", (analysis_id,))
            for shot in shots:
                columns = ["id", "analysis_id"] + list(shot.keys()); values = [_id(), analysis_id] + list(shot.values())
                await db.execute(f"INSERT INTO reference_video_shots({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values)
            summary = {"source": data.get("source"), "summary": data.get("summary"), "analysis": data.get("analysis")}
            completed = _now(); await db.execute("""UPDATE video_analyses SET status='COMPLETED',progress=100,source_sha256=?,cache_key=?,
                summary_json=?,artifact_dir=?,breakdown_path=?,report_html_path=?,report_md_path=?,storyboard_path=?,completed_at=?,updated_at=? WHERE id=?""",
                (digest, cache_key, json.dumps(summary, ensure_ascii=False), str(artifact_dir), str(breakdown_path),
                 str(artifact_dir / "report.html"), str(artifact_dir / "report.md"), str(artifact_dir / "storyboard.jpg"), completed, completed, analysis_id)); await db.commit()
    except asyncio.CancelledError:
        await db.execute("UPDATE video_analyses SET status='CANCELLED',error_code='CANCELLED',updated_at=? WHERE id=?", (_now(), analysis_id)); await db.commit(); raise
    except Exception as exc:
        code = "TIMEOUT" if isinstance(exc, TimeoutError) else "ANALYSIS_FAILED"
        await db.execute("UPDATE video_analyses SET status='FAILED',error_code=?,error_message=?,updated_at=? WHERE id=?", (code, str(exc)[:4000], _now(), analysis_id)); await db.commit()
    finally: shutil.rmtree(temp_dir, ignore_errors=True)


async def get_analysis(analysis_id: str) -> dict:
    rows = await _rows("SELECT * FROM video_analyses WHERE id=?", (analysis_id,))
    if not rows: raise ValueError("Video analysis not found")
    item = rows[0]
    for key in ("analysis_config_json", "summary_json"):
        try: item[key.removesuffix("_json")] = json.loads(item.pop(key) or "{}")
        except ValueError: item[key.removesuffix("_json")] = {}
    item["shots"] = await _rows("SELECT * FROM reference_video_shots WHERE analysis_id=? ORDER BY order_index", (analysis_id,))
    return item


async def review_shot(analysis_id: str, shot_id: str, status: str, notes: str | None,
                      method: str | None, start: float | None, end: float | None) -> dict:
    rows = await _rows("SELECT * FROM reference_video_shots WHERE id=? AND analysis_id=?", (shot_id, analysis_id))
    if not rows: raise ValueError("Reference shot not found")
    shot = rows[0]; actual_start = start if start is not None else shot["reference_start_s"]; actual_end = end if end is not None else shot["reference_end_s"]
    if actual_start < 0 or actual_end <= actual_start: raise ValueError("Invalid reference time range")
    if method and method not in METHODS: raise ValueError("Unknown production method")
    db = await get_db(); await db.execute("UPDATE reference_video_shots SET reviewer_status=?,reviewer_notes=?,manual_method=?,manual_start_s=?,manual_end_s=? WHERE id=?",
        (status, notes, method, start, end, shot_id)); await db.commit()
    return (await _rows("SELECT * FROM reference_video_shots WHERE id=?", (shot_id,)))[0]


async def create_search_brief(analysis_id: str, shot_id: str) -> dict:
    analysis = await get_analysis(analysis_id); shot = next((x for x in analysis["shots"] if x["id"] == shot_id), None)
    if not shot: raise ValueError("Reference shot not found")
    from agent.services import footage_research
    duration = (shot.get("manual_end_s") or shot["reference_end_s"]) - (shot.get("manual_start_s") or shot["reference_start_s"])
    brief = (shot.get("visual_description") or "") + f"\nProduction method: {shot.get('manual_method') or shot['production_method']}"
    job = await footage_research.create_job(analysis.get("profile_id"), brief, max(5, duration),
                                             _nested(analysis, "summary", "source", "aspect_ratio", default="9:16"), "internal_first")
    await footage_research.analyze_job(job["id"])
    db = await get_db(); await db.execute("INSERT INTO reference_shot_search_links(id,reference_shot_id,footage_research_job_id,created_at) VALUES(?,?,?,?)",
                                          (_id(), shot_id, job["id"], _now())); await db.commit()
    return await footage_research.get_job(job["id"])


async def export_analysis(analysis_id: str) -> Path:
    analysis = await get_analysis(analysis_id); root = config.REA_VIDEO_OUTPUT_DIR / f"{analysis_id}-export"
    if root.exists(): shutil.rmtree(root)
    root.mkdir(parents=True); (root / "thumbnails").mkdir()
    breakdown = Path(analysis["breakdown_path"]); shutil.copy2(breakdown, root / "breakdown.json")
    report = Path(analysis["report_html_path"])
    if report.is_file(): shutil.copy2(report, root / "reference_report.html")
    import csv
    columns = ["scene_order", "reference_start_seconds", "reference_end_seconds", "desired_duration_seconds",
               "visual_brief", "production_method", "rights_status", "reviewer_status", "notes"]
    with (root / "shotlist.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns); writer.writeheader()
        for shot in analysis["shots"]:
            start = shot.get("manual_start_s") if shot.get("manual_start_s") is not None else shot["reference_start_s"]
            end = shot.get("manual_end_s") if shot.get("manual_end_s") is not None else shot["reference_end_s"]
            writer.writerow({"scene_order": shot["order_index"], "reference_start_seconds": start,
                "reference_end_seconds": end, "desired_duration_seconds": round(end-start, 3),
                "visual_brief": shot.get("visual_description") or "", "production_method": shot.get("manual_method") or shot["production_method"],
                "rights_status": "REFERENCE_ONLY", "reviewer_status": shot["reviewer_status"], "notes": shot.get("reviewer_notes") or ""})
            thumb = Path(shot["thumbnail_path"]) if shot.get("thumbnail_path") else None
            if thumb and thumb.is_file(): shutil.copy2(thumb, root / "thumbnails" / f"{shot['order_index']:03d}.jpg")
    (root / "README.txt").write_text("Reference analysis only. Reference timecodes are not replacement-footage timecodes. Use footage search to select owned/licensed media.\n", encoding="utf-8")
    archive = config.REA_VIDEO_OUTPUT_DIR / f"{analysis_id}-export.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in root.rglob("*"):
            if path.is_file(): bundle.write(path, path.relative_to(root))
    return archive
