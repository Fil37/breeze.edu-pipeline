"""
What plays under the voice, all made here from numbers (no clip, no licence, no Content ID claim):
  - a music bed in the channel's mood (MOODS: its key, chords and tempo) and a style (STYLES:
    "ambient", soft chords, a bass note and a light arpeggio; "lofi", electric piano chords, a soft
    beat and a little vinyl hiss; "cinematic", a slow string pad, low piano notes and a quiet pulse),
    the length of the whole video, faded in and out;
  - sound effects on the animation: a soft "pop" when a thing appears (spawn), a "tick" when a value
    changes (set_value), a "whoosh" when a scene gives way to the next.
Both are written as WAV files; app/render/video.py mixes them under the voice (the music ducked while
someone speaks) before the loudness is brought to its target, so -16 LUFS still holds.
Seeded by the channel's name: the same video always gets the same music.
"""

import wave
import zlib

import numpy as np
from scipy.signal import butter, lfilter

RATE = 48000
A4 = 440.0
# Moods: the root (MIDI note), the chords (semitones from the root: a triad, played as a pad) and the
# tempo. Minor and slow for space, minor and brisk for electronics, major for maths and economics.
MOODS = {
    "tech":  {"root": 57, "bpm": 92, "chords": [(0, 3, 7), (-4, 0, 3), (-9, -5, -2), (-2, 2, 5)]},     # Am F C G
    "space": {"root": 50, "bpm": 72, "chords": [(0, 3, 7), (-2, 2, 5), (-4, 0, 3), (-5, -1, 2)]},      # Dm C Bb A
    "calm":  {"root": 60, "bpm": 84, "chords": [(0, 4, 7), (-3, 0, 4), (-7, -3, 0), (-5, -1, 2)]},     # C Am F G
    "warm":  {"root": 53, "bpm": 80, "chords": [(0, 4, 7), (-5, -1, 2), (-3, 0, 4), (-7, -3, 0)]},     # F C Dm Bb
}
CHANNEL_MOODS = (("electronics", "tech"), ("physics", "space"), ("math", "calm"), ("economics", "warm"))
BEATS_PER_CHORD = 8
FADE_IN, FADE_OUT = 2.0, 3.0
SFX_GAP = 0.25            # s: effects closer than this are one (a scene's things popping in together)


def mood_of(channel_id):
    return next((mood for word, mood in CHANNEL_MOODS if word in str(channel_id)), "calm")


def hz(midi):
    return A4 * 2 ** ((midi - 69) / 12)


def envelope(n, attack, release):
    """0 -> 1 over `attack` samples, 1 -> 0 over the last `release`."""
    env = np.ones(n)
    a, r = min(attack, n), min(release, n)
    env[:a] = np.linspace(0, 1, a, endpoint=False)
    env[n - r:] *= np.linspace(1, 0, r)
    return env


def chord_starts(n, spec, bpm=None):
    """(k, start sample, chord) for each chord of a bed `n` samples long."""
    chord_len = int(BEATS_PER_CHORD * 60.0 / (bpm or spec["bpm"]) * RATE)
    return [(k, start, spec["chords"][k % len(spec["chords"])]) for k, start in enumerate(range(0, n, chord_len))], chord_len


def ambient(n, spec, rng):
    """Soft chords (a pad), a bass note every other beat, a light arpeggio."""
    beat = 60.0 / spec["bpm"]
    out = np.zeros((n, 2))
    span = BEATS_PER_CHORD * beat
    chord_len = int(span * RATE)
    overlap = int(1.5 * RATE)          # each chord rings into the next: no gap, no click
    for k, start in enumerate(range(0, n, chord_len)):
        chord = spec["chords"][k % len(spec["chords"])]
        length = min(chord_len + overlap, n - start)
        t = np.arange(length) / RATE
        env = envelope(length, int(1.2 * RATE), overlap)
        pad = np.zeros(length)
        for step in chord + (chord[0] + 12,):          # the triad and its root an octave up
            f = hz(spec["root"] + step)
            for detune in (0.9985, 1.0015):            # two voices slightly apart: a soft chorus
                pad += np.sin(2 * np.pi * f * detune * t) + 0.25 * np.sin(4 * np.pi * f * detune * t)
        pad *= 0.05 * env
        bass = np.zeros(length)
        for b in range(0, BEATS_PER_CHORD, 2):         # the root, two octaves down, every other beat
            at = int(b * beat * RATE)
            if at >= length:
                break
            tb = np.arange(length - at) / RATE
            bass[at:] += 0.12 * np.sin(2 * np.pi * hz(spec["root"] + chord[0] - 24) * tb) * np.exp(-tb / 0.6)
        notes = [spec["root"] + 12 + s for s in chord + (chord[0] + 12, chord[1] + 12)]
        pattern = notes + notes[-2:0:-1]               # up, then down
        arp = np.zeros((length, 2))
        for i in range(BEATS_PER_CHORD * 2):           # eighth notes
            at = int(i * beat / 2 * RATE)
            if at >= min(chord_len, length):
                break
            ta = np.arange(min(int(0.9 * RATE), length - at)) / RATE
            pluck = (0.045 + 0.01 * rng.random()) * np.sin(2 * np.pi * hz(pattern[i % len(pattern)]) * ta) * np.exp(-ta / 0.22)
            pan = 0.5 + 0.3 * (1 if i % 2 else -1)
            arp[at:at + len(ta), 0] += pluck * (1 - pan)
            arp[at:at + len(ta), 1] += pluck * pan
        out[start:start + length] += (pad + bass)[:, None] * 0.7 + arp
    return out


