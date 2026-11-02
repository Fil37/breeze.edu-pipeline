"""
Recurring defects report: what goes wrong again and again, run after run, per channel.

INPUT:  schemas/rows.json (what each agent reported in each run) + schemas/reports.json (each run's
        agent statuses and errors). Read only: nothing is written unless --out is given.
OUTPUT: a Markdown report on stdout (or --out FILE), or JSON with --json:
          1. the runs looked at: topic, worst status (and which agent), video or not, QA revisions,
             why it stopped (the critical agent's error)
          2. the defects seen in at least --min-runs runs, most frequent first: in how many runs,
             how many times, the last run, an example
          3. how many were seen in a single run
NOTES:  A defect is counted once per run (a QA revision that repeats it does not count twice) and
        its occurrences are counted too. Standalone agent runs (run id "standalone") are left out:
        their rows cannot be told apart.
        The defects come from three kinds of sources, grouped three ways:
          - messages our code writes (layout conflicts, render warnings, agent004's coherence rules
            and errors): a fixed grammar, turned into a template where entity ids become their role
            ("arrow_slow overlaps arrow_earth" -> "badge chevauche badge"); the role is guessed from
            the id ("arrow_", "vector_", "axes_"...), as past storyboards are not kept
          - the QA's issues (free French text from the LLM): grouped by theme (QA_THEMES, keyword
            rules, the first that matches), with their severities
          - why a run stopped (the critical agent's error in reports.json), numbers and quoted parts
            blanked out, so the same failure (a quota, a missing key) adds up across runs
          - the QA's "unsupported" list (what the narration needs and no component draws): grouped by
            what is missing (MISSING_THINGS): the vocabulary to add
        The themes and roles are heuristics: each line shows a real example to check them against.

  .venv/bin/python app/defect_report.py                                  # every channel, last 10 runs each
  .venv/bin/python app/defect_report.py --channel "breeze_(math)" --last 5
  .venv/bin/python app/defect_report.py --json --out instance/defects.json
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # standalone runs

from app.agent import REPORTS_PATH, ROWS_PATH, load_json   # noqa: E402


def plain(text):
    """Lowercase, without accents: what the keyword rules match on."""
    return "".join(c for c in unicodedata.normalize("NFD", str(text).lower()) if unicodedata.category(c) != "Mn")


# The QA's issues, by theme: the first rule that matches (on the text without accents) wins.
QA_THEMES = [
    ("élément impossible à dessiner avec les composants", r"representable|non disponible|aucun composant|pas de composant|"
     r"ne peu\w* pas (etre )?(dessin|montr|rend|produi|represent)|cannot|not available|faux-semblant"),
    ("flèche ou vecteur mal orienté ou mal placé", r"(fleche|vecteur|arrow|vector|annotation)\b.{0,90}(pointe|orient|direction|tangent|dans le vide)"),
    ("courbe, trajectoire ou repère qui ne correspond pas", r"orbit|trajectoire|courbe|parabol|sinus|cosinus|repere|axe des|graphique"),
    ("icône détournée ou ambiguë (jauge, tendance, chariot...)", r"icone|jauge|gauge|tendance|trending|chariot|\bcart\b|pictogramme|\bscale\b|balance"),
    ("étiquette, légende ou annotation fausse ou ambiguë", r"etiquet|label|libelle|annotation|legende"),
    ("apparition ou disparition mal minutée", r"\bfade|apparai|disparai|\bspawn|trop tot|trop tard|timing|avant que|apres que"),
    ("formule fausse ou mal choisie", r"formule|latex|equation"),
    ("circuit, fils ou mesure", r"circuit|\bfils?\b|branche|connexion|voltmetre|amperemetre|sonde"),
    ("chevauchement ou surcharge visuelle", r"chevauch|overlap|superpos|illisib|lisib|surcharg"),
    ("visuel qui ne suit pas la narration", r"narration|synchro|\bcue\b|moment cle|key visual"),
    ("texte imprécis (titre, formulation, valeur chiffrée)", r"titre|formul|grammatic|orthograph|\bvaleurs?\b|chiffre|%|precis|explicit"),
]
# The QA's "unsupported" entries, by what is missing.
MISSING_THINGS = [
    ("astres (Terre, Soleil, Lune, planètes)", r"\bterre\b|soleil|\blune\b|planete|globe|hemisphere|astre"),
    ("orbite ou trajectoire fermée", r"orbit|trajectoire fermee|cercle|ellips"),
    ("personnages (astronaute, personne)", r"astronaute|personne|humain|personnage|enfant|eleve"),
    ("lumière et optique", r"lumi|faisceau|rayon|lampe torche|ombre|terminateur"),
    ("objet en mouvement (chute, lancer, déplacement)", r"chute|lanc|tomb|mouvement|deplac|anim|balle|projectile"),
    ("objets techniques et véhicules (station, satellite, ascenseur, fusée)",
     r"ascenseur|tour\b|voiture|vehicule|fusee|propulsion|peage|route|station|\biss\b|satellite|vaisseau|navette"),
    ("tableau, carte ou schéma composite", r"tableau|carte|panneau|schema|composite|loupe"),
    ("notions abstraites (économie, confiance...)", r"notion|abstrait|confiance|conjoncture|refinancement|horizon"),
]
# An entity id -> its role, guessed from the words in it (past storyboards are not kept).
ROLES = [("badge", r"arrow|annotation|note|badge|pill"), ("vecteur", r"vector|vecteur|force|poids|vitesse"),
         ("graphique", r"axes|axis|graph|repere"), ("formule", r"formula|formule|equation|eq\d|tex"),
         ("courbe", r"curve|courbe|plot"), ("fil", r"wire|bus|fil")]
# Messages our code writes, as (pattern, template); the named groups are entity ids.
TEMPLATES = [
    (r"^(?P<a>\S+)(?P<la> \(label\))? overlaps (?P<b>\S+)(?P<lb> \(label\))?$", "{a}{la} chevauche {b}{lb}"),
    (r"^(?P<a>\S+) points at nothing$", "{a} ne pointe sur rien"),
    (r"^(?P<a>\S+) enters the title zone$", "{a} empiète sur la zone du titre"),
    (r"^(?P<a>\S+) leaves the frame$", "{a} sort de l'image"),
    (r"^(?P<a>[^\s:]+): no free spot", "{a} : pas de place libre, chevauche un autre composant"),
    (r"^no clean route from", "fil sans tracé propre"),
    (r"points at \S+, the formula of .*must name it", "badge dont le texte ne nomme pas la grandeur de sa formule"),
    (r"narration speaks of courant", "narration parle de courant, sans start_flow"),
    (r"narration speaks of tension", "narration parle de tension, sans mesure"),
    (r"narration opens the circuit", "narration ouvre le circuit, sans interrupteur ouvert"),
    (r'needs a "cue"', "action sans cue"),
    (r"has the cue .* not in the narration", "cue absent de la narration"),
    (r"one theme per scene", "analogie mélangée à un circuit dans une scène"),
    (r"fades out: an analogy", "analogie qui disparaît avant la fin de la scène"),
    (r"circuit is not closed", "circuit ouvert"),
    (r"cut off at max_tokens", "réponse du LLM tronquée (max_tokens)"),
    (r"voice: ElevenLabs failed", "voix ElevenLabs en échec, edge-tts à la place"),
    (r"renderer is 'skip'", "renderer 'skip' : pas de vidéo"),
]


def role(entity_id):
    name = plain(entity_id)
    return next((label for label, pattern in ROLES if re.search(pattern, name)), "composant")


def template(message):
    """One of our code's messages -> its template, entity ids replaced by their role."""
    text = re.sub(r"^scene[ _]\d+:\s*", "", str(message).strip())
    for pattern, form in TEMPLATES:
        match = re.search(pattern, text)
        if match:
            ids = {k: role(v) if k in ("a", "b") else (v or "") for k, v in match.groupdict().items()}
            if "a" in ids and "b" in ids and (ids["b"], ids["lb"]) < (ids["a"], ids["la"]):   # "x chevauche y" = "y chevauche x"
                ids["a"], ids["la"], ids["b"], ids["lb"] = ids["b"], ids["lb"], ids["a"], ids["la"]
            return form.format(**ids).replace(" (label)", " (étiquette)")
    text = re.sub(r"'[^']*'|\"[^\"]*\"|«[^»]*»", "'…'", text)
    text = re.sub(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", lambda m: role(m.group()), text)
    return re.sub(r"\b\d+(?:\.\d+)?\b", "N", text)[:140]


def theme(text, rules):
    name = plain(text)
    return next((label for label, pattern in rules if re.search(pattern, name)), "autre")


def stop_reason(report):
    """(critical agent, its error) of a run's reports.json entry, or (None, None)."""
    agents = report.get("agents") or {}
    critical = next((name for name, status in agents.items() if status == "critical" and name != "agent009"), None)
    if critical is None:
        return None, None
    error = next((e for e in reversed(report.get("errors") or []) if str(e).startswith(critical + ":")), None)
    return critical, error


def defects_of(rows, report=None):
    """[(source, key, example, severity or None)] from one run's rows (and its reports.json entry)."""
    found = []
    critical, error = stop_reason(report or {})
    if critical:
        reason = re.sub(r"\b\d+(?:\.\d+)?\b", "N", re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", str(error or "no error recorded")))
        found.append((f"Run : arrêt ({critical})", reason[:120], error or "", None))
    for row in rows:
        data, agent = row.get("data") or {}, row["agent"]
        if agent == "agent004":
            found += [("Storyboard : règle non respectée après 3 essais", template(m), m, None) for m in data.get("coherence_left") or []]
            if data.get("error"):
                for line in str(data["error"]).replace("last errors:", "\n").splitlines()[1:] or [data["error"]]:
                    if line.strip():
                        found.append(("Storyboard : échec", template(line), line.strip(), None))
        if agent == "agent005":
            for issue in data.get("issues") or []:
                text, severity = (issue.get("text", ""), issue.get("severity")) if isinstance(issue, dict) else (issue, None)
                found.append(("QA : issue", theme(text, QA_THEMES), text, severity))
            found += [("QA : impossible à dessiner", theme(u, MISSING_THINGS), u, None) for u in data.get("unsupported") or []]
            found += [("QA : mise en page", template(c), c, None) for c in data.get("layout_conflicts") or []]
        if agent in ("agent006", "agent010"):
            for scene in data.get("scenes") or []:
                if isinstance(scene, dict):
                    found += [("Rendu : conflit", template(c), c, None) for c in scene.get("layout_conflicts") or []]
            found += [("Rendu : avertissement", template(w), w, None) for w in data.get("warnings") or []
                      if "layout conflicts:" not in str(w)]   # the same conflicts, already counted per scene
    return found


def collect(rows, reports, channel=None, last=10):
    """The runs looked at (newest last) and their defects, per channel."""
    runs = defaultdict(list)
    for row in rows:
        if row.get("run_id") and row["run_id"] != "standalone" and row.get("channel") not in (None, "global"):
            if channel is None or row["channel"] == channel:
                runs[(row["channel"], row["run_id"])].append(row)
    report_of = {(r.get("channel"), r.get("run_id")): r for r in reports or []}
    by_channel = defaultdict(list)
    for (chan, run_id), run_rows in runs.items():
        by_channel[chan].append((min(r.get("timestamp", "") for r in run_rows), run_id, run_rows))
    result = {}
    for chan, items in sorted(by_channel.items()):
        items = sorted(items)[-last:]
        result[chan] = []
        for started, run_id, run_rows in items:
            report = report_of.get((chan, run_id)) or {}
            statuses = [s for name, s in (report.get("agents") or {}).items() if name != "agent009"]
            research = next((r["data"] for r in run_rows if r["agent"] == "agent001"), {}) or {}
            critical, error = stop_reason(report)
            result[chan].append({
                "run_id": run_id, "started": started, "topic": research.get("imposed_topic") or research.get("concept"),
                "status": next((s for s in ("critical", "not_healthy", "healthy") if s in statuses), "unknown")
                          + (f" ({critical})" if critical else ""),
                "video": any(r["agent"] in ("agent006", "agent010") and (r.get("data") or {}).get("video_path") for r in run_rows),
                "revisions": max(sum(r["agent"] == "agent005" for r in run_rows) - 1, 0),
                "stopped_by": error,
                "defects": defects_of(run_rows, report)})
    return result


def recurring(runs, min_runs=2):
    """Defects grouped by (source, key): in how many runs, how many times, last seen, an example."""
    groups = {}
    for index, run in enumerate(runs):
        for source, key, example, severity in run["defects"]:
            g = groups.setdefault((source, key), {"source": source, "defect": key, "runs": set(), "count": 0,
                                                  "severities": defaultdict(int), "example": example, "last": None})
            g["runs"].add(index)
            g["count"] += 1
            g["last"], g["example"] = run["run_id"], example     # the newest example
            if severity:
                g["severities"][severity] += 1
    ranked = sorted(groups.values(), key=lambda g: (-len(g["runs"]), -g["count"], g["source"], g["defect"]))
    for g in ranked:
        g["runs"], g["severities"] = len(g["runs"]), dict(g["severities"])
    return [g for g in ranked if g["runs"] >= min_runs], [g for g in ranked if g["runs"] < min_runs]


SEVERITY_FR = {"blocking": "bloquante", "corrected": "corrigée", "informative": "informative"}


def cell(text, width=110):
    text = re.sub(r"\s+", " ", str(text or "")).replace("|", "/")
    return text if len(text) <= width else text[:width - 1] + "…"


def markdown(collected, min_runs):
    out = []
    for chan, runs in collected.items():
        top, once = recurring(runs, min_runs)
        out += [f"# Défauts récurrents : {chan}", "",
                f"{len(runs)} run(s), du {runs[0]['started'][:16].replace('T', ' ')} au {runs[-1]['started'][:16].replace('T', ' ')} (UTC).", "",
                "## Les runs", "", "| Run | Sujet | Statut | Vidéo | Révisions QA | Arrêt |", "|---|---|---|---|---|---|"]
        out += [f"| {r['run_id']} | {cell(r['topic'], 60)} | {r['status']} | {'oui' if r['video'] else 'non'} | {r['revisions']} "
                f"| {cell(r['stopped_by'], 80)} |" for r in runs]
        out += ["", f"## Défauts vus dans au moins {min_runs} runs", ""]
        if top:
            out += ["| Runs | Fois | Origine | Défaut | Dernier run | Exemple |", "|---|---|---|---|---|---|"]
            for g in top:
                severities = ", ".join(f"{n} {SEVERITY_FR.get(s, s)}" for s, n in sorted(g["severities"].items()))
                defect = g["defect"] + (f" ({severities})" if severities else "")
                out.append(f"| {g['runs']}/{len(runs)} | {g['count']} | {g['source']} | {cell(defect, 90)} | {g['last']} | {cell(g['example'])} |")
        else:
            out.append("Aucun.")
        by_source = defaultdict(int)
        for g in once:
            by_source[g["source"]] += 1
        out += ["", f"## Vus dans un seul run : {len(once)}", ""]
        out += [f"- {source} : {n}" for source, n in sorted(by_source.items())] or ["Aucun."]
        out.append("")
    return "\n".join(out) if out else "Aucun run trouvé (les runs « standalone » ne sont pas comptés).\n"


def as_json(collected, min_runs):
    return {chan: {"runs": [{k: v for k, v in r.items() if k != "defects"} for r in runs],
                   "recurring": recurring(runs, min_runs)[0], "seen_once": len(recurring(runs, min_runs)[1])}
            for chan, runs in collected.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recurring defects, run after run (reads schemas/rows.json and reports.json)")
    parser.add_argument("--channel", help='only this channel, e.g. "breeze_(math)" (quote it)')
    parser.add_argument("--last", type=int, default=10, help="the last N runs of each channel (default 10)")
    parser.add_argument("--min-runs", type=int, default=2, help="seen in at least this many runs to be listed (default 2)")
    parser.add_argument("--json", action="store_true", help="JSON instead of Markdown")
    parser.add_argument("--out", help="write the report to this file instead of printing it")
    args = parser.parse_args(argv)
    collected = collect(load_json(ROWS_PATH) or [], load_json(REPORTS_PATH) or [], args.channel, max(args.last, 1))
    text = (json.dumps(as_json(collected, args.min_runs), ensure_ascii=False, indent=2) if args.json
            else markdown(collected, args.min_runs))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"report written to {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
