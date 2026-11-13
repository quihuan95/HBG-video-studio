import io
import wave

import httpx
import pytest

from agent.services.vbee_tts import _chunks, synthesize_vbee


def _wav(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000); audio.writeframes(payload)
    return buffer.getvalue()


def test_chunks_respect_vbee_limit():
    result = _chunks(("Một câu đủ dài để kiểm tra. " * 30).strip())
    assert len(result) > 1
    assert all(0 < len(chunk) <= 300 for chunk in result)


def test_merge_ignores_streaming_nframes_header():
    from agent.services.vbee_tts import _merge_wav
    raw = bytearray(_wav(b"\x00\x00" * 10))
    raw[40:44] = (0xFFFFFFFF).to_bytes(4, "little")
    merged = _merge_wav([bytes(raw)])
    assert merged.startswith(b"RIFF") and len(merged) < 1000


@pytest.mark.asyncio
async def test_synthesize_vbee_sends_auth_and_merges_wav(monkeypatch, tmp_path):
    requests = []
    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, content=_wav(b"\x00\x00" * 10))
    monkeypatch.setattr("agent.config.VBEE_APP_ID", "app")
    monkeypatch.setattr("agent.config.VBEE_API_TOKEN", "secret")
    output = tmp_path / "voice.wav"
    await synthesize_vbee("Câu đầu. " * 50, output, "voice-code", transport=httpx.MockTransport(handler))
    assert len(requests) > 1 and output.read_bytes().startswith(b"RIFF")
    assert requests[0].headers["Authorization"] == "Bearer secret"
    assert requests[0].headers["App-Id"] == "app"
    assert b'"outputFormat":"wav"' in requests[0].read()
