"""Vbee Realtime TTS client."""
from __future__ import annotations

import io
import re
import asyncio
import wave
from pathlib import Path

import httpx

from agent import config


def _chunks(text: str, limit: int = 300) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts: list[str] = []
    while len(text) > limit:
        window = text[: limit + 1]
        cut = max(window.rfind(mark) for mark in (". ", "! ", "? ", "; ", ", ", " "))
        if cut < 1:
            cut = limit
        elif window[cut] in ".!?;,":
            cut += 1
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


def _merge_wav(chunks: list[bytes]) -> bytes:
    output = io.BytesIO()
    params = None
    frames: list[bytes] = []
    for raw in chunks:
        with wave.open(io.BytesIO(raw), "rb") as source:
            current = source.getparams()
            signature = (current.nchannels, current.sampwidth, current.framerate, current.comptype)
            if params is None:
                params = current
            elif signature != (params.nchannels, params.sampwidth, params.framerate, params.comptype):
                raise RuntimeError("Vbee returned WAV chunks with incompatible audio formats")
            frames.append(source.readframes(current.nframes))
    if params is None:
        return b""
    with wave.open(output, "wb") as target:
        # Vbee streams WAV with an unknown/maximum nframes header. Copy only
        # the actual format fields and let wave calculate length from frames.
        target.setnchannels(params.nchannels)
        target.setsampwidth(params.sampwidth)
        target.setframerate(params.framerate)
        target.setcomptype(params.comptype, params.compname)
        for frame in frames:
            target.writeframes(frame)
    return output.getvalue()


async def synthesize_vbee(text: str, output: Path, voice_code: str, *,
                          transport: httpx.AsyncBaseTransport | None = None) -> None:
    if not config.VBEE_APP_ID or not config.VBEE_API_TOKEN:
        raise RuntimeError("VBEE_APP_ID and VBEE_API_TOKEN are required for Vbee voice-over")
    if not voice_code:
        raise RuntimeError("A Vbee voiceCode is required in the production profile")
    headers = {"Authorization": f"Bearer {config.VBEE_API_TOKEN}", "App-Id": config.VBEE_APP_ID,
               "Content-Type": "application/json"}
    audio_chunks: list[bytes] = []
    async with httpx.AsyncClient(timeout=config.VBEE_TIMEOUT_S, transport=transport,
                                follow_redirects=True) as client:
        for chunk in _chunks(text):
            response = await client.post(config.VBEE_TTS_URL, headers=headers, json={
                "text": chunk, "mode": "sync", "voiceCode": voice_code,
                "outputFormat": "wav", "bitrate": config.VBEE_BITRATE, "speed": config.VBEE_SPEED})
            if response.status_code == 400 and "Voice not found" in response.text:
                await _synthesize_vbee_batch(client, headers, text, output, voice_code)
                return
            if response.is_error:
                raise RuntimeError(f"Vbee TTS failed ({response.status_code}): {response.text[:500]}")
            if response.content[:4] != b"RIFF":
                raise RuntimeError("Vbee TTS returned an invalid WAV response")
            audio_chunks.append(response.content)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_merge_wav(audio_chunks))


async def _synthesize_vbee_batch(client: httpx.AsyncClient, headers: dict[str, str], text: str,
                                  output: Path, voice_code: str) -> None:
    """Generate library/community voices asynchronously, polling without relying on webhook delivery."""
    response = await client.post(config.VBEE_TTS_URL, headers=headers, json={
        "text": text.strip(), "mode": "async", "webhookUrl": config.VBEE_WEBHOOK_URL,
        "voiceCode": voice_code, "outputFormat": "wav", "bitrate": config.VBEE_BITRATE,
        "speed": config.VBEE_SPEED,
    })
    if response.is_error:
        raise RuntimeError(f"Vbee Batch TTS failed ({response.status_code}): {response.text[:500]}")
    request_id = response.json().get("requestId")
    if not request_id:
        raise RuntimeError("Vbee Batch TTS did not return requestId")
    deadline = asyncio.get_running_loop().time() + config.VBEE_POLL_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(config.VBEE_POLL_INTERVAL_S)
        status_response = await client.get(f"{config.VBEE_TTS_URL}/requests/{request_id}", headers=headers)
        if status_response.is_error:
            raise RuntimeError(f"Vbee Batch status failed ({status_response.status_code}): {status_response.text[:500]}")
        data = status_response.json(); status = data.get("status")
        if status == "FAILED":
            raise RuntimeError(f"Vbee Batch TTS failed: {data.get('error') or data}")
        if status == "COMPLETED":
            audio_link = data.get("audioLink")
            if not audio_link:
                raise RuntimeError("Vbee Batch TTS completed without audioLink")
            audio = await client.get(audio_link)
            audio.raise_for_status()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(audio.content)
            return
    raise RuntimeError(f"Vbee Batch TTS timed out after {config.VBEE_POLL_TIMEOUT_S:g}s")
