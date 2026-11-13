import json

from agent.services.production_orchestrator import _usable_start


def test_usable_start_prefers_selected_candidate_timestamp():
    asset = {
        "source_start_s": 42,
        "usable_ranges_json": json.dumps([{"start": 0, "end": 8}]),
    }

    assert _usable_start(asset) == 42


def test_usable_start_falls_back_to_classified_range():
    asset = {"usable_ranges_json": json.dumps([{"start": 12.5, "end": 20}])}

    assert _usable_start(asset) == 12.5