def keys_note(f, length, decay):
    """An electric piano's note: a sine and its overtones fading, a slow tremolo."""
    t = np.arange(length) / RATE
    tone = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) * np.exp(-t / 0.3) + 0.1 * np.sin(6 * np.pi * f * t) * np.exp(-t / 0.15)
    return tone * np.exp(-t / decay) * (1 + 0.15 * np.sin(2 * np.pi * 4.5 * t)) * envelope(length, int(0.005 * RATE), int(0.05 * RATE))


def lofi(n, spec, rng):
    """Electric piano chords (with their seventh), a soft kick, hats and a rim, a little vinyl hiss."""
    bpm = min(spec["bpm"], 82)
    beat = 60.0 / bpm
    out = np.zeros((n, 2))
    starts, chord_len = chord_starts(n, spec, bpm)
    for k, start, chord in starts:
        seventh = chord[0] + (10 if chord[1] - chord[0] == 3 else 11)
        for hit in (0, 3, 4.5):                         # the chord struck three times, a little off the beat
            at = start + int(hit * beat * RATE)
            length = min(int(3 * beat * RATE), n - at)
            if length <= 0:
                continue
            for i, step in enumerate(chord + (seventh,)):
                note = keys_note(hz(spec["root"] + step), length, 1.4) * (0.05 if hit == 0 else 0.035)
                out[at:at + length, i % 2] += note
                out[at:at + length, 1 - i % 2] += note * 0.6
        bass_len = min(chord_len, n - start)
        tb = np.arange(bass_len) / RATE
        out[start:start + bass_len] += (0.1 * np.sin(2 * np.pi * hz(spec["root"] + chord[0] - 24) * tb) * np.exp(-tb / 1.5))[:, None]
    tk = np.arange(int(0.25 * RATE)) / RATE
    kick = np.sin(2 * np.pi * np.cumsum(50 + 90 * np.exp(-tk / 0.03)) / RATE) * np.exp(-tk / 0.12)
    th = np.arange(int(0.05 * RATE)) / RATE
    b, a = butter(2, 7000 / (RATE / 2), btype="high")
    hat = lfilter(b, a, rng.standard_normal(len(th))) * np.exp(-th / 0.012)
    b, a = butter(2, [900 / (RATE / 2), 3000 / (RATE / 2)], btype="band")
    tr = np.arange(int(0.12 * RATE)) / RATE
    rim = lfilter(b, a, rng.standard_normal(len(tr))) * np.exp(-tr / 0.03)
    for i in range(int(n / (beat * RATE / 2))):        # eighth notes
        at = int(i * beat / 2 * RATE)
        for sound, gain, when in ((kick, 0.22, i % 8 in (0, 5)), (rim, 0.06, i % 4 == 2), (hat, 0.03 + 0.01 * (i % 2), True)):
            if when and at < n:
                end = min(n, at + len(sound))
                out[at:end] += (sound[:end - at] * gain)[:, None]
    b, a = butter(1, 4000 / (RATE / 2))
    out += lfilter(b, a, rng.standard_normal((n, 2)) * 0.004, axis=0)   # vinyl hiss
    return out


