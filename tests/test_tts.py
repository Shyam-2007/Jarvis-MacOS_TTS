import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_sends_balanced_latency_and_assembles_stream():
    import tts
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3" + b"\x00" * 100)

    async with _client(handler) as c:
        r = await tts.synthesize_chunk("Good evening, sir.", api_key="k", voice_id="v", client=c)
    assert seen["url"] == tts.FISH_TTS_URL
    assert seen["auth"] == "Bearer k"
    assert seen["body"] == {"text": "Good evening, sir.", "reference_id": "v",
                            "format": "mp3", "mp3_bitrate": 128, "latency": "balanced"}
    assert r is not None and r.audio.startswith(b"ID3") and len(r.audio) == 103
    assert r.first_byte_sec >= 0 and r.total_sec >= r.first_byte_sec


@pytest.mark.asyncio
async def test_non_200_returns_none():
    import tts
    async with _client(lambda req: httpx.Response(401, content=b"nope")) as c:
        assert await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c) is None


@pytest.mark.asyncio
async def test_transport_error_returns_none():
    import tts

    def boom(request):
        raise httpx.ConnectError("down")

    async with _client(boom) as c:
        assert await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c) is None


@pytest.mark.asyncio
async def test_empty_text_or_missing_key_short_circuits():
    import tts
    calls = []

    async with _client(lambda req: calls.append(1) or httpx.Response(200, content=b"x")) as c:
        assert await tts.synthesize_chunk("   ", api_key="k", voice_id="v", client=c) is None
        assert await tts.synthesize_chunk("hi", api_key="", voice_id="v", client=c) is None
    assert calls == []


# --- the macOS voice (`say`) ---------------------------------------------------
#
# `tts._spawn_say` is the one process boundary; every test below fakes it, so
# the real `say` never runs.

