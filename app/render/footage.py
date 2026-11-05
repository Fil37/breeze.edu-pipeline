"""
Real film behind the hook (scene 1): agent004 may give it a "footage" {"query": "ciel bleu nuages"},
a few French words of what to film; agent010 finds the clip, cuts it into the scene's frames and draws
them full-frame behind the scene, darkened, under its titles and badges.

Where a clip comes from, in this order:
  1. assets/footage/local/: clips put there by hand (.mp4, .webm, .mov), matched by the words of their
     file name ("ciel_bleu_nuages.mp4");
  2. a clip already fetched for the same query (assets/footage/index.json);
  3. Pixabay's video search (PIXABAY_API_KEY in .env): only the query's words are sent. A clip is
     taken only if it is rated for everyone (isGRated), not marked low quality, at least MIN_SECONDS
     long, and its tags name no face in the foreground (a portrait, a close-up, a selfie: people far
     off or from behind are fine; the Pixabay licence: no recognisable people used in a misleading
     way) and no brand (no logos for commercial use), nor a made-up picture (AI-generated,
     3D render, animation, science fiction: a science video shows the real thing). When a chooser
     is given (agent004: the LLM reads the candidates' tags against the hook's narration), it picks
     the clip that shows the subject, or none (an oil lamp for an electric one, Titan for the Moon).
     It is downloaded once from Pixabay's CDN (https://cdn.pixabay.com, at most MAX_BYTES), never
     hot-linked.
index.json keeps, for every clip used, where it comes from (Pixabay id, page, author, tags, the
query, the day it was fetched): the licence's trace. Nothing is ever deleted here. "rejected" lists, by
hand, clips seen to be wrong ({"pixabay:159674": "an electrician at a panel, for a chip factory"}):
never offered again, nor taken from the cache.
"""

import json
import os
import re
import shutil
from datetime import datetime, timezone
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOOTAGE_DIR = os.path.join(BASE_DIR, "assets", "footage")
LOCAL_DIR = os.path.join(FOOTAGE_DIR, "local")
INDEX_PATH = os.path.join(FOOTAGE_DIR, "index.json")
LOCAL_TYPES = (".mp4", ".webm", ".mov")

PIXABAY_URL = "https://pixabay.com/api/videos/"
PIXABAY_CDN = "cdn.pixabay.com"
PER_PAGE = 30
TIMEOUT_SEC = 30
DOWNLOAD_TIMEOUT_SEC = 300
MIN_SECONDS = 6            # shorter clips loop too visibly
MAX_BYTES = 80_000_000
WIDTH = 1920               # the variant wanted: the frame's width, else the largest below it

QUERY = re.compile(r"[a-zà-öø-ÿ' -]+")
QUERY_WORDS = (1, 4)
QUERY_MAX_CHARS = 40
# Tags (French, as Pixabay gives them with lang=fr, and English) that rule a clip out.
FACES = {"visage", "visages", "portrait", "portraits", "selfie", "mannequin", "modèle", "sourire", "souriant", "souriante",
         "yeux", "regard", "face", "faces", "smile", "model", "headshot", "closeup"}
CLOSE_UP = re.compile(r"\bgros plan\b|\bclose[- ]up\b")
BRANDS = {"logo", "logos", "marque", "marques", "brand", "publicité", "advertising"}
FICTION = {"exoplanète", "exoplanètes", "exoplanet", "fiction", "fantaisie", "fantastique", "fantasy", "animation", "animé",
           "rendu", "render", "cgi", "illustration", "dessin", "cartoon", "imaginaire", "surréaliste", "surreal"}
MAX_CANDIDATES = 8         # allowed hits shown to a chooser, most popular first


class FootageError(RuntimeError):
    pass


def clean_query(value):
    """A query as sent and cached: lowercase French words, 1 to 4, letters only; else None."""
    if not isinstance(value, str):
        return None
    query = " ".join(value.lower().split())
    if not query or len(query) > QUERY_MAX_CHARS or not QUERY.fullmatch(query):
        return None
    return query if QUERY_WORDS[0] <= len(query.split()) <= QUERY_WORDS[1] else None


