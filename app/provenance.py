"""
Provenance of the artefacts in instance/<channel>/: which run wrote each file, which agent, when.
OBSERVATION MODE: it records and warns. It never moves, deletes or blocks anything.

instance/<channel>/manifest.json describes the channel's current run:
  {"run_id": "2026-10-30T16-19-05-electronics", "channel": "breeze_(electronics)",
   "topic": "...", "started_at": "...", "orchestrator_run_id": "20261030T161905Z" | null,
   "artifacts": {"script.json": {"agent": "agent003", "written_at": "...",
                                 "history": [{"agent": "agent003", "written_at": "..."}]}}}
Each agent adds its files as it writes them (register_artifact), so the manifest grows during the
run. A new run replaces it; the previous manifest (the manifest only: artefacts stay where they
are) is kept as instance/<channel>/manifests/<its run_id>.json.

Which run an agent belongs to (current_run_id), in this order:
  1. the LBREEZE_RUN_ID environment variable: the orchestrator sets it for each channel, and
     `--run-id X` on an agent's command line sets it too;
  2. else the run named in the channel's manifest.json: an agent run alone continues the current
     run, which is how agents are tested one after the other;
  3. else a new run id (the channel has no manifest yet), with a warning.
Why an environment variable: the orchestrator calls each agent in-process as
run(channel_id, settings, routes). An environment variable reaches every agent, and standalone
runs too, without changing that signature or any agent's logic.

On start, an agent calls check_inputs(): every input file that exists but is not declared in the
current run's manifest gets a warning "artefact non tracé dans le manifeste : <file>". The agent
then carries on as usual.
"""

import glob
import logging
import os
import re
from datetime import datetime, timezone

from app.agent import INSTANCE_DIR, load_json, save_json, utc_now

RUN_ID_ENV = "LBREEZE_RUN_ID"
MANIFEST = "manifest.json"
ARCHIVE_DIR = "manifests"
CHANNEL_PATTERN = re.compile(r"^breeze_\(([a-z_]+)\)$")
RUN_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:\.\d+)?-([a-z_]+)$")

log = logging.getLogger("breeze.provenance")   # no handler set: warnings go to stderr


def generate_run_id(channel, root=None):
    """A unique run id for a channel: UTC date and time to the second, then the channel's short
    name. "breeze_(electronics)" -> "2026-10-30T16-19-05-electronics". A second run started within
    the same second gets a counter: "2026-10-30T16-19-05.2-electronics"."""
    match = CHANNEL_PATTERN.match(channel or "")
    short = match.group(1) if match else re.sub(r"[^a-z0-9_]+", "_", str(channel).lower())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    archive = os.path.join(root or INSTANCE_DIR, channel, ARCHIVE_DIR)
    taken = {load_manifest(channel, root).get("run_id")}            # the current run and the archived ones
    if os.path.isdir(archive):
        taken |= {os.path.splitext(name)[0] for name in os.listdir(archive)}
    run_id, counter = f"{stamp}-{short}", 1
    while run_id in taken:
        counter += 1
        run_id = f"{stamp}.{counter}-{short}"
    return run_id


def channel_of(run_id):
    """The channel a generated run id belongs to ("...-electronics" -> "breeze_(electronics)"), else None."""
    match = RUN_ID_PATTERN.match(run_id or "")
    return f"breeze_({match.group(1)})" if match else None


def manifest_path(channel, root=None):
    return os.path.join(root or INSTANCE_DIR, channel, MANIFEST)


def load_manifest(channel, root=None) -> dict:
    """The channel's current manifest, or {} when it has none."""
    return load_json(manifest_path(channel, root))


