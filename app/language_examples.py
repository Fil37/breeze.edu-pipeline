"""
The examples of a language channel (German taught in French), read by the program:

  foreign_quotes(text, language, words)  the « quotes » of `text` written in that language (not the
                                         French meanings, « je reste à la maison »)
  is_foreign_word(word, language, words) a word of that language outside quotes ("weil", "bleibe")
  order_problem(words, order)            why a German word order is wrong ("weil ich bin krank": the
                                         conjugated verb is not at the end), None when it is right

Used by the voice (app/tts_manager: the examples said apart, in German), the script (agent003: one
example per scene) and the storyboard (agent004: a wrong order marked wrong, the example said is the
one shown).
"""

import re

WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")

FUNCTION_WORDS = {
    "de": set("ich du er sie es wir ihr mich mir dich dir sich uns euch mein dein sein unser der die das den dem "
              "ein eine einen einem einer kein keine nicht und oder aber denn sondern weil dass wenn ob obwohl als "
              "bevor nachdem während damit seit seitdem bis falls sodass trotzdem deshalb deswegen dann also "
              "bin bist ist sind seid war waren habe hast hat haben habt hatte werde wirst wird werden kann kannst "
              "können muss musst müssen will willst wollen soll sollen darf dürfen möchte möchten "
              "zu zum zur mit von vom bei beim nach aus auf für ohne gegen um über unter vor hinter neben zwischen "
              "heute morgen gestern jetzt hier dort schon noch sehr gern gerne auch nur immer nie oft "
              # questions and prepositions said alone (the German run 5 of 2026-11-20: « Wo? » and « Wohin? » were
              # said by the French voice); "in", "an" count in quotes only (FRENCH_TOO outside)
              "wo wohin woher wann warum wie wer was welche welcher welches in an im am ins ans trotz wegen "
              "innerhalb außerhalb statt anstatt durch entlang gegenüber seit".split())}
# Words a foreign lexicon shares with French: outside quotes, they are French.
FRENCH_TOO = set("es an in so des du de le la les en et un une on ou il a à est position film hotel restaurant "
                 "taxi bus sport radio chance garage normal information international".split())
# French words that tell a French quote (a meaning) from a German one.
FRENCH_COMMON = set("je tu il elle on nous vous ils elles le la les un une des du de et ou que qui est suis sont "
                    "parce pas ne ce cette mon ma mes à au aux en dans pour avec sur reste aujourd maison malade".split())

# German clause openers that send the conjugated verb to the end, and the ones that change nothing.
SUBORDINATORS = set("weil dass wenn ob obwohl als bevor nachdem während damit seit seitdem bis falls sodass da "
                    "wie wo warum wer was ehe sobald solange indem".split())
COORDINATORS = set("und oder aber denn sondern".split())
# Question words also open clauses ("..., wo ich wohne") but a label naming them asks the case's question (Wo? Wohin?).
QUESTION_WORDS = set("wo wohin woher wie warum wer was wann".split())


def lexicon(language, words=()):
    return FUNCTION_WORDS.get(language, set()) | {str(w).lower() for w in words if w}


def foreign_quotes(text, language, words=()):
    """[(start, end, quote)] of the « quotes » in `text` with more words of `language` (its function
    words and `words`, the video's own examples) than French ones; start/end inside the « »."""
    known, found = lexicon(language, words), []
    for quote in re.finditer(r"«([^«»]*)»", str(text or "")):
        tokens = [t.lower() for t in WORD.findall(quote.group(1))]
        if tokens and sum(t in known for t in tokens) > sum(t in FRENCH_COMMON for t in tokens):
            found.append((quote.start(1), quote.end(1), quote.group(1).strip()))
    return found


def is_foreign_word(word, language, words=()):
    return word.lower() in lexicon(language, words) and word.lower() not in FRENCH_TOO


def tokens(text):
    """The words of a sentence, lowercased, for comparing two examples ("Weil ich krank bin," = "weil ich krank bin")."""
    return tuple(t.lower() for t in WORD.findall(str(text or "")))


def clauses(words, order):
    """The clauses of a SENTENCE in that order: lists of (text, role), cut at its commas and full stops
    ("Ich bin müde. Trotzdem lerne ich.": two)."""
    out, current = [], []
    for i in order:
        if not (isinstance(i, int) and 0 <= i < len(words)):
            continue
        word = words[i] if isinstance(words[i], dict) else {}
        text, role = str(word.get("text") or ""), str(word.get("role") or "other")
        if role == "punct":
            if text.strip() in (",", ".", ";", "!", "?") and current:
                out.append(current)
                current = []
            continue
        current.append((text, role))
    if current:
        out.append(current)
    return out


def order_problem(words, order):
    """Why this German word order is wrong, None when it is right (or the program cannot tell). Two rules,
    from the roles: in a clause opened by weil / dass / wenn... the clause ends on a verb; in a main clause
    the first verb is the second part (words of one role in a row make one part: "zu Hause"), the first
    one after a clause in front ("Weil ich krank bin, bleibe ich..."). A question or an order (no subject
    before the verb) is left alone."""
    before = None                      # the clause in front: "sub" or "main"
    for clause in clauses(words, order):
        if clause and clause[0][0].lower() in COORDINATORS:
            clause = clause[1:]
        if not clause:
            continue
        said = " ".join(text for text, _ in clause)
        if clause[0][0].lower() in SUBORDINATORS:
            if any(role == "verb" for _, role in clause) and clause[-1][1] != "verb":
                verb = next(text for text, role in clause if role == "verb")
                return f"« {said} »: after « {clause[0][0]} » the conjugated verb « {verb} » goes to the end"
            before = "sub"
            continue
        parts = []
        for text, role in clause:
            if parts and parts[-1][1] == role and role != "verb":
                parts[-1] = (parts[-1][0] + " " + text, role)
            else:
                parts.append((text, role))
        first_verb = next((i for i, (_, role) in enumerate(parts) if role == "verb"), None)
        if first_verb is not None:
            place = 0 if before == "sub" else 1
            subject_first = any(role == "subject" for _, role in parts[:first_verb])
            if first_verb > place and (subject_first or before == "sub"):
                verb = parts[first_verb][0]
                where = "right after the clause in front" if before == "sub" else "in second place"
                return f"« {said} »: the conjugated verb « {verb} » goes {where}"
        before = "main"
    return None
