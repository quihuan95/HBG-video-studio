import json

from agent.services.capcut_export import _apply_caption_style, _backup_path, _draft_name


def test_draft_name_is_windows_safe():
    assert _draft_name('Tour: Hà Nội / "Noel"', "12345678-rest") == "Tour Hà Nội Noel - 12345678"


def test_backup_path_is_short_and_does_not_repeat_project_title(tmp_path):
    backup = _backup_path(tmp_path, "e6d6486f-5534-4238-ad63-fa7890450236")
    assert backup.parent == tmp_path
    assert backup.name.startswith("e6d6486f-")
    assert len(backup.name) < 50


def test_caption_style_applies_montserrat_size_and_position(monkeypatch, tmp_path):
    font = tmp_path / "Montserrat-Regular.ttf"; font.write_bytes(b"font")
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_FONT_PATH", str(font))
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_FONT_NAME", "Montserrat")
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_FONT_SIZE", 36)
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_X", 0)
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_Y", 773)
    content = {"text": "Xin chào", "styles": [{"range": [0, 8], "size": 15}]}
    draft = {"materials": {"texts": [{"id": "text-1", "content": json.dumps(content)}]},
             "tracks": [{"type": "text", "segments": [
                 {"material_id": "text-1", "clip": {"transform": {"x": .2, "y": 0}}}]}]}
    target = tmp_path / "draft_content.json"; target.write_text(json.dumps(draft), encoding="utf-8")

    _apply_caption_style(tmp_path, 1920)

    saved = json.loads(target.read_text(encoding="utf-8"))
    material = saved["materials"]["texts"][0]
    assert material["font_name"] == "Montserrat" and material["font_size"] == 36
    style = json.loads(material["content"])["styles"][0]
    assert style["size"] == 36 and style["font"]["path"].endswith("Montserrat-Regular.ttf")
    transform = saved["tracks"][0]["segments"][0]["clip"]["transform"]
    assert transform["x"] == 0 and transform["y"] == 773 / 1920


def test_caption_y_is_not_clamped(monkeypatch, tmp_path):
    font = tmp_path / "font.ttf"; font.write_bytes(b"font")
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_FONT_PATH", str(font))
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_FONT_NAME", "Montserrat")
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_FONT_SIZE", 7)
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_X", 0)
    monkeypatch.setattr("agent.config.CAPCUT_TEXT_Y", -975)
    content = {"text": "Xin chào", "styles": [{"range": [0, 8], "size": 15}]}
    draft = {"materials": {"texts": [{"id": "text-1", "content": json.dumps(content)}]},
             "tracks": [{"type": "text", "segments": [
                 {"material_id": "text-1", "clip": {"transform": {"x": 0, "y": 0}}}]}]}
    target = tmp_path / "draft_content.json"
    target.write_text(json.dumps(draft), encoding="utf-8")

    _apply_caption_style(tmp_path, 1920)

    saved = json.loads(target.read_text(encoding="utf-8"))
    material = saved["materials"]["texts"][0]
    transform = saved["tracks"][0]["segments"][0]["clip"]["transform"]
    assert material["font_size"] == 7
    assert json.loads(material["content"])["styles"][0]["size"] == 7
    assert transform["y"] == -975 / 1920
