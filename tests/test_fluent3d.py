"""
Check the objects in relief (Fluent Emoji 3D, MIT; 2026-11-21: the user found the line icons too plain).
  1. every image named in FLUENT_3D is in assets/fluent_3d/, with the MIT licence beside them
  2. an OBJECT icon with a 3D image is shown as that PNG; one without (a person, "cpu") keeps its Lucide outline
  3. the objects only Fluent draws (volcano, dna...) are in the OBJECT vocabulary and each has its image
  4. every image is a small PNG (the page carries them as data: URIs)
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_fluent3d.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.render import fluent3d                                       # noqa: E402
from app.agent.agent010_html_renderer import icon_data_uri            # noqa: E402
from models.visual_brief_schema import OBJECT_ICONS                    # noqa: E402

failed = []


def report(label, problems):
    print(("PASS  " if not problems else "FAIL  ") + label)
    for p in problems:
        print("      - " + p)
    if problems:
        failed.append(label)


p = [f"{k}: {v} missing" for k, v in fluent3d.FLUENT_3D.items() if not fluent3d.png_path(k)]
licence = os.path.join(fluent3d.FLUENT_DIR, "LICENSE")
if not os.path.isfile(licence) or "MIT License" not in open(licence).read():
    p.append("the MIT licence is not beside the images")
report("1. every named image on disk, with its licence", p)

p = []
if not icon_data_uri("droplet").startswith("data:image/png;base64,"):
    p.append("droplet should be the 3D PNG")
if not icon_data_uri("COINS").startswith("data:image/png;base64,"):
    p.append("the COINS component should be the 3D PNG")
for name in ("user", "cpu"):
    if not icon_data_uri(name).startswith("data:image/svg+xml;base64,"):
        p.append(f"{name} should keep its Lucide outline")
report("2. 3D image when there is one, Lucide outline otherwise", p)

names = {n for v in OBJECT_ICONS.values() for n in v}
p = [f"{n} not offered" for n in fluent3d.FLUENT_ONLY if n not in names]
p += [f"{n} has no image" for n in fluent3d.FLUENT_ONLY if not fluent3d.png_path(n)]
report("3. the Fluent-only objects offered, each with its image", p)

p = []
for f in os.listdir(fluent3d.FLUENT_DIR):
    if f.endswith(".png"):
        path = os.path.join(fluent3d.FLUENT_DIR, f)
        if open(path, "rb").read(8) != b"\x89PNG\r\n\x1a\n" or os.path.getsize(path) > 200_000:
            p.append(f"{f}: not a small PNG")
report("4. small PNG files only", p)

sys.exit(1 if failed else 0)
