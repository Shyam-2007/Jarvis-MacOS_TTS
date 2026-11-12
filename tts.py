"""
tts.py — speech synthesis, one call per sentence chunk.

Two engines, picked by `JARVIS_TTS_ENGINE` (see `engine_from_env`):

- **macos** (the default): the Mac's own speech synthesizer via `say`. No
  key, no network. Writes one WAV per chunk, which the browser decodes and
  plays exactly as it played Fish's MP3, so the orb, the `played` acks and
  barge-in are untouched.
- **fish**: Fish Audio's HTTP API. The response is streamed so
  time-to-first-byte can be measured; the chunk is returned whole because
  the browser decodes one complete MP3 per chunk.

Either way the result is one complete, self-describing audio file in
`SynthResult.audio`, and a failure is `None`, never an exception.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("jarvis.tts")

FISH_TTS_URL = "https://api.fish.audio/v1/tts"


@dataclass
class SynthResult:
    audio: bytes
    first_byte_sec: float
    total_sec: float


async def synthesize_chunk(text: str, *, api_key: str, voice_id: str,
                           client: Optional[httpx.AsyncClient] = None,
                           latency: str = "balanced", timeout: float = 15.0) -> Optional[SynthResult]:
    text = (text or "").strip()
    if not text or not api_key:
        return None
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    t0 = time.monotonic()
    first: Optional[float] = None
    buf = bytearray()
    try:
        async with client.stream(
            "POST", FISH_TTS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"text": text, "reference_id": voice_id, "format": "mp3", "mp3_bitrate": 128, "latency": latency},
            timeout=timeout,
        ) as resp:
            if resp.status_code != 200:
                log.error(f"TTS {resp.status_code} for {text[:40]!r}")
                return None
            async for part in resp.aiter_bytes():
                if first is None:
                    first = time.monotonic() - t0
                buf.extend(part)
    except (httpx.HTTPError, OSError) as e:
        log.error(f"TTS error: {e}")
        return None
    finally:
        if own:
            try:
                await client.aclose()
            except Exception as e:      # never turn a clean None into an exception
                log.debug(f"TTS client close failed: {e}")
    if not buf:
        return None
    return SynthResult(bytes(buf), first if first is not None else 0.0, time.monotonic() - t0)


# ── engine selection ────────────────────────────────────────────────────

ENGINE_MACOS = "macos"
ENGINE_FISH = "fish"
ENGINES = (ENGINE_MACOS, ENGINE_FISH)


def engine_from_env(env: Optional[Mapping[str, str]] = None) -> str:
    """The configured engine. Anything but an explicit `fish` is the macOS
    voice — an unset or misspelt value must still leave JARVIS a voice."""
    env = os.environ if env is None else env
    raw = (env.get("JARVIS_TTS_ENGINE") or "").strip().lower()
    if raw and raw not in ENGINES:
        log.warning(f"JARVIS_TTS_ENGINE={raw!r} is not one of {ENGINES}; using {ENGINE_MACOS}")
    return ENGINE_FISH if raw == ENGINE_FISH else ENGINE_MACOS


# ── macOS `say` ─────────────────────────────────────────────────────────

# 16-bit little-endian PCM at 22.05 kHz: what `say` speaks at natively, small
# enough to base64 over the voice socket, and decodable by every browser's
# `decodeAudioData`. The container (WAV) is inferred from the `.wav` suffix.
SAY_DATA_FORMAT = "LEI16@22050"
SAY_BIN = "say"


async def _spawn_say(*args: str, capture_stdout: bool = False):
    """The one process boundary for `say`, so tests fake this instead of
    asyncio (tests/conftest.py blocks it everywhere but test_tts.py)."""
    return await asyncio.create_subprocess_exec(
        SAY_BIN, *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE if capture_stdout else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )


async def synthesize_macos(text: str, *, voice: str = "", rate: int = 0,
                           timeout: float = 15.0) -> Optional[SynthResult]:
    """Speak `text` into a WAV with the Mac's built-in voice.

    The text goes in on stdin (`-f -`), never as an argument, so a sentence
    that starts with a dash is still a sentence. `voice` is a name from
    `say -v ?` (empty = the system voice); `rate` is words per minute
    (0 = the voice's own).
    """
    text = (text or "").strip()
    if not text:
        return None
    fd, path = tempfile.mkstemp(prefix="jarvis-say-", suffix=".wav")
    os.close(fd)
    args = ["-o", path, f"--data-format={SAY_DATA_FORMAT}"]
    if voice:
        args += ["-v", voice]
    if rate > 0:
        args += ["-r", str(rate)]
    args += ["-f", "-"]
    t0 = time.monotonic()
    proc = None
    try:
        proc = await _spawn_say(*args)
        try:
            _, err = await asyncio.wait_for(proc.communicate(text.encode("utf-8")), timeout)
        except asyncio.TimeoutError:
            log.error(f"TTS (say) timed out after {timeout}s for {text[:40]!r}")
            return None
        if proc.returncode != 0:
            detail = (err or b"").decode("utf-8", "replace").strip()[:200]
            log.error(f"TTS (say) exited {proc.returncode} for {text[:40]!r}: {detail}")
            return None
        with open(path, "rb") as f:
            audio = f.read()
    except OSError as e:          # `say` missing (not a Mac), unreadable output
        log.error(f"TTS (say) error: {e}")
        return None
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass
        try:
            os.unlink(path)
        except OSError:
            pass
    if not audio:
        return None
    total = time.monotonic() - t0
    return SynthResult(audio, total, total)


# `say -v ?` prints one voice per line:
#   Daniel              en_GB    # Hello! My name is Daniel.
#   Eddy (English (UK)) en_GB    # Hello! My name is Eddy.
# The name may contain spaces and parentheses, so it is everything before
# the last locale-shaped word that precedes the `#`.
_VOICE_LINE_RE = re.compile(r"^(?P<name>\S.*?)\s+(?P<lang>[a-z]{2,3}(?:[_-][A-Za-z0-9]+)+)\s+#")


def parse_voice_list(output: str) -> list[dict[str, str]]:
    """`say -v ?` output -> [{"name", "lang"}], in the order `say` gave."""
    voices = []
    for line in output.splitlines():
        m = _VOICE_LINE_RE.match(line)
        if m:
            voices.append({"name": m.group("name").strip(), "lang": m.group("lang")})
    return voices


async def list_macos_voices(timeout: float = 5.0) -> list[dict[str, str]]:
    """The voices installed on this Mac; empty if `say` is unavailable."""
    proc = None
    try:
        proc = await _spawn_say("-v", "?", capture_stdout=True)
        out, _ = await asyncio.wait_for(proc.communicate(b""), timeout)
    except (OSError, asyncio.TimeoutError) as e:
        log.warning(f"could not list macOS voices: {e!r}")
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass
        return []
    return parse_voice_list(out.decode("utf-8", "replace"))