def query_problem(footage):
    """Why a scene's "footage" is wrong, or None."""
    if not isinstance(footage, dict) or set(footage) != {"query"} or clean_query(footage.get("query")) is None:
        return (f'"footage" is {{"query": "<1 to 4 French words of what to film, letters only, at most '
                f'{QUERY_MAX_CHARS} characters>"}}, e.g. {{"query": "ciel bleu nuages"}}; got {footage!r}'[:300])
    return None


def words(text):
    return set(re.findall(r"[a-zà-öø-ÿ]+", str(text).lower()))


def load_index():
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, ValueError):
        index = {}
    index.setdefault("clips", {})
    index.setdefault("queries", {})
    return index


def save_index(index):
    os.makedirs(FOOTAGE_DIR, exist_ok=True)
    with open(INDEX_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    os.replace(INDEX_PATH + ".tmp", INDEX_PATH)


def local_clip(query):
    """The local clip whose file name shares the most words with the query (at least one), or None."""
    if not os.path.isdir(LOCAL_DIR):
        return None
    wanted, best = words(query), None
    for name in sorted(os.listdir(LOCAL_DIR)):
        if not name.lower().endswith(LOCAL_TYPES):
            continue
        shared = len(wanted & words(os.path.splitext(name)[0].replace("_", " ").replace("-", " ")))
        if shared and (best is None or shared > best[0]):
            best = (shared, name)
    if best is None:
        return None
    return {"source": "local", "file": os.path.join(LOCAL_DIR, best[1]), "name": best[1], "query": query}


def allowed(hit):
    """Why a Pixabay hit is ruled out, or None."""
    tags = words(hit.get("tags", ""))
    if tags & FACES or CLOSE_UP.search(str(hit.get("tags", "")).lower()):
        return f"a face in the foreground: {sorted(tags & FACES) or 'gros plan'}"
    if tags & BRANDS:
        return f"a brand in its tags: {sorted(tags & BRANDS)}"
    if tags & FICTION or re.search(r"\b3d\b", str(hit.get("tags", "")).lower()) or hit.get("isAiGenerated") is True:
        return "a made-up picture (AI-generated, 3D, animation, fiction)"
    if hit.get("isGRated") is False or hit.get("isLowQuality") is True:
        return "not rated for everyone, or low quality"
    if not isinstance(hit.get("duration"), (int, float)) or hit["duration"] < MIN_SECONDS:
        return f"shorter than {MIN_SECONDS} s"
    return None if variant(hit) else "no variant of a usable size on Pixabay's CDN"


def variant(hit):
    """The file to download: WIDTH wide if there is one, else the widest below it; on the CDN, not too big."""
    usable = []
    for item in (hit.get("videos") or {}).values():
        url = str((item or {}).get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.netloc == PIXABAY_CDN and 0 < (item.get("size") or 0) <= MAX_BYTES \
                and 0 < (item.get("width") or 0) <= WIDTH:
            usable.append(item)
    return max(usable, key=lambda item: item["width"]) if usable else None


def search_pixabay(query, key):
    import requests
    response = requests.get(PIXABAY_URL, params={"key": key, "q": query, "lang": "fr", "safesearch": "true",
                                                 "per_page": PER_PAGE, "order": "popular"}, timeout=TIMEOUT_SEC)
    if response.status_code != 200:
        raise FootageError(f"Pixabay search: HTTP {response.status_code}")   # never the URL: it holds the key
    return response.json().get("hits") or []


def download(url, path):
    import requests
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SEC) as response:
        if response.status_code != 200:
            raise FootageError(f"Pixabay download: HTTP {response.status_code}")
        size = 0
        with open(path + ".part", "wb") as f:
            for chunk in response.iter_content(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FootageError(f"Pixabay download: more than {MAX_BYTES} bytes")
                f.write(chunk)
    os.replace(path + ".part", path)


def pixabay_clip(query, key, index, choose=None):
    """The first allowed hit of Pixabay's search (most popular first), or the one `choose` picks among
    the first MAX_CANDIDATES (choose(query, [{"tags", "duration"}]) -> their index, or None: none fits),
    downloaded and indexed."""
    hits = search_pixabay(query, key)
    rejected = index.get("rejected") or {}
    candidates = [hit for hit in hits if allowed(hit) is None and f"pixabay:{hit.get('id')}" not in rejected][:MAX_CANDIDATES]
    if choose is not None and candidates:
        pick = choose(query, [{"tags": str(h.get("tags", ""))[:300], "duration": h.get("duration")} for h in candidates])
        if type(pick) is not int or not 0 <= pick < len(candidates):
            raise FootageError(f"none of the {len(candidates)} Pixabay clips for {query!r} shows the subject")
        candidates = [candidates[pick]]
    for hit in candidates:
        clip_id = f"pixabay:{int(hit['id'])}"
        record = index["clips"].get(clip_id)
        if record is None or not os.path.isfile(os.path.join(FOOTAGE_DIR, record["file"])):
            chosen = variant(hit)
            name = f"pixabay_{int(hit['id'])}_{chosen['width']}.mp4"
            os.makedirs(FOOTAGE_DIR, exist_ok=True)
            download(chosen["url"], os.path.join(FOOTAGE_DIR, name))
            record = {"source": "pixabay", "id": int(hit["id"]), "file": name, "page_url": str(hit.get("pageURL", ""))[:200],
                      "user": str(hit.get("user", ""))[:80], "tags": str(hit.get("tags", ""))[:300],
                      "duration": hit.get("duration"), "width": chosen["width"], "ai_generated": bool(hit.get("isAiGenerated")),
                      "query": query, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            index["clips"][clip_id] = record
        index["queries"][query] = clip_id
        if choose is not None and query not in index.setdefault("checked", []):
            index["checked"].append(query)     # picked for the narration: a later chooser trusts it
        save_index(index)
        return {**record, "file": os.path.join(FOOTAGE_DIR, record["file"])}
    raise FootageError(f"no allowed Pixabay clip for {query!r} ({len(hits)} found, none without a face in the foreground, a brand or a made-up picture)")


def find_clip(query, choose=None):
    """{"source", "file" (absolute), and for Pixabay "id", "page_url", "user", ...} for a query; with a
    chooser (see pixabay_clip), a clip cached without one is searched again.
    Raises FootageError when no clip is found (no local match and no key, nothing allowed or chosen, network)."""
    query = clean_query(query)
    if query is None:
        raise FootageError("invalid query")
    found = local_clip(query)
    if found:
        return found
    index = load_index()
    cached_id = index["queries"].get(query, "")
    cached = None if cached_id in (index.get("rejected") or {}) else index["clips"].get(cached_id)
    if cached and os.path.isfile(os.path.join(FOOTAGE_DIR, cached["file"])) \
            and (choose is None or query in index.get("checked", [])):
        return {**cached, "file": os.path.join(FOOTAGE_DIR, cached["file"])}
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        raise FootageError("no local clip matches and PIXABAY_API_KEY is not set")
    try:
        return pixabay_clip(query, key, index, choose)
    except FootageError:
        raise
    except Exception as exc:              # network error, unexpected answer
        raise FootageError(f"Pixabay: {type(exc).__name__}") from exc


def credit(clip):
    """What the render manifest and the video's description keep of a clip."""
    if clip.get("source") == "pixabay":
        return {key: clip.get(key) for key in ("source", "id", "page_url", "user", "query")}
    return {"source": clip.get("source"), "name": clip.get("name"), "query": clip.get("query")}


def cut_frames(clip_path, seconds, folder, fps, width, height, ffmpeg):
    """The clip as JPEG frames covering `seconds` (looped if shorter), cropped to fill width x height,
    in `folder` (00001.jpg...). Returns how many."""
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    ffmpeg(["-stream_loop", "-1", "-i", clip_path, "-t", f"{seconds:.3f}", "-an",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}",
            "-q:v", "3", os.path.join(folder, "%05d.jpg")], "cut footage frames")
    return len([name for name in os.listdir(folder) if name.endswith(".jpg")])
