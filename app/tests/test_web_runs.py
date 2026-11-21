"""
Check the runs started from the site (2026-11-21), with a fake launcher: no real run starts here.
  1. a start needs the browser's CSRF token (else 400) and a channel of routes.json (else 404)
  2. the command: the orchestrator for that channel, as a list (no shell); the topic in one "--topic=" argument
     (a topic starting with "-" stays a topic), cut at 200 characters; publication and analytics skipped when ticked
  3. one run at a time: refused while a run started here is alive, or while a real run is going (busy_runs)
  4. the log: plain text (never HTML), the secrets of .env removed, only a run's own file (no path)
  5. the channel's page shows the form and the runs started from it, with their state and log
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_web_runs.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
from app.web import app as web                                            # noqa: E402
from app.web import page                                                  # noqa: E402
from app.supervision import SupervisionStore                          # noqa: E402

CHANNEL = page.routes()[0]["channel_id"]
QUOTED = CHANNEL.replace("(", "%28").replace(")", "%29")


class FakeProcess:
    def __init__(self, argv):
        self.argv, self.pid, self.code = argv, 999999, None

    def poll(self):
        return self.code


def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def setup():
    root = tempfile.mkdtemp()
    started = []

    def launcher(argv, log_path):
        with open(log_path, "w") as f:
            f.write("breeze run\n")
        started.append(FakeProcess(argv))
        return started[-1]
    web.RUNNING.clear()
    web.app.config.update(RUNS_DIR=os.path.join(root, "runs"), LAUNCHER=launcher,
                          SUPERVISION_DB=os.path.join(root, "breeze.db"))
    client = web.app.test_client()
    client.get(f"/channel/{QUOTED}")                     # the CSRF cookie
    return client, client.get_cookie("csrf").value, started, root


def done():
    for key in ("RUNS_DIR", "LAUNCHER", "SUPERVISION_DB"):
        web.app.config.pop(key, None)
    web.RUNNING.clear()


def case_guarded():
    client, token, started, _ = setup()
    problems = []
    if client.post("/runs/start", data={"channel": CHANNEL, "csrf": "forged"}).status_code != 400:
        problems.append("a start without the CSRF token accepted")
    if client.post("/runs/start", data={"channel": "breeze_(nope)", "csrf": token}).status_code != 404:
        problems.append("an unknown channel accepted")
    if started:
        problems.append("a run started by a refused request")
    done()
    return report("1. a start needs the CSRF token and a known channel", problems)


def case_command():
    client, token, started, _ = setup()
    problems = []
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token, "topic": "  -rm  les   orbites " + "x" * 300, "skip": "1"})
    argv = started[0].argv if started else []
    want = [sys.executable, web.ORCHESTRATOR, "--channel", CHANNEL]
    if argv[:4] != want or not isinstance(argv, list):
        problems.append(f"the command: {argv[:4]}")
    topic = [a for a in argv if a.startswith("--topic=")]
    if len(topic) != 1 or not topic[0].startswith("--topic=-rm les orbites") or len(topic[0]) != len("--topic=") + 200:
        problems.append(f"the topic: {topic}")
    if "--skip-agents=agent008,agent009" not in argv:
        problems.append("publication and analytics not skipped when ticked")
    started[0].code = 0
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token})
    if len(started) != 2 or any(a.startswith(("--topic", "--skip")) for a in started[1].argv):
        problems.append(f"a run without topic nor skip: {started[-1].argv if started else None}")
    done()
    return report("2. the orchestrator for the channel, no shell, one --topic= argument, the skip when ticked", problems)


def case_one_at_a_time():
    client, token, started, root = setup()
    problems = []
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token})
    response = client.post("/runs/start", data={"channel": CHANNEL, "csrf": token})
    if len(started) != 1 or "run=busy" not in response.headers.get("Location", ""):
        problems.append("a second run started while the first is alive")
    started[0].code = 0
    store = SupervisionStore(os.path.join(root, "breeze.db"))
    real = store.new_run("breeze run real")              # this process: alive
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token})
    if len(started) != 1:
        problems.append("a run started while a real run is going")
    store.finish_run(real, "succeeded")
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token})
    if len(started) != 2:
        problems.append("no run once the others are over")
    done()
    return report("3. one run at a time, none while a real run is going", problems)


def case_log():
    client, token, started, root = setup()
    problems = []
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token})
    name = os.path.basename(next(f for f in os.listdir(os.path.join(root, "runs")) if f.endswith(".log")))[:-4]
    secret = "sk-test-0123456789abcdef"
    os.environ["DEEPSEEK_API_KEY_TEST"] = secret
    with open(os.path.join(root, "runs", name + ".log"), "a") as f:
        f.write(f"error with key {secret}\n<script>alert(1)</script>\n")
    response = client.get(f"/runs/{name}/log")
    text = response.get_data(as_text=True)
    if not response.content_type.startswith("text/plain") or secret in text or "breeze run" not in text:
        problems.append(f"the log: {response.content_type} {secret in text}")
    for bad in ("..%2F..%2Fschemas%2Fsettings", "nope", name + "x"):
        if client.get(f"/runs/{bad}/log").status_code != 404:
            problems.append(f"{bad} served")
    os.environ.pop("DEEPSEEK_API_KEY_TEST", None)
    done()
    return report("4. the log as plain text, secrets removed, only a run's own file", problems)


def case_page():
    client, token, started, _ = setup()
    problems = []
    client.post("/runs/start", data={"channel": CHANNEL, "csrf": token, "topic": "Les orbites"})
    text = client.get(f"/channel/{QUOTED}?run=started").get_data(as_text=True)
    later = client.get(f"/channel/{QUOTED}").get_data(as_text=True)
    if "No run can start now" not in later or "disabled" not in later:
        problems.append("the page lets a second run start")
    for want in ('action="/runs/start"', 'name="topic"', "The run started", "Les orbites", "/log"):
        if want not in text:
            problems.append(f"the page does not show {want!r}")
    done()
    return report("5. the channel's page: the form, the runs started from it, their log", problems)


if __name__ == "__main__":
    results = [case_guarded(), case_command(), case_one_at_a_time(), case_log(), case_page()]
    sys.exit(0 if all(results) else 1)
