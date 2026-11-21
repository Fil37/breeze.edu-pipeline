"""
INPUT:  instance/{channel_id}/storyboard.json (each scene with a visual_brief from agent004)
        + script.json + qa.json (verdict must be "pass") + settings (dry_run, render_backend_by_channel)
OUTPUT: instance/{channel_id}/video.mp4 + render_manifest.json = {video_path, duration,
        resolution, renderer_used, rendered_at, status, scenes:[{scene_id, start_sec, end_sec,
        duration_sec, voice_sec, voice_engine, voice_fallback, compression_ratio, status, error}],
        voice_engine ("elevenlabs", "edge-tts" or "mixed"; None in a dry run)}
NOTES:  The ONLY agent that calls a render backend. For each scene, in a temporary folder:
          1. scene_001.mp3         French voice-over (app/tts_manager.py: ElevenLabs, else edge-tts),
                                   duration measured with ffprobe
          2. scene_001_visual.mp4  the engine (app/render/breeze_engine.py) plays the brief in a Manim
                                   subprocess; its timeline is stretched to the voice + TAIL_PAUSE
          3. scene_001.mp4         FFmpeg joins picture and voice (silence fills the pause)
        then FFmpeg concatenates the scenes into video.mp4, normalizes its audio to -14 LUFS
        (LOUDNESS_TARGET, two-pass loudnorm, picture copied), and the temporary folder is deleted.
        The LLM never writes Manim code: the engine maps each component type and action to fixed code.
        The text overlay still on screen at the end of a scene is passed to the next one, which keeps
        it unless its overlay says clear_previous=true.
        compression_ratio (from the engine): 1.0 when the animations fit the voice; below 1 they were
        sped up to end with it; below RUSHED_RATIO the scene is flagged as rushed.
        A scene that fails to render becomes a black screen showing the error; the details go to
        stderr and to the manifest. With settings.dry_run=true it writes a placeholder file.
HEALTH: not_healthy if dry_run, backend "skip", the engine skipped something (unknown port or
        state, action on an unknown entity...), a scene is rushed, or a scene failed to render; critical if an input is
        missing, a scene has no valid visual_brief, QA did not pass, ffmpeg is missing, or the
        voice-over or the final assembly fails.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)  # standalone runs

from pydantic import ValidationError

from app.agent import channel_dir, finish, load_json, run_standalone, save_json, utc_now
from app import provenance
from app.tts_manager import generate_voice, media_duration, voice_report   # the voice: ElevenLabs, else edge-tts
from models.visual_brief_schema import SceneVisualBrief

AGENT = "agent006"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
TAIL_PAUSE = 0.4          # seconds of picture after the voice ends: a breath between scenes
PLACEHOLDER = b"BREEZE DRY RUN PLACEHOLDER - not a real video\n"
ERROR_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MANIM_TIMEOUT_SEC = 600
FFMPEG_TIMEOUT_SEC = 600
WARNING_PREFIX = "BREEZE_WARNING: "
RATIO_PREFIX = "BREEZE_INFO: compression_ratio="
RUSHED_RATIO = 0.5        # animations sped up more than 2x: too fast to follow

# Same encoding for every scene, so the final concatenation can copy the streams without re-encoding.
# The BT.709 / limited-range tags stop players such as VLC from guessing the color range.
VIDEO_CODEC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
# Loudness of the final video (EBU R128): YouTube plays everything at about -14 LUFS, so a video
# mixed quieter (the voices come out near -23 LUFS) sounds weak next to the others.
LOUDNESS_TARGET = {"I": -14.0, "TP": -1.5, "LRA": 11.0}   # integrated LUFS, true peak dBTP, range LU

# The whole Manim script for one scene: no LLM text in it, only two paths we control.
SCENE_SCRIPT = '''import sys
sys.path.insert(0, {base_dir!r})
from app.render.breeze_engine import BreezeSceneEngine


class BreezeScene(BreezeSceneEngine):
    brief_file = {brief_file!r}
'''


def scene_field(scene, *names):
    """First present value among several field names (agent003's names first)."""
    return next((scene[name] for name in names if scene.get(name) is not None), None)


def ffmpeg(args, what):
    """Run ffmpeg quietly; raise with the end of its error output if it fails."""
    result = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                            capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SEC)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({what}): {result.stderr.strip()[-400:]}")


