"""
What every video goes through after its pictures are drawn (agent010, the HTML renderer): the frame
size and rate, one encoding for every scene, the error screen of a scene that failed, picture + voice
joined per scene, the scenes concatenated, and the audio brought to YouTube's loudness (-14 LUFS).
Also the storyboard check the renderer starts with. ffmpeg and ffprobe come from the system.

(Moved here from agent006, the Manim renderer, when it was retired: see archive/manim/README.md.)
"""

import json
import os
import re
import subprocess
import sys
import textwrap

from pydantic import ValidationError

from models.visual_brief_schema import SceneVisualBrief

WIDTH, HEIGHT, FPS = 1920, 1080, 30
TAIL_PAUSE = 0.4          # seconds of picture after the voice ends: a breath between scenes
END_HOLD = 2.0            # the last scene: seconds more of picture after its voice, the end ...
END_FADE = 1.2            # ... of which the last ones fade to the background (no cut)
PLACEHOLDER = b"BREEZE DRY RUN PLACEHOLDER - not a real video\n"
ERROR_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FFMPEG_TIMEOUT_SEC = 600

# Same encoding for every scene, so the final concatenation can copy the streams without re-encoding.
# The BT.709 / limited-range tags stop players such as VLC from guessing the color range.
VIDEO_CODEC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
# Loudness of the final video (EBU R128): YouTube plays everything at about -14 LUFS, so a video
# mixed quieter (the voices come out near -23 LUFS) sounds weak next to the others.
LOUDNESS_TARGET = {"I": -16.0, "TP": -1.5, "LRA": 11.0}   # integrated LUFS, true peak dBTP, range LU


def scene_field(scene, *names):
    """First present value among several field names (agent003's names first)."""
    return next((scene[name] for name in names if scene.get(name) is not None), None)


def ffmpeg(args, what):
    """Run ffmpeg quietly; raise with the end of its error output if it fails."""
    result = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                            capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SEC)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({what}): {result.stderr.strip()[-400:]}")


def make_error_visual(message, duration, path):
    """Black screen with the error in white, so a failed scene is obvious when watching."""
    text_file = path + ".txt"
    with open(text_file, "w", encoding="utf-8") as f:
        f.write("\n".join(textwrap.fill(line, 70) for line in message.splitlines())[:600])
    drawtext = (f"drawtext=fontfile='{ERROR_FONT}':textfile='{text_file}':fontcolor=white:fontsize=40:"
                "line_spacing=12:x=(w-text_w)/2:y=(h-text_h)/2")
    ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.3f}",
            "-vf", drawtext, *VIDEO_CODEC, path], "error screen")


def mux_scene(visual_path, audio_path, total, path):
    """Picture + voice -> one scene clip of exactly `total` seconds: the picture is held on its last
    frame if it is short, the voice is followed by silence for the tail pause."""
    ffmpeg(["-i", visual_path, "-i", audio_path,
            "-filter_complex", "[0:v]tpad=stop_mode=clone:stop_duration=5[v];[1:a]apad[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", *VIDEO_CODEC, *AUDIO_CODEC, path], "join scene")


def measure_loudness(path):
    """loudnorm's first pass on the file's audio: {"input_i", "input_tp", "input_lra", "input_thresh",
    "target_offset"} (strings, as ffmpeg prints them)."""
    target = ":".join(f"{key}={value}" for key, value in LOUDNESS_TARGET.items())
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
                             "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SEC)
    found = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr)
    if result.returncode != 0 or not found:
        raise RuntimeError(f"ffmpeg failed (measure loudness): {result.stderr.strip()[-400:]}")
    return json.loads(found[-1])


def normalize_loudness(source, video_path):
    """The whole video's audio to LOUDNESS_TARGET, in two passes (measure, then a linear correction:
    the voice keeps its dynamics), once on the assembled video so every scene gets the same gain.
    The picture is copied, not re-encoded. Returns the loudness measured before (LUFS), or None when
    there is nothing to normalize (silence): the file is then only copied."""
    measured = measure_loudness(source)
    try:
        loudness = float(measured["input_i"])
    except (KeyError, ValueError):
        loudness = float("-inf")
    if loudness == float("-inf"):            # silent: loudnorm has nothing to work on
        ffmpeg(["-i", source, "-c", "copy", "-movflags", "+faststart", video_path], "copy silent video")
        return None
    target = ":".join(f"{key}={value}" for key, value in LOUDNESS_TARGET.items())
    second = (f"loudnorm={target}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
              f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
              f":offset={measured['target_offset']}:linear=true")
    ffmpeg(["-i", source, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", second, *AUDIO_CODEC,
            "-movflags", "+faststart", video_path], "normalize loudness")
    return round(loudness, 1)


def concat_scenes(clip_paths, list_path, video_path):
    """The scene clips, end to end (streams copied), then the audio normalized to LOUDNESS_TARGET.
    Returns the loudness before normalization (LUFS), or None for a silent video."""
    with open(list_path, "w", encoding="utf-8") as f:
        for clip in clip_paths:
            f.write("file '" + clip.replace("'", "'\\''") + "'\n")
    joined = os.path.join(os.path.dirname(list_path), "joined.mp4")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", joined], "concatenate scenes")
    loudness = normalize_loudness(joined, video_path)
    os.remove(joined)
    if loudness is not None:
        print(f"--- render: audio normalized from {loudness} to {LOUDNESS_TARGET['I']} LUFS", file=sys.stderr, flush=True)
    return loudness


def check_briefs(storyboard):
    """Every scene needs a visual_brief that passes the schema. Returns an error message or None."""
    for scene in storyboard["scenes"]:
        if "visual_brief" not in scene:
            return f"scene {scene.get('scene_id')} has no visual_brief (older storyboard): rerun agent004"
        try:
            SceneVisualBrief.model_validate(scene["visual_brief"])
        except ValidationError as exc:
            return f"scene {scene.get('scene_id')}: invalid visual_brief: {str(exc)[:300]}"
    return None
