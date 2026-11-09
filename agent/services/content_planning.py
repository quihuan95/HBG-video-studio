"""Profile rule, topic, post revision and calendar domain logic."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from agent.db.schema import get_db
from agent.services.google_oauth import get_valid_access_token


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _id() -> str: return str(uuid.uuid4())
def _hash(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _rows(sql: str, args=()) -> list[dict]:
    db = await get_db(); cur = await db.execute(sql, args)
    return [dict(row) for row in await cur.fetchall()]


async def latest_rule(profile_id: str) -> dict | None:
    rows = await _rows("SELECT * FROM rule_versions WHERE profile_id=? AND status='published' ORDER BY version DESC LIMIT 1", (profile_id,))
    return rows[0] if rows else None


async def create_rule(profile_id: str, content: str, publish_config: dict | None = None) -> dict:
    content = content.strip()
    if not content: raise ValueError("Rule content is required")
    current = await latest_rule(profile_id); digest = _hash(content)
    if current and current["content_hash"] == digest: return current
    db = await get_db(); now = _now(); rid = _id(); version = (current["version"] if current else 0) + 1
    await db.execute("INSERT INTO rule_versions VALUES(?,?,?,?,?,?,?,?)",
                     (rid, profile_id, version, content, digest, json.dumps(publish_config or {}), "published", now))
    await db.commit()
    return (await _rows("SELECT * FROM rule_versions WHERE id=?", (rid,)))[0]


async def list_rules(profile_id: str) -> list[dict]:
    return await _rows("SELECT * FROM rule_versions WHERE profile_id=? ORDER BY version DESC", (profile_id,))


def _drive_id(value: str | None) -> str | None:
    if not value: return None
    match = re.search(r"/folders/([\w-]+)", value)
    return match.group(1) if match else value.strip()


async def sync_rules(profile: dict) -> dict | None:
    folder = _drive_id(profile.get("folder_id_rules"))
    if not folder and profile.get("folder_id_output"):
        folder = _drive_id(profile["folder_id_output"].replace("/OUTPUT", "/RULES"))
    if not folder: return None
    token = await get_valid_access_token(); headers = {"Authorization": f"Bearer {token}"}
    query = f"'{folder}' in parents and trashed=false"
    async with httpx.AsyncClient(timeout=30) as client:
        listing = await client.get("https://www.googleapis.com/drive/v3/files", headers=headers,
            params={"q": query, "fields": "files(id,name,mimeType)"})
        listing.raise_for_status(); files = {f["name"]: f for f in listing.json().get("files", [])}
        parts = []
        for name in ("CONTENT_RULE.md", "BRAND_FACTS.md", "VIDEO_RULE.md"):
            if name in files:
                response = await client.get(f"https://www.googleapis.com/drive/v3/files/{files[name]['id']}?alt=media", headers=headers)
                response.raise_for_status(); parts.append(response.text)
        publish = {}
        if "PRODUCTION_CONFIG.json" in files:
            response = await client.get(f"https://www.googleapis.com/drive/v3/files/{files['PRODUCTION_CONFIG.json']['id']}?alt=media", headers=headers)
            try: publish = response.json() if response.is_success else {}
            except ValueError: publish = {}
    return await create_rule(profile["id"], "\n\n---\n\n".join(parts), publish) if parts else None


def _date(value: str) -> str:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try: return datetime.strptime(value, fmt).date().isoformat()
        except ValueError: pass
    raise ValueError(f"Invalid content_date: {value}")


def _time(value: str) -> str:
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try: return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError: pass
    raise ValueError(f"Invalid publish_time: {value}")


async def sync_topics(profile: dict, values: list[list[str]]) -> dict:
    if not values: raise ValueError("TOPICS sheet is empty")
    headers = [str(x).strip().lower() for x in values[0]]
    required = {"topic_id", "content_date", "publish_time", "topic_title"}
    missing = required - set(headers)
    if missing: raise ValueError("Missing TOPICS headers: " + ", ".join(sorted(missing)))
    normalized = []; seen = set()
    aliases = {"link_anh_nguon": "source_image_drive_link", "link ảnh nguồn": "source_image_drive_link",
               "link_khung_anh": "image_frame_drive_link", "link khung ảnh": "image_frame_drive_link"}
    for raw in values[1:]:
        if not any(str(x).strip() for x in raw): continue
        row = {aliases.get(headers[i], headers[i]): str(raw[i]).strip() if i < len(raw) else "" for i in range(len(headers))}
        if not all(row.get(k) for k in required): raise ValueError("TOPICS row is missing required values")
        if row["topic_id"] in seen: raise ValueError(f"Duplicate topic_id: {row['topic_id']}")
        seen.add(row["topic_id"]); row["content_date"] = _date(row["content_date"]); row["publish_time"] = _time(row["publish_time"])
        normalized.append(row)
    db = await get_db(); now = _now(); inserted = updated = 0
    for row in normalized:
        digest = _hash(row); cur = await db.execute("SELECT * FROM topics WHERE profile_id=? AND topic_id=?", (profile["id"], row["topic_id"])); old = await cur.fetchone()
        fields = (row["topic_title"], row["content_date"], row["publish_time"], row.get("image_rule"), row.get("source_image_drive_link"), row.get("image_frame_drive_link"))
        if old:
            if old["source_hash"] != digest:
                await db.execute("UPDATE topics SET topic_title=?,content_date=?,publish_time=?,image_rule=?,source_image_drive_link=?,image_frame_drive_link=?,source_revision=source_revision+1,source_hash=?,updated_at=? WHERE id=?", (*fields, digest, now, old["id"])); updated += 1
        else:
            await db.execute("INSERT INTO topics(id,profile_id,topic_id,topic_title,content_date,publish_time,image_rule,source_image_drive_link,image_frame_drive_link,status,source_revision,source_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',1,?,?,?)", (_id(), profile["id"], row["topic_id"], *fields, digest, now, now)); inserted += 1
    placeholders = ",".join("?" for _ in seen) or "''"
    removed = await _rows(f"SELECT topic_id FROM topics WHERE profile_id=? AND topic_id NOT IN ({placeholders})", (profile["id"], *seen))
    for item in removed:
        if profile.get("retain_removed_posts", 1):
            await db.execute("UPDATE posts SET status='ARCHIVED',updated_at=? WHERE profile_id=? AND topic_id=?", (now, profile["id"], item["topic_id"]))
        else: await db.execute("DELETE FROM posts WHERE profile_id=? AND topic_id=?", (profile["id"], item["topic_id"]))
        await db.execute("DELETE FROM topics WHERE profile_id=? AND topic_id=?", (profile["id"], item["topic_id"]))
    await db.commit(); return {"inserted": inserted, "updated": updated, "removed": len(removed)}


async def fetch_and_sync_topics(profile: dict) -> dict:
    sheet = profile.get("sheet_id_topics") or profile.get("sheet_url")
    if not sheet: raise ValueError("sheet_id_topics is required")
    match = re.search(r"/spreadsheets/d/([\w-]+)", sheet); sheet_id = match.group(1) if match else sheet
    token = await get_valid_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/TOPICS!A1:Z500", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
    return await sync_topics(profile, response.json().get("values", []))


async def create_post(profile: dict, topic_id: str | None, content_date: str | None, scheduled_time: str | None, source="manual") -> dict:
    rule = await latest_rule(profile["id"])
    if not rule: raise ValueError("A published Rule is required before creating a Post")
    topic = None
    if topic_id:
        rows = await _rows("SELECT * FROM topics WHERE profile_id=? AND topic_id=?", (profile["id"], topic_id)); topic = rows[0] if rows else None
        if not topic: raise ValueError("Topic not found")
        existing = await _rows("SELECT * FROM posts WHERE profile_id=? AND topic_id=?", (profile["id"], topic_id))
        if existing: return existing[0]
    tz = ZoneInfo(profile.get("timezone") or "Asia/Ho_Chi_Minh")
    day = content_date or (topic and topic["content_date"]) or datetime.now(tz).date().isoformat()
    when = scheduled_time or (topic and topic["publish_time"]) or profile.get("default_time") or "09:00"
    day, when = _date(day), _time(when); pid = _id(); rid = _id(); now = _now()
    snapshot = {"topic_id": topic_id, "topic_title": topic and topic["topic_title"], "content_date": day, "scheduled_time": when,
                "rule_version_id": rule["id"], "rule_hash": rule["content_hash"]}
    revision_hash = _hash(snapshot)
    db = await get_db()
    await db.execute("INSERT INTO posts(id,profile_id,topic_id,topic_title,content_date,scheduled_time,status,creation_source,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?,'DRAFT',?,?,?,?)",
                     (pid, profile["id"], topic_id, snapshot["topic_title"], day, when, source, rid, now, now))
    await db.execute("INSERT INTO post_revisions(id,post_id,revision,blockers_json,rule_version_id,rule_hash,revision_hash,created_at) VALUES(?,?,1,?,?,?,?,?)",
                     (rid, pid, json.dumps(["caption_missing", "image_missing"]), rule["id"], rule["content_hash"], revision_hash, now))
    await db.commit(); return (await _rows("SELECT * FROM posts WHERE id=?", (pid,)))[0]


async def calendar_items() -> list[dict]:
    posts = await _rows("SELECT p.*,pr.color,pr.name profile_name FROM posts p JOIN production_profile pr ON pr.id=p.profile_id")
    occupied = {(p["profile_id"], p["topic_id"]) for p in posts if p["topic_id"]}
    topics = await _rows("SELECT t.*,pr.color,pr.name profile_name FROM topics t JOIN production_profile pr ON pr.id=t.profile_id")
    result = [{**p, "kind": "post", "date": p["content_date"], "time": p["scheduled_time"]} for p in posts]
    result += [{**t, "kind": "topic", "date": t["content_date"], "time": t["publish_time"]} for t in topics if (t["profile_id"], t["topic_id"]) not in occupied]
    return sorted(result, key=lambda x: (x.get("date") or "9999", x.get("time") or "99:99"))
