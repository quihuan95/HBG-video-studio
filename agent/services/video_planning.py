"""Spreadsheet-tab video plans and production job domain logic."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone

import httpx

from agent import config
from agent.db.schema import get_db
from agent.services.google_oauth import get_valid_access_token
from agent.services.content_planning import latest_rule


def _id(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc).isoformat()
def _hash(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def _rows(sql: str, args=()):
    db = await get_db(); cur = await db.execute(sql, args)
    return [dict(row) for row in await cur.fetchall()]


def spreadsheet_id(value: str) -> str:
    match = re.search(r"/spreadsheets/d/([\w-]+)", value or "")
    result = match.group(1) if match else (value or "").strip()
    if not re.fullmatch(r"[\w-]+", result): raise ValueError("Invalid Google Spreadsheet ID or URL")
    return result


def _key(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    raw = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


# Sheet columns: THỜI LƯỢNG | VOICE | TEXT TRÊN VIDEO | HÌNH ẢNH / GỢI Ý DỰNG.
# Older headers are still mapped so previously synced tabs keep parsing.
HEADER_MAP = {
    "thoi_luong": "timecode", "voice": "narration_text", "text_tren_video": "on_screen_text",
    "hinh_anh_goi_y_dung": "visual_intent",
    "phan": "section", "shot": "shot_code", "timecode": "timecode",
    "hinh_anh_de_xuat": "visual_intent", "text_on_screen": "on_screen_text",
    "voice_over_vi_loi_doc_tieng_viet": "narration_text", "voice_over": "narration_text",
    "cach_dung": "editing_instruction", "tu_lieu_tham_khao": "footage_references",
    "am_thanh": "audio_instruction", "ghi_chu": "notes",
}
SCENE_FIELDS = {"section", "shot_code", "timecode", "visual_intent", "on_screen_text",
                "narration_text", "editing_instruction", "footage_references", "audio_instruction", "notes"}
# A source tab is an editorial brief, not a finished script. The production
# pipeline enriches optional content, voice, visual and editing fields later.
REQUIRED = {"timecode"}


def _header_field(value: str) -> str:
    key = _key(value)
    if key.startswith("thoi_luong"): return "timecode"
    if key.startswith("text_tren_video"): return "on_screen_text"
    if key.startswith("hinh_anh_goi_y") or key.startswith("hinh_anh"): return "visual_intent"
    if key.startswith("text_on_screen"): return "on_screen_text"
    if key.startswith("voice_over_") and not key.startswith("voice_over_dich"): return "narration_text"
    if key.startswith("dich_voice_over") or key.startswith("dich_tieng_viet"): return ""
    if key.startswith("hinh_anh_de_xuat"): return "visual_intent"
    if key.startswith("cach_dung"): return "editing_instruction"
    if key.startswith("tu_lieu_tham_khao"): return "footage_references"
    if key.startswith("am_thanh"): return "audio_instruction"
    if key.startswith("ghi_chu"): return "notes"
    return HEADER_MAP.get(key, "")


def _footage_link(row: list) -> str:
    for cell in row:
        value = str(cell).strip()
        # Sheets may return A3 as a raw URL, a bare folder ID, or a
        # =HYPERLINK("url", "label") formula when valueRenderOption=FORMULA.
        url = re.search(r"https?://drive\.google\.com/[^\s\"');,]+", value, re.I)
        if url:
            return url.group(0)
        if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
            return value
    return ""


def _footage_link_from_cell(cell: dict) -> str:
    """Read a Drive link from Sheets A3 cell metadata, including rich-text links."""
    candidates = [cell.get("hyperlink")]
    entered = cell.get("userEnteredValue") or {}
    effective = cell.get("effectiveValue") or {}
    candidates.extend(entered.values())
    candidates.extend(effective.values())
    for run in cell.get("textFormatRuns") or []:
        candidates.append((((run.get("format") or {}).get("link") or {}).get("uri")))
    for run in cell.get("chipRuns") or []:
        candidates.append(((((run.get("chip") or {}).get("richLinkProperties") or {}).get("uri"))))
    return _footage_link([value for value in candidates if value])


def _seconds(value: str) -> float:
    # Accepts "6", "6s", "6 giây", "6,5s", "00:06" and "00:00:06".
    text = re.sub(r"\s*(?:s|sec|giây|giay)\s*$", "", value.strip(), flags=re.I).replace(",", ".")
    try:
        parts = [float(x) for x in text.split(":")]
    except ValueError:
        raise ValueError(f"Invalid time value: {value}") from None
    if len(parts) == 1: return parts[0]
    if len(parts) == 2: return parts[0] * 60 + parts[1]
    if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid time value: {value}")


def _timecode(value: str) -> tuple[float, float]:
    parts = re.split(r"\s*[-–—]\s*", value.strip())
    if len(parts) != 2: raise ValueError(f"Invalid timecode: {value}")
    start, end = _seconds(parts[0]), _seconds(parts[1])
    if start < 0 or end <= start: raise ValueError(f"Invalid timecode range: {value}")
    return start, end


def parse_video_tab(values: list[list], tab_name: str) -> dict:
    title = str(values[0][0]).strip() if values and values[0] else tab_name
    brief = str(values[1][0]).strip() if len(values) > 1 and values[1] else ""
    if len(values) < 3: raise ValueError(f"Tab '{tab_name}' must contain title, brief and headers")
    footage_folder_url = _footage_link(values[2]) if len(values) > 2 else ""
    header_index = 3 if footage_folder_url else 2
    if len(values) <= header_index: raise ValueError(f"Tab '{tab_name}' has no scene headers")
    normalized = [_header_field(str(cell)) for cell in values[header_index]]
    missing = REQUIRED - set(normalized)
    if missing: raise ValueError(f"Tab '{tab_name}' is missing columns: {', '.join(sorted(missing))}")
    scenes = []; previous_end = 0.0
    for row_number, raw in enumerate(values[header_index + 1:], start=header_index + 2):
        if not any(str(cell).strip() for cell in raw): continue
        data = {normalized[i]: str(raw[i]).strip() if i < len(raw) else "" for i in range(len(normalized)) if normalized[i]}
        if not data.get("timecode"): raise ValueError(f"Tab '{tab_name}' row {row_number} has no timecode")
        start, end = _timecode(data["timecode"])
        if start < previous_end: raise ValueError(f"Tab '{tab_name}' row {row_number} overlaps the previous scene")
        previous_end = end
        scene = {"scene_order": len(scenes) + 1, "start_time_s": start, "end_time_s": end,
                 "duration_s": end - start, **{key: data.get(key, "") for key in SCENE_FIELDS if key != "timecode"}}
        scene["shot_code"] = scene["shot_code"] or f"{scene['scene_order']:02d}"
        scenes.append(scene)
    if not scenes: raise ValueError(f"Tab '{tab_name}' contains no scenes")
    orientation = "VERTICAL" if re.search(r"(?:9\s*:\s*16|vertical|dọc)", brief, re.I) else "HORIZONTAL"
    return {"title": title or tab_name, "brief": brief, "footage_folder_url": footage_folder_url,
            "orientation": orientation,
            "target_duration_s": scenes[-1]["end_time_s"], "scenes": scenes}


async def sync_spreadsheet(profile: dict) -> dict:
    source = profile.get("sheet_id_topics") or profile.get("sheet_url")
    if not source: raise ValueError("Spreadsheet URL or ID is required")
    sid = spreadsheet_id(source); token = await get_valid_access_token(); auth = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        meta_response = await client.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sid}", headers=auth,
            params={"fields": "sheets(properties(sheetId,title,index,hidden,gridProperties(rowCount,columnCount)))"})
        meta_response.raise_for_status(); sheets = meta_response.json().get("sheets", [])
        ranges = [f"'{s['properties']['title'].replace(chr(39), chr(39)*2)}'!A1:J1000" for s in sheets]
        a3_ranges = [f"'{s['properties']['title'].replace(chr(39), chr(39)*2)}'!A3" for s in sheets]
        link_response = await client.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sid}", headers=auth,
            params=[("ranges", item) for item in a3_ranges] + [("includeGridData", "true"),
                ("fields", "sheets(properties(sheetId),data(rowData(values(hyperlink,userEnteredValue,effectiveValue,textFormatRuns,chipRuns))))")])
        link_response.raise_for_status()
        a3_links = {}
        for sheet_data in link_response.json().get("sheets", []):
            data = sheet_data.get("data") or []
            rows = data[0].get("rowData", []) if data else []
            values = rows[0].get("values", []) if rows else []
            link = _footage_link_from_cell(values[0]) if values else ""
            if link:
                a3_links[int(sheet_data["properties"]["sheetId"])] = link
        values_response = await client.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values:batchGet", headers=auth,
            params=[("ranges", item) for item in ranges] + [("majorDimension", "ROWS"),
                                                            ("valueRenderOption", "FORMULA")])
        values_response.raise_for_status(); value_ranges = values_response.json().get("valueRanges", [])
    db = await get_db(); now = _now(); seen = set(); inserted = updated = archived = 0; errors = []
    for sheet, value_range in zip(sheets, value_ranges):
        props = sheet["properties"]; source_sheet_id = int(props["sheetId"]); seen.add(source_sheet_id)
        try: parsed = parse_video_tab(value_range.get("values", []), props["title"])
        except ValueError as exc: errors.append({"sheet_id": source_sheet_id, "tab": props["title"], "error": str(exc)}); continue
        if source_sheet_id in a3_links:
            parsed["footage_folder_url"] = a3_links[source_sheet_id]
        status = "ARCHIVED" if props.get("hidden") else "READY"; digest = _hash(parsed)
        old_rows = await _rows("SELECT * FROM video_topics WHERE profile_id=? AND spreadsheet_id=? AND source_sheet_id=?", (profile["id"], sid, source_sheet_id))
        if old_rows:
            old = old_rows[0]
            if old["source_hash"] != digest or old["source_tab_name"] != props["title"] or old["status"] != status:
                revision = old["source_revision"] + (old["source_hash"] != digest)
                await db.execute("UPDATE video_topics SET source_tab_name=?,title=?,brief=?,footage_folder_url=?,orientation=?,target_duration_s=?,status=?,source_revision=?,source_hash=?,updated_at=? WHERE id=?",
                    (props["title"], parsed["title"], parsed["brief"], parsed["footage_folder_url"], parsed["orientation"], parsed["target_duration_s"], status, revision, digest, now, old["id"]))
                if old["source_hash"] != digest:
                    await db.execute("DELETE FROM video_topic_scenes WHERE video_topic_id=?", (old["id"],)); await _insert_scenes(db, old["id"], parsed["scenes"])
                updated += 1
            topic_id = old["id"]
        else:
            topic_id = _id(); await db.execute("INSERT INTO video_topics(id,profile_id,spreadsheet_id,source_sheet_id,source_tab_name,title,brief,footage_folder_url,orientation,target_duration_s,status,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (topic_id, profile["id"], sid, source_sheet_id, props["title"], parsed["title"], parsed["brief"], parsed["footage_folder_url"], parsed["orientation"], parsed["target_duration_s"], status, digest, now, now)); await _insert_scenes(db, topic_id, parsed["scenes"]); inserted += 1
        if status == "ARCHIVED": archived += 1
    existing = await _rows("SELECT id,source_sheet_id FROM video_topics WHERE profile_id=? AND spreadsheet_id=?", (profile["id"], sid))
    for item in existing:
        if item["source_sheet_id"] not in seen:
            await db.execute("UPDATE video_topics SET status='ARCHIVED',updated_at=? WHERE id=?", (now, item["id"]))
            await db.execute("UPDATE production_jobs SET status='ARCHIVED',updated_at=? WHERE video_topic_id=?", (now, item["id"]))
    await db.commit()
    return {"spreadsheet_id": sid, "tabs": len(sheets), "inserted": inserted, "updated": updated, "archived": archived, "errors": errors}


async def _insert_scenes(db, topic_id: str, scenes: list[dict]):
    columns = ["section","shot_code","start_time_s","end_time_s","duration_s","visual_intent","on_screen_text","narration_text","editing_instruction","footage_references","audio_instruction","notes"]
    for scene in scenes:
        await db.execute(f"INSERT INTO video_topic_scenes(id,video_topic_id,scene_order,{','.join(columns)}) VALUES(?,?,?,{','.join('?' for _ in columns)})",
            (_id(), topic_id, scene["scene_order"], *(scene.get(c) for c in columns)))


async def list_video_topics(include_archived=False):
    where = "" if include_archived else " WHERE vt.status='READY'"
    topics = await _rows("SELECT vt.*,p.name profile_name,p.color FROM video_topics vt JOIN production_profile p ON p.id=vt.profile_id" + where + " ORDER BY vt.created_at")
    for topic in topics:
        try: topic["footage_result"] = json.loads(topic.get("footage_result_json") or "{}")
        except ValueError: topic["footage_result"] = {}
    return topics


async def create_production_job(profile: dict, video_topic_id: str, production_date=None, scheduled_time=None,
                                force: bool = False, footage_mode: str = "HYBRID"):
    topics = await _rows("SELECT * FROM video_topics WHERE id=? AND profile_id=?", (video_topic_id, profile["id"]))
    if not topics: raise ValueError("Video topic not found")
    existing = await _rows("SELECT * FROM production_jobs WHERE profile_id=? AND video_topic_id=?", (profile["id"], video_topic_id))
    if existing and not force and existing[0]["status"] != "CANCELLED": return existing[0]
    if existing and force and existing[0]["status"] in {"DRAFT", "PROCESSING", "APPROVED"}:
        raise ValueError(f"Video is still active with status {existing[0]['status']}")
    if footage_mode not in {"DRIVE_ONLY", "INTERNET_ONLY", "HYBRID"}:
        raise ValueError("Invalid footage mode")
    rule = await latest_rule(profile["id"])
    if not rule:
        raise ValueError("A published Profile Rule is required before creating a Production Job")
    topic = topics[0]; scenes = await _rows("SELECT * FROM video_topic_scenes WHERE video_topic_id=? ORDER BY scene_order", (video_topic_id,))
    production_date = production_date or topic.get("production_date")
    scheduled_time = scheduled_time or topic.get("scheduled_time")
    snapshot = {"title": topic["title"], "brief": topic["brief"], "orientation": topic["orientation"],
                "target_duration_s": topic["target_duration_s"], "production_date": production_date, "scheduled_time": scheduled_time,
                "spreadsheet_id": topic["spreadsheet_id"], "source_sheet_id": topic["source_sheet_id"],
                "footage_mode": footage_mode}
    rule_hash = rule["content_hash"] if rule else None
    now = _now(); job_id = existing[0]["id"] if existing else _id(); revision_id = _id(); revision_hash = _hash({"snapshot": snapshot, "scenes": scenes, "rule": rule_hash})
    blockers = ["voice_missing", "timeline_missing", "footage_missing", "render_missing"]
    db = await get_db()
    if existing:
        revision_number = int((await (await db.execute("SELECT COALESCE(MAX(revision),0) FROM production_revisions WHERE production_job_id=?", (job_id,))).fetchone())[0]) + 1
        await db.execute("UPDATE production_jobs SET title=?,production_date=?,scheduled_time=?,footage_mode=?,status='DRAFT',current_revision_id=?,output_drive_file_id=NULL,output_url=NULL,capcut_draft_path=NULL,capcut_error=NULL,error_stage=NULL,error_message=NULL,updated_at=? WHERE id=?",
                         (topic["title"], production_date, scheduled_time, footage_mode, revision_id, now, job_id))
    else:
        revision_number = 1
        await db.execute("INSERT INTO production_jobs(id,profile_id,video_topic_id,title,production_date,scheduled_time,status,creation_source,footage_mode,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?,'DRAFT','manual',?,?,?,?)",
            (job_id, profile["id"], video_topic_id, topic["title"], production_date, scheduled_time, footage_mode, revision_id, now, now))
    await db.execute("INSERT INTO production_revisions(id,production_job_id,revision,snapshot_json,scenes_json,blockers_json,rule_version_id,rule_hash,revision_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (revision_id, job_id, revision_number, json.dumps(snapshot, ensure_ascii=False), json.dumps(scenes, ensure_ascii=False), json.dumps(blockers), rule["id"] if rule else None, rule_hash, revision_hash, now))
    if existing:
        action = "REGENERATE_PRODUCTION" if force else "RESTART_PRODUCTION"
        await db.execute("INSERT INTO production_audit_events(id,production_job_id,revision_id,action,detail_json,created_at) VALUES(?,?,?,?,?,?)",
                         (_id(), job_id, revision_id, action, json.dumps({"revision": revision_number}), now))
    await db.commit()
    from agent.services.production_progress import initialize_production_progress
    await initialize_production_progress(job_id)
    return (await _rows("SELECT * FROM production_jobs WHERE id=?", (job_id,)))[0]


async def delete_production_job(job_id: str) -> dict:
    """Remove a terminal job so its source topic becomes creatable again."""
    jobs = await _rows("SELECT * FROM production_jobs WHERE id=?", (job_id,))
    if not jobs:
        raise ValueError("Production Job not found")
    job = jobs[0]
    if job["status"] not in {"COMPLETED", "READY_FOR_MANUAL_UPLOAD", "MANUALLY_UPLOADED",
                             "ARCHIVED", "CANCELLED", "FAILED"}:
        raise RuntimeError(f"Production Job is still active with status {job['status']}")
    db = await get_db()
    await db.execute("DELETE FROM production_jobs WHERE id=?", (job_id,))
    await db.commit()

    # Shared footage is stored elsewhere; only this job's rendered local workspace is removed.
    root = (config.OUTPUT_DIR / "production_jobs").resolve()
    workspace = (root / job_id).resolve()
    if workspace.parent == root and workspace.is_dir():
        await asyncio.to_thread(shutil.rmtree, workspace)
    return {"success": True, "job_id": job_id, "video_topic_id": job.get("video_topic_id")}


async def production_calendar():
    topics = await list_video_topics(False); jobs = await _rows("SELECT j.*,p.name profile_name,p.color FROM production_jobs j JOIN production_profile p ON p.id=j.profile_id")
    occupied = {j["video_topic_id"] for j in jobs if j["video_topic_id"] and j["status"] not in {"CANCELLED", "ARCHIVED"}}
    result = [{**j, "kind": "job", "topic_title": j["title"], "date": j["production_date"] or "", "time": j["scheduled_time"] or ""} for j in jobs]
    result += [{**t, "kind": "topic", "topic_id": t["id"], "topic_title": t["title"], "date": t["production_date"] or "", "time": t["scheduled_time"] or ""} for t in topics if t["id"] not in occupied]
    return sorted(result, key=lambda x: (x["date"] or "9999-99-99", x["time"] or "99:99", x["title"]))
