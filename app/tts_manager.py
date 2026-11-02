"""
French voice-overs for the renderer (agent010): generate_voice(text, mp3_path, spoken).

  1. ElevenLabs first (a livelier, more expressive voice), when ELEVENLABS_API_KEY is set (.env):
     POST /v1/text-to-speech/{voice}/with-timestamps, which returns the MP3 and when each character
     is said, so the word timings agent010 times its cues on are kept.
  2. edge-tts otherwise, or when ElevenLabs fails (network, timeout, invalid key, quota): a WARNING
     on stderr, and the scene gets the edge-tts voice instead, so the render never stops for that.
     edge-tts also gives word timings (WordBoundary events).
The narration is spoken through normalize_text_for_tts first (on the fly: script.json, the
storyboard and the text on screen keep "10x" and "0,999..."), so "10x" is not read "dix-sexe" and
"0,999..." does not stutter. The word timings are those of the normalized text.
The duration is measured with ffprobe on the written file, whatever the engine. The key is read from
the environment at each call, never written anywhere; nothing else is sent but the narration text.

Settings (environment / .env, all optional):
  ELEVENLABS_API_KEY    no key: edge-tts only (said once on stderr)
  ELEVENLABS_VOICE_ID   the voice; default ELEVENLABS_DEFAULT_VOICE below
  ELEVENLABS_MODEL_ID   default "eleven_multilingual_v2" (speaks French with any voice)
"""

import asyncio
import base64
import os
import re
import subprocess
import sys
import time

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass  # python-dotenv not installed: rely on variables already in the environment

# ElevenLabs. Change the voice here or with ELEVENLABS_VOICE_ID: the voice id is in the ElevenLabs
# app (Voices -> the voice -> "Copy voice ID"); a native French voice from the Voice Library sounds
# the most natural. Default: "Charlotte" (premade voice, multilingual: speaks French with v2).
ELEVENLABS_DEFAULT_VOICE = "GFj5Qf6cNQ3Lgp8VKBwc"
ELEVENLABS_DEFAULT_MODEL = "eleven_multilingual_v2"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"
ELEVENLABS_FORMAT = "mp3_44100_128"
# Lower stability = more expressive delivery; style adds emphasis (a teaching tone, not flat).
ELEVENLABS_SETTINGS = {"stability": 0.4, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True}
ELEVENLABS_TIMEOUT_SEC = 60
ELEVENLABS_ATTEMPTS = 2   # a second try on a network error / 429 / 5xx (not on a refused key or quota)

# edge-tts (the fallback, and the voice when there is no key).
VOICE_PRIMARY = "fr-FR-VivienneMultilingualNeural"   # neural voice; or "fr-FR-RemyMultilingualNeural" (male)
VOICE_RATE = "+3%"                                   # a touch faster: an energetic teaching tone
VOICE_PITCH = "+0Hz"
TTS_TIMEOUT_SEC = 120
TTS_ATTEMPTS = 4          # edge-tts is a free online service: it sometimes answers with no audio
TTS_RETRY_WAIT_SEC = (2, 5, 10)   # pause before attempts 2, 3, 4

_said_no_key = False

# Normalization for the voice only (normalize_text_for_tts). A hyphen is a minus only in a calculation
# (a number on one side, "x - y" with spaces, or before a number): "c'est-à-dire", "a-t-il",
# "Covid-19" keep theirs. A slash is "sur" only between numbers / one-letter variables ("1/2", "U/I"),
# so "km/h" stays. A number keeps a French ordinal ("1er", "2e", "21ème") or an hour ("10h", "10h30")
# stuck to it.
NUM_LEFT, VAR_LEFT = r"(?<=[\d)])", r"(?<=\b[A-Za-z])"     # what ends just before the sign (a closing bracket too)
NUM_RIGHT, VAR_RIGHT = r"(?=[\d(])", r"(?=[A-Za-z]\b)"      # what starts just after it (an opening bracket too)
DIGIT_WORDS = "zéro un deux trois quatre cinq six sept huit neuf".split()
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺ⁿˣ", "0123456789-+nx")
# A letter alone is a quantity or a point ("I égal U sur R", "le point A"): said by its French name,
# so a multilingual voice never reads "I" as the English "aï". Lowercase: only x and n, never words.
LETTER_NAMES = {"A": "a", "B": "bé", "C": "cé", "D": "dé", "E": "eu", "F": "effe", "G": "gé", "H": "ache", "I": "i",
                "J": "ji", "K": "ka", "L": "elle", "M": "emme", "N": "enne", "O": "o", "P": "pé", "Q": "ku", "R": "erre",
                "S": "esse", "T": "té", "U": "u", "V": "vé", "W": "double vé", "X": "ixe", "Y": "i grec", "Z": "zède",
                "x": "ixe", "n": "enne"}
