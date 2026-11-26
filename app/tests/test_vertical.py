"""
Check the vertical (TikTok) version, VERTICAL_FORMAT (2026-11-26, option 2: built from the rendered video,
no new render, no quality loss):
  1. the .srt is read into timed lines; narration text cannot inject ASS override blocks
  2. on a real 1920 x 1080 video: a 1080 x 1920 file, same duration, the audio kept; the picture scaled DOWN
     with its bottom subtitle band (96 px) cut, so the small burnt subtitles never show above the large ones
  3. a failure is a warning: agent010 still delivers the horizontal video
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_vertical.py
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
from app.render import vertical                                            # noqa: E402

failed = 0


def report(label, problems):
    global failed
    failed += bool(problems)
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))


SRT = "1\n00:00:00,500 --> 00:00:01,800\nUn {\\b1}premier{\\b0} essai\n\n2\n00:00:02,000 --> 00:00:02,900\nPuis la suite\n"
problems = []
cues = vertical.srt_cues(SRT)
if [(round(a, 1), round(b, 1)) for a, b, _ in cues] != [(0.5, 1.8), (2.0, 2.9)]:
    problems.append(f"times: {cues}")
ass = vertical.build_ass("Pourquoi {ça} ?", cues, 3.0)
if "{\\b1}" in ass or "Pourquoi (ça) ?" not in ass or "Dialogue: 1,0:00:00.50,0:00:01.80,Caption" not in ass:
    problems.append("ASS lines or escaping")
report("1. timed lines, no ASS injection from the narration", problems)

problems = []
with tempfile.TemporaryDirectory() as temp:
    source = os.path.join(temp, "video.mp4")
    # red picture, a WHITE bottom band of 96 px (where the burnt subtitles live), a tone for the audio
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=1920x1080:r=30:d=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-vf", "drawbox=x=0:y=984:w=1920:h=96:color=white:t=fill", "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", "-shortest", source], check=True)
    srt = os.path.join(temp, "subtitles.srt")
    with open(srt, "w", encoding="utf-8") as stream:
        stream.write(SRT)
    out = os.path.join(temp, "video_vertical.mp4")
    made = vertical.make_vertical(source, srt, "Une question ?", out, duration=3.0)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                            "-of", "csv=p=0", out], capture_output=True, text=True).stdout.split()
    if "1080,1920,video" not in [",".join(reversed(x.split(","))) for x in probe] and "video,1080,1920" not in probe:
        problems.append(f"streams: {probe}")
    if not any(x.startswith("audio") for x in probe):
        problems.append("audio lost")
    duration = float(probe[-1])
    if abs(duration - 3.0) > 0.15:
        problems.append(f"duration {duration}")
    frame = os.path.join(temp, "frame.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.5", "-i", out, "-frames:v", "1",
                    frame], check=True)
    from PIL import Image
    image = Image.open(frame).convert("RGB")
    top, height = vertical.PICTURE_TOP, round(984 * 1080 / 1920)
    red = image.getpixel((540, top + height // 2))
    under = image.getpixel((540, top + height + 6))
    if not (red[0] > 180 and red[1] < 80):
        problems.append(f"picture not where expected: {red}")
    if min(under) > 200:
        problems.append(f"the white subtitle band shows under the picture: {under}")
    if made["captions"] != 2 or not made["subtitle_band_cut"]:
        problems.append(f"result: {made}")
report("2. 1080 x 1920, same length, audio kept, subtitle band cut, picture scaled down", problems)

problems = []
from app.agent import agent010_html_renderer as a10                     # noqa: E402
with tempfile.TemporaryDirectory() as temp:
    video = os.path.join(temp, "video.mp4")
    with open(video, "wb") as stream:
        stream.write(b"not a video")
    warnings = []
    result = a10.make_vertical_version("breeze_(electronics)", {"vertical": {"enabled": True}}, temp, video,
                                       {"question": "?"}, "html_playwright", warnings)
    if result is not None or not any("vertical version not made" in w for w in warnings):
        problems.append(f"result {result}, warnings {warnings}")
    if a10.make_vertical_version("x", {"vertical": {"enabled": False}}, temp, video, {}, "html_playwright", []):
        problems.append("made while disabled")
report("3. a failure is a warning, never a lost horizontal video; the setting turns it off", problems)

sys.exit(1 if failed else 0)
