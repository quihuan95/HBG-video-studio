import json
from pathlib import Path

import pytest

from agent.services import rea_video_adapter as adapter


FIXTURE = Path(__file__).parents[1] / "fixtures" / "rea_video_breakdown_v1.json"


def test_normalizes_real_upstream_breakdown_fixture(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    shots = adapter.normalize_breakdown(data, tmp_path, 1.52)
    assert len(shots) == 1
    assert shots[0]["reference_start_s"] == 0
    assert shots[0]["reference_end_s"] == 1.52
    assert shots[0]["production_method"] == "code_render"
    assert shots[0]["confidence"] == pytest.approx(.701)


def test_rejects_unknown_schema(tmp_path):
    with pytest.raises(ValueError, match="Unsupported rea-video schema"):
        adapter.normalize_breakdown({"schema": "other", "shots": []}, tmp_path, 1)


def test_rejects_invalid_or_overlapping_reference_timecodes(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second = dict(data["shots"][0], index=2, start=1.0, end=1.4)
    data["shots"].append(second)
    with pytest.raises(ValueError, match="Invalid reference timecode"):
        adapter.normalize_breakdown(data, tmp_path, 1.52)


def _shot(index, start, end, label, confidence=.7, text_coverage=0.0, boxes=()):
    return {"index": index, "start": start, "end": end, "base": {"label": label, "confidence": confidence},
            "overlay": {"boxes": [{"bbox": list(box)} for box in boxes]},
            "text": {"tracks": [], "text_coverage": text_coverage}}


def test_broll_picker_prefers_long_live_action_without_text():
    data = {"schema": adapter.SCHEMA, "shots": [
        _shot(1, 0, 4, "code_render", .9),
        _shot(2, 4, 9, "live_action", .65, text_coverage=.12),
        _shot(3, 9, 10, "live_action", .7),
        _shot(4, 10, 16, "live_action", .6, boxes=[(0, .92, .22, .05)]),
        _shot(5, 16, 21, "ai_video", .7),
        _shot(6, 21, 25, "screen_capture", .95),
    ]}
    picked = adapter.pick_broll_segments(data, 4, 3)
    assert [item["shot_index"] for item in picked] == [4, 5, 2]
    assert picked[0]["start"] == pytest.approx(10.15) and picked[0]["end"] == pytest.approx(15.85)
    assert all(item["method"] not in {"code_render", "screen_capture"} for item in picked)


def test_broll_picker_rejects_text_heavy_clips():
    data = {"schema": adapter.SCHEMA, "shots": [_shot(1, 0, 6, "live_action", .7, text_coverage=.3)]}
    assert adapter.pick_broll_segments(data, 4, 2) == []


@pytest.mark.asyncio
async def test_broll_analysis_reuses_cached_breakdown(monkeypatch, tmp_path):
    source = tmp_path / "clip.mp4"; source.write_bytes(b"video")
    cli = tmp_path / "rea-video.exe"; cli.write_bytes(b"")
    calls = []

    async def fake_decompose(path, artifact_dir, use_vlm):
        calls.append(path); artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "breakdown.json").write_text(json.dumps(
            {"schema": adapter.SCHEMA, "shots": [_shot(1, 0, 5, "live_action")]}), encoding="utf-8")

    monkeypatch.setattr(adapter.config, "REA_VIDEO_CLI", cli)
    monkeypatch.setattr(adapter.config, "REA_VIDEO_OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(adapter, "_decompose", fake_decompose)
    first = await adapter.analyze_broll_clip(source, 3, 2)
    second = await adapter.analyze_broll_clip(source, 3, 2)
    assert first == second and first[0]["shot_index"] == 1
    assert len(calls) == 1


def test_runtime_vlm_is_opt_in(monkeypatch):
    monkeypatch.setattr(adapter.config, "REA_VIDEO_ALLOW_VLM", False)
    assert adapter.runtime_status()["vlm_allowed"] is False