# Acronyms said as words: left alone; any other 2 to 4 capitals ("IPC", "PIB", "ISS") are spelled.
SPOKEN_ACRONYMS = {"NASA", "ONU", "OTAN", "OPEP", "UNESCO", "UNICEF", "CAC", "SMIC", "LED", "OK"}
UNITS = {"V": "volts", "mV": "millivolts", "kV": "kilovolts", "A": "ampères", "mA": "milliampères", "W": "watts",
         "kW": "kilowatts", "Ω": "ohms", "N": "newtons", "J": "joules", "Hz": "hertz", "kg": "kilos"}


def power(written):
    """An exponent, "⁻ⁿ" / "^(-n)" / "²" -> " puissance moins n " / " au carré"."""
    exponent = written.translate(SUPERSCRIPTS).strip("()").replace("-", " moins ").replace("+", " plus ")
    return {"2": " au carré", "3": " au cube"}.get(exponent.strip(), f" puissance {exponent} ")


TTS_RULES = [
    (re.compile(r"\^\s*\{([^{}]{1,8})\}|\^\s*(\([^()]{1,8}\)|-?\w+)|([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺ⁿˣ]+)"),
     lambda m: power(m.group(1) or m.group(2) or m.group(3))),              # 10⁻ⁿ, x^2, 10^{-n}
    (re.compile(r"(?<![\w\\])([A-Za-z])_\{?([A-Za-z0-9]{1,3})\}?(?![\w])"), r"\1 indice \2"),   # t_n, t_{n}
    (re.compile(r"<=|≤"), " inférieur ou égal à "),
    (re.compile(r">=|≥"), " supérieur ou égal à "),
    (re.compile(r"≠|!="), " différent de "),
    (re.compile(r"(?<=[\w)….])\s*<\s*(?=[\w(−-])"), " inférieur à "),       # 0,999… < y < 1
    (re.compile(r"(?<=[\w)….])\s*>\s*(?=[\w(−-])"), " supérieur à "),
    (re.compile(r"≈"), " environ égal à "),
    (re.compile(r"→"), " tend vers "),
    (re.compile(r"(\d+),(\d+)\s*(?:…|\.{3})\s*(\d)(?!\d)"),                       # 0,999…9: a truncation, it ends
     lambda m: f"{m.group(1)} virgule {' '.join(DIGIT_WORDS[int(d)] for d in m.group(2))}, et ainsi de suite "
               f"jusqu'à un dernier {DIGIT_WORDS[int(m.group(3))]}"),
    (re.compile(r"\s*[−–]\s*(?=[\w(])"), " moins "),                                  # the maths minus sign
    (re.compile(r"(\d+),(\d+)\s*(?:…|\.{3})"),                                          # 0,999… : the 9s go on
     lambda m: f"{m.group(1)} virgule {' '.join(DIGIT_WORDS[int(d)] for d in m.group(2))} à l'infini"),
    (re.compile(r"\+\s*(?:…|\.{3})"), " et ainsi de suite"),                            # 9/10 + 9/100 + …
    (re.compile(r"\.{3}|…"), " "),                                          # ellipsis: no stutter
    (re.compile(r"(?<=\d),(?=\d)"), " virgule "),                          # 0,999 -> 0 virgule 999
    (re.compile(r"(?<=\d)\s*(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")(?![\w'’])"),
     lambda m: " " + UNITS[m.group(1)]),                                    # 6 V -> 6 volts, 12 Ω -> 12 ohms
    (re.compile(r"(\d)(?!(?:er|re|e|ème|eme|nd|nde)\b|h\d|h\b)([A-Za-zÀ-ÿ])"), r"\1 \2"),   # 10x -> 10 x
    (re.compile(r"="), " égal "),
    (re.compile(r"\+"), " plus "),
    (re.compile(r"[×*]"), " fois "),
    (re.compile(rf"(?:{NUM_LEFT}|{VAR_LEFT})\s*/\s*(?:{NUM_RIGHT}|{VAR_RIGHT})"), " sur "),
    (re.compile(rf"{NUM_LEFT}\s*-\s*(?:{NUM_RIGHT}|{VAR_RIGHT})|{VAR_LEFT}\s*-\s*{NUM_RIGHT}"
                rf"|{VAR_LEFT}\s+-\s+{VAR_RIGHT}|(?<![\w-])-(?=\s*\d)"), " moins "),
    (re.compile(r"(?<![\w-])([A-Z]{2,4})(?![\w'’-])"),                    # l'IPC -> l'i pé cé (not NASA)
     lambda m: m.group(1) if m.group(1) in SPOKEN_ACRONYMS else " ".join(LETTER_NAMES[c] for c in m.group(1))),
    (re.compile(r"(?<![\w'’-])([A-Zxn])(?![\w'’-])"), lambda m: LETTER_NAMES[m.group(1)]),   # I -> i, R -> erre
]


def normalize_text_for_tts(text: str) -> str:
    """What the voice reads for `text`: "10x = 0,999..." -> "10 ixe égal 0 virgule neuf neuf neuf à
    l'infini". A decimal ending in an ellipsis is said digit by digit, "à l'infini" (said "999", it
    is a finite number); "+ …" is "et ainsi de suite"; other ellipses become a space; exponents are
    "puissance" (2 and 3: "au carré", "au cube"), LaTeX braces too ("10^{-n}"); an index "t_n" is
    "t indice n"; < > ≤ ≥ ≠ ≈ → are "inférieur à", "supérieur à", "inférieur ou égal à"...; a truncated
    decimal "0,999…9" goes on "jusqu'à un dernier neuf" (not "à l'infini"); the maths minus "−" is "moins"; a digit and a letter
    stuck together are split; a decimal comma is "virgule"; a unit after a number is its name (6 V ->
    6 volts); = + × * / - are "égal", "plus", "fois", "sur", "moins" (/ and - only in a calculation,
    see TTS_RULES); a capital letter alone, and x or n, by its French name; 2 to 4 capitals spelled
    (IPC -> i pé cé), but for the acronyms said as words (SPOKEN_ACRONYMS)."""
    text = str(text or "")
    for pattern, replacement in TTS_RULES:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def warn(message):
    print(f"WARNING tts: {message}", file=sys.stderr, flush=True)


def media_duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                            capture_output=True, text=True, timeout=60)
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe could not read the duration of {os.path.basename(path)}: {result.stderr.strip()}")


def words_from_alignment(alignment):
    """ElevenLabs' character alignment -> [(start in s, word)], a word being a run of non-spaces."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    words, current, start = [], "", None
    for char, at in zip(chars, starts):
        if char.isspace():
            if current:
                words.append((start, current))
            current, start = "", None
        else:
            current, start = current + char, at if start is None else start
    if current:
        words.append((start, current))
    return words


class ElevenLabsError(RuntimeError):
    def __init__(self, message, retry):
        super().__init__(message)
        self.retry = retry


def elevenlabs_voice(text, mp3_path, key):
    """Write ElevenLabs' MP3 of `text` to mp3_path; returns its word timings [(seconds, word)]."""
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or ELEVENLABS_DEFAULT_VOICE
    model = os.environ.get("ELEVENLABS_MODEL_ID", "").strip() or ELEVENLABS_DEFAULT_MODEL
    try:
        response = requests.post(ELEVENLABS_URL.format(voice=voice), params={"output_format": ELEVENLABS_FORMAT},
                                 headers={"xi-api-key": key, "Content-Type": "application/json"},
                                 json={"text": text, "model_id": model, "voice_settings": ELEVENLABS_SETTINGS},
                                 timeout=ELEVENLABS_TIMEOUT_SEC)
    except requests.RequestException as exc:          # network error, timeout
        raise ElevenLabsError(f"{type(exc).__name__}: {exc}", retry=True) from exc
    if response.status_code != 200:
        detail = response.text[:200].replace("\n", " ")
        raise ElevenLabsError(f"HTTP {response.status_code}: {detail}",
                              retry=response.status_code == 429 or response.status_code >= 500)
    try:
        body = response.json()
        audio = base64.b64decode(body["audio_base64"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ElevenLabsError(f"unexpected answer: {exc!r}", retry=True) from exc
    if not audio:
        raise ElevenLabsError("empty audio", retry=True)
    with open(mp3_path, "wb") as f:
        f.write(audio)
    return words_from_alignment(body.get("alignment") or {})


async def speak(communicate, mp3_path, words):
    """Write the voice to mp3_path; with WordBoundary events on, add (start in s, word) to `words`."""
    with open(mp3_path, "wb") as audio:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append((chunk["offset"] / 1e7, chunk["text"]))   # offsets in 100 ns ticks


def edge_voice(text, mp3_path, words=None):
    """edge-tts is async-only: run its one coroutine to completion, with a timeout. The service now
    and then returns no audio (NoAudioReceived) or drops the connection, mostly after many requests
    in a row: try again, up to TTS_ATTEMPTS times with growing pauses, before failing."""
    import edge_tts
    for attempt in range(1, TTS_ATTEMPTS + 1):
        try:
            spoken = []
            communicate = edge_tts.Communicate(text, VOICE_PRIMARY, rate=VOICE_RATE, pitch=VOICE_PITCH,
                                               boundary="WordBoundary" if words is not None else "SentenceBoundary")
            asyncio.run(asyncio.wait_for(speak(communicate, mp3_path, spoken), TTS_TIMEOUT_SEC))
            if words is not None:
                words[:] = spoken
            return
        except Exception as exc:       # NoAudioReceived, timeout, network error...
            if attempt == TTS_ATTEMPTS:
                raise RuntimeError(f"edge-tts failed {TTS_ATTEMPTS} times: {exc!r}") from exc
            wait = TTS_RETRY_WAIT_SEC[attempt - 1]
            print(f"--- tts: edge-tts attempt {attempt} failed ({type(exc).__name__}), retrying in {wait}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)


def generate_voice(text, mp3_path, spoken=None, engine=None):
    """French voice-over of `text` in mp3_path: ElevenLabs, else edge-tts (see the module's notes).
    Returns the measured duration in seconds. Given a list `spoken`, fills it with when each word is
    said: [(seconds, word)] (agent010 times the actions' cues on them). Given a dict `engine`, sets
    engine["used"] to "elevenlabs" or "edge-tts", and engine["fallback"] to why ElevenLabs failed
    when edge-tts stood in for it (None otherwise: ElevenLabs worked, or there is no key).
    Raises only if edge-tts fails too."""
    global _said_no_key
    text = normalize_text_for_tts(text)        # for both engines; the caller's text is left as it is
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    used, fallback = "edge-tts", None
    if key:
        for attempt in range(1, ELEVENLABS_ATTEMPTS + 1):
            try:
                words = elevenlabs_voice(text, mp3_path, key)
                used = "elevenlabs"
                break
            except ElevenLabsError as exc:
                if exc.retry and attempt < ELEVENLABS_ATTEMPTS:
                    time.sleep(2)
                    continue
                warn(f"ElevenLabs failed ({exc}); falling back to edge-tts for this voice-over")
                fallback = str(exc)[:200]
                break
    elif not _said_no_key:
        print("--- tts: ELEVENLABS_API_KEY not set: edge-tts voice", file=sys.stderr, flush=True)
        _said_no_key = True
    if used == "edge-tts":
        words = [] if spoken is not None else None
        edge_voice(text, mp3_path, words)
    if spoken is not None:
        spoken[:] = words or []
    if engine is not None:
        engine.update(used=used, fallback=fallback)
    return media_duration(mp3_path)


def voice_report(scenes, warnings):
    """For render_manifest.json: the video's voice engine from its scenes' "voice_engine" ("elevenlabs",
    "edge-tts", "mixed" when they differ, None when no voice was made, e.g. a dry run). Adds a warning
    to `warnings` for the scenes where ElevenLabs failed and edge-tts stood in ("voice_fallback")."""
    engines = {scene["voice_engine"] for scene in scenes if scene.get("voice_engine")}
    fell_back = [str(scene["scene_id"]) for scene in scenes if scene.get("voice_fallback")]
    if fell_back:
        warnings.append(f"voice: ElevenLabs failed for scene(s) {', '.join(fell_back)}, edge-tts stood in"
                        + (" (mixed voices in the video)" if len(engines) > 1 else ""))
    return "mixed" if len(engines) > 1 else next(iter(engines), None)
