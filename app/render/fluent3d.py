"""
Fluent Emoji 3D (Microsoft, MIT licence, https://github.com/microsoft/fluentui-emoji): objects drawn in relief,
shown in place of a flat Lucide icon when one fits (the user found the line icons too plain, 2026-11-21).

  png_path("droplet") -> ".../assets/fluent_3d/droplet.png"     png_path("cpu") -> None (the Lucide icon stays)

Only the images named in FLUENT_3D are kept in app/assets/fluent_3d/ (with the licence), so the repository stays small.
People keep their Lucide icon: an emoji person has a face and a skin colour, which a lesson does not need.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLUENT_DIR = os.path.join(BASE_DIR, "app", "assets", "fluent_3d")

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
# Everyday vocabulary (the German channel's words), animals, places, weather...: Fluent-only objects too, by theme
# in app/models/visual_brief_schema.py OBJECT_ICONS. Ear and nose are not in 3D in Fluent: left out.
FLUENT_3D_MORE = {
    "bread": "Bread", "baguette-bread": "Baguette bread", "pretzel": "Pretzel", "bagel": "Bagel",
    "cheese-wedge": "Cheese wedge", "butter": "Butter", "green-apple": "Green apple", "banana": "Banana",
    "grapes": "Grapes", "strawberry": "Strawberry", "cherries": "Cherries", "lemon": "Lemon",
    "tangerine": "Tangerine", "pear": "Pear", "peach": "Peach", "pineapple": "Pineapple",
    "watermelon": "Watermelon", "melon": "Melon", "kiwi-fruit": "Kiwi fruit", "coconut": "Coconut",
    "tomato": "Tomato", "potato": "Potato", "onion": "Onion", "garlic": "Garlic", "cucumber": "Cucumber",
    "broccoli": "Broccoli", "ear-of-corn": "Ear of corn", "hot-pepper": "Hot pepper",
    "bell-pepper": "Bell pepper", "eggplant": "Eggplant", "avocado": "Avocado", "leafy-green": "Leafy green",
    "green-salad": "Green salad", "peanuts": "Peanuts", "chestnut": "Chestnut", "pizza": "Pizza",
    "hamburger": "Hamburger", "french-fries": "French fries", "hot-dog": "Hot dog", "sandwich": "Sandwich",
    "spaghetti": "Spaghetti", "steaming-bowl": "Steaming bowl", "pot-of-food": "Pot of food",
    "cooked-rice": "Cooked rice", "meat-on-bone": "Meat on bone", "poultry-leg": "Poultry leg",
    "cut-of-meat": "Cut of meat", "bacon": "Bacon", "cooking": "Cooking", "pancakes": "Pancakes",
    "waffle": "Waffle", "shortcake": "Shortcake", "birthday-cake": "Birthday cake", "cupcake": "Cupcake",
    "pie": "Pie", "cookie": "Cookie", "doughnut": "Doughnut", "chocolate-bar": "Chocolate bar",
    "candy": "Candy", "lollipop": "Lollipop", "honey-pot": "Honey pot", "ice-cream": "Ice cream",
    "soft-ice-cream": "Soft ice cream", "teacup-without-handle": "Teacup without handle", "teapot": "Teapot",
    "beer-mug": "Beer mug", "wine-glass": "Wine glass", "cup-with-straw": "Cup with straw",
    "beverage-box": "Beverage box", "tumbler-glass": "Tumbler glass", "salt": "Salt",
    "canned-food": "Canned food", "fork-and-knife": "Fork and knife", "spoon": "Spoon",
    "kitchen-knife": "Kitchen knife", "bowl-with-spoon": "Bowl with spoon",
    "shallow-pan-of-food": "Shallow pan of food", "cow": "Cow", "pig": "Pig", "horse": "Horse", "ewe": "Ewe",
    "ram": "Ram", "goat": "Goat", "chicken": "Chicken", "rooster": "Rooster", "duck": "Duck", "goose": "Goose",
    "owl": "Owl", "eagle": "Eagle", "penguin": "Penguin", "dove": "Dove", "parrot": "Parrot", "swan": "Swan",
    "flamingo": "Flamingo", "frog": "Frog", "snake": "Snake", "lizard": "Lizard", "crocodile": "Crocodile",
    "whale": "Whale", "dolphin": "Dolphin", "shark": "Shark", "octopus": "Octopus", "crab": "Crab",
    "shrimp": "Shrimp", "squid": "Squid", "jellyfish": "Jellyfish", "tropical-fish": "Tropical fish",
    "honeybee": "Honeybee", "butterfly": "Butterfly", "ant": "Ant", "spider": "Spider",
    "spider-web": "Spider web", "mosquito": "Mosquito", "fly": "Fly", "worm": "Worm", "elephant": "Elephant",
    "lion": "Lion", "tiger": "Tiger", "bear": "Bear", "polar-bear": "Polar bear", "panda": "Panda",
    "koala": "Koala", "monkey": "Monkey", "gorilla": "Gorilla", "giraffe": "Giraffe", "zebra": "Zebra",
    "camel": "Camel", "kangaroo": "Kangaroo", "hedgehog": "Hedgehog", "fox": "Fox", "wolf": "Wolf",
    "deer": "Deer", "mouse": "Mouse", "rat": "Rat", "hamster": "Hamster", "bat": "Bat",
    "hippopotamus": "Hippopotamus", "rhinoceros": "Rhinoceros", "sauropod": "Sauropod", "t-rex": "T-rex",
    "mammoth": "Mammoth", "bison": "Bison", "beaver": "Beaver", "otter": "Otter", "sloth": "Sloth",
    "raccoon": "Raccoon", "badger": "Badger", "moose": "Moose", "seal": "Seal", "feather": "Feather",
    "spiral-shell": "Spiral shell", "coral": "Coral", "nest-with-eggs": "Nest with eggs",
    "motorcycle": "Motorcycle", "motor-scooter": "Motor scooter", "kick-scooter": "Kick scooter",
    "taxi": "Taxi", "police-car": "Police car", "ambulance": "Ambulance", "fire-engine": "Fire engine",
    "racing-car": "Racing car", "pickup-truck": "Pickup truck", "articulated-lorry": "Articulated lorry",
    "tram": "Tram", "metro": "Metro", "locomotive": "Locomotive", "railway-car": "Railway car",
    "helicopter": "Helicopter", "small-airplane": "Small airplane", "sailboat": "Sailboat", "canoe": "Canoe",
    "speedboat": "Speedboat", "ferry": "Ferry", "parachute": "Parachute",
    "vertical-traffic-light": "Vertical traffic light", "stop-sign": "Stop sign",
    "construction": "Construction", "motorway": "Motorway", "railway-track": "Railway track",
    "bus-stop": "Bus stop", "station": "Station", "chair": "Chair", "bed": "Bed",
    "couch-and-lamp": "Couch and lamp", "window": "Window", "mirror": "Mirror", "toilet": "Toilet",
    "shower": "Shower", "bathtub": "Bathtub", "soap": "Soap", "toothbrush": "Toothbrush", "sponge": "Sponge",
    "broom": "Broom", "bucket": "Bucket", "roll-of-paper": "Roll of paper", "scissors": "Scissors",
    "pencil": "Pencil", "pen": "Pen", "crayon": "Crayon", "paintbrush": "Paintbrush", "paperclip": "Paperclip",
    "pushpin": "Pushpin", "triangular-ruler": "Triangular ruler", "notebook": "Notebook", "books": "Books",
    "closed-book": "Closed book", "newspaper": "Newspaper", "envelope": "Envelope", "calendar": "Calendar",
    "spiral-calendar": "Spiral calendar", "clipboard": "Clipboard", "memo": "Memo",
    "file-folder": "File folder", "backpack": "Backpack", "glasses": "Glasses", "sunglasses": "Sunglasses",
    "umbrella": "Umbrella", "watch": "Watch", "ring": "Ring", "gem-stone": "Gem stone", "necktie": "Necktie",
    "t-shirt": "T-shirt", "jeans": "Jeans", "dress": "Dress", "coat": "Coat", "scarf": "Scarf",
    "gloves": "Gloves", "socks": "Socks", "running-shoe": "Running shoe", "billed-cap": "Billed cap",
    "top-hat": "Top hat", "crown": "Crown", "handbag": "Handbag", "luggage": "Luggage", "bell": "Bell",
    "candle": "Candle", "flashlight": "Flashlight", "television": "Television", "radio": "Radio",
    "telephone": "Telephone", "desktop-computer": "Desktop computer", "keyboard": "Keyboard",
    "computer-mouse": "Computer mouse", "printer": "Printer", "camera": "Camera",
    "video-camera": "Video camera", "headphone": "Headphone", "microphone": "Microphone",
    "loudspeaker": "Loudspeaker", "floppy-disk": "Floppy disk", "optical-disk": "Optical disk",
    "joystick": "Joystick", "video-game": "Video game", "hourglass-done": "Hourglass done",
    "teddy-bear": "Teddy bear", "balloon": "Balloon", "wrapped-gift": "Wrapped gift", "kite": "Kite",
    "puzzle-piece": "Puzzle piece", "chess-pawn": "Chess pawn", "soccer-ball": "Soccer ball",
    "basketball": "Basketball", "tennis": "Tennis", "musical-keyboard": "Musical keyboard", "guitar": "Guitar",
    "violin": "Violin", "trumpet": "Trumpet", "drum": "Drum", "saxophone": "Saxophone",
    "musical-note": "Musical note", "toolbox": "Toolbox", "screwdriver": "Screwdriver",
    "nut-and-bolt": "Nut and bolt", "axe": "Axe", "carpentry-saw": "Carpentry saw", "ladder": "Ladder",
    "hook": "Hook", "chains": "Chains", "link": "Link",
    "magnifying-glass-tilted-left": "Magnifying glass tilted left", "shield": "Shield",
    "fire-extinguisher": "Fire extinguisher", "hammer-and-wrench": "Hammer and wrench", "clamp": "Clamp",
    "pick": "Pick", "oil-drum": "Oil drum", "old-key": "Old key", "unlocked": "Unlocked", "scroll": "Scroll",
    "ledger": "Ledger", "placard": "Placard", "wastebasket": "Wastebasket", "megaphone": "Megaphone",
    "speech-balloon": "Speech balloon", "thought-balloon": "Thought balloon",
    "dollar-banknote": "Dollar banknote", "pound-banknote": "Pound banknote", "yen-banknote": "Yen banknote",
    "money-with-wings": "Money with wings", "shopping-cart": "Shopping cart",
    "admission-tickets": "Admission tickets", "sports-medal": "Sports medal",
    "1st-place-medal": "1st place medal", "bullseye": "Bullseye", "e-mail": "E-mail",
    "house-with-garden": "House with garden", "houses": "Houses", "hut": "Hut",
    "derelict-house": "Derelict house", "castle": "Castle", "church": "Church", "stadium": "Stadium",
    "hotel": "Hotel", "post-office": "Post office", "building-construction": "Building construction",
    "tent": "Tent", "camping": "Camping", "fountain": "Fountain", "bridge-at-night": "Bridge at night",
    "cityscape": "Cityscape", "national-park": "National park", "desert": "Desert",
    "desert-island": "Desert island", "beach-with-umbrella": "Beach with umbrella",
    "snow-capped-mountain": "Snow-capped mountain", "sunrise": "Sunrise", "sunset": "Sunset",
    "night-with-stars": "Night with stars", "ferris-wheel": "Ferris wheel", "roller-coaster": "Roller coaster",
    "playground-slide": "Playground slide", "sun-behind-small-cloud": "Sun behind small cloud",
    "sun-behind-rain-cloud": "Sun behind rain cloud", "cloud-with-snow": "Cloud with snow",
    "cloud-with-lightning-and-rain": "Cloud with lightning and rain",
    "umbrella-with-rain-drops": "Umbrella with rain drops", "snowman": "Snowman", "cyclone": "Cyclone",
    "star": "Star", "glowing-star": "Glowing star", "shooting-star": "Shooting star", "new-moon": "New moon",
    "first-quarter-moon": "First quarter moon", "last-quarter-moon": "Last quarter moon",
    "waxing-crescent-moon": "Waxing crescent moon", "waning-crescent-moon": "Waning crescent moon",
    "waxing-gibbous-moon": "Waxing gibbous moon", "waning-gibbous-moon": "Waning gibbous moon",
    "globe-showing-americas": "Globe showing americas",
    "globe-showing-asia-australia": "Globe showing asia-australia", "sunflower": "Sunflower", "rose": "Rose",
    "tulip": "Tulip", "blossom": "Blossom", "cherry-blossom": "Cherry blossom", "hibiscus": "Hibiscus",
    "herb": "Herb", "four-leaf-clover": "Four leaf clover", "maple-leaf": "Maple leaf",
    "fallen-leaf": "Fallen leaf", "cactus": "Cactus", "palm-tree": "Palm tree",
    "deciduous-tree": "Deciduous tree", "potted-plant": "Potted plant", "mushroom": "Mushroom",
    "sweat-droplets": "Sweat droplets", "drop-of-blood": "Drop of blood",
    "adhesive-bandage": "Adhesive bandage", "x-ray": "X-ray", "anatomical-heart": "Anatomical heart",
    "robot": "Robot", "mechanical-arm": "Mechanical arm", "crutch": "Crutch",
    "medical-symbol": "Medical symbol", "biohazard": "Biohazard", "low-battery": "Low battery",
    "timer-clock": "Timer clock", "satellite-antenna": "Satellite antenna",
    "hammer-and-pick": "Hammer and pick", "check-mark-button": "Check mark button", "cross-mark": "Cross mark",
    "warning": "Warning", "prohibited": "Prohibited", "red-question-mark": "Red question mark",
    "red-exclamation-mark": "Red exclamation mark",
}
FLUENT_3D.update(FLUENT_3D_MORE)
FLUENT_ONLY_BASE = tuple(sorted(("volcano", "comet", "ringed-planet", "dna", "microbe", "battery", "gear", "rock", "wood",
                            "ice", "tornado", "rainbow", "cloud-lightning", "sun-cloud", "lungs", "bone", "tooth",
                            "petri-dish", "seedling", "full-moon", "milky-way", "fog", "bubbles", "brick")))

FLUENT_ONLY = tuple(sorted(FLUENT_ONLY_BASE + tuple(FLUENT_3D_MORE)))


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
