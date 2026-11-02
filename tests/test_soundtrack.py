"""
Check the music and sound effects under the voice (app/render/soundtrack.py, mix in app/render/video.py),
offline:
  1. the music bed: as long as the video, the same for the same channel, faded in and out, a mood
     per channel, three styles that differ; never louder than half scale
  2. the effects: one per action (pop, tick) and a whoosh between scenes, those closer than SFX_GAP
     merged; none outside the video
  3. the mix: on a voice that speaks one second out of two, the music sits about MUSIC_UNDER_VOICE
     below it, lower while it speaks (ducked), and the video still ends at -16 LUFS
Prints PASS or FAIL per case. Needs ffmpeg.

  .venv/bin/python tests/test_soundtrack.py
"""

import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.render import soundtrack, video                               # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_music():
    problems = []
    bed = soundtrack.music_bed(20, "tech", seed=7)
    if bed.shape != (20 * soundtrack.RATE, 2) or not np.allclose(bed, soundtrack.music_bed(20, "tech", seed=7)):
        problems.append(f"shape {bed.shape} or not the same twice")
    rms = lambda x: np.sqrt((x ** 2).mean())
    if abs(bed).max() > 0.5001 or rms(bed[:2000]) > rms(bed[soundtrack.RATE * 8:soundtrack.RATE * 10]) / 10 or abs(bed[-50:]).max() > 1e-3:
        problems.append("not faded in and out, or too loud")
    beds = {style: soundtrack.music_bed(12, "warm", 3, style) for style in soundtrack.STYLES}
    for style, other in beds.items():
        if abs(other).max() > 0.5001 or abs(other[-50:]).max() > 1e-3 or rms(other[soundtrack.RATE * 5:soundtrack.RATE * 7]) < 0.01:
            problems.append(f"the {style} style: silent, too loud or not faded out")
    if np.allclose(beds["lofi"], beds["cinematic"]) or np.allclose(beds["ambient"], beds["lofi"]):
        problems.append("two styles sound the same")
    made, _ = soundtrack.soundtrack(1, [], "x", os.devnull, os.devnull, style="unknown")
    if made["style"] != "ambient":
        problems.append(f"an unknown style kept: {made}")
    moods = [soundtrack.mood_of(f"breeze_({c})") for c in ("electronics", "physics", "math", "economics")]
    if moods != ["tech", "space", "calm", "warm"] or soundtrack.mood_of("other") != "calm":
        problems.append(f"moods {moods}")
    return report("1. a music bed per channel and style (ambient, lofi, cinematic), the same each time, faded", problems)


def case_effects():
    problems = []
    events = [(1.0, "pop"), (1.1, "pop"), (2.0, "tick"), (4.7, "whoosh"), (4.75, "pop"), (12, "pop"), (-1, "pop")]
    track, count = soundtrack.effects(10, events)
    if count != 3:
        problems.append(f"{count} effects kept, expected 3 (1.0 pop, 2.0 tick, 4.7 whoosh)")
    loud = lambda a, b: abs(track[int(a * soundtrack.RATE):int(b * soundtrack.RATE)]).max()
    if loud(1.0, 1.1) < 0.1 or loud(2.0, 2.05) < 0.1 or loud(4.7, 5.2) < 0.1 or loud(6, 10) > 0:
        problems.append("effects not where they should be")
    return report("2. one effect per action, a whoosh between scenes, close ones merged", problems)


def case_mix():
    problems = []
    with tempfile.TemporaryDirectory() as folder:
        rate, seconds = 48000, 12
        t = np.arange(rate * seconds) / rate
        voice = 0.2 * np.sin(2 * np.pi * 220 * t) * (np.floor(t) % 2 == 0)        # speaks one second out of two
        wav = os.path.join(folder, "voice.wav")
        soundtrack.write_wav(wav, np.stack([voice, voice], axis=1))
        joined = os.path.join(folder, "joined.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=320x180:d={seconds}", "-i", wav,
                        "-shortest", "-c:v", "libx264", "-c:a", "aac", joined], check=True)
        made, beds = soundtrack.soundtrack(seconds, [(3.5, "pop")], "breeze_(math)", os.path.join(folder, "m.wav"),
                                           os.path.join(folder, "e.wav"), sound_effects=False)
        mixed, final = os.path.join(folder, "mixed.mp4"), os.path.join(folder, "final.mp4")
        if made != {"music": "calm", "style": "ambient", "effects": 0} or [k for k, _ in beds] != ["music"]:
            problems.append(f"made {made}, beds {beds}")
        video.mix_beds(joined, beds, mixed)
        video.normalize_loudness(mixed, final)
        loudness = float(video.measure_loudness(final)["input_i"])
        load = lambda p: np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                                                      capture_output=True).stdout, dtype=np.float32)
        before, after = load(joined), load(mixed)
        n = min(len(before), len(after))
        music = after[:n] - before[:n]
        db = lambda a, b: 20 * np.log10(np.sqrt((music[int(a * rate):int(b * rate)] ** 2).mean()) + 1e-9)
        speaking = np.mean([db(k + 0.3, k + 0.9) for k in (4, 6, 8)])
        quiet = np.mean([db(k + 0.5, k + 0.95) for k in (5, 7, 9)])
        voice_db = 20 * np.log10(np.sqrt((before[4 * rate:5 * rate] ** 2).mean()))
    if abs(loudness - video.LOUDNESS_TARGET["I"]) > 0.6:
        problems.append(f"the final loudness {loudness} LUFS")
    if not quiet - speaking >= 2:
        problems.append(f"the music not ducked under the voice: {speaking:.1f} dB speaking, {quiet:.1f} dB quiet")
    if not 14 <= voice_db - quiet <= 28:
        problems.append(f"the music {voice_db - quiet:.1f} dB under the voice")
    return report("3. the music under the voice, ducked while it speaks; -16 LUFS kept", problems,
                  [f"voice {voice_db:.1f} dB, music {speaking:.1f} dB under speech, {quiet:.1f} dB in the pauses; {loudness} LUFS"])


if __name__ == "__main__":
    results = [case_music(), case_effects(), case_mix()]
    sys.exit(0 if all(results) else 1)
