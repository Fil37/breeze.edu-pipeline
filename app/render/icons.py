"""
The Lucide icon set kept in assets/icons/lucide/ (1,539 icons of lucide-static 0.460.0, ISC, with their tags.json),
for CARD_SCENE (the trial of 2026-11-21): the LLM names a thing in plain English ("orbit", "volcano", "stomach") or
a Lucide name, the program picks the icon.

  find_icon("volcano") -> "mountain-snow" | ...    names(): every icon name
"""

import functools
import json
import os
import re
import unicodedata

LUCIDE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "assets", "icons", "lucide")
FALLBACK = "circle-help"


@functools.lru_cache(maxsize=1)
def _index():
    try:
        with open(os.path.join(LUCIDE_DIR, "tags.json"), encoding="utf-8") as f:
            tags = json.load(f)
    except (OSError, ValueError):
        tags = {}
    names = {n[:-4] for n in os.listdir(LUCIDE_DIR) if n.endswith(".svg")} if os.path.isdir(LUCIDE_DIR) else set()
    return names, {n: [str(t).lower() for t in tags.get(n, [])] for n in names}


def names():
    return sorted(_index()[0])


def _words(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return [w for w in re.split(r"[^a-z0-9]+", text) if w]


def find_icon(query):
    """The Lucide icon for a plain word or a Lucide name; FALLBACK when nothing matches. Scores: the exact name,
    then a tag equal to the query, then names and tags holding its words (a plural tried as singular)."""
    known, tags = _index()
    words = _words(query)
    if not words:
        return FALLBACK
    slug = "-".join(words)
    if slug in known:
        return slug
    forms = set(words) | {w[:-1] for w in words if len(w) > 3 and w.endswith("s")}
    phrase = " ".join(words)
    best, best_score = FALLBACK, 0
    for name in sorted(known):
        parts, score = set(name.split("-")), 0
        if phrase in tags[name]:
            score += 3
        score += 4 * len(forms & parts)
        score += 1 if name.split("-")[0] in forms else 0      # "tree-pine" before "folder-tree"
        score += 2 * sum(1 for t in tags[name] if t in forms)
        score += sum(1 for t in tags[name] for w in forms if len(w) > 3 and w in t.split())
        score -= 0.01 * len(parts)            # the simplest name wins a tie ("orbit" before "orbit-x")
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 2 else FALLBACK


def near(query, count=6):
    """Icons whose name or tags share a word stem (4 letters) with the query: what to suggest for a miss."""
    known, tags = _index()
    stems = {w[:4] for w in _words(query) if len(w) >= 4}
    found = [n for n in sorted(known) if any(p[:4] in stems for p in n.split("-"))
             or any(t[:4] in stems for t in tags[n])]
    return found[:count]
