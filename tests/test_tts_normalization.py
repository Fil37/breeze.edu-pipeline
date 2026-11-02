"""
Check normalize_text_for_tts (app/tts_manager.py): what the voice reads, never what is shown.
Offline (no ElevenLabs, no edge-tts call):
  1. "10x = 0,999..." -> "10 ixe égal 0 virgule neuf neuf neuf à l'infini" (said "999", the number
     would be finite: the run of 2026-11-01 on 0,999... = 1 said it so a dozen times)
  2. the other rules (ellipsis, digit + letter, decimal comma, = + × * / -, the maths minus, exponents,
     units, letters alone, acronyms), and the French text they must leave alone: "c'est-à-dire",
     "a-t-il", "Covid-19", "km/h", "1er", "2e siècle", "10h30", "L'ascenseur", "NASA"...
  3. generate_voice sends the normalized text to ElevenLabs and to edge-tts (the fallback), and the
     caller's text is unchanged (script.json and the storyboard are never touched)
  4. agent010 still times a cue written "10x" / "0,999" on the voice's words ("10", "ixe" / "0",
     "virgule", "999")
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_tts_normalization.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import tts_manager                                     # noqa: E402
from app.agent import agent010_html_renderer as renderer        # noqa: E402
from app.tts_manager import normalize_text_for_tts              # noqa: E402

RULES = [
    ("10x = 0,999...", "10 ixe égal 0 virgule neuf neuf neuf à l'infini"),
    ("0,999… = 1", "0 virgule neuf neuf neuf à l'infini égal 1"),
    ("0,999 et 2,5", "0 virgule 999 et 2 virgule 5"),
    ("f(x) = 2x + 1", "f(ixe) égal 2 ixe plus 1"),
    ("U = R × I", "u égal erre fois i"),
    ("2*3", "2 fois 3"),
    ("1/2 et U/I", "1 sur 2 et u sur i"),
    ("x - 2", "ixe moins 2"),
    ("10-x", "10 moins ixe"),
    ("-3 degrés", "moins 3 degrés"),
    ("4,5 V", "4 virgule 5 volts"),
    ("1 − 10⁻ⁿ", "1 moins 10 puissance moins enne"),
    ("x² et 10^3", "ixe au carré et 10 au cube"),
    ("9/10 + 9/100 + …", "9 sur 10 plus 9 sur 100 et ainsi de suite"),
    ("1/(1 − 1/10)", "1 sur (1 moins 1 sur 10)"),
    ("6 V, 0,5 A, 12 Ω", "6 volts, 0 virgule 5 ampères, 12 ohms"),
    ("I = U / R", "i égal u sur erre"),
    ("l'IPC et le PIB", "l'i pé cé et le pé i bé"),
    ("la NASA, l'ONU", "la NASA, l'ONU"),
    # French text that must stay as it is
    ("c'est-à-dire", "c'est-à-dire"),
    ("y a-t-il, va-t-on, dis-moi, peut-être", "y a-t-il, va-t-on, dis-moi, peut-être"),
    ("Covid-19", "Covid-19"),
    ("130 km/h", "130 km/h"),
    ("le 1er, le 2e siècle, le 21ème", "le 1er, le 2e siècle, le 21ème"),
    ("à 10h30, à 10h", "à 10h30, à 10h"),
    ("L'ascenseur, d'abord, il y a", "L'ascenseur, d'abord, il y a"),
    ("en 2024, 3 personnes", "en 2024, 3 personnes"),
]


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_example():
    want = "10 ixe égal 0 virgule neuf neuf neuf à l'infini"
    got = normalize_text_for_tts("10x = 0,999...")
    return report(f'1. "10x = 0,999..." -> "{want}"', [] if got == want else [repr(got)],
                  [f"-> {got!r}"])


def case_rules():
    problems = [f"{text!r} -> {normalize_text_for_tts(text)!r}, expected {expected!r}"
                for text, expected in RULES if normalize_text_for_tts(text) != expected]
    return report(f"2. {len(RULES)} rules and French text left alone", problems)


def case_engines():
    """generate_voice with both engines stubbed: what text does each one receive?"""
    sent, problems = {}, []
    narration = "On a 10x = 0,999..."
    original = {name: getattr(tts_manager, name) for name in ("elevenlabs_voice", "edge_voice", "media_duration")}

    def failing_elevenlabs(text, mp3_path, key, voice_id=None):
        sent["elevenlabs"], sent["voice_id"] = text, voice_id
        raise tts_manager.ElevenLabsError("HTTP 401 (test)", retry=False)

    def edge(text, mp3_path, words=None):
        sent["edge-tts"] = text
    saved_key = os.environ.get("ELEVENLABS_API_KEY")
    try:
        tts_manager.elevenlabs_voice, tts_manager.edge_voice = failing_elevenlabs, edge
        tts_manager.media_duration = lambda path: 1.0
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        stderr, sys.stderr = sys.stderr, open(os.devnull, "w")      # the fallback's WARNING
        try:
            tts_manager.generate_voice(narration, os.devnull, voice_id="channel-voice")
        finally:
            sys.stderr.close()
            sys.stderr = stderr
    finally:
        for name, value in original.items():
            setattr(tts_manager, name, value)
        if saved_key is None:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        else:
            os.environ["ELEVENLABS_API_KEY"] = saved_key
    expected = "On a 10 ixe égal 0 virgule neuf neuf neuf à l'infini"
    for engine in ("elevenlabs", "edge-tts"):
        if sent.get(engine) != expected:
            problems.append(f"{engine} received {sent.get(engine)!r}, expected {expected!r}")
    if sent.get("voice_id") != "channel-voice":
        problems.append(f"the channel's voice not passed on: {sent.get('voice_id')!r}")
    if narration != "On a 10x = 0,999...":
        problems.append("the caller's text changed")
    return report("3. ElevenLabs and edge-tts both receive the normalized text; the channel's voice is used", problems,
                  [f"{engine}: {text!r}" for engine, text in sent.items() if engine != "voice_id"])


def case_cues():
    brief = {"entities": [{"id": "f", "type": "TEX_FORMULA", "position": "CENTER", "initial_state": {"latex": "10x"}},
                          {"id": "g", "type": "TEX_FORMULA", "position": "LEFT", "initial_state": {"latex": "0,999"}}],
             "actions": [{"at": 0.5, "action": "spawn", "target": "f", "cue": "10x"},
                         {"at": 1.0, "action": "spawn", "target": "g", "cue": "0,999"}], "connections": []}
    # The voice's words for "On a 10x = 0,999...", as ElevenLabs returns them for the normalized text.
    spoken = [(0.0, "On"), (0.2, "a"), (0.5, "10"), (0.9, "ixe"), (1.3, "égal"), (1.8, "0"), (2.1, "virgule"), (2.6, "999")]
    events = {e["target"]: e["at"] for e in renderer.timeline(brief, 4.0, 4, spoken) if e["action"] == "spawn"}
    problems = [f"{target} spawns at {events.get(target)}, expected {at} (when its cue is said)"
                for target, at in (("f", 0.5), ("g", 1.8)) if events.get(target) != at]
    return report('4. agent010: cues "10x" and "0,999" timed on the spoken "10 ixe" and "0 virgule 999"', problems)


results = [case_example(), case_rules(), case_engines(), case_cues()]
sys.exit(0 if all(results) else 1)
