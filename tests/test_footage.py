"""
Check the real film behind the hook (app/render/footage.py), offline (Pixabay replaced by fixed
answers; the real assets/footage/ is never touched) but for the browser:
  1. a query is 1 to 4 French words, letters only; anything else is refused
  2. a Pixabay hit with a face in the foreground or a brand in its tags, not rated for everyone, too
     short, or whose file is not on Pixabay's CDN is ruled out (people far off are fine); the 1920-wide file is taken, else the widest below
  3. finding a clip: a local clip whose name matches comes first; else Pixabay's first allowed hit,
     downloaded once and indexed with its source (id, page, author, query); the same query again
     uses the index, no search; no local clip and no key: an error, never something made up
  4. agent004: "footage" only on the hook, with a valid query and little drawn over it; agent007
     credits each Pixabay clip in the description
  5. agent010 page: the film's frame for t full-frame behind the scene, seek waiting until it is shown
Prints PASS or FAIL per case. Case 5 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_footage.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as agent004        # noqa: E402
from app.agent import agent007_metadatagenerator as agent007           # noqa: E402
from app.agent import agent010_html_renderer as renderer               # noqa: E402
from app.render import footage                                         # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                # noqa: E402

CDN = "https://cdn.pixabay.com/video/2016/02/13/2142_large.mp4"


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def hit(clip_id, tags, duration=20, rated=True, url=CDN, width=1920):
    return {"id": clip_id, "tags": tags, "duration": duration, "isGRated": rated, "isLowQuality": False,
            "pageURL": f"https://pixabay.com/videos/id-{clip_id}/", "user": "Auteur",
            "videos": {"large": {"url": url, "width": width, "height": 1080, "size": 5_000_000},
                       "small": {"url": CDN.replace("large", "small"), "width": 960, "height": 540, "size": 1_000_000}}}


def case_query():
    problems = []
    good = {"ciel bleu nuages": "ciel bleu nuages", "  Péage   autoroute ": "péage autoroute", "pluie": "pluie"}
    for value, expected in good.items():
        if footage.clean_query(value) != expected:
            problems.append(f"{value!r} -> {footage.clean_query(value)!r}")
    for value in ("", "ciel bleu nuages blancs du soir", "ciel<script>", "https://x.y", "10 volts", None, ["ciel"],
                  "a" * 41):
        if footage.clean_query(value) is not None:
            problems.append(f"{value!r} accepted")
    if footage.query_problem({"query": "ciel", "extra": 1}) is None or footage.query_problem({"query": "ciel"}) is not None:
        problems.append("the footage field's shape")
    return report("1. a query is a few French words, nothing else", problems)


def case_allowed():
    problems = []
    for h in (hit(1, "ciel, nuages, bleu"), hit(2, "plage, femme, mer"), hit(3, "ville, foule")):
        if footage.allowed(h) is not None:
            problems.append(f"{h['tags']!r} ruled out: {footage.allowed(h)}")
    for why, h in (("a portrait", hit(2, "femme, portrait, sourire")), ("a close-up", hit(3, "homme, gros plan, bureau")),
                   ("a brand", hit(4, "voiture, logo")), ("not rated", hit(5, "ciel", rated=False)),
                   ("too short", hit(6, "ciel", duration=3)),
                   ("off the CDN", {**hit(7, "ciel"), "videos": {"large": {"url": "https://evil.example/x.mp4", "width": 1920, "size": 10}}}),
                   ("plain http", {**hit(8, "ciel"), "videos": {"large": {"url": CDN.replace("https", "http"), "width": 1920, "size": 10}}})):
        if footage.allowed(h) is None:
            problems.append(f"{why} allowed")
    wide = hit(9, "ciel", width=3840)
    wide["videos"]["medium"] = {"url": CDN.replace("large", "medium"), "width": 1280, "height": 720, "size": 2_000_000}
    if footage.variant(hit(10, "ciel"))["width"] != 1920 or footage.variant(wide)["width"] != 1280:
        problems.append("the variant chosen")
    return report("2. faces in the foreground, brands, unrated, short or off-CDN clips are ruled out; people far off kept", problems)


class Sandbox:
    """footage's folders in a temporary one; Pixabay's search and download replaced."""
    def __init__(self, hits):
        self.hits, self.searches, self.downloads = hits, [], []

    def __enter__(self):
        self.root = tempfile.mkdtemp()
        self.saved = {name: getattr(footage, name) for name in ("FOOTAGE_DIR", "LOCAL_DIR", "INDEX_PATH", "search_pixabay", "download")}
        footage.FOOTAGE_DIR = self.root
        footage.LOCAL_DIR = os.path.join(self.root, "local")
        footage.INDEX_PATH = os.path.join(self.root, "index.json")
        footage.search_pixabay = lambda query, key: self.searches.append(query) or self.hits
        footage.download = lambda url, path: self.downloads.append(url) or open(path, "wb").write(b"film")
        self.key = os.environ.pop("PIXABAY_API_KEY", None)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(footage, name, value)
        if self.key is not None:
            os.environ["PIXABAY_API_KEY"] = self.key
        shutil.rmtree(self.root)


def case_find():
    problems = []
    with Sandbox([hit(11, "plage, femme, portrait"), hit(12, "ciel, nuages, bleu")]) as box:
        try:
            footage.find_clip("ciel bleu")
            problems.append("no key and no local clip: a clip was found")
        except footage.FootageError:
            pass
        os.environ["PIXABAY_API_KEY"] = "test"
        clip = footage.find_clip("Ciel bleu")
        if clip.get("id") != 12 or not os.path.isfile(clip["file"]) or box.downloads != [CDN]:
            problems.append(f"Pixabay clip {clip}, downloads {box.downloads}")
        index = footage.load_index()
        record = index["clips"].get("pixabay:12", {})
        if index["queries"].get("ciel bleu") != "pixabay:12" or record.get("page_url") != "https://pixabay.com/videos/id-12/" \
                or record.get("user") != "Auteur" or not record.get("fetched_at"):
            problems.append(f"index {index}")
        again = footage.find_clip("ciel bleu")
        if box.searches != ["ciel bleu"] or again["file"] != clip["file"]:
            problems.append(f"the same query searched again: {box.searches}")
        os.makedirs(footage.LOCAL_DIR)
        open(os.path.join(footage.LOCAL_DIR, "ciel_bleu_du_soir.mp4"), "wb").write(b"local")
        local = footage.find_clip("ciel bleu")
        if local.get("source") != "local" or not local["file"].endswith("ciel_bleu_du_soir.mp4"):
            problems.append(f"the local clip not first: {local}")
        if footage.credit(clip) != {"source": "pixabay", "id": 12, "page_url": "https://pixabay.com/videos/id-12/",
                                    "user": "Auteur", "query": "ciel bleu"}:
            problems.append(f"credit {footage.credit(clip)}")
        box.hits = [hit(13, "femme, visage, plage")]
        try:
            footage.find_clip("plage")
            problems.append("a clip with a face in the foreground taken")
        except footage.FootageError:
            pass
        del os.environ["PIXABAY_API_KEY"]
    return report("3. local clip first, then Pixabay once and indexed; never a face in the foreground", problems)


def case_agents():
    problems = []
    brief = lambda scene_id, n: SceneVisualBrief.model_validate({
        "scene_id": scene_id, "text_overlay": {"title": "Pourquoi ?"}, "connections": [], "actions": [],
        "entities": [{"id": f"n{i}", "type": "ARROW_ANNOTATION", "position": [0, i, 0],
                      "initial_state": {"text": "Une question", "kind": "status"}} for i in range(n)]})
    order = ["1", "2"]
    briefs = {"1": brief("1", 1), "2": brief("2", 1)}
    ok = {"1": {"footage": {"query": "ciel bleu"}}}
    if agent004.footage_problems(order, briefs, ok):
        problems.append(f"a good hook film refused: {agent004.footage_problems(order, briefs, ok)}")
    for why, layouts, crowded in (("on scene 2", {"2": {"footage": {"query": "ciel"}}}, 1),
                                  ("a bad query", {"1": {"footage": {"query": "ciel<b>"}}}, 1),
                                  ("too much over it", ok, 4)):
        if not agent004.footage_problems(order, {**briefs, "1": brief("1", crowded)}, layouts):
            problems.append(f"{why}: not sent back")
    if agent004.scene_footage("1", order, ok["1"]) != {"footage": {"query": "ciel bleu"}} \
            or agent004.scene_footage("2", order, {"footage": {"query": "ciel"}}) != {}:
        problems.append("the storyboard's footage field")
    rendered = [{"scene_id": 1, "footage": {"source": "pixabay", "user": "FindingFootage", "page_url": "https://pixabay.com/videos/id-2142/"}},
                {"scene_id": "plan"}, {"scene_id": 2, "footage": {"source": "local", "name": "pluie.mp4"}}]
    if agent007.film_credits(rendered) != ["Images : FindingFootage sur Pixabay (https://pixabay.com/videos/id-2142/)"]:
        problems.append(f"credits {agent007.film_credits(rendered)}")
    return report("4. agent004: film on the hook only, few things over it; agent007 credits Pixabay", problems)


def case_page():
    from playwright.sync_api import sync_playwright
    problems = []
    brief = {"scene_id": "1", "text_overlay": {"title": "Pourquoi le ciel est-il bleu ?"}, "connections": [], "actions": [],
             "entities": []}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        frames = os.path.join(folder, "scene_001_footage")
        os.makedirs(frames)
        for n, colour in enumerate(("red", "green", "blue"), start=1):   # one second per frame: 1 fps
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=192x108", "-frames:v", "1",
                            os.path.join(frames, f"{n:05d}.jpg")], check=True)
        data = renderer.page_data(brief, 3, None)
        data["footage"] = {"dir": "scene_001_footage", "count": 3, "fps": 1}
        path = os.path.join(folder, "scene_001.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(data))
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            seen = []
            for t in (0.5, 1.5, 2.5, 9):
                page.evaluate(f"window.seek({t})")       # returns once the frame is decoded
                seen.append(page.evaluate("""() => { const img = document.getElementById('footage');
                  return [img.getAttribute('src'), img.complete && img.naturalWidth > 0]; }"""))
            pixel = page.screenshot(clip={"x": 960, "y": 600, "width": 1, "height": 1})
            classes = page.evaluate("document.getElementById('stage').className")
        finally:
            browser.close()
    srcs = [s for s, _ in seen]
    if srcs != ["scene_001_footage/00001.jpg", "scene_001_footage/00002.jpg", "scene_001_footage/00003.jpg",
                "scene_001_footage/00003.jpg"] or not all(ok for _, ok in seen):
        problems.append(f"frames shown {seen}")
    if "on-footage" not in classes:
        problems.append("titles not set for a film behind")
    import io
    try:
        from PIL import Image
        r, g, b = Image.open(io.BytesIO(pixel)).convert("RGB").getpixel((0, 0))
        if not (b > r + 40 and b > g + 40):
            problems.append(f"the last frame (blue) not behind the scene: pixel {(r, g, b)}")
    except ImportError:
        pass
    return report("5. the film's frame for t, full-frame behind the scene", problems, [str(srcs)])


if __name__ == "__main__":
    results = [case_query(), case_allowed(), case_find(), case_agents(), case_page()]
    sys.exit(0 if all(results) else 1)
