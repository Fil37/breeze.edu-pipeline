"""
Linear systems written in LaTeX (EQUATION_STEPS solving a system by the pivot de Gauss), read and worked
out exactly (fractions):
  - linear_equations(latex): the equations of a line, "\\begin{cases} 2x+y-z=8 \\\\ ... \\end{cases}" or
    "z=3,\\ y=2", as [{unknown: coefficient, "": constant moved left}], None when one is not linear
  - row_operations(before, after): how each changed row was made, L_i <- a L_i + b L_j (or a swap)
  - operation_detail(before, after): that worked out term by term, as LaTeX lines for the page
agent004 checks every line keeps the first system's solution (gauss_problems); agent010 shows the detail
of a reduction beside the steps.
"""

import re
from fractions import Fraction

LATEX_NOISE = re.compile(r"\\begin\{[a-z*]+\}|\\end\{[a-z*]+\}|\\[,;:! ]|&|\\left|\\right|~")
LATEX_FRACTION = re.compile(r"\\[dt]?frac\s*\{\s*(\d+)\s*\}\s*\{\s*(\d+)\s*\}")
LINEAR_TERM = re.compile(r"\s*([+-])?\s*(\d+(?:[.,]\d+)?(?:/\d+)?)?\s*(?:\\cdot|\\times)?\s*([a-z])?\s*")


def number(text):
    if "/" in text:
        top, bottom = text.split("/")
        return Fraction(int(top), int(bottom))
    return Fraction(text.replace(",", "."))


def linear_side(text):
    """{unknown or "": coefficient} for one side ("2x + y - z"), or None when not linear."""
    found, at = {}, 0
    text = text.strip()
    while at < len(text):
        m = LINEAR_TERM.match(text, at)
        if not m or m.end() == at or not (m.group(2) or m.group(3)):
            return None
        value = (number(m.group(2)) if m.group(2) else Fraction(1)) * (-1 if m.group(1) == "-" else 1)
        found[m.group(3) or ""] = found.get(m.group(3) or "", 0) + value
        at = m.end()
    return found if found else None


def linear_equations(latex):
    """The linear equations of a line ([{unknown: coefficient}, "" the constant moved left]), None if one is not."""
    text = LATEX_FRACTION.sub(r"\1/\2", str(latex).replace("\\\\", "\n"))
    text = LATEX_NOISE.sub(" ", text).replace("−", "-")
    equations = []
    for row in re.split(r"\n|[;,](?=\s*[a-z]\s*=)", text):
        if not row.strip():
            continue
        if row.count("=") != 1:
            return None
        left, right = (linear_side(side) for side in row.split("="))
        if left is None or right is None:
            return None
        for k, v in right.items():
            left[k] = left.get(k, 0) - v
        equations.append(left)
    return equations or None


def unknowns_of(*systems):
    return sorted({k for system in systems for eq in system for k in eq if k})


def row(eq, unknowns):
    """An equation as its coefficients then its right-hand side."""
    return [Fraction(eq.get(u, 0)) for u in unknowns] + [-Fraction(eq.get("", 0))]


def row_operations(before, after):
    """How each changed row of `after` comes from `before`: [(i, a, j, b)] for L_i <- a L_i + b L_j (j None:
    a scaling), ("swap", i, j) for L_i <-> L_j; None when a row is not such a combination."""
    if not before or not after or len(before) != len(after):
        return None
    unknowns = unknowns_of(before, after)
    old, new = [row(e, unknowns) for e in before], [row(e, unknowns) for e in after]
    ops = []
    for i, target in enumerate(new):
        if target == old[i]:
            continue
        swap = next((j for j in range(len(old)) if j != i and old[j] == target and new[j] == old[i]), None)
        if swap is not None:
            if ("swap", swap, i) not in ops:
                ops.append(("swap", i, swap))
            continue
        found = None
        for j in [None] + [j for j in range(len(old)) if j != i]:
            found = combination(old[i], None if j is None else old[j], target)
            if found:
                ops.append((i, found[0], j, found[1]))
                break
        if not found:
            return None
    return ops


