"""
Check the loudness normalization of the final video (concat_scenes in app/render/video.py, used by
agent010): two-pass loudnorm to LOUDNESS_TARGET (-16 LUFS), once on the assembled video.
Offline: the scene clips are made here with ffmpeg (a test picture + a quiet tone) and joined by the
renderers' own mux_scene and concat_scenes, in a temporary folder.
  1. a quiet video (two scenes 6 dB apart, far below the target): the result is at the target
     (within 1 LU), true peak <= -1 dBFS, same duration, the picture copied bit for bit, and both
     scenes got the same gain (their level difference is kept)
  2. a silent video: nothing to normalize (None), the file is still written
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_loudnorm.py
"""

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.render import video as agent006   # noqa: E402


def run(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, check=True)


def clip(folder, name, volume_db, silent=False, seconds=3.0):
    """A scene clip as the renderers make it: picture + voice (here a tone) through mux_scene."""
    visual, audio, out = (os.path.join(folder, f"{name}{ext}") for ext in ("_visual.mp4", ".wav", ".mp4"))
    run(["-f", "lavfi", "-i", f"testsrc=size=640x360:rate={agent006.FPS}:duration={seconds}", "-pix_fmt", "yuv420p", visual])
    source = "anullsrc=r=48000:cl=mono" if silent else "sine=frequency=440:sample_rate=48000"
    run(["-f", "lavfi", "-i", source, "-t", str(seconds), "-af", f"volume={volume_db}dB", audio])
    agent006.mux_scene(visual, audio, seconds, out)
    return out


def loudness(path, start=None, length=None):
    """(integrated LUFS, true peak dBFS) of the file's audio, or of the part [start, start + length]."""
    cut = ["-ss", str(start), "-t", str(length)] if start is not None else []
    text = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *cut, "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    summary = text[text.rfind("Summary:"):]
    return float(re.search(r"I:\s+(-?[\d.]+|-inf)", summary).group(1)), float(re.search(r"Peak:\s+(-?[\d.]+|-inf)", summary).group(1))


def video_md5(path):
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-map", "0:v", "-c", "copy", "-f", "md5", "-"],
                          capture_output=True, text=True).stdout.strip()


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout)


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_quiet(folder):
    clips = [clip(folder, "scene_001", -36), clip(folder, "scene_002", -30)]   # the second 6 dB louder
    joined = os.path.join(folder, "joined_reference.mp4")
    run(["-f", "concat", "-safe", "0", "-i", _list(folder, clips), "-c", "copy", joined])
    video = os.path.join(folder, "video.mp4")
    before = agent006.concat_scenes(clips, os.path.join(folder, "scenes.txt"), video)
    level, peak = loudness(video)
    problems, target = [], agent006.LOUDNESS_TARGET["I"]
    if before is None or abs(level - target) > 1.0:
        problems.append(f"{level} LUFS, expected {target} (before: {before})")
    if peak > -1.0:
        problems.append(f"true peak {peak} dBFS")
    if video_md5(video) != video_md5(joined):
        problems.append("the picture was re-encoded")
    if abs(duration(video) - duration(joined)) > 0.1:
        problems.append(f"duration {duration(video):.3f} s, before {duration(joined):.3f} s")
    first, second = loudness(video, 0.5, 2.0)[0], loudness(video, 3.5, 2.0)[0]
    if abs((second - first) - 6.0) > 1.0:
        problems.append(f"scene levels {first} / {second} LUFS: the 6 dB difference was not kept (not one gain)")
    return report("1. quiet video -> the target LUFS, picture copied, one gain for all scenes", problems,
                  [f"{before} -> {level} LUFS, true peak {peak} dBFS, scenes {first} / {second} LUFS",
                   f"duration {duration(joined):.3f} -> {duration(video):.3f} s"])


def case_silent(folder):
    clips = [clip(folder, "silent_001", 0, silent=True)]
    video = os.path.join(folder, "silent.mp4")
    before = agent006.concat_scenes(clips, os.path.join(folder, "silent.txt"), video)
    problems = [] if before is None and os.path.exists(video) and duration(video) > 2.5 else \
        [f"returned {before!r}, file {'written' if os.path.exists(video) else 'missing'}"]
    return report("2. silent video: left as it is, still written", problems)


def _list(folder, clips):
    path = os.path.join(folder, "reference.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(f"file '{c}'\n" for c in clips)
    return path


with tempfile.TemporaryDirectory() as tmp:
    stderr, sys.stderr = sys.stderr, open(os.devnull, "w")      # the "audio normalized" log line
    try:
        results = [case_quiet(tmp), case_silent(tmp)]
    finally:
        sys.stderr.close()
        sys.stderr = stderr
sys.exit(0 if all(results) else 1)
