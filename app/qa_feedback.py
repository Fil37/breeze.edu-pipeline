"""
The QA's feedback for an agent the orchestrator redoes after a reject (agent003, agent004).

The orchestrator puts it in the LBREEZE_QA_FEEDBACK environment variable, as JSON
{rejection_notes, blocking_issues: [{scene_id, text, ...}], revision}, for that redo only: the agents
never read qa.json themselves. feedback_section() turns it into a section of the agent's LLM prompt
("Corrections demandées par le QA (révision N)"): the rejection notes, then each blocking issue with
its scene. Missing, not valid JSON or empty: no section, and the agent runs as usual.
"""

import json
import os
import sys

QA_FEEDBACK_ENV = "LBREEZE_QA_FEEDBACK"
MAX_FEEDBACK_ISSUES = 20
MAX_NOTES_CHARS = 3000


def feedback_section(agent, rejected, extra=""):
    """(prompt section, summary for the logs) from LBREEZE_QA_FEEDBACK; ("", None) without usable
    feedback. `rejected`: what the QA rejected ("storyboard", "script"); `extra`: a line added after
    the request to correct (what the agent should keep in mind)."""
    raw = os.environ.get(QA_FEEDBACK_ENV)
    if not raw:
        return "", None
    try:
        feedback = json.loads(raw)
    except ValueError:
        print(f"--- {agent}: {QA_FEEDBACK_ENV} is not valid JSON: ignored", file=sys.stderr, flush=True)
        return "", None
    if not isinstance(feedback, dict):
        return "", None
    notes = str(feedback.get("rejection_notes") or "").strip()
    issues = [i for i in feedback.get("blocking_issues") or [] if isinstance(i, dict)][:MAX_FEEDBACK_ISSUES]
    if not notes and not issues:
        return "", None
    revision = feedback.get("revision", "?")
    lines = [f"\n\nCorrections demandées par le QA (révision {revision}): the previous {rejected} was rejected by the",
             f"pedagogical QA. Correct every point below in this new {rejected}, and keep what was right."]
    if extra:
        lines.append(extra)
    if notes:
        lines.append(f"Rejection notes: {notes[:MAX_NOTES_CHARS]}")
    lines += [f"- scene {issue.get('scene_id') or '?'}: {str(issue.get('text') or '')[:500]}" for issue in issues]
    return "\n".join(lines), {"revision": revision, "blocking_issues": len(issues), "rejection_notes": bool(notes)}