def cinematic(n, spec, rng):
    """A slow string pad (many overtones, swelling), low piano notes, a quiet pulse in eighth notes."""
    beat = 60.0 / spec["bpm"]
    out = np.zeros((n, 2))
    starts, chord_len = chord_starts(n, spec)
    overlap = int(2.5 * RATE)
    for k, start, chord in starts:
        length = min(chord_len + overlap, n - start)
        t = np.arange(length) / RATE
        pad = np.zeros((length, 2))
        for i, step in enumerate((chord[0] - 12,) + chord + (chord[2] + 12,)):
            f = hz(spec["root"] + step)
            for side, detune in ((0, 0.997), (1, 1.003)):
                tone = sum(np.sin(2 * np.pi * f * detune * h * t + h) / h ** 1.6 for h in range(1, 7))
                pad[:, side] += tone * (1 + 0.08 * np.sin(2 * np.pi * 0.2 * t + i))
        pad *= 0.022 * envelope(length, int(2.5 * RATE), overlap)[:, None]
        piano = np.zeros(length)
        for hit, step in ((0, chord[0]), (4, chord[2])):
            at = int(hit * beat * RATE)
            if at < length:
                piano[at:] += keys_note(hz(spec["root"] + step - 12), length - at, 2.5) * 0.09
        pulse = np.zeros(length)
        tp = np.arange(int(0.2 * RATE)) / RATE
        tick = np.sin(2 * np.pi * hz(spec["root"] + chord[0] - 24) * tp) * np.exp(-tp / 0.07)
        for i in range(BEATS_PER_CHORD * 2):
            at = int(i * beat / 2 * RATE)
            if at + len(tp) <= min(chord_len, length):
                pulse[at:at + len(tp)] += tick * (0.08 if i % 2 == 0 else 0.05)
        out[start:start + length] += pad + (piano + pulse)[:, None]
    return out


STYLES = {"ambient": ambient, "lofi": lofi, "cinematic": cinematic}


def music_bed(seconds, mood, seed=0, style="ambient"):
    """A stereo music bed (float, -1..1, shape (n, 2)) of `seconds`, in MOODS[mood] (key, chords,
    tempo) and STYLES[style] (the instruments), filtered soft, faded in and out."""
    n = int(seconds * RATE)
    out = STYLES[style](n, MOODS[mood], np.random.default_rng(seed))
    b, a = butter(2, 3500 / (RATE / 2))                # nothing sharp: it stays under the voice
    out = lfilter(b, a, out, axis=0)
    out *= envelope(n, int(FADE_IN * RATE), int(FADE_OUT * RATE))[:, None]
    peak = np.abs(out).max()
    return out / peak * 0.5 if peak > 0 else out


def pop():
    t = np.arange(int(0.09 * RATE)) / RATE
    f = 520 + 480 * np.exp(-t / 0.02)                  # a quick fall in pitch
    return np.sin(2 * np.pi * np.cumsum(f) / RATE) * envelope(len(t), int(0.003 * RATE), len(t) - int(0.003 * RATE)) ** 2


def tick():
    t = np.arange(int(0.05 * RATE)) / RATE
    return 0.6 * np.sin(2 * np.pi * 1900 * t) * np.exp(-t / 0.008)


def whoosh(seed=0):
    n = int(0.55 * RATE)
    noise = np.random.default_rng(seed).standard_normal(n)
    b, a = butter(2, [300 / (RATE / 2), 3000 / (RATE / 2)], btype="band")
    shaped = lfilter(b, a, noise) * np.sin(np.linspace(0, np.pi, n)) ** 2   # swells, then fades
    return shaped / np.abs(shaped).max() * 0.7


SOUNDS = {"pop": pop, "tick": tick, "whoosh": whoosh}


def effects(seconds, events):
    """The sound effects track (stereo, -1..1) for [(time s, "pop" | "tick" | "whoosh")], one effect
    for effects closer than SFX_GAP (a whoosh first)."""
    out = np.zeros((int(seconds * RATE), 2))
    kept, last = [], -1.0
    for at, kind in sorted(events, key=lambda e: (e[0], e[1] != "whoosh")):
        if at - last >= SFX_GAP and 0 <= at < seconds:
            kept.append((at, kind))
            last = at
    for at, kind in kept:
        sound = SOUNDS[kind]()
        start = int(at * RATE)
        end = min(len(out), start + len(sound))
        out[start:end] += sound[:end - start, None] * 0.5
    return out, len(kept)


def write_wav(path, samples):
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(data.tobytes())


def soundtrack(seconds, events, channel_id, music_path, effects_path, music=True, sound_effects=True, style="ambient"):
    """Write the music bed and the effects of a `seconds`-long video; returns what was made
    ({"music": mood or None, "style", "effects": how many}) and the WAV paths to mix ([] if neither).
    `style`: one of STYLES (an unknown one: "ambient")."""
    style = style if style in STYLES else "ambient"
    made, paths = {"music": None, "style": style if music else None, "effects": 0}, []
    if music:
        made["music"] = mood_of(channel_id)
        write_wav(music_path, music_bed(seconds, made["music"], zlib.crc32(str(channel_id).encode()), style))
        paths.append(("music", music_path))
    if sound_effects and events:
        track, made["effects"] = effects(seconds, events)
        write_wav(effects_path, track)
        paths.append(("effects", effects_path))
    return made, paths
