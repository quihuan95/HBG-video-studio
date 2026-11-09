import pytest

from agent.db import crud
from agent.services.content_planning import (
    calendar_items, create_post, create_rule, latest_rule, sync_topics,
)


@pytest.fixture
async def profile(test_db):
    return await crud.create_production_profile(
        name="HBG", rules_json="{}", timezone="Asia/Ho_Chi_Minh",
        default_time="09:00", workflow_mode="semi_auto", active=1,
        color="#00aa55", retain_removed_posts=1,
    )


@pytest.mark.asyncio
async def test_rule_versions_only_when_content_changes(profile):
    first = await create_rule(profile["id"], "Rule A")
    same = await create_rule(profile["id"], "Rule A")
    second = await create_rule(profile["id"], "Rule B")
    assert first["id"] == same["id"]
    assert second["version"] == 2
    assert (await latest_rule(profile["id"]))["content_hash"] == second["content_hash"]


@pytest.mark.asyncio
async def test_topic_sync_revision_and_validation(profile):
    values = [["topic_id", "content_date", "publish_time", "topic_title"],
              ["T001", "12/11/2026", "19:30", "Title one"]]
    assert await sync_topics(profile, values) == {"inserted": 1, "updated": 0, "removed": 0}
    assert await sync_topics(profile, values) == {"inserted": 0, "updated": 0, "removed": 0}
    values[1][3] = "Changed"
    assert (await sync_topics(profile, values))["updated"] == 1


@pytest.mark.asyncio
async def test_post_snapshots_rule_and_replaces_topic_on_calendar(profile):
    rule = await create_rule(profile["id"], "Published rule")
    await sync_topics(profile, [["topic_id", "content_date", "publish_time", "topic_title"],
                                ["T001", "2026-11-12", "19:30", "Topic"]])
    post = await create_post(profile, "T001", None, None)
    duplicate = await create_post(profile, "T001", None, None)
    assert duplicate["id"] == post["id"]
    from agent.services.content_planning import _rows
    revision = (await _rows("SELECT * FROM post_revisions WHERE post_id=?", (post["id"],)))[0]
    assert revision["rule_version_id"] == rule["id"]
    items = await calendar_items()
    assert [(item["kind"], item["topic_id"]) for item in items] == [("post", "T001")]


@pytest.mark.asyncio
async def test_removed_topic_archives_post(profile):
    await create_rule(profile["id"], "Rule")
    await sync_topics(profile, [["topic_id", "content_date", "publish_time", "topic_title"],
                                ["T001", "2026-11-12", "19:30", "Topic"]])
    post = await create_post(profile, "T001", None, None)
    await sync_topics(profile, [["topic_id", "content_date", "publish_time", "topic_title"]])
    from agent.services.content_planning import _rows
    saved = (await _rows("SELECT * FROM posts WHERE id=?", (post["id"],)))[0]
    assert saved["status"] == "ARCHIVED"
