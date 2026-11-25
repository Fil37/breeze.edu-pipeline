"""
Check the web interface's protections found by Secure Agents on 2026-11-25 (Flask test client, no server):
  1. HOST_GUARD: localhost, 127.0.0.1 and the names of TRUSTED_EXTRA_HOSTS are answered; any other Host header is
     a 400 (a page opened in the browser cannot drive the site by DNS rebinding); a malformed name is ignored
  2. HEADER_FRAME: the pages cannot be framed by another site (frame-ancestors 'none', X-Frame-Options DENY) and
     send a Referrer-Policy
  3. FLASK_DEBUG: app.run is never called with debug=True (its console runs Python code)
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_web_security.py
"""

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
os.environ["TRUSTED_EXTRA_HOSTS"] = "phone.example.ts.net, *.evil.example, bad host"
from app.web import app as web                                            # noqa: E402

client = web.app.test_client()
failed = 0


def report(label, problems):
    global failed
    failed += bool(problems)
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))


problems = []
for host, expected in (("localhost", 200), ("127.0.0.1:5000", 200), ("phone.example.ts.net", 200),
                       ("PHONE.example.ts.net:5000", 200), ("evil.example", 400), ("a.evil.example", 400),
                       ("127.0.0.1.evil.example", 400)):
    status = client.get("/standup", headers={"Host": host}).status_code
    if status != expected:
        problems.append(f"Host {host}: {status}, expected {expected}")
if "bad host" in web.TRUSTED_HOSTS or any("*" in h for h in web.TRUSTED_HOSTS):
    problems.append(f"malformed names kept: {sorted(web.TRUSTED_HOSTS)}")
report("HOST_GUARD: only local and listed host names", problems)

response = client.get("/standup")
headers = response.headers
problems = [name for name, ok in (("frame-ancestors", "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")),
                                  ("X-Frame-Options", headers.get("X-Frame-Options") == "DENY"),
                                  ("Referrer-Policy", bool(headers.get("Referrer-Policy")))) if not ok]
report("HEADER_FRAME: no framing, a referrer policy", problems)

problems = []
for relative in ("app/web/app.py", "app/archive/web_v1/app.py"):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run":
            for keyword in node.keywords:
                if keyword.arg == "debug" and getattr(keyword.value, "value", None) is True:
                    problems.append(f"{relative}:{node.lineno} debug=True")
report("FLASK_DEBUG: never the Werkzeug debugger", problems)

sys.exit(1 if failed else 0)
