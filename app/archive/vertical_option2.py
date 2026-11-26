"""
The vertical (TikTok) version of a rendered video: 1080 x 1920, built from the 1920 x 1080 video agent010 has
just made, without rendering again and without losing quality (2026-11-26, the user's choice "option 2").

  top          the video's question (script.json "question"), large, in the channel's font (Inter)
  middle       the whole picture, scaled DOWN only (lanczos), never up: nothing is blurred or cut from the drawing
  under it     the subtitles, large (~54 px instead of the 21 px the 38 px subtitles would shrink to)
  then         the channel's logo
  background   the video itself, heavily blurred and darkened: a coloured glow, no readable ghost of a title

Why the bottom band is cut: with subtitles burnt in, the page keeps the bottom 96 px free for them
(SUBS_SPACE in agent010: the diagram, the vector legend and every panel stay above it); only the subtitle
line and the watermark live there. A subtitle line is one line at most (LINE_MAX_CHARS 62), so cutting that
band removes the small subtitles entirely and the large ones below never repeat them on screen.
The layout keeps clear of TikTok's own interface: the tabs at the top, the buttons on the right, the
description at the bottom. Encoding: H.264 CRF 18, BT.709, the audio copied as it is (no new loss).
"""
import os
import re
import shutil
import subprocess
import tempfile

from app.render.video import FFMPEG_TIMEOUT_SEC, FPS

WIDTH, HEIGHT = 1080, 1920
SOURCE_WIDTH, SOURCE_HEIGHT = 1920, 1080
SUBTITLE_BAND = 96                 # px of the 1080p frame kept for the burnt subtitles (agent010 SUBS_SPACE)
PICTURE_TOP = 520                  # y of the picture in the vertical frame
TITLE_TOP = 230                    # below TikTok's tabs
CAPTION_TOP = 1125                 # under the picture
LOGO_TOP, LOGO_SIZE = 1360, 84
TITLE_SIZE, CAPTION_SIZE = 64, 54
SIDE_MARGIN = 90                   # clear of TikTok's buttons on the right (and symmetric)
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css")
VIDEO_CODEC = ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-movflags", "+faststart"]


def srt_cues(text):
    """[(start_seconds, end_seconds, text)] of an .srt file's content."""
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        times = next((l for l in lines if "-->" in l), None)
        if not times:
            continue
        start, end = (seconds(t) for t in times.split("-->"))
        words = " ".join(l.strip() for l in lines[lines.index(times) + 1:] if l.strip())
        if words:
            cues.append((start, end, words))
    return cues


def seconds(stamp):
    h, m, rest = stamp.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def ass_time(value):
    value = max(0.0, value)
    hours, rest = divmod(value, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def ass_text(text):
    """Plain text for an ASS line: no override blocks from the narration, no hard line breaks."""
    return str(text).replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def build_ass(question, cues, duration):
    """The ASS script of the vertical frame: the question for the whole video, the subtitles on their times."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Question,Inter,{TITLE_SIZE},&H00F8FAFC,&H00F8FAFC,&H802A170F,&H802A170F,-1,0,0,0,100,100,0,0,1,3,2,8,{SIDE_MARGIN},{SIDE_MARGIN},{TITLE_TOP},1
Style: Caption,Inter,{CAPTION_SIZE},&H00F8FAFC,&H00F8FAFC,&H2E2A170F,&H2E2A170F,-1,0,0,0,100,100,0,0,3,14,0,8,{SIDE_MARGIN},{SIDE_MARGIN},{CAPTION_TOP},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if question:
        events.append(f"Dialogue: 0,{ass_time(0)},{ass_time(duration)},Question,,0,0,0,,{ass_text(question)}")
    for start, end, text in cues:
        events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(min(end, duration))},Caption,,0,0,0,,{ass_text(text)}")
    return head + "\n".join(events) + "\n"


def filter_graph(ass_path, cut_band, logo):
    """ffmpeg filter graph: blurred background, the picture (its subtitle band cut) scaled down, the ASS layer,
    the logo."""
    kept = SOURCE_HEIGHT - (SUBTITLE_BAND if cut_band else 0)
    escaped = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fonts = FONTS_DIR.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    graph = (f"[0:v]split=2[back][front];"
             f"[back]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
             f"gblur=sigma=110,eq=brightness=-0.42:saturation=0.75[bg];"
             f"[front]crop={SOURCE_WIDTH}:{kept}:0:0,scale={WIDTH}:-2:flags=lanczos[fg];"
             f"[bg][fg]overlay=0:{PICTURE_TOP}[stack];"
             f"[stack]ass='{escaped}':fontsdir='{fonts}'[texts]")
    if logo:
        graph += (f";[1:v]scale={LOGO_SIZE}:{LOGO_SIZE}:force_original_aspect_ratio=decrease,format=rgba,"
                  f"colorchannelmixer=aa=0.75[logo];[texts][logo]overlay=(W-w)/2:{LOGO_TOP}[out]")
    else:
        graph += ";[texts]null[out]"
    return graph


def make_vertical(video_path, srt_path, question, out_path, *, duration, burnt_subtitles=True, logo=None,
                  run=subprocess.run):
    """Write the vertical version of `video_path` to `out_path`. Raises RuntimeError when ffmpeg fails."""
    try:
        with open(srt_path, encoding="utf-8") as stream:
            cues = srt_cues(stream.read())
    except OSError:
        cues = []
    with tempfile.TemporaryDirectory(prefix="breeze-vertical-") as temp:
        ass_path = os.path.join(temp, "vertical.ass")          # a plain path: no "(" or ":" for the filter
        with open(ass_path, "w", encoding="utf-8") as stream:
            stream.write(build_ass(question, cues, duration))
        logo = logo if logo and os.path.isfile(logo) else None
        part = out_path + ".part.mp4"
        command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_path]
        if logo:
            command += ["-i", logo]
        command += ["-filter_complex", filter_graph(ass_path, burnt_subtitles, logo), "-map", "[out]",
                    "-map", "0:a?", *VIDEO_CODEC, "-c:a", "copy", part]
        done = run(command, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SEC * 2)
        if done.returncode:
            if os.path.exists(part):
                os.remove(part)
            raise RuntimeError(f"vertical version failed: {(done.stderr or '')[-400:]}")
        shutil.move(part, out_path)
    return {"path": out_path, "resolution": f"{WIDTH}x{HEIGHT}", "captions": len(cues),
            "subtitle_band_cut": bool(burnt_subtitles)}
