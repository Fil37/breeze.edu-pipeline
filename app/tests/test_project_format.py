"""
Check the project format (the temperature-bench run of 2026-11-04 turned "réaliser pas à pas un banc"
into a lesson on hysteresis), offline, the LLM stubbed:
  1. agent001 takes a topic to build ("réaliser", "construire", "banc", "pas à pas"...) as a project:
     its prompt asks for the build stages, research.json gets "format": "project" and the topic as
     its concept; other topics are left alone
  2. agent002 plans a project as build stages (its own prompt) and marks the outline; agent003 is
     told to write one build stage a scene, the breadboard and the power-up last; agent004 is given
     the right wiring of a comparator with hysteresis
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_project_format.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
from app.agent import agent001_conceptresearcher as agent001            # noqa: E402
from app.agent import agent002_curriculumsimplifier as agent002         # noqa: E402
from app.agent import agent003_scriptwriter as agent003                 # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_detect():
    problems = []
    for topic, project in (("Réaliser pas à pas un banc de régulation de température", True),
                           ("Construire un détecteur de lumière", True), ("FPGA", False),
                           ("Le prix Nobel de physique 2025", False), ("Ce qui a causé la hausse des prix des composants", False)):
        if agent001.is_project(topic, {"domain": "electronics"}) != project:
            problems.append(f"{topic!r} taken as a project: {not project}")
    # the maths run of 2026-11-06: "pas à pas" made a solver "mounted on a board, switched on"
    for topic, domain in (("Le pivot de Gauss : résoudre un système pas à pas", "math"),
                          ("Construire un budget : épargne et dépenses", "economics")):
        if agent001.is_project(topic, {"domain": domain}):
            problems.append(f"{topic!r} ({domain}) taken as a build on a bench")
    # the economics run of 2026-11-07 never said what the Zucman tax was: the research brings its key facts,
    # the outline carries them, the script says only those figures, the QA checks them
    from app.agent import agent003_scriptwriter as agent003, agent005_educationqa as agent005
    import inspect
    from app.agent import agent002_curriculumsimplifier as agent002
    if '"facts"' not in agent001.PROMPT or "who proposed it" not in agent001.PROMPT or 'outline["facts"]' not in inspect.getsource(agent002) \
            or "facts" not in agent003.PROMPT or '"facts"' not in agent005.PROMPT:
        problems.append("the key facts not carried from the research to the script and the QA")
    if "stages" not in agent001.IMPOSED_PROJECT or "mistakes a beginner" not in agent001.IMPOSED_PROJECT:
        problems.append("agent001's project prompt asks no build stages")
    # a worked problem and a course (2026-11-07: the cinema problem became "why row operations work", the
    # AOP course "why does it saturate", the inverter left out)
    for topic, domain, kind in (("Résoudre un problème de lycée : au cinéma, trouver le prix d'une place", "math", "problem"),
                                ("L'AOP en détail : suiveur, inverseur, non inverseur, sommateur et comparateur, leurs gains", "electronics", "course"),
                                ("Les différents montages de l'AOP", "electronics", "course"),
                                ("Le pendule et le ressort : pourquoi la période ne dépend pas de l'amplitude", "physics_math", None),
                                ("Réaliser un banc de régulation de température", "electronics", "project")):
        if agent001.video_format(topic, {"domain": domain}) != kind:
            problems.append(f"{topic!r}: {agent001.video_format(topic, {'domain': domain})}, expected {kind}")
    if agent001.topic_items("L'AOP : suiveur, inverseur, non inverseur, sommateur et comparateur, leurs formules de gain") != \
            ["suiveur", "inverseur", "non inverseur", "sommateur", "comparateur"]:
        problems.append(f"the course's items: {agent001.topic_items('L AOP : suiveur, inverseur, non inverseur, sommateur et comparateur, leurs formules')}")
    from app.agent import agent003_scriptwriter as agent003
    if "IN FULL" not in agent003.PROBLEM_RULES or "none left out" not in agent003.COURSE_RULES:
        problems.append("agent003 not told to state the problem in full, or to give every item its scene")
    return report("1. agent001: a topic to build is a project, a problem is solved, a course gives each item its scene", problems)


def case_prompts():
    problems = []
    asked = []
    saved = {}
    with tempfile.TemporaryDirectory() as folder:
        stubs = {"channel_dir": lambda c: folder, "load_json": lambda p: {"concept": "banc", "format": "project"},
                 "llm_call": lambda prompt: asked.append(prompt) or '{"learning_outline": ["a", "b", "c"], "aha_moment": "x"}',
                 "save_json": lambda p, d: saved.update(d), "find_route": lambda r, c: {"target_age_band": "12-16"},
                 "finish": lambda *a, **k: None}
        old = {k: getattr(agent002, k) for k in stubs}
        old_check, old_register = agent002.provenance.check_inputs, agent002.provenance.register_artifact
        try:
            for k, v in stubs.items():
                setattr(agent002, k, v)
            agent002.provenance.check_inputs = lambda *a: "run"
            agent002.provenance.register_artifact = lambda *a: None
            agent002.run("breeze_(electronics)", {}, [])
        finally:
            for k, v in old.items():
                setattr(agent002, k, v)
            agent002.provenance.check_inputs, agent002.provenance.register_artifact = old_check, old_register
    if not asked or "PROJECT BUILT STEP BY STEP" not in asked[0] or saved.get("format") != "project":
        problems.append(f"agent002 did not plan a project: {saved}")
    if "what it is FOR" not in agent003.PROJECT_RULES or "what it is FOR" not in agent002.PROJECT_PROMPT:
        problems.append("the hook not told to start from what the project is for")
    if "ONE build stage" not in agent003.PROJECT_RULES or "breadboard" not in agent003.PROJECT_RULES:
        problems.append("agent003 not told to write the build")
    if "THROUGH a\n    resistor" not in agent004.PROMPT and "THROUGH a" not in agent004.PROMPT:
        problems.append("agent004 not given the comparator's wiring")
    return report("2. agent002 plans the build, agent003 writes it stage by stage, agent004 wires it right", problems)


if __name__ == "__main__":
    results = [case_detect(), case_prompts()]
    sys.exit(0 if all(results) else 1)
