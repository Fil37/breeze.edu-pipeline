"""
breeze's test launcher: every tests/test_*.py, one after the other, PASS / FAIL per file, exit 1 if any fails.
It refuses to start while a real run is in progress (the studio kit's busy_runs: a run of instance/breeze.db still
"running" with a live process), since the suite's browsers and renders could starve that run of memory.

  .venv/bin/python tests/run_tests.py            # every file
  .venv/bin/python tests/run_tests.py web curr   # only the files whose name holds one of these words
"""

import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.supervision import busy_runs                                # noqa: E402

DB_PATH = os.path.join(ROOT, "instance", "breeze.db")


def main(words=(), db_path=DB_PATH):
    busy = busy_runs(db_path)
    if busy:
        print(f"refused: a real run is in progress ({', '.join(busy)}); start the tests once it is over")
        return 2
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "tests", "test_*.py"))
                   if not words or any(w in os.path.basename(f) for w in words))
    failed = []
    for path in files:
        started = time.perf_counter()
        result = subprocess.run([sys.executable, path], cwd=ROOT, capture_output=True, text=True)
        name = os.path.basename(path)
        print(f'{"PASS" if result.returncode == 0 else "FAIL"}  {name}  ({time.perf_counter() - started:.0f} s)')
        if result.returncode:
            failed.append(name)
            print("      " + "\n      ".join((result.stdout + result.stderr).strip().splitlines()[-8:]))
    print(f"{len(files) - len(failed)}/{len(files)} files passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
