"""SQLite schema — async via aiosqlite."""
import asyncio
import aiosqlite
import logging
from agent.config import DB_PATH

logger = logging.getLogger(__name__)

_db_connection: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()
# Guards get_db()'s lazy connect. Separate from _db_lock because crud calls
# get_db() while holding that one. Rebuilt per event loop: a lock that has
# been waited on is bound to its loop, and pytest runs each test in a new one.
_db_init_lock: asyncio.Lock | None = None
_db_init_loop: asyncio.AbstractEventLoop | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS character (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT,  -- auto-generated from name via slugify()
    entity_type TEXT NOT NULL DEFAULT 'character' CHECK(entity_type IN ('character','location','creature','visual_asset','generic_troop','faction')),
    description TEXT,
    image_prompt TEXT,
    voice_description TEXT,  -- max ~30 words, e.g. "Deep gravelly voice with a warm laugh"
    reference_image_url TEXT,
    media_id TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS project (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    story       TEXT,
    thumbnail_url TEXT,
    language    TEXT NOT NULL DEFAULT 'en',
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED','DELETED')),
    user_paygate_tier TEXT NOT NULL DEFAULT 'PAYGATE_TIER_ONE',
    narrator_voice TEXT,
    narrator_ref_audio TEXT,
    material TEXT DEFAULT 'realistic',
    allow_music INTEGER NOT NULL DEFAULT 0,
    allow_voice INTEGER NOT NULL DEFAULT 0,
    video_model_family TEXT NOT NULL DEFAULT 'veo',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS material (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    style_instruction TEXT NOT NULL,
    negative_prompt TEXT,
    scene_prefix TEXT,
    lighting    TEXT DEFAULT 'Studio lighting, highly detailed',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS project_character (
    project_id    TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    character_id  TEXT NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, character_id)
);

CREATE TABLE IF NOT EXISTS video (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    description   TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','PROCESSING','COMPLETED','FAILED')),
    vertical_url  TEXT,
    horizontal_url TEXT,
    thumbnail_url TEXT,
    duration      REAL,
    target_duration_s REAL,   -- desired final length; concat/finalize trims to it
    resolution    TEXT,
    orientation   TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    privacy       TEXT NOT NULL DEFAULT 'unlisted',
    tags          TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS scene (
    id              TEXT PRIMARY KEY,
    video_id        TEXT NOT NULL REFERENCES video(id) ON DELETE CASCADE,
    display_order   INTEGER NOT NULL DEFAULT 0,
    prompt          TEXT,
    image_prompt    TEXT,
    video_prompt    TEXT,
    character_names TEXT,  -- JSON array of reference entity names (characters, locations, assets)

    parent_scene_id TEXT REFERENCES scene(id) ON DELETE SET NULL,
    chain_type      TEXT NOT NULL DEFAULT 'ROOT' CHECK(chain_type IN ('ROOT','CONTINUATION','INSERT')),
    source          TEXT NOT NULL DEFAULT 'root' CHECK(source IN ('root','user','system')),

    -- Vertical orientation
    vertical_image_url          TEXT,
    vertical_image_media_id TEXT,
    vertical_image_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(vertical_image_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    vertical_video_url          TEXT,
    vertical_video_media_id TEXT,
    vertical_video_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(vertical_video_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    vertical_upscale_url        TEXT,
    vertical_upscale_media_id TEXT,
    vertical_upscale_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK(vertical_upscale_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),

    -- Horizontal orientation
    horizontal_image_url          TEXT,
    horizontal_image_media_id TEXT,
    horizontal_image_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(horizontal_image_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    horizontal_video_url          TEXT,
    horizontal_video_media_id TEXT,
    horizontal_video_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(horizontal_video_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    horizontal_upscale_url        TEXT,
    horizontal_upscale_media_id TEXT,
    horizontal_upscale_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK(horizontal_upscale_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),

    -- Chain source (for continuation scenes)
    vertical_end_scene_media_id   TEXT,
    horizontal_end_scene_media_id TEXT,

    -- Trim
    trim_start  REAL,
    trim_end    REAL,
    duration    REAL,

    -- Transition (chain scenes only: describes motion from this scene to next)
    transition_prompt TEXT,

    -- Narration
    narrator_text TEXT,

    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS request (
    id            TEXT PRIMARY KEY,
    project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
    video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
    scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
    character_id  TEXT REFERENCES character(id) ON DELETE CASCADE,
    type          TEXT NOT NULL CHECK(type IN ('GENERATE_IMAGE','REGENERATE_IMAGE','EDIT_IMAGE','GENERATE_VIDEO','REGENERATE_VIDEO','GENERATE_VIDEO_REFS','UPSCALE_VIDEO','GENERATE_CHARACTER_IMAGE','REGENERATE_CHARACTER_IMAGE','EDIT_CHARACTER_IMAGE')),
    orientation   TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    request_id    TEXT,   -- external operation ID
    media_id  TEXT,
    output_url    TEXT,
    error_message TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    edit_prompt   TEXT,    -- prompt for EDIT_IMAGE requests
    source_media_id TEXT,  -- source image media_id for EDIT_IMAGE requests
    provider      TEXT,    -- media provider backend: flow | assistant | ...
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_scene_video ON scene(video_id);
CREATE INDEX IF NOT EXISTS idx_scene_order ON scene(video_id, display_order);
CREATE INDEX IF NOT EXISTS idx_request_status ON request(status);
CREATE INDEX IF NOT EXISTS idx_request_scene ON request(scene_id);
CREATE INDEX IF NOT EXISTS idx_video_project ON video(project_id);

CREATE TABLE IF NOT EXISTS production_profile (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT,
    language          TEXT NOT NULL DEFAULT 'vi',
    tone              TEXT,
    rules_json        TEXT NOT NULL DEFAULT '{}',
    logo_path         TEXT,
    logo_position     TEXT NOT NULL DEFAULT 'top-right',
    voice_provider    TEXT NOT NULL DEFAULT 'openai',
    voice_id          TEXT NOT NULL DEFAULT 'marin',
    music_path        TEXT,
    sheet_url         TEXT,
    output_drive_url  TEXT,
    status            TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED')),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS footage_source (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK(source_type IN ('local','google_drive')),
    name        TEXT NOT NULL,
    location    TEXT NOT NULL,
    recursive   INTEGER NOT NULL DEFAULT 1,
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_scanned_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS footage_asset (
    id            TEXT PRIMARY KEY,
    profile_id    TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    source_id     TEXT NOT NULL REFERENCES footage_source(id) ON DELETE CASCADE,
    external_id   TEXT,
    file_name     TEXT NOT NULL,
    uri           TEXT NOT NULL,
    mime_type     TEXT,
    size_bytes    INTEGER,
    duration_s    REAL,
    width         INTEGER,
    height        INTEGER,
    fps           REAL,
    status        TEXT NOT NULL DEFAULT 'DISCOVERED' CHECK(status IN ('DISCOVERED','ANALYZING','READY','FAILED')),
    summary       TEXT,
    category      TEXT,
    tags_json     TEXT NOT NULL DEFAULT '[]',
    usable_ranges_json TEXT NOT NULL DEFAULT '[]',
    quality_score REAL,
    has_dialogue  INTEGER,
    analysis_json TEXT,
    error_message TEXT,
    analyzed_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(source_id, uri)
);

CREATE INDEX IF NOT EXISTS idx_footage_source_profile ON footage_source(profile_id);
CREATE INDEX IF NOT EXISTS idx_footage_asset_profile ON footage_asset(profile_id);
CREATE INDEX IF NOT EXISTS idx_footage_asset_source ON footage_asset(source_id);
CREATE INDEX IF NOT EXISTS idx_footage_asset_status ON footage_asset(status);

CREATE TABLE IF NOT EXISTS rule_versions (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    version INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
    publish_config_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL, UNIQUE(profile_id, version)
);
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL, topic_title TEXT NOT NULL, content_date TEXT NOT NULL,
    publish_time TEXT NOT NULL, image_rule TEXT, source_image_drive_link TEXT,
    image_frame_drive_link TEXT, status TEXT NOT NULL DEFAULT 'READY', source_revision INTEGER NOT NULL DEFAULT 1,
    source_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(profile_id, topic_id)
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    topic_id TEXT, topic_title TEXT, content_date TEXT NOT NULL, scheduled_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT', creation_source TEXT NOT NULL DEFAULT 'manual',
    current_revision_id TEXT, published_url TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(profile_id, topic_id)
);
CREATE TABLE IF NOT EXISTS post_revisions (
    id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL, caption TEXT NOT NULL DEFAULT '', headline TEXT NOT NULL DEFAULT '',
    cta TEXT NOT NULL DEFAULT '', image_brief TEXT NOT NULL DEFAULT '', images_json TEXT NOT NULL DEFAULT '[]',
    blockers_json TEXT NOT NULL DEFAULT '[]', rule_version_id TEXT REFERENCES rule_versions(id),
    rule_hash TEXT, revision_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(post_id, revision)
);
CREATE TABLE IF NOT EXISTS post_approvals (
    id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES post_revisions(id), revision_hash TEXT NOT NULL,
    approved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_profile_date ON topics(profile_id, content_date);
CREATE INDEX IF NOT EXISTS idx_posts_profile_date ON posts(profile_id, content_date, scheduled_time);

CREATE TABLE IF NOT EXISTS video_topics (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    spreadsheet_id TEXT NOT NULL,
    source_sheet_id INTEGER NOT NULL,
    source_tab_name TEXT NOT NULL,
    title TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    orientation TEXT NOT NULL DEFAULT 'VERTICAL',
    target_duration_s REAL,
    production_date TEXT,
    scheduled_time TEXT,
    status TEXT NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','ARCHIVED')),
    source_revision INTEGER NOT NULL DEFAULT 1,
    source_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, spreadsheet_id, source_sheet_id)
);
CREATE TABLE IF NOT EXISTS video_topic_scenes (
    id TEXT PRIMARY KEY,
    video_topic_id TEXT NOT NULL REFERENCES video_topics(id) ON DELETE CASCADE,
    scene_order INTEGER NOT NULL,
    section TEXT,
    shot_code TEXT,
    start_time_s REAL NOT NULL,
    end_time_s REAL NOT NULL,
    duration_s REAL NOT NULL,
    visual_intent TEXT,
    on_screen_text TEXT,
    narration_text TEXT,
    editing_instruction TEXT,
    footage_references TEXT,
    audio_instruction TEXT,
    notes TEXT,
    UNIQUE(video_topic_id, scene_order)
);
CREATE TABLE IF NOT EXISTS production_jobs (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES production_profile(id) ON DELETE CASCADE,
    video_topic_id TEXT REFERENCES video_topics(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    production_date TEXT,
    scheduled_time TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    creation_source TEXT NOT NULL DEFAULT 'manual',
    current_revision_id TEXT,
    output_drive_file_id TEXT,
    output_url TEXT,
    error_stage TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, video_topic_id)
);
CREATE TABLE IF NOT EXISTS production_revisions (
    id TEXT PRIMARY KEY,
    production_job_id TEXT NOT NULL REFERENCES production_jobs(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    scenes_json TEXT NOT NULL,
    assets_json TEXT NOT NULL DEFAULT '{}',
    blockers_json TEXT NOT NULL DEFAULT '[]',
    rule_version_id TEXT REFERENCES rule_versions(id),
    rule_hash TEXT,
    revision_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(production_job_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_video_topics_profile_status ON video_topics(profile_id,status);
CREATE INDEX IF NOT EXISTS idx_production_jobs_status_schedule ON production_jobs(status,production_date,scheduled_time);

CREATE TABLE IF NOT EXISTS oauth_states (
    state        TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
    id                TEXT PRIMARY KEY,
    provider          TEXT NOT NULL,
    user_id           TEXT NOT NULL,
    encrypted_tokens  TEXT NOT NULL,
    scopes            TEXT NOT NULL,
    account_email     TEXT,
    account_name      TEXT,
    status            TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','needs_reconnect')),
    last_health_check TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(provider, user_id)
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);
CREATE INDEX IF NOT EXISTS idx_connections_provider_user ON connections(provider, user_id);

-- Persistent provider jobs: the handoff queue between the FlowKit worker and
-- external media providers/agents (assistant, HTTP workers, ...). A job is
-- created QUEUED, claimed by a worker (claim/lease), heartbeated while
-- running, then completed/failed/cancelled. Leases expire so crashed workers
-- don't strand jobs — an expired lease is reclaimable.
CREATE TABLE IF NOT EXISTS provider_job (
    id            TEXT PRIMARY KEY,   -- ProviderJob.job_id
    provider      TEXT NOT NULL,      -- target backend: flow | assistant | ...
    kind          TEXT NOT NULL,      -- image | edit_image | i2v | r2v | upscale
    status        TEXT NOT NULL DEFAULT 'QUEUED'
                    CHECK(status IN ('QUEUED','CLAIMED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    prompt        TEXT NOT NULL DEFAULT '',
    orientation   TEXT,               -- VERTICAL | HORIZONTAL
    source_url    TEXT,               -- input image URL (edit_image)
    start_url     TEXT,               -- start frame URL (i2v video)
    end_url       TEXT,
    extra         TEXT,               -- JSON: provider-specific params
    claimed_by    TEXT,               -- worker id holding the lease
    claimed_at    TEXT,
    lease_expires_at TEXT,            -- heartbeat deadline; expired => reclaimable
    progress      INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT,
    result        TEXT,               -- JSON result payload (output_url, media_id, ...)
    error_message TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_provider_job_provider_status ON provider_job(provider, status);
CREATE INDEX IF NOT EXISTS idx_provider_job_lease ON provider_job(lease_expires_at);
"""


async def init_db():
    """Initialize database with schema and run migrations."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(SCHEMA)
        # Migration: add provider column to request table (per-request media provider)
        cursor = await db.execute("PRAGMA table_info(request)")
        req_columns = {row[1] for row in await cursor.fetchall()}
        if "provider" not in req_columns:
            await db.execute("ALTER TABLE request ADD COLUMN provider TEXT")
            logger.info("Migrated: added provider column to request table")
        # Migration: add slug column to character table + backfill
        cursor = await db.execute("PRAGMA table_info(character)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "slug" not in columns:
            await db.execute("ALTER TABLE character ADD COLUMN slug TEXT")
            logger.info("Migrated: added slug column to character table")
        # Backfill slugs for existing characters (Python-side since SQLite has no slugify)
        cursor = await db.execute("SELECT id, name FROM character WHERE slug IS NULL OR slug = ''")
        chars_without_slug = await cursor.fetchall()
        if chars_without_slug:
            from agent.utils.slugify import slugify as _slugify
            for row in chars_without_slug:
                _slug = _slugify(row[1])
                await db.execute("UPDATE character SET slug=? WHERE id=?", (_slug, row[0]))
            logger.info("Backfilled slug for %d characters", len(chars_without_slug))
        # Migration: add voice_description if missing (added after initial schema)
        cursor = await db.execute("PRAGMA table_info(character)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "voice_description" not in columns:
            await db.execute("ALTER TABLE character ADD COLUMN voice_description TEXT DEFAULT ''")
            logger.info("Migrated: added voice_description column to character table")
        # Migration: add edit_prompt and source_media_id to request table
        cursor = await db.execute("PRAGMA table_info(request)")
        req_columns = {row[1] for row in await cursor.fetchall()}
        if "edit_prompt" not in req_columns:
            await db.execute("ALTER TABLE request ADD COLUMN edit_prompt TEXT")
            logger.info("Migrated: added edit_prompt column to request table")
        if "source_media_id" not in req_columns:
            await db.execute("ALTER TABLE request ADD COLUMN source_media_id TEXT")
            logger.info("Migrated: added source_media_id column to request table")
        # Migration: add queue columns to request table
        cursor = await db.execute("PRAGMA table_info(request)")
        request_columns = {row[1] for row in await cursor.fetchall()}
        if "next_retry_at" not in request_columns:
            await db.execute("ALTER TABLE request ADD COLUMN next_retry_at TEXT")
            logger.info("Migrated: added next_retry_at column to request table")
        if "retry_count" not in request_columns:
            await db.execute("ALTER TABLE request ADD COLUMN retry_count INTEGER DEFAULT 0")
            logger.info("Migrated: added retry_count column to request table")
        # Migration: ensure request table CHECK constraint includes all request types
        # SQLite can't alter CHECK constraints, so recreate the table
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE name='request' AND type='table'")
        row = await cursor.fetchone()
        needs_recreate = False
        if row:
            table_sql = row[0]
            if 'GENERATE_IMAGES' in table_sql and 'GENERATE_IMAGE,' not in table_sql:
                needs_recreate = True  # old GENERATE_IMAGES typo
            if 'REGENERATE_IMAGE' not in table_sql:
                needs_recreate = True  # missing REGENERATE/EDIT types
        if needs_recreate:
            await db.execute("PRAGMA foreign_keys=OFF")
            await db.execute("ALTER TABLE request RENAME TO _request_old")
            await db.executescript("""
CREATE TABLE IF NOT EXISTS request (
    id            TEXT PRIMARY KEY,
    project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
    video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
    scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
    character_id  TEXT REFERENCES character(id) ON DELETE CASCADE,
    type          TEXT NOT NULL CHECK(type IN ('GENERATE_IMAGE','REGENERATE_IMAGE','EDIT_IMAGE','GENERATE_VIDEO','REGENERATE_VIDEO','GENERATE_VIDEO_REFS','UPSCALE_VIDEO','GENERATE_CHARACTER_IMAGE','REGENERATE_CHARACTER_IMAGE','EDIT_CHARACTER_IMAGE')),
    orientation   TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    request_id    TEXT,
    media_id      TEXT,
    output_url    TEXT,
    error_message TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    edit_prompt   TEXT,
    source_media_id TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_request_status ON request(status);
CREATE INDEX IF NOT EXISTS idx_request_scene ON request(scene_id);
""")
            await db.execute("INSERT OR IGNORE INTO request SELECT * FROM _request_old")
            await db.execute("UPDATE request SET type='GENERATE_IMAGE' WHERE type='GENERATE_IMAGES'")
            await db.execute("DROP TABLE _request_old")
            await db.execute("PRAGMA foreign_keys=ON")
            logger.info("Migrated: renamed GENERATE_IMAGES -> GENERATE_IMAGE in request table")
        # Migration: add source column to scene table
        cursor = await db.execute("PRAGMA table_info(scene)")
        scene_columns = {row[1] for row in await cursor.fetchall()}
        if "source" not in scene_columns:
            await db.execute("ALTER TABLE scene ADD COLUMN source TEXT NOT NULL DEFAULT 'root'")
            logger.info("Migrated: added source column to scene table")
        if "narrator_text" not in scene_columns:
            await db.execute("ALTER TABLE scene ADD COLUMN narrator_text TEXT")
            logger.info("Migrated: added narrator_text column to scene table")
        # Migration: add start_url to provider_job table (i2v start frame)
        cursor = await db.execute("PRAGMA table_info(provider_job)")
        pj_columns = {row[1] for row in await cursor.fetchall()}
        if "start_url" not in pj_columns:
            await db.execute("ALTER TABLE provider_job ADD COLUMN start_url TEXT")
            logger.info("Migrated: added start_url column to provider_job table")
        # Migration: add narrator fields to project table
        cursor = await db.execute("PRAGMA table_info(project)")
        project_columns = {row[1] for row in await cursor.fetchall()}
        if "narrator_voice" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN narrator_voice TEXT")
            logger.info("Migrated: added narrator_voice column to project table")
        if "narrator_ref_audio" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN narrator_ref_audio TEXT")
            logger.info("Migrated: added narrator_ref_audio column to project table")
        if "material" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN material TEXT DEFAULT 'realistic'")
            logger.info("Migrated: added material column to project table")
        if "allow_music" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN allow_music INTEGER NOT NULL DEFAULT 0")
            logger.info("Migrated: added allow_music column to project table")
        if "allow_voice" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN allow_voice INTEGER NOT NULL DEFAULT 0")
            logger.info("Migrated: added allow_voice column to project table")
        if "video_model_family" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN video_model_family TEXT NOT NULL DEFAULT 'veo'")
            logger.info("Migrated: added video_model_family column to project table")
        # Migration: add orientation to video table + backfill from scene data
        cursor = await db.execute("PRAGMA table_info(video)")
        video_columns = {row[1] for row in await cursor.fetchall()}
        if "orientation" not in video_columns:
            await db.execute("ALTER TABLE video ADD COLUMN orientation TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL'))")
            # Backfill: detect orientation from completed scene fields
            cursor = await db.execute("SELECT id FROM video")
            video_ids = [row[0] for row in await cursor.fetchall()]
            for vid in video_ids:
                cursor2 = await db.execute(
                    "SELECT horizontal_image_status, vertical_image_status FROM scene WHERE video_id = ? LIMIT 1", (vid,))
                scene = await cursor2.fetchone()
                if scene:
                    if scene[0] == "COMPLETED":
                        await db.execute("UPDATE video SET orientation = 'HORIZONTAL' WHERE id = ?", (vid,))
                    elif scene[1] == "COMPLETED":
                        await db.execute("UPDATE video SET orientation = 'VERTICAL' WHERE id = ?", (vid,))
            logger.info("Migrated: added orientation column to video table with backfill")
        # Migration: add target_duration_s to video table
        if "target_duration_s" not in video_columns:
            await db.execute("ALTER TABLE video ADD COLUMN target_duration_s REAL")
            logger.info("Migrated: added target_duration_s column to video table")
        if "youtube_id" in video_columns:
            await db.execute("ALTER TABLE video DROP COLUMN youtube_id")
            logger.info("Migrated: removed legacy youtube_id column")
        cursor = await db.execute("PRAGMA table_info(production_profile)")
        profile_columns = {row[1] for row in await cursor.fetchall()}
        profile_additions = {
            "brand": "TEXT", "profile_type": "TEXT", "timezone": "TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh'",
            "default_time": "TEXT NOT NULL DEFAULT '09:00'", "folder_id_rules": "TEXT",
            "folder_id_output": "TEXT", "sheet_id_topics": "TEXT", "workflow_mode": "TEXT NOT NULL DEFAULT 'manual'",
            "active": "INTEGER NOT NULL DEFAULT 1", "color": "TEXT NOT NULL DEFAULT '#22c55e'",
            "logo_data": "TEXT", "facebook_page_id": "TEXT", "retain_removed_posts": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, definition in profile_additions.items():
            if name not in profile_columns:
                await db.execute(f"ALTER TABLE production_profile ADD COLUMN {name} {definition}")
        # Migration: create material table if missing
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='material'")
        if not await cursor.fetchone():
            await db.execute("""CREATE TABLE material (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, style_instruction TEXT NOT NULL,
    negative_prompt TEXT, scene_prefix TEXT, lighting TEXT DEFAULT 'Studio lighting, highly detailed',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))""")
            logger.info("Migrated: created material table")
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


def _get_db_init_lock() -> asyncio.Lock:
    global _db_init_lock, _db_init_loop
    loop = asyncio.get_running_loop()
    if _db_init_lock is None or _db_init_loop is not loop:
        _db_init_lock = asyncio.Lock()
        _db_init_loop = loop
    return _db_init_lock


async def get_db() -> aiosqlite.Connection:
    """Return the shared database connection, creating it if needed.

    The first two callers used to race here: both saw None, both connected,
    the second overwrote the global, and the first then ran its PRAGMAs on
    the second's connection while a statement was open on it — failing with
    "database table is locked" and leaking a connection (whose worker thread
    keeps the interpreter alive). Connect under a lock, set up a local, and
    publish it only once it is ready.
    """
    global _db_connection
    if _db_connection is not None:
        return _db_connection
    async with _get_db_init_lock():
        if _db_connection is None:
            conn = await aiosqlite.connect(str(DB_PATH))
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            # Force WAL checkpoint so this connection sees all committed writes
            # from previous processes (e.g. after hot-reload)
            await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            _db_connection = conn
    return _db_connection


async def close_db() -> None:
    """Close the shared database connection."""
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None
        logger.info("Database connection closed")
