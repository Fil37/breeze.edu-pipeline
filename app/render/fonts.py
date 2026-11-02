"""
The web fonts of the channels' themes (agent010): Inter, Fira Code and Space Grotesk, from their
npm packages (@fontsource, SIL Open Font License), pinned and checked against their published sha512,
cached in assets/fonts/ on first use, then inlined into each page as data: URIs, so the page itself
never touches the network. Without them (offline first run, wrong hash), the page keeps DejaVu Sans.
"""

import base64
import hashlib
import io
import os
import sys
import tarfile
import urllib.request

from app.render.asset_resolver import BASE_DIR

FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")
FONT_MAX_BYTES = 20_000_000
# family -> (npm package, version, sha512 of its tarball, the weights kept)
FONT_PACKAGES = {
    "Inter": ("inter", "5.3.0", "RofMylZmjlJEfELXeNHFWBRcSs75rGU/6bV2S2jfnvv/3rPXPGe0LgUJTklcHZ9lM4OZmAVFhcJPnACfb91A3g==",
              (400, 600, 800)),
    "Fira Code": ("fira-code", "5.3.0", "EJL968RJRkakubAj/coU8pSUaeTE5UNoRjtzAr6kGiSZ3jWuN8/AKWHwym/PFUaQL1q7IL/H+EXs4358YhrTBQ==",
                  (400, 600)),
    "Space Grotesk": ("space-grotesk", "5.3.0", "ksnGizDPXIDuvqcTYTSrmZ+evx9sDlS8rp7+42BQ7wU+spt3twEoXfbJz672C+5CLg6VeUQwRy5RXshWb67LcQ==",
                      (500, 700)),
}


def font_path(family, weight):
    package = FONT_PACKAGES[family][0]
    return os.path.join(FONTS_DIR, f"{package}-latin-{weight}-normal.woff2")


def download_font(family):
    """Fetch the family's tarball, check its sha512, keep only its latin woff2 files for the weights
    used. True on success; never raises (no network, wrong hash...)."""
    package, version, sha512, weights = FONT_PACKAGES[family]
    url = f"https://registry.npmjs.org/@fontsource/{package}/-/{package}-{version}.tgz"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(FONT_MAX_BYTES + 1)
    except OSError as exc:
        print(f"WARNING fonts: {family} not downloaded ({exc}): DejaVu Sans instead", file=sys.stderr)
        return False
    if len(data) > FONT_MAX_BYTES or base64.b64encode(hashlib.sha512(data).digest()).decode() != sha512:
        print(f"WARNING fonts: {family} tarball does not match its pinned sha512: not used", file=sys.stderr)
        return False
    wanted = {f"package/files/{package}-latin-{w}-normal.woff2": font_path(family, w) for w in weights}
    os.makedirs(FONTS_DIR, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name in wanted:
                with open(wanted[member.name], "wb") as f:
                    f.write(tar.extractfile(member).read())
    return all(os.path.exists(path) for path in wanted.values())


def font_face_css(families):
    """@font-face rules for these families (data: URIs), downloading them on first use; a family that
    cannot be had is left out (the page's font stack falls back to DejaVu Sans)."""
    rules = []
    for family in families:
        if family not in FONT_PACKAGES:
            continue
        weights = FONT_PACKAGES[family][3]
        if not all(os.path.exists(font_path(family, w)) for w in weights) and not download_font(family):
            continue
        for weight in weights:
            with open(font_path(family, weight), "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            rules.append(f"@font-face {{ font-family:'{family}'; font-weight:{weight}; font-style:normal; "
                         f"src:url(data:font/woff2;base64,{data}) format('woff2'); }}")
    return "\n".join(rules)
