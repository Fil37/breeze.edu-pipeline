"""
Check app/provenance.py in observation mode, in a temporary instance folder (the real instance/
is never touched):
  1. a manifest.json for run A and a script.json it does not declare: check_artifact(A,
     "script.json") returns False and logs "artefact non tracé dans le manifeste : script.json"
  2. no file was moved, renamed, deleted or changed
  3. load_manifest returns run A's manifest, unchanged
  4. once agent003 registers script.json, check_artifact(A, "script.json") returns True
  5. an agent run alone with LBREEZE_RUN_ID=B (no manifest for B): it starts an empty manifest
     for B with a warning (A's is copied to manifests/), warns about its untracked input, and
     still moves nothing
Prints PASS or FAIL for each check, and exits with 1 if any failed.

  .venv/bin/python tests/test_provenance.py
"""

import hashlib
import json
import logging
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import provenance   # noqa: E402

CHANNEL = "breeze_(electronics)"
RUN_A = "2026-10-30T06-30-00-electronics"
RUN_B = "2026-10-30T16-19-00-electronics"
MANIFEST_A = {"run_id": RUN_A, "channel": CHANNEL, "topic": "La masse (GND)", "started_at": "2026-10-30T06:30:00+00:00",
              "orchestrator_run_id": None,
              "artifacts": {"metadata.json": {"agent": "agent007", "written_at": "2026-10-30T06:41:00+00:00",
                                              "history": [{"agent": "agent007", "written_at": "2026-10-30T06:41:00+00:00"}]}}}


class Captured(logging.Handler):
    """Keeps the provenance warnings, to check them."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def snapshot(folder):
    """{relative path: sha256} of every file under folder, the manifests excepted (they are the
    provenance module's own files)."""
    files = {}
    for directory, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, folder)
            if name != "manifest.json" and "manifests" not in relative.split(os.sep):
                with open(path, "rb") as f:
                    files[relative] = hashlib.sha256(f.read()).hexdigest()
    return files


results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n      {detail}" if detail and not ok else ""))


captured = Captured()
provenance.log.addHandler(captured)
os.environ.pop(provenance.RUN_ID_ENV, None)
with tempfile.TemporaryDirectory() as root:
    folder = os.path.join(root, CHANNEL)
    os.makedirs(folder)
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(MANIFEST_A, f)
    for name, content in (("script.json", {"scenes": [{"scene_id": "1"}]}), ("metadata.json", {"title": "GND"})):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            json.dump(content, f)
    before = snapshot(root)

    # 1. An undeclared file: False, and a warning that names it.
    declared = provenance.check_artifact(RUN_A, "script.json", root=root)
    warned = any("artefact non tracé dans le manifeste : script.json" in m for m in captured.messages)
    check("check_artifact(run A, script.json) is False and logs the warning", declared is False and warned,
          f"returned {declared!r}, warnings {captured.messages}")

    # 2. Nothing moved.
    check("no file moved, renamed, deleted or changed", snapshot(root) == before, f"{before} -> {snapshot(root)}")

    # 3. load_manifest gives run A back, as written.
    check("load_manifest returns run A's manifest", provenance.load_manifest(CHANNEL, root=root) == MANIFEST_A,
          json.dumps(provenance.load_manifest(CHANNEL, root=root)))

    # 4. Declared by its writer: now True, with its agent recorded.
    provenance.register_artifact(RUN_A, CHANNEL, "script.json", "agent003", root=root)
    entry = provenance.load_manifest(CHANNEL, root=root)["artifacts"].get("script.json", {})
    check("after register_artifact, check_artifact is True and names agent003",
          provenance.check_artifact(RUN_A, "script.json", root=root) is True and entry.get("agent") == "agent003",
          json.dumps(entry))

    # 5. An agent alone with another run id: empty manifest for B, A's kept aside, warnings, no move.
    captured.messages.clear()
    os.environ[provenance.RUN_ID_ENV] = RUN_B
    run_id = provenance.check_inputs(CHANNEL, "agent004", ["script.json"], root=root)
    os.environ.pop(provenance.RUN_ID_ENV)
    manifest = provenance.load_manifest(CHANNEL, root=root)
    archived = os.path.exists(os.path.join(folder, "manifests", f"{RUN_A}.json"))
    ok = (run_id == RUN_B and manifest.get("run_id") == RUN_B and manifest.get("artifacts") == {} and archived
          and any(f"no manifest for run {RUN_B}" in m for m in captured.messages)
          and any("agent004: artefact non tracé dans le manifeste : script.json" in m for m in captured.messages)
          and snapshot(root) == before)
    check("an agent with LBREEZE_RUN_ID=B: empty manifest for B (A kept in manifests/), warnings, nothing moved", ok,
          f"run_id={run_id} manifest={manifest} archived={archived} warnings={captured.messages}")

provenance.log.removeHandler(captured)
print(f"\n{sum(results)}/{len(results)} PASS")
sys.exit(0 if all(results) else 1)
