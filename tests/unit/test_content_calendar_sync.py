import pytest

from agent.api import content_calendar


@pytest.mark.asyncio
async def test_sync_profile_syncs_rule_before_spreadsheet(monkeypatch):
    profile = {"id": "profile-1", "folder_id_rules": "rules", "sheet_id_topics": "sheet"}
    calls = []

    async def fake_profile(profile_id):
        assert profile_id == profile["id"]
        return profile

    async def fake_sync_rules(value):
        assert value is profile
        calls.append("rules")
        return {"id": "rule-1", "version": 2}

    async def fake_sync_spreadsheet(value):
        assert value is profile
        calls.append("spreadsheet")
        return {"inserted": 1}

    monkeypatch.setattr(content_calendar, "_profile", fake_profile)
    monkeypatch.setattr(content_calendar, "sync_rules", fake_sync_rules)
    monkeypatch.setattr(content_calendar, "sync_spreadsheet", fake_sync_spreadsheet)

    result = await content_calendar.sync_profile(profile["id"])

    assert calls == ["rules", "spreadsheet"]
    assert result == {
        "profile_id": profile["id"],
        "rule": {"id": "rule-1", "version": 2},
        "videos": {"inserted": 1},
    }


@pytest.mark.asyncio
async def test_sync_all_profiles_syncs_rules_and_spreadsheets(monkeypatch):
    profiles = [{"id": "profile-1", "active": True, "sheet_id_topics": "sheet"}]
    calls = []

    async def fake_list_profiles():
        return profiles

    async def fake_sync_rules(profile):
        calls.append(("rules", profile["id"]))
        return {"id": "rule-1"}

    async def fake_sync_spreadsheet(profile):
        calls.append(("spreadsheet", profile["id"]))
        return {"updated": 1}

    monkeypatch.setattr(content_calendar.crud, "list_production_profiles", fake_list_profiles)
    monkeypatch.setattr(content_calendar, "sync_rules", fake_sync_rules)
    monkeypatch.setattr(content_calendar, "sync_spreadsheet", fake_sync_spreadsheet)

    result = await content_calendar.sync_all_profiles()

    assert calls == [("rules", "profile-1"), ("spreadsheet", "profile-1")]
    assert result["results"][0]["rule"] == {"id": "rule-1"}