def new_manifest(run_id, channel, topic=None, orchestrator_run_id=None, root=None) -> dict:
    """Start the manifest of run `run_id` (no artefacts yet). The previous run's manifest is copied
    to manifests/<its run_id>.json first; no artefact is touched."""
    previous = load_manifest(channel, root)
    if previous.get("run_id") and previous["run_id"] != run_id:
        archive = os.path.join(root or INSTANCE_DIR, channel, ARCHIVE_DIR)
        os.makedirs(archive, exist_ok=True)
        save_json(os.path.join(archive, f"{previous['run_id']}.json"), previous)
    manifest = {"run_id": run_id, "channel": channel, "topic": topic, "started_at": utc_now(),
                "orchestrator_run_id": orchestrator_run_id, "artifacts": {}}
    os.makedirs(os.path.dirname(manifest_path(channel, root)), exist_ok=True)
    save_json(manifest_path(channel, root), manifest)
    return manifest


def set_topic(channel, topic, root=None):
    """Write the run's topic once it is known (agent001 chooses it)."""
    manifest = load_manifest(channel, root)
    if manifest and topic and manifest.get("topic") != topic:
        manifest["topic"] = topic
        save_json(manifest_path(channel, root), manifest)


def current_run_id(channel, root=None):
    """The run an agent belongs to (see the module's docstring)."""
    run_id = os.environ.get(RUN_ID_ENV) or load_manifest(channel, root).get("run_id")
    if run_id:
        return run_id
    run_id = generate_run_id(channel, root)
    log.warning("--- provenance: %s has no manifest and no run id was given: new run %s", channel, run_id)
    new_manifest(run_id, channel, root=root)
    return run_id


def manifest_for(run_id, channel, root=None) -> dict:
    """The manifest of run `run_id`. If the channel's manifest is for no run or for another one,
    an empty manifest for `run_id` is started, with a warning (observation mode: nothing moves)."""
    manifest = load_manifest(channel, root)
    if manifest.get("run_id") != run_id:
        log.warning("--- provenance: no manifest for run %s in %s%s: starting an empty one",
                    run_id, channel, f" (it held run {manifest['run_id']})" if manifest.get("run_id") else "")
        manifest = new_manifest(run_id, channel, root=root)
    return manifest


def register_artifact(run_id, channel, filename, agent_name, root=None):
    """Declare that `agent_name` has just written instance/<channel>/<filename> in run `run_id`.
    Called by each agent right after it writes the file: the manifest is kept up to date as the
    run goes, never rebuilt at the end. A file written again (QA corrections, revisions) keeps the
    history of its writers."""
    manifest = manifest_for(run_id, channel, root)
    now = utc_now()
    entry = manifest.setdefault("artifacts", {}).setdefault(filename, {"history": []})
    entry.update(agent=agent_name, written_at=now)
    entry["history"].append({"agent": agent_name, "written_at": now})
    save_json(manifest_path(channel, root), manifest)


def check_artifact(run_id, filename, channel=None, root=None, agent_name=None) -> bool:
    """Is `filename` declared in run `run_id`'s manifest? If not, log a warning and return False.
    Never moves or blocks anything. The channel defaults to the one in a generated run id; for
    another run id, the manifests of every channel are searched."""
    channel = channel or channel_of(run_id)
    if channel is None:
        found = [os.path.basename(os.path.dirname(path))
                 for path in glob.glob(os.path.join(root or INSTANCE_DIR, "*", MANIFEST))
                 if load_json(path).get("run_id") == run_id]
        channel = found[0] if found else None
    manifest = load_manifest(channel, root) if channel else {}
    if manifest.get("run_id") == run_id and filename in manifest.get("artifacts", {}):
        return True
    who = f"{agent_name}: " if agent_name else ""
    log.warning("--- %sartefact non tracé dans le manifeste : %s (run %s, %s)", who, filename, run_id, channel or "no manifest")
    return False


def check_inputs(channel, agent_name, filenames, root=None):
    """At an agent's start: its run id (see current_run_id), the run's manifest made sure of, and a
    warning for each input file present in instance/<channel>/ but not declared in it. Returns the
    run id, for register_artifact."""
    run_id = current_run_id(channel, root)
    manifest_for(run_id, channel, root)
    for filename in filenames:
        if os.path.exists(os.path.join(root or INSTANCE_DIR, channel, filename)):
            check_artifact(run_id, filename, channel, root, agent_name)
    return run_id