def combination(a_row, b_row, target):
    """(a, b) with target = a·a_row + b·b_row (b 0 with no b_row), exactly, or None."""
    n = len(target)
    if b_row is None:
        k = next((c for c in range(n) if a_row[c] != 0), None)
        a = target[k] / a_row[k] if k is not None else None
        return (a, Fraction(0)) if a is not None and all(target[c] == a * a_row[c] for c in range(n)) else None
    for p in range(n):                      # two columns that pin a and b down, then every column checked
        for q in range(p + 1, n):
            det = a_row[p] * b_row[q] - a_row[q] * b_row[p]
            if det == 0:
                continue
            a = (target[p] * b_row[q] - target[q] * b_row[p]) / det
            b = (a_row[p] * target[q] - a_row[q] * target[p]) / det
            if b != 0 and all(target[c] == a * a_row[c] + b * b_row[c] for c in range(n)):
                return a, b
            return None
    return None


def tex_number(value, sign=False):
    """A coefficient in LaTeX: 3, -\\tfrac{3}{2}; with sign, its + or - in front."""
    value = Fraction(value)
    text = str(abs(value.numerator)) if value.denominator == 1 else rf"\tfrac{{{abs(value.numerator)}}}{{{value.denominator}}}"
    return (("-" if value < 0 else "+") + " " if sign else ("-" if value < 0 else "")) + text


def tex_row(values, unknowns, zeros=()):
    """A row as an equation: 0x terms left out but for the unknowns in `zeros` (just eliminated: shown as 0x)."""
    terms = []
    for c, u in zip(values, unknowns):
        if c == 0 and u not in zeros:
            continue
        mag = "" if abs(c) == 1 else tex_number(abs(c))
        head = ("-" if c < 0 else "") if not terms else ("- " if c < 0 else "+ ")
        terms.append(f"{head}{mag}{u}")
    return (" ".join(terms) or "0") + f" = {tex_number(values[-1])}"


def tex_factor(value, name):
    """a·L_i in LaTeX: L_2, -L_2, \\tfrac{3}{2}L_1."""
    value = Fraction(value)
    return ("-" if value == -1 else "" if value == 1 else tex_number(value)) + name


def operation_detail(before, after):
    """Each changed row worked out term by term, for the page: [{"title": text, "lines": [LaTeX]}], or None."""
    ops = row_operations(before, after)
    if not ops:
        return None
    unknowns = unknowns_of(before, after)
    old, new = [row(e, unknowns) for e in before], [row(e, unknowns) for e in after]
    out = []
    for op in ops:
        if op[0] == "swap":
            _, i, j = op
            out.append({"title": f"L{i + 1} ↔ L{j + 1}", "lines": [rf"L_{i + 1} \leftrightarrow L_{j + 1}"]})
            continue
        i, a, j, b = op
        name = f"L_{i + 1}"
        if j is None:
            out.append({"title": f"L{i + 1} ← {plain_factor(a, f'L{i + 1}')}",
                        "lines": [rf"{tex_factor(a, name)} :\ {tex_row([a * c for c in old[i]], unknowns)}"]})
            continue
        gone = [u for k, u in enumerate(unknowns) if new[i][k] == 0 and old[i][k] != 0]
        lines = [rf"{tex_factor(a, name)} :\ {tex_row([a * c for c in old[i]], unknowns)}",
                 rf"{'+' if b > 0 else '-'}\ {tex_factor(abs(b), f'L_{j + 1}')} :\ {tex_row([abs(b) * c for c in old[j]], unknowns)}",
                 rf"= \ {tex_row(new[i], unknowns, zeros=gone)}"]
        if gone:
            lines.append(", ".join(gone) + (r"\text{ s'annule}" if len(gone) == 1 else r"\text{ s'annulent}"))
        out.append({"title": f"L{i + 1} ← {plain_factor(a, f'L{i + 1}')} {'+' if b > 0 else '−'} {plain_factor(abs(b), f'L{j + 1}')}",
                    "lines": lines})
    return out


def plain_factor(value, name):
    """a·L_i as plain text (a note's title): L2, −L2, 3/2 L1."""
    value = Fraction(value)
    if value == 1:
        return name
    if value == -1:
        return "−" + name
    return f"{'−' if value < 0 else ''}{abs(value)} {name}"
