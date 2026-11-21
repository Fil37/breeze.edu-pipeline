import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEDIA_DIR = ROOT / "media" / "test_single_scene"

brief = {
    "scene_id": "test_01",
    "text_overlay": {
        "title": "Circuit simple",
        "subtitle": "La lampe s'allume quand le courant circule",
        "clear_previous": True,
    },
    "entities": [
        {"id": "bat", "type": "BATTERY", "position": [-3, -0.5, 0],
         "initial_state": {}},
        {"id": "lamp", "type": "LAMP", "position": [3, -0.5, 0],
         "initial_state": {}},
    ],
    "connections": [
        {"source_id": "bat", "source_port": "positive",
         "target_id": "lamp", "target_port": "left_terminal"},
        {"source_id": "lamp", "source_port": "right_terminal",
         "target_id": "bat", "target_port": "negative"},
    ],
    "actions": [
        {"at": 0.2, "action": "spawn", "target": "bat"},
        {"at": 0.6, "action": "spawn", "target": "lamp"},
        {"at": 1.5, "action": "set_state", "target": "bat", "state": "active"},
        {"at": 2.0, "action": "set_state", "target": "lamp", "state": "on"},
        {"at": 2.5, "action": "start_flow", "path": ["bat", "lamp"]},
    ],
}

with tempfile.TemporaryDirectory(prefix="breeze-test-") as temp:
    temp = Path(temp)
    brief_path = temp / "brief.json"
    runner_path = temp / "runner.py"

    brief_path.write_text(json.dumps({
        "brief": brief,
        "duration": 6,
        "planned_duration": 6,
        "carried_overlay": None,
    }), encoding="utf-8")

    runner_path.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from app.render.breeze_engine import BreezeSceneEngine\n"
        "class TestScene(BreezeSceneEngine):\n"
        f"    brief_file = {str(brief_path)!r}\n",
        encoding="utf-8",
    )

    subprocess.run([
        sys.executable, "-m", "manim", "render",
        str(runner_path), "TestScene",
        "--resolution", "854,480",
        "--fps", "15",
        "--media_dir", str(MEDIA_DIR),
        "-o", "test_scene",
        "--format", "mp4",
        "--disable_caching",
        "--progress_bar", "none",
    ], cwd=ROOT, check=True)

videos = list(MEDIA_DIR.rglob("test_scene.mp4"))
print(f"Vidéo générée : {videos[0]}" if videos else "Rendu terminé, vidéo introuvable.")