"""
Real-looking electronic parts (Fritzing parts library, breadboard view, CC BY-SA 3.0, https://fritzing.org):
the REAL_PART piece shows one of them as it looks in the hand (2026-11-21: the user accepted the licence for the
electronics channel only). A video that shows one is credited and offered under CC BY-SA 3.0 in its description
(agent007).

  part_svg("resistor", 4700) -> the resistor's SVG, its bands yellow, violet, red (worked out here, never by the LLM)
  resistor_bands(4700)       -> {"digits": [4, 7], "multiplier": 2, "colours": [...], "names": ["jaune", ...]}

The files are copied as they are from fritzing-parts (svg/core/breadboard), checked to hold nothing active.
"""

import math
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRITZING_DIR = os.path.join(BASE_DIR, "app", "assets", "fritzing")
CREDIT = ("Composants dessinés avec Fritzing (fritzing.org, CC BY-SA 3.0). Cette vidéo est donc proposée sous "
          "licence CC BY-SA 3.0 : https://creativecommons.org/licenses/by-sa/3.0/deed.fr")

# part -> French name (for the prompt and the label when none is given)
REAL_PARTS = {
    "resistor": "Résistance", "led": "LED", "capacitor": "Condensateur céramique", "electrolytic": "Condensateur chimique",
    "transistor": "Transistor NPN", "diode": "Diode", "battery-9v": "Pile 9 V", "battery-aa": "Pile AA",
    "potentiometer": "Potentiomètre", "switch": "Interrupteur", "pushbutton": "Bouton-poussoir", "motor": "Moteur",
    "ldr": "Photorésistance", "arduino-uno": "Arduino Uno", "breadboard": "Plaque d'essai",
}

# the colour code (IEC 60062): digit -> (colour, French name); multipliers 10^-2 and 10^-1 are silver and gold
DIGIT_COLOURS = [("#111111", "noir"), ("#8A3D06", "marron"), ("#C40808", "rouge"), ("#F97316", "orange"),
                 ("#FACC15", "jaune"), ("#16A34A", "vert"), ("#2563EB", "bleu"), ("#7C3AED", "violet"),
                 ("#9CA3AF", "gris"), ("#F8FAFC", "blanc")]
MULTIPLIER_COLOURS = {-2: ("#C0C0C0", "argent"), -1: ("#C9A227", "or")}
TOLERANCE = ("or", 5)        # the drawing's fourth band, kept: ± 5 %
UNSAFE = re.compile(r"<script|javascript:|\son[a-z]+\s*=|<foreignObject|<!ENTITY|href\s*=\s*[\"']https?:", re.I)


BAND_WORDS = re.compile(r"\b(?:noir|marron|brun|rouge|orange|jaune|vert|bleu|violet|gris|blanc|argent|or|doré)\b", re.I)


def band_colours_named(text):
    """True when a text names two colours of the resistor code or more (it reads the bands)."""
    return len(BAND_WORDS.findall(str(text or ""))) >= 2


def resistor_bands(value):
    """The 4-band code of a resistance in ohms, or None when it has more than two significant digits or is out of
    the code's range (0,1 Ω to 99 GΩ)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.1 <= value < 1e11:
        return None
    exponent = math.floor(math.log10(value)) - 1            # 4700 -> 47 x 10^2
    digits = round(value / 10 ** exponent)
    if digits == 100:                                       # 99.99... rounded up
        digits, exponent = 10, exponent + 1
    if abs(digits * 10 ** exponent - value) > 1e-9 * value or not -2 <= exponent <= 9:
        return None
    d1, d2 = divmod(digits, 10)
    colour, name = MULTIPLIER_COLOURS.get(exponent) or DIGIT_COLOURS[exponent]
    return {"digits": [d1, d2], "multiplier": exponent,
            "colours": [DIGIT_COLOURS[d1][0], DIGIT_COLOURS[d2][0], colour],
            "names": [DIGIT_COLOURS[d1][1], DIGIT_COLOURS[d2][1], name, TOLERANCE[0]]}


def nearest_two_digits(value):
    """A close resistance the code can show (two significant digits), for the message sent back."""
    if not isinstance(value, (int, float)) or value <= 0:
        return 220
    exponent = math.floor(math.log10(value)) - 1
    return round(value / 10 ** exponent) * 10 ** exponent


def ohms_text(value):
    """4700 -> "4,7 kΩ", 220 -> "220 Ω", 1e6 -> "1 MΩ" (French decimal comma)."""
    for factor, prefix in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, "")):
        if value >= factor or factor == 1:
            number = value / factor
            text = f"{number:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"{text} {prefix}Ω"


def part_svg(part, value=None):
    """The part's SVG text, a resistor's bands coloured from its value. None for an unknown part."""
    if part not in REAL_PARTS:
        return None
    with open(os.path.join(FRITZING_DIR, f"{part}.svg"), encoding="utf-8") as f:
        text = f.read()
    if UNSAFE.search(text):                 # never expected: the files are checked when copied
        return None
    bands = resistor_bands(value) if part == "resistor" else None
    if bands:
        for band_id, colour in zip(("band_1_st", "band_2_nd", "band_rd_multiplier"), bands["colours"]):
            text = re.sub(r'(<[^>]*id="%s"[^>]*?fill=")[^"]*(")' % band_id, r"\g<1>%s\g<2>" % colour, text)
            text = re.sub(r'(<[^>]*fill=")[^"]*("[^>]*id="%s")' % band_id, r"\g<1>%s\g<2>" % colour, text)
    return text


def view_box(text):
    """The SVG's width / height ratio, from its viewBox (1 when there is none)."""
    match = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', text or "")
    return float(match.group(1)) / float(match.group(2)) if match and float(match.group(2)) else 1.0
