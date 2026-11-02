"""
Subtitles: each scene's narration cut into short lines, each shown while the voice says it (timed on
the voice's word timings, the same ones the actions' cues use). The renderer (agent010) burns them
into the picture (D.subtitles, drawn by the page's seek) and writes the whole video's lines to
instance/<channel_id>/subtitles.srt for YouTube's own captions (agent008).

The text shown is the narration as written (what the viewer reads), not the text read by the voice
(numbers and symbols spelled out): each line is found in the voice's words through that spelled-out
form.
"""

import math
import re

from app.tts_manager import normalize_text_for_tts
from models.visual_brief_schema import find_cue, narration_words

LINE_MAX_CHARS = 62        # one line on screen at 1080p
BREAK_AFTER_CHARS = 28     # a comma or a colon ends the line once it is this long
SEARCH_AHEAD = 8           # words: a line's start is looked for this close to where the last one ended
MIN_SHOWN_SEC = 0.6        # a line too short to read stays at least this long (if the next one allows)
END_PAST_VOICE = 0.3       # the last line stays a little after the voice ends


def lines_of(text):
    """The narration as subtitle lines of at most LINE_MAX_CHARS: cut at each sentence's end, and at a
    comma, semicolon or colon once BREAK_AFTER_CHARS long; a piece still too long is cut into lines of
    even length (never a short leftover such as "un seul chemin." alone)."""
    pieces, current = [], []
    for word in str(text or "").split():
        current.append(word)
        if re.search(r"[.!?…»]$", word) or (re.search(r"[,;:]$", word) and len(" ".join(current)) >= BREAK_AFTER_CHARS):
            pieces.append(current)
            current = []
    if current:
        pieces.append(current)
    lines = []
    for words in pieces:
        count = math.ceil(len(" ".join(words)) / LINE_MAX_CHARS)
        target = len(" ".join(words)) / count
        line = []
        for word in words:
            if line and len(" ".join(line + [word])) > target + 4:
                lines.append(" ".join(line))
                line = []
            line.append(word)
        lines.append(" ".join(line))
    return lines


def subtitle_cues(narration, spoken, voice, display=lambda text: text):
    """[{"at", "end", "text"}] for one voice-over (seconds from its start). `spoken`: the voice's word
    timings [(seconds, word)]; without them the lines share the voice's length by their length.
    `display` turns a line into the text shown (agent010: LaTeX-like ^ and _ into plain symbols)."""
    lines = lines_of(narration)
    if not lines:
        return []
    words = [(at, word) for at, text in (spoken or []) for _, word in narration_words(text)]
    starts = []
    if words:
        position = 0
        for line in lines:
            said = [word for _, word in narration_words(normalize_text_for_tts(line))]
            index = find_cue(words, " ".join(said[:3]), position) if said else None
            if index is None or index > position + SEARCH_AHEAD:
                index = min(position, len(words) - 1)    # not found nearby: right after the last line
            starts.append(max(words[index][0], starts[-1] if starts else 0.0))
            position = index + len(said)
    else:
        total, done = sum(len(line) for line in lines), 0
        for line in lines:
            starts.append(voice * done / total)
            done += len(line)
    cues = []
    for i, (line, at) in enumerate(zip(lines, starts)):
        end = starts[i + 1] if i + 1 < len(lines) else voice + END_PAST_VOICE
        if end - at < MIN_SHOWN_SEC and i + 1 == len(lines):
            end = at + MIN_SHOWN_SEC
        if end > at:
            cues.append({"at": round(at, 2), "end": round(end, 2), "text": display(line)})
    return cues


def srt_time(seconds):
    millis = round(max(seconds, 0) * 1000)
    return f"{millis // 3_600_000:02d}:{millis // 60_000 % 60:02d}:{millis // 1000 % 60:02d},{millis % 1000:03d}"


def srt(cues):
    """SubRip text of [{"at", "end", "text"}] (seconds from the video's start)."""
    return "".join(f"{n}\n{srt_time(cue['at'])} --> {srt_time(cue['end'])}\n{cue['text']}\n\n"
                   for n, cue in enumerate(cues, start=1))
