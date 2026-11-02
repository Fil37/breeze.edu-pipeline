"""
Universal SVG asset resolver: component type -> local SVG file, for the SVG-based components.

  resolve("WATER_TANK") -> ("/.../assets/icons/cylinder.svg", "cache" | "cdn" | "fallback")

Order:
  1. ICON_ALIASES turns a component type (or a free name) into a Lucide icon name.
  2. assets/icons/<icon>.svg already on disk (downloaded before, or put there by hand) -> "cache".
  3. Download from the Lucide CDN (version pinned), check it is a small, plain SVG, save it -> "cdn".
  4. Otherwise the Lucide "circle-help" icon if cached, else a built-in SVG -> "fallback".
     A fallback is never saved under the icon's own name, so the next run tries the download again.

Only the icon name is sent to the CDN. No network at all: everything still renders (fallback).
"""

import os
import re
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONS_DIR = os.path.join(BASE_DIR, "assets", "icons")

LUCIDE_VERSION = "0.460.0"    # pinned: icon names and drawings do not change under us
CDN_URL = "https://unpkg.com/lucide-static@{version}/icons/{name}.svg"
DOWNLOAD_TIMEOUT_SEC = 8
MAX_SVG_BYTES = 100_000

# Component type (lower case) or free name -> Lucide icon (https://lucide.dev/icons).
ICON_ALIASES = {
    "water_tank": "cylinder",
    "pipe_valve": "git-commit-horizontal",   # a pipe with a valve body in the middle
    "coins": "coins",
    "scale": "scale",
    "bank": "landmark",
    "cart": "shopping-cart",
    "trending_up": "trending-up",
    "trending_down": "trending-down",
    "gauge": "gauge",
}
FALLBACK_ICON = "circle-help"

# Last resort when nothing can be downloaded: a rounded square with a question mark (24x24, like Lucide).
BUILTIN_FALLBACK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
 stroke="#1F2933" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="3" />
  <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14" />
  <path d="M12 17h.01" />
</svg>
"""

ICON_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Anything active in an SVG: refused, the file is only meant to hold shapes.
UNSAFE_SVG = re.compile(r"<script|javascript:|\son[a-z]+\s*=|<foreignObject|<!ENTITY|xlink:href\s*=\s*[\"']http",
                        re.IGNORECASE)


class AssetResolver:
    """Finds (and caches) the SVG file for a component type. One instance per scene is enough."""

    def __init__(self, icons_dir=ICONS_DIR, offline=False):
        self.icons_dir = icons_dir
        self.offline = offline or os.environ.get("BREEZE_OFFLINE") == "1"

    def icon_name(self, name):
        """"WATER_TANK" / "water_tank" -> "cylinder"; an unknown name is used as a Lucide name."""
        key = str(name).strip().lower()
        return ICON_ALIASES.get(key, key.replace("_", "-"))

    def resolve(self, name):
        """Return (path of a local SVG file, source): source is "cache", "cdn" or "fallback"."""
        icon = self.icon_name(name)
        os.makedirs(self.icons_dir, exist_ok=True)
        if ICON_NAME_PATTERN.match(icon):
            path = os.path.join(self.icons_dir, icon + ".svg")
            if os.path.exists(path):
                return path, "cache"
            if not self.offline and self.download(icon, path):
                return path, "cdn"
        return self.fallback(), "fallback"

    def download(self, icon, path):
        """Fetch one icon from the CDN into `path`. True on success; never raises."""
        url = CDN_URL.format(version=LUCIDE_VERSION, name=icon)
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SEC) as response:
                data = response.read(MAX_SVG_BYTES + 1)
        except OSError:          # no network, timeout, 404...
            return False
        text = data.decode("utf-8", errors="replace")
        if len(data) > MAX_SVG_BYTES or "<svg" not in text or UNSAFE_SVG.search(text):
            return False
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
        return True

    def fallback(self):
        """The generic "unknown object" icon: Lucide's circle-help, else the built-in one."""
        path = os.path.join(self.icons_dir, FALLBACK_ICON + ".svg")
        if os.path.exists(path) or (not self.offline and self.download(FALLBACK_ICON, path)):
            return path
        path = os.path.join(self.icons_dir, "_builtin_fallback.svg")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(BUILTIN_FALLBACK_SVG)
        return path