def make_visual(name, brief, duration, planned_duration, carried_overlay, temp_dir, warnings, transition=None):
    """Render one brief with the engine, `duration` seconds long. Returns (silent mp4 path,
    compression ratio the engine applied). Raises with Manim's last error line (the full stderr is
    printed for debugging)."""
    brief_file = os.path.join(temp_dir, name + ".json")
    save_json(brief_file, {"brief": brief, "duration": round(duration, 3), "planned_duration": planned_duration,
                           "carried_overlay": carried_overlay, **(transition or {})})
    py_path = os.path.join(temp_dir, name + ".py")
    with open(py_path, "w", encoding="utf-8") as f:
        f.write(SCENE_SCRIPT.format(base_dir=BASE_DIR, brief_file=brief_file))
    media_dir = os.path.join(temp_dir, "media")
    output_name = name + "_visual"
    result = subprocess.run([sys.executable, "-m", "manim", "render", py_path, "BreezeScene",
                             "--resolution", f"{WIDTH},{HEIGHT}", "--fps", str(FPS), "--media_dir", media_dir,
                             "-o", output_name, "--format", "mp4", "--disable_caching", "--progress_bar", "none"],
                            capture_output=True, text=True, timeout=MANIM_TIMEOUT_SEC)
    warnings += [f"{name}: {line[len(WARNING_PREFIX):]}" for line in result.stdout.splitlines()
                 if line.startswith(WARNING_PREFIX)]
    ratio = next((float(line[len(RATIO_PREFIX):].split()[0]) for line in result.stdout.splitlines()
                  if line.startswith(RATIO_PREFIX)), None)
    if result.returncode != 0:
        print(f"--- {AGENT}: manim failed on {name}; stderr follows ---\n{result.stderr}", file=sys.stderr)
        last_line = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise RuntimeError(f"manim failed: {last_line}")
    for root, _, files in os.walk(media_dir):
        if output_name + ".mp4" in files:
            visual_path = os.path.join(temp_dir, output_name + ".mp4")
            shutil.move(os.path.join(root, output_name + ".mp4"), visual_path)
            return visual_path, ratio
    raise RuntimeError("manim produced no file")


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
        print(f"--- {AGENT}: audio normalized from {loudness} to {LOUDNESS_TARGET['I']} LUFS", file=sys.stderr, flush=True)
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


def transition_to(next_scene):
    """How a scene ends: pan away if another scene follows (a cut otherwise), holding the title in
    place when the next scene keeps it (no overlay of its own, or clear_previous=false)."""
    if next_scene is None:
        return {"pan_out": False, "overlay_stays": False}
    overlay = next_scene["visual_brief"].get("text_overlay")
    return {"pan_out": True, "overlay_stays": overlay is None or not overlay.get("clear_previous", True)}


def overlay_after(brief, carried):
    """The overlay on screen at the end of a scene: its own (unless it timed out), else the kept one."""
    overlay = brief.get("text_overlay")
    if overlay is None:
        return carried
    if overlay.get("duration"):
        return None
    if overlay.get("title") or overlay.get("subtitle"):
        return {"title": overlay.get("title"), "subtitle": overlay.get("subtitle")}
    return None if overlay.get("clear_previous", True) else carried


