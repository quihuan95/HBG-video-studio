"""Spreadsheet-tab video plans and production job domain logic."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

import httpx

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


HEADER_MAP = {
    "phan": "section", "shot": "shot_code", "timecode": "timecode",
    "hinh_anh_de_xuat": "visual_intent", "text_on_screen": "on_screen_text",
    "voice_over_vi_loi_doc_tieng_viet": "narration_text", "voice_over": "narration_text",
    "cach_dung": "editing_instruction", "tu_lieu_tham_khao": "footage_references",
    "am_thanh": "audio_instruction", "ghi_chu": "notes",
}
SCENE_FIELDS = {"section", "shot_code", "timecode", "visual_intent", "on_screen_text",
                "narration_text", "editing_instruction", "footage_references", "audio_instruction", "notes"}
REQUIRED = {"section", "shot_code", "timecode", "visual_intent", "on_screen_text",
            "narration_text", "editing_instruction", "footage_references"}


def _header_field(value: str) -> str:
    key = _key(value)
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
        if re.search(r"drive\.google\.com/(?:drive/(?:u/\d+/)?folders|open)", value) or re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
            return value
    return ""


def _seconds(value: str) -> float:
    parts = [float(x) for x in value.strip().split(":")]
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
        scenes.append({"scene_order": len(scenes) + 1, "start_time_s": start, "end_time_s": end,
                       "duration_s": end - start, **{key: data.get(key, "") for key in SCENE_FIELDS if key != "timecode"}})
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
        values_response = await client.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values:batchGet", headers=auth,
            params=[("ranges", item) for item in ranges] + [("majorDimension", "ROWS")])
        values_response.raise_for_status(); value_ranges = values_response.json().get("valueRanges", [])
    db = await get_db(); now = _now(); seen = set(); inserted = updated = archived = 0; errors = []
    for sheet, value_range in zip(sheets, value_ranges):
        props = sheet["properties"]; source_sheet_id = int(props["sheetId"]); seen.add(source_sheet_id)
        try: parsed = parse_video_tab(value_range.get("values", []), props["title"])
        except ValueError as exc: errors.append({"sheet_id": source_sheet_id, "tab": props["title"], "error": str(exc)}); continue
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
    return await _rows("SELECT vt.*,p.name profile_name,p.color FROM video_topics vt JOIN production_profile p ON p.id=vt.profile_id" + where + " ORDER BY vt.created_at")


async def create_production_job(profile: dict, video_topic_id: str, production_date=None, scheduled_time=None):
    topics = await _rows("SELECT * FROM video_topics WHERE id=? AND profile_id=?", (video_topic_id, profile["id"]))
    if not topics: raise ValueError("Video topic not found")
    existing = await _rows("SELECT * FROM production_jobs WHERE profile_id=? AND video_topic_id=?", (profile["id"], video_topic_id))
    if existing: return existing[0]
    rule = await latest_rule(profile["id"])
    if not rule: raise ValueError("A published Video Rule is required")
    topic = topics[0]; scenes = await _rows("SELECT * FROM video_topic_scenes WHERE video_topic_id=? ORDER BY scene_order", (video_topic_id,))
    snapshot = {"title": topic["title"], "brief": topic["brief"], "orientation": topic["orientation"],
                "target_duration_s": topic["target_duration_s"], "production_date": production_date, "scheduled_time": scheduled_time,
                "spreadsheet_id": topic["spreadsheet_id"], "source_sheet_id": topic["source_sheet_id"]}
    now = _now(); job_id = _id(); revision_id = _id(); revision_hash = _hash({"snapshot": snapshot, "scenes": scenes, "rule": rule["content_hash"]})
    blockers = ["voice_missing", "timeline_missing", "footage_missing", "render_missing"]
    db = await get_db(); await db.execute("INSERT INTO production_jobs(id,profile_id,video_topic_id,title,production_date,scheduled_time,status,creation_source,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?,'DRAFT','manual',?,?,?)",
        (job_id, profile["id"], video_topic_id, topic["title"], production_date, scheduled_time, revision_id, now, now))
    await db.execute("INSERT INTO production_revisions(id,production_job_id,revision,snapshot_json,scenes_json,blockers_json,rule_version_id,rule_hash,revision_hash,created_at) VALUES(?,?,1,?,?,?,?,?,?,?)",
        (revision_id, job_id, json.dumps(snapshot, ensure_ascii=False), json.dumps(scenes, ensure_ascii=False), json.dumps(blockers), rule["id"], rule["content_hash"], revision_hash, now))
    await db.commit(); return (await _rows("SELECT * FROM production_jobs WHERE id=?", (job_id,)))[0]


async def production_calendar():
    topics = await list_video_topics(False); jobs = await _rows("SELECT j.*,p.name profile_name,p.color FROM production_jobs j JOIN production_profile p ON p.id=j.profile_id")
    occupied = {j["video_topic_id"] for j in jobs if j["video_topic_id"]}
    result = [{**j, "kind": "job", "topic_title": j["title"], "date": j["production_date"] or "", "time": j["scheduled_time"] or ""} for j in jobs]
    result += [{**t, "kind": "topic", "topic_id": t["id"], "topic_title": t["title"], "date": t["production_date"] or "", "time": t["scheduled_time"] or ""} for t in topics if t["id"] not in occupied]
    return sorted(result, key=lambda x: (x["date"] or "9999-99-99", x["time"] or "99:99", x["title"]))