def _wav_bytes(n_samples: int = 2205) -> bytes:
    data = bytes(n_samples * 2)
    fmt = (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (22050).to_bytes(4, "little") \
        + (44100).to_bytes(4, "little") + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
    body = b"WAVE" + b"fmt " + len(fmt).to_bytes(4, "little") + fmt \
        + b"data" + len(data).to_bytes(4, "little") + data
    return b"RIFF" + len(body).to_bytes(4, "little") + body


class _FakeSay:
    """Stands in for the `say` process: records argv and stdin, writes a
    WAV to the `-o` path (or not), and exits with `rc`."""

    def __init__(self, args, *, rc=0, audio=None, hang=False, stdout=b""):
        self.args = list(args)
        self.rc, self.audio, self.hang, self.stdout = rc, audio, hang, stdout
        self.returncode = None
        self.stdin = None
        self.killed = False

    async def communicate(self, data=None):
        self.stdin = data
        if self.hang:
            await asyncio.sleep(60)
        if "-o" in self.args and self.audio is not None:
            Path(self.args[self.args.index("-o") + 1]).write_bytes(self.audio)
        self.returncode = self.rc
        return self.stdout, b"say: boom" if self.rc else b""

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def _install_say(monkeypatch, **kw):
    import tts
    procs = []

    async def spawn(*args, capture_stdout=False):
        p = _FakeSay(args, **kw)
        procs.append(p)
        return p

    monkeypatch.setattr(tts, "_spawn_say", spawn)
    return procs


import asyncio  # noqa: E402  (used by the fakes above)


@pytest.mark.asyncio
async def test_macos_voice_returns_the_wav_say_wrote(monkeypatch):
    import tts
    wav = _wav_bytes()
    procs = _install_say(monkeypatch, audio=wav)
    r = await tts.synthesize_macos("Good evening, sir.")
    assert r is not None and r.audio == wav
    assert r.total_sec >= 0 and r.first_byte_sec == r.total_sec
    args = procs[0].args
    assert args[0] == "-o" and args[1].endswith(".wav")
    assert f"--data-format={tts.SAY_DATA_FORMAT}" in args
    assert args[-2:] == ["-f", "-"]
    assert "-v" not in args and "-r" not in args, "no voice/rate unless asked for"


@pytest.mark.asyncio
async def test_the_text_goes_in_on_stdin_never_as_an_argument(monkeypatch):
    """A sentence starting with a dash must not be read as an option."""
    import tts
    procs = _install_say(monkeypatch, audio=_wav_bytes())
    await tts.synthesize_macos("-v Zarvox is not a voice request.")
    assert procs[0].stdin == "-v Zarvox is not a voice request.".encode()
    assert not any("Zarvox" in a for a in procs[0].args)


@pytest.mark.asyncio
async def test_voice_and_rate_are_passed_when_set(monkeypatch):
    import tts
    procs = _install_say(monkeypatch, audio=_wav_bytes())
    await tts.synthesize_macos("Hello.", voice="Eddy (English (UK))", rate=190)
    args = procs[0].args
    assert args[args.index("-v") + 1] == "Eddy (English (UK))"
    assert args[args.index("-r") + 1] == "190"


@pytest.mark.asyncio
async def test_the_temp_file_is_removed_whatever_happens(monkeypatch):
    import tts
    for kw in ({"audio": _wav_bytes()}, {"rc": 1, "audio": _wav_bytes()}, {"audio": b""}):
        procs = _install_say(monkeypatch, **kw)
        await tts.synthesize_macos("Hello.")
        assert not Path(procs[0].args[1]).exists(), kw


@pytest.mark.asyncio
async def test_a_failing_say_is_none_not_an_exception(monkeypatch):
    import tts
    _install_say(monkeypatch, rc=1, audio=_wav_bytes())
    assert await tts.synthesize_macos("Hello.") is None
    _install_say(monkeypatch, audio=b"")
    assert await tts.synthesize_macos("Hello.") is None, "an empty file is no audio"

    async def missing(*a, **k):
        raise FileNotFoundError("say")
    monkeypatch.setattr(tts, "_spawn_say", missing)
    assert await tts.synthesize_macos("Hello.") is None, "not a Mac"


@pytest.mark.asyncio
async def test_a_hung_say_is_killed_and_given_up_on(monkeypatch):
    import tts
    procs = _install_say(monkeypatch, hang=True)
    assert await tts.synthesize_macos("Hello.", timeout=0.05) is None
    assert procs[0].killed


@pytest.mark.asyncio
async def test_empty_text_never_spawns_say(monkeypatch):
    import tts
    procs = _install_say(monkeypatch, audio=_wav_bytes())
    assert await tts.synthesize_macos("   ") is None
    assert procs == []


SAY_V_SAMPLE = """\
Albert              en_US    # Hello! My name is Albert.
Daniel              en_GB    # Hello! My name is Daniel.
Eddy (English (UK)) en_GB    # Hello! My name is Eddy.
Grandma (Chinese (China mainland)) zh_CN    # 你好！我叫Grandma。
Paulina             es_MX    # ¡Hola! Me llamo Paulina.
not a voice line at all
"""


def test_parse_voice_list_handles_names_with_spaces_and_parentheses():
    import tts
    voices = tts.parse_voice_list(SAY_V_SAMPLE)
    assert [v["name"] for v in voices] == [
        "Albert", "Daniel", "Eddy (English (UK))", "Grandma (Chinese (China mainland))", "Paulina"]
    assert voices[2]["lang"] == "en_GB" and voices[3]["lang"] == "zh_CN"


@pytest.mark.asyncio
async def test_list_macos_voices_reads_say_and_survives_its_absence(monkeypatch):
    import tts
    procs = _install_say(monkeypatch, stdout=SAY_V_SAMPLE.encode())
    voices = await tts.list_macos_voices()
    assert procs[0].args == ["-v", "?"] and len(voices) == 5

    async def missing(*a, **k):
        raise FileNotFoundError("say")
    monkeypatch.setattr(tts, "_spawn_say", missing)
    assert await tts.list_macos_voices() == []


def test_engine_defaults_to_macos_and_only_fish_selects_fish():
    import tts
    assert tts.engine_from_env({}) == "macos"
    assert tts.engine_from_env({"JARVIS_TTS_ENGINE": "fish"}) == "fish"
    assert tts.engine_from_env({"JARVIS_TTS_ENGINE": " FISH "}) == "fish"
    assert tts.engine_from_env({"JARVIS_TTS_ENGINE": "macos"}) == "macos"
    assert tts.engine_from_env({"JARVIS_TTS_ENGINE": "fsih"}) == "macos", \
        "a typo must still leave him a voice"