def render_video(storyboard, script, video_path, folder, warnings):
    """Voice, picture and assembly for every scene. Returns the manifest's scene list."""
    temp_dir = os.path.join(folder, "temp_render")
    shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir)
    script_scenes = {s.get("scene_id"): s for s in script["scenes"]}
    carried = None   # text overlay still on screen from the previous scene
    clips, scenes, start = [], [], 0.0
    try:
        scenes_in_order = storyboard["scenes"]
        for number, scene in enumerate(scenes_in_order, start=1):
            name = f"scene_{number:03d}"
            source = script_scenes.get(scene["scene_id"], {})
            narration = str(scene_field(source, "narration_text", "narration") or "").strip()
            if not narration:
                raise RuntimeError(f"{name} (scene_id {scene['scene_id']}): no narration in script.json")
            # 1. Voice first: its real length sets the length of the scene.
            audio_path = os.path.join(temp_dir, name + ".mp3")
            engine = {}
            voice = generate_voice(narration, audio_path, engine=engine)
            total = voice + TAIL_PAUSE
            # 2. Picture: the engine stretches the brief's timeline (planned on the script's duration)
            #    to the voice, and keeps the picture moving through the tail pause.
            entry = {"scene_id": scene["scene_id"], "voice_sec": round(voice, 2), "voice_engine": engine["used"],
                     "voice_fallback": engine["fallback"], "compression_ratio": None, "status": "ok", "error": None}
            visual_path = os.path.join(temp_dir, name + "_visual.mp4")
            try:
                next_scene = scenes_in_order[number] if number < len(scenes_in_order) else None
                visual_path, ratio = make_visual(name, scene["visual_brief"], total,
                                                 scene_field(source, "duration_sec", "duration_seconds"),
                                                 carried, temp_dir, warnings, transition_to(next_scene))
                entry["compression_ratio"] = ratio
                if ratio is not None and ratio < RUSHED_RATIO:
                    warnings.append(f"{name}: rushed, animations sped up x{1 / ratio:.1f} to fit the voice "
                                    "(lengthen the narration or use fewer actions)")
            except Exception as exc:  # Manim failed or timed out: show the error on a black screen
                print(f"--- {AGENT}: {name} rendered as an error screen: {exc}", file=sys.stderr)
                warnings.append(f"{name}: {exc}")
                entry.update(status="error_screen", error=str(exc))
                make_error_visual(f"{name}\n{exc}", total, visual_path)
            carried = overlay_after(scene["visual_brief"], carried)
            # 3. Picture + voice -> scene clip.
            clip_path = os.path.join(temp_dir, name + ".mp4")
            mux_scene(visual_path, audio_path, total, clip_path)
            duration = media_duration(clip_path)
            entry.update(start_sec=round(start, 2), end_sec=round(start + duration, 2), duration_sec=round(duration, 2))
            start += duration
            clips.append(clip_path)
            scenes.append(entry)
        concat_scenes(clips, os.path.join(temp_dir, "scenes.txt"), video_path)
        return scenes
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    video_path = os.path.join(folder, "video.mp4")
    manifest_path = os.path.join(folder, "render_manifest.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["storyboard.json", "script.json", "qa.json"])
    storyboard = load_json(os.path.join(folder, "storyboard.json"))
    script = load_json(os.path.join(folder, "script.json"))
    qa = load_json(os.path.join(folder, "qa.json"))
    if not (storyboard.get("scenes") and script.get("scenes") and qa):
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error="missing storyboard, script or qa")
    if qa.get("verdict") != "pass":
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error="QA verdict is not pass")
    brief_error = check_briefs(storyboard)
    if brief_error:
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error=brief_error)

    renderer = settings.get("render_backend_by_channel", {}).get(channel_id)
    warnings, scenes, duration = [], [], None
    try:
        if settings.get("dry_run", True):
            with open(video_path, "wb") as f:
                f.write(PLACEHOLDER)
            renderer_used = "dry_run"
            warnings.append("dry_run: placeholder video written")
        elif renderer == "skip":
            renderer_used = "skip"
            warnings.append("renderer is 'skip': no video produced")
        elif renderer == "manim":
            missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
            if missing:
                raise RuntimeError(f"{' and '.join(missing)} not found on PATH")
            scenes = render_video(storyboard, script, video_path, folder, warnings)
            duration = round(media_duration(video_path), 2)
            renderer_used = "breeze_engine"
        else:
            raise RuntimeError(f"unknown renderer {renderer!r}")
    except Exception as exc:  # edge_tts offline or timed out, ffmpeg error...
        print(f"--- {AGENT}: render failed for {channel_id}: {exc!r}", file=sys.stderr)
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error=f"render failed: {exc!r}")

    voice_engine = voice_report(scenes, warnings)
    status = "not_healthy" if warnings else "healthy"
    manifest = {"video_path": video_path if renderer_used != "skip" else None,
                "duration": duration if duration is not None else script.get("total_duration_sec"),
                "resolution": f"{WIDTH}x{HEIGHT}", "renderer_used": renderer_used,
                "rendered_at": utc_now(), "status": status, "voice_engine": voice_engine, "scenes": scenes}
    if os.path.exists(video_path) and renderer_used != "skip":   # written by ffmpeg (or the dry-run placeholder)
        provenance.register_artifact(run_id, channel_id, "video.mp4", AGENT)
    save_json(manifest_path, manifest)
    provenance.register_artifact(run_id, channel_id, "render_manifest.json", AGENT)
    return finish(channel_id, AGENT, "render", status, manifest_path, data={**manifest, "warnings": warnings})


if __name__ == "__main__":
    run_standalone(run)
