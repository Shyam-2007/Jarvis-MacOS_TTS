"""Which voice JARVIS speaks with: the macOS `say` voice (the default) or
Fish Audio, chosen by JARVIS_TTS_ENGINE at boot.

Nothing here runs the real `say` or reaches Fish: `tts.synthesize_macos` and
`tts.synthesize_chunk` are replaced on the module, and `tts._spawn_say` is
blocked suite-wide by conftest.py.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

ORIGIN = {"Origin": "http://localhost:5173"}


def _load_server(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_ENV_FILE", str(tmp_path / ".env"))
    for key in ("JARVIS_TTS_ENGINE", "JARVIS_VOICE", "JARVIS_VOICE_RATE"):
        if key in env:
            monkeypatch.setenv(key, env[key])
        else:
            monkeypatch.delenv(key, raising=False)
    import data_paths
    importlib.reload(data_paths)
    import run_store
    importlib.reload(run_store)
    import server as server_module
    importlib.reload(server_module)
    run_store.init_db()
    return server_module


def _no_startup_preflight(monkeypatch):
    """The lifespan runs preflight, and with JARVIS_VOICE set its voice check
    would list the real installed voices with `say -v ?`."""
    import preflight

    async def nothing(**kw):
        return []
    monkeypatch.setattr(preflight, "run_checks", nothing)


def _record_engines(monkeypatch):
    import tts
    from tts import SynthResult
    calls = []

    async def macos(text, *, voice="", rate=0, timeout=15.0):
        calls.append(("macos", text, voice, rate))
        return SynthResult(b"RIFF-wav", 0.1, 0.1)

    async def fish(text, *, api_key, voice_id, client=None, **kw):
        calls.append(("fish", text, api_key, voice_id))
        return SynthResult(b"ID3-mp3", 0.1, 0.1)

    monkeypatch.setattr(tts, "synthesize_macos", macos)
    monkeypatch.setattr(tts, "synthesize_chunk", fish)
    return calls


@pytest.mark.asyncio
async def test_the_macos_voice_is_the_default(monkeypatch, tmp_path):
    server = _load_server(monkeypatch, tmp_path)
    calls = _record_engines(monkeypatch)
    assert server.TTS_ENGINE == "macos"
    assert await server._synth_for_speech("Good evening.") == b"RIFF-wav"
    assert calls == [("macos", "Good evening.", "", 0)]


@pytest.mark.asyncio
async def test_voice_and_rate_reach_say(monkeypatch, tmp_path):
    server = _load_server(monkeypatch, tmp_path, JARVIS_VOICE="Daniel", JARVIS_VOICE_RATE="185")
    calls = _record_engines(monkeypatch)
    await server._synth_for_speech("Hello.")
    assert calls == [("macos", "Hello.", "Daniel", 185)]


@pytest.mark.asyncio
async def test_a_junk_rate_is_the_voices_own(monkeypatch, tmp_path):
    server = _load_server(monkeypatch, tmp_path, JARVIS_VOICE_RATE="fast")
    assert server.MACOS_VOICE_RATE == 0


@pytest.mark.asyncio
async def test_fish_is_still_there_when_asked_for(monkeypatch, tmp_path):
    server = _load_server(monkeypatch, tmp_path, JARVIS_TTS_ENGINE="fish")
    calls = _record_engines(monkeypatch)
    assert await server._synth_for_speech("Hello.") == b"ID3-mp3"
    assert calls[0][0] == "fish"


@pytest.mark.asyncio
async def test_the_test_clip_is_the_live_voice(monkeypatch, tmp_path):
    """`/api/tts-test` used to carry its own Fish client; it now speaks with
    whatever is live, so the clip is the voice you will actually hear."""
    server = _load_server(monkeypatch, tmp_path)
    calls = _record_engines(monkeypatch)
    assert await server.synthesize_speech("Testing.") == b"RIFF-wav"
    assert calls[0][0] == "macos"


def test_voice_settings_are_writable_and_validated(monkeypatch, tmp_path):
    server = _load_server(monkeypatch, tmp_path)
    for key, value in (("JARVIS_TTS_ENGINE", "fish"), ("JARVIS_TTS_ENGINE", "macos"),
                       ("JARVIS_VOICE", "Eddy (English (UK))"), ("JARVIS_VOICE", ""),
                       ("JARVIS_VOICE_RATE", "180"), ("JARVIS_VOICE_RATE", "")):
        assert server._env_value_problem(key, value) is None, (key, value)
    assert server._env_value_problem("JARVIS_TTS_ENGINE", "elevenlabs")
    for bad in ("fast", "-5", "0", "1e3", "100000"):
        assert server._env_value_problem("JARVIS_VOICE_RATE", bad), bad
    server._write_env_key("JARVIS_VOICE", "Eddy (English (UK))")
    _, parsed = server._read_env()
    assert parsed["JARVIS_VOICE"] == "Eddy (English (UK))", "spaces and parentheses round-trip"


def test_status_reports_the_live_and_the_configured_voice(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    server = _load_server(monkeypatch, tmp_path, JARVIS_VOICE="Daniel")
    (tmp_path / ".env").write_text("JARVIS_TTS_ENGINE=fish\nJARVIS_VOICE=Moira\n")
    _no_startup_preflight(monkeypatch)
    with TestClient(server.app, headers=ORIGIN) as c:
        voice = c.get("/api/settings/status").json()["voice"]
    assert voice == {"engine": "macos", "macos_voice": "Daniel",
                     "configured_engine": "fish", "configured_macos_voice": "Moira"}


def test_the_voice_list_endpoint(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import tts
    server = _load_server(monkeypatch, tmp_path)

    async def voices(timeout=5.0):
        return [{"name": "Daniel", "lang": "en_GB"}]

    monkeypatch.setattr(tts, "list_macos_voices", voices)
    _no_startup_preflight(monkeypatch)
    with TestClient(server.app, headers=ORIGIN) as c:
        r = c.get("/api/settings/voices")
    assert r.status_code == 200 and r.json() == {"voices": [{"name": "Daniel", "lang": "en_GB"}]}
