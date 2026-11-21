"""
Fluent Emoji 3D (Microsoft, MIT licence, https://github.com/microsoft/fluentui-emoji): objects drawn in relief,
shown in place of a flat Lucide icon when one fits (the user found the line icons too plain, 2026-11-21).

  png_path("droplet") -> ".../assets/fluent_3d/droplet.png"     png_path("cpu") -> None (the Lucide icon stays)

Only the images named in FLUENT_3D are kept in assets/fluent_3d/ (with the licence), so the repository stays small.
People keep their Lucide icon: an emoji person has a face and a skin colour, which a lesson does not need.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLUENT_DIR = os.path.join(BASE_DIR, "assets", "fluent_3d")

# Our icon name (Lucide's, or a component type in lower case) -> the Fluent emoji folder it comes from.
FLUENT_3D = {
    "anchor": "Anchor", "apple": "Red apple", "atom": "Atom symbol", "banknote": "Euro banknote", "bike": "Bicycle",
    "bird": "Bird", "book-open": "Open book", "box": "Package", "brain": "Brain", "briefcase": "Briefcase",
    "bug": "Lady beetle", "building": "Office building", "building-2": "Classical building", "bus": "Bus",
    "calculator": "Abacus", "car": "Automobile", "carrot": "Carrot", "cat": "Cat", "clock": "Alarm clock",
    "cloud": "Cloud", "cloud-rain": "Cloud with rain", "coffee": "Hot beverage", "compass": "Compass",
    "credit-card": "Credit card", "croissant": "Croissant", "dice-5": "Game die", "dog": "Dog", "door-closed": "Door",
    "droplet": "Droplet", "earth": "Globe showing europe-africa",
    "egg": "Egg", "elevator": "Elevator", "eye": "Eye", "factory": "Factory", "fish": "Fish",
    "flag": "Triangular flag", "flame": "Fire", "flask-conical": "Alembic", "fuel": "Fuel pump",
    "gavel": "Balance scale", "globe": "Globe with meridians", "graduation-cap": "Graduation cap",
    "hammer": "Hammer", "handshake": "Handshake", "heart": "Red heart", "heart-pulse": "Anatomical heart",
    "hospital": "Hospital", "hourglass": "Hourglass not done", "house": "House", "key": "Key", "laptop": "Laptop",
    "leaf": "Leaf fluttering in wind", "lightbulb": "Light bulb", "lock": "Locked", "magnet": "Magnet",
    "microscope": "Microscope", "milk": "Glass of milk", "moon": "Crescent moon", "mountain": "Mountain",
    "orbit": "Ringed planet", "package": "Package", "paw-print": "Paw prints", "piggy-bank": "Money bag",
    "pill": "Pill", "plane": "Airplane", "plug": "Electric plug", "rabbit": "Rabbit", "radiation": "Radioactive",
    "radio-tower": "Satellite antenna", "receipt": "Receipt", "rocket": "Rocket", "ruler": "Straight ruler",
    "satellite": "Satellite", "school": "School", "ship": "Ship", "shopping-bag": "Shopping bags",
    "shopping-basket": "Basket", "smartphone": "Mobile phone", "snail": "Snail", "snowflake": "Snowflake",
    "squirrel": "Chipmunk", "stethoscope": "Stethoscope", "store": "Convenience store", "sun": "Sun",
    "syringe": "Syringe", "tag": "Label", "telescope": "Telescope", "test-tube": "Test tube",
    "thermometer": "Thermometer", "ticket": "Ticket", "timer": "Stopwatch", "tractor": "Tractor",
    "train-front": "High-speed train", "tree-pine": "Evergreen tree", "trophy": "Trophy", "truck": "Delivery truck",
    "turtle": "Turtle", "vote": "Ballot box with ballot", "wallet": "Purse", "warehouse": "Department store",
    "waves": "Water wave", "weight": "Balance scale", "wheat": "Sheaf of rice", "wind": "Wind face",
    "wrench": "Wrench", "zap": "High voltage",
    # component types drawn as an icon
    "coins": "Coin", "bank": "Bank", "cart": "Shopping cart", "scale": "Balance scale",
    "trending_up": "Chart increasing", "trending_down": "Chart decreasing",
    # objects only Fluent draws (added to the OBJECT vocabulary): the earth sciences, life, matter
    "volcano": "Volcano", "comet": "Comet", "ringed-planet": "Ringed planet", "dna": "Dna", "microbe": "Microbe",
    "battery": "Battery", "gear": "Gear", "rock": "Rock", "wood": "Wood", "ice": "Ice", "tornado": "Tornado",
    "rainbow": "Rainbow", "cloud-lightning": "Cloud with lightning", "sun-cloud": "Sun behind cloud",
    "lungs": "Lungs", "bone": "Bone", "tooth": "Tooth", "petri-dish": "Petri dish", "seedling": "Seedling",
    "full-moon": "Full moon", "milky-way": "Milky way", "fog": "Fog", "bubbles": "Bubbles", "brick": "Brick",
    "coin": "Coin", "money-bag": "Money bag", "world-map": "World map", "bar-chart": "Bar chart",
}
FLUENT_ONLY = tuple(sorted(("volcano", "comet", "ringed-planet", "dna", "microbe", "battery", "gear", "rock", "wood",
                            "ice", "tornado", "rainbow", "cloud-lightning", "sun-cloud", "lungs", "bone", "tooth",
                            "petri-dish", "seedling", "full-moon", "milky-way", "fog", "bubbles", "brick")))


def file_name(folder):
    """The Fluent folder "Cloud with rain" -> its image "cloud_with_rain_3d.png" (Fluent's own naming)."""
    return folder.lower().replace(" ", "_") + "_3d.png"


def png_path(name):
    """The local 3D image for an icon name or a component type, or None when there is none."""
    key = str(name).strip().lower()
    folder = FLUENT_3D.get(key) or FLUENT_3D.get(key.replace("_", "-"))
    if not folder:
        return None
    path = os.path.join(FLUENT_DIR, file_name(folder))
    return path if os.path.isfile(path) else None
