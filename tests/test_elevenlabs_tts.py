"""
Check the voice-over (app/tts_manager.generate_voice): ElevenLabs first, edge-tts when it fails.
Needs the internet; case 1 uses a few dozen characters of the ElevenLabs quota (ELEVENLABS_API_KEY
from .env).
  1. ElevenLabs: "Ceci est un test de la voix ElevenLabs pour L_breeze." -> an .mp3 longer than 0 s,
     made by ElevenLabs, with the word timings (in order) agent010 times its cues on
  2. fallback, invalid key: ElevenLabs refuses it -> a WARNING, edge-tts makes the .mp3, no crash
  3. fallback, network error (ElevenLabs unreachable) -> the same
  4. no key at all (as if removed from .env) -> edge-tts directly
  In 1-4, the engine reported for render_manifest.json: "used" and "fallback" (why ElevenLabs failed,
  only in 2 and 3).
  5. offline: voice_report, the video's "voice_engine" in render_manifest.json: "elevenlabs",
     "mixed" with a warning naming the scenes that fell back, "edge-tts" without a key (no warning),
     None for a dry run
Prints PASS or FAIL per case. With --keep, the .mp3 files are kept in media/test_elevenlabs_tts/ to
listen to (otherwise a temporary folder).

  .venv/bin/python tests/test_elevenlabs_tts.py
"""

import contextlib
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import tts_manager   # noqa: E402  (loads .env)

TEXT = "Ceci est un test de la voix ElevenLabs pour L_breeze."
KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()


@contextlib.contextmanager
def environment(key, url=None):
    """ELEVENLABS_API_KEY = key (None: unset) and, if given, another ElevenLabs URL, for one case."""
    saved_key, saved_url = os.environ.get("ELEVENLABS_API_KEY"), tts_manager.ELEVENLABS_URL
    if key is None:
        os.environ.pop("ELEVENLABS_API_KEY", None)
    else:
        os.environ["ELEVENLABS_API_KEY"] = key
    tts_manager.ELEVENLABS_URL = url or saved_url
    try:
        yield
    finally:
        tts_manager.ELEVENLABS_URL = saved_url
        if saved_key is None:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        else:
            os.environ["ELEVENLABS_API_KEY"] = saved_key


def check(label, folder, name, key, expected_engine, expect_warning, url=None):
    path, spoken, engine, problems, log = os.path.join(folder, name + ".mp3"), [], {}, [], io.StringIO()
    duration = 0.0
    with environment(key, url), contextlib.redirect_stderr(log):
        try:
            duration = tts_manager.generate_voice(TEXT, path, spoken, engine)
        except Exception as exc:
            problems.append(f"crashed: {exc!r}")
    if not problems:
        if engine.get("used") != expected_engine:
            problems.append(f"voice by {engine.get('used')!r}, expected {expected_engine!r}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            problems.append("no .mp3 written")
        if bool(engine.get("fallback")) != expect_warning:
            problems.append(f"engine fallback {engine.get('fallback')!r}")
        if not duration > 0:
            problems.append(f"duration {duration}")
        if not spoken or [at for at, _ in spoken] != sorted(at for at, _ in spoken):
            problems.append(f"word timings missing or out of order: {spoken[:5]}")
    warned = "WARNING tts:" in log.getvalue()
    if warned != expect_warning:
        problems.append("no WARNING logged" if expect_warning else "an unexpected WARNING")
    print(f'{"FAIL" if problems else "PASS"}  {label}  ({engine.get("used")}, {duration:.2f} s, {len(spoken)} words)'
          + "".join(f"\n      {line}" for line in log.getvalue().splitlines() if "WARNING" in line or "tts:" in line)
          + "".join(f"\n      problem: {p}" for p in problems))
    if spoken:
        print("      words: " + ", ".join(f"{word}@{at:.2f}" for at, word in spoken[:6]) + (" ..." if len(spoken) > 6 else ""))
    return not problems


def main(folder):
    results = []
    if KEY:
        results.append(check("1. ElevenLabs: the phrase as .mp3, with word timings", folder, "elevenlabs", KEY,
                             "elevenlabs", False))
    else:
        print("FAIL  1. ElevenLabs: ELEVENLABS_API_KEY is not set (.env)")
        results.append(False)
    results.append(check("2. fallback, invalid key: edge-tts takes over", folder, "fallback_invalid_key",
                         "invalid-key-for-test", "edge-tts", True))
    results.append(check("3. fallback, ElevenLabs unreachable: edge-tts takes over", folder, "fallback_network",
                         "invalid-key-for-test", "edge-tts", True, url="http://127.0.0.1:9/{voice}"))
    results.append(check("4. no key: edge-tts directly", folder, "no_key", None, "edge-tts", False))
    results.append(check_report())
    return all(results)


def check_report():
    def scenes(*engines):
        return [{"scene_id": str(i + 1), "voice_engine": used, "voice_fallback": "HTTP 401" if fell_back else None}
                for i, (used, fell_back) in enumerate(engines)]
    eleven, fallback, edge = ("elevenlabs", False), ("edge-tts", True), ("edge-tts", False)
    cases = [(scenes(eleven, eleven), "elevenlabs", False), (scenes(eleven, fallback, eleven), "mixed", True),
             (scenes(edge, edge), "edge-tts", False), ([], None, False)]
    problems = []
    for scene_list, expected, expect_warning in cases:
        warnings = []
        got = tts_manager.voice_report(scene_list, warnings)
        if got != expected or bool(warnings) != expect_warning:
            problems.append(f"{[s['voice_engine'] for s in scene_list]} -> {got!r}, warnings {warnings}")
        if warnings:
            print(f"      warning: {warnings[0]}")
    print(f'{"FAIL" if problems else "PASS"}  5. voice_engine for render_manifest.json (offline)'
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


if "--keep" in sys.argv:
    out = os.path.join(ROOT, "media", "test_elevenlabs_tts")
    os.makedirs(out, exist_ok=True)
    ok = main(out)
    print(f"files: {out}")
else:
    with tempfile.TemporaryDirectory() as tmp:
        ok = main(tmp)
sys.exit(0 if ok else 1)
