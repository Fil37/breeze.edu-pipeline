# Construire une pièce (guide pour un autre Claude ou un humain)

Une « pièce » est un type de composant que l'agent004 (le LLM) peut placer dans une scène, et que le
rendu (agent010) dessine et anime lui-même. Le LLM ne fournit que des **données** ; tout chiffre affiché
(somme, résultat, équilibre, période...) est **calculé par le programme**. Le texte venant du LLM est
toujours affiché en `textContent`, jamais en HTML.

Choisir sa pièce dans `docs/pieces/ORDRE.md` (sa ligne dit quelles fiches de `catalogue.json` elle
couvre ; lire ces fiches : ce qu'elle montre, ses états, sa vérification). Ne pas prendre une pièce
déjà marquée « fait » ou prise par quelqu'un d'autre.

## Les cinq endroits à toucher (suivre une pièce existante : `OSCILLATOR`, `PIE_CHART`, `TABLE`)

1. **`models/visual_brief_schema.py`**
   - le nom dans `class ComponentType` (avec un commentaire d'une ligne) ;
   - ses ports dans `COMPONENT_PORTS` (`()` si elle ne se branche pas) ;
   - sa vérification : un cas dans `phys_piece_problem` (physique) ou `simple_piece_problem`, et son nom
     dans `PHYS_PIECES` ou `SIMPLE_PIECES` ; le commentaire au-dessus décrit son `initial_state` et ses
     `set_state`. Refuser tout réglage hors bornes (le message est renvoyé au LLM : clair et court).
2. **`app/layout_solver.py`** : sa taille en pixels (`PHYS_SIZES` / `SIMPLE_SIZES`).
3. **`app/agent/agent010_html_renderer.py`**
   - le calcul en Python dans `phys_data` / `simple_data` (tout ce qui est affiché comme chiffre) ;
   - le dessin dans `buildPhys` / `buildSimple` (SVG via `sv()`, textes via `txt()`) ;
   - l'animation dans `seekPhys` / `seekSimple` : **fonction du temps t uniquement** (déterministe :
     la même image pour le même t). Helpers : `inTurn(e, "step", i)`, `stateTime(e, "clé")`,
     `shownFrom(e, "clé", t)`, `lastState(e, t, "clé")`, `arrowSvg`, `clamp`, `easeInOut`.
4. **`app/agent/agent004_visualbriefgenerator.py`**
   - sa ligne dans `STATES` (ses `set_state` et un exemple d'`initial_state`) ;
   - une règle dans le prompt (les puces « ONE ... ») : quels mots de la narration l'appellent, et ce
     qu'il ne faut pas faire à la place (icônes, disques posés à la main...).
5. **`app/agent/agent005_educationqa.py`** : ses clés dans `STATE_KEYS` (set_state) et
   `INITIAL_STATE_KEYS` (initial_state).

## Vérifier

- Un test dans `tests/` (modèle : `tests/test_physics_pieces.py`) : les chiffres calculés justes, les
  réglages faux refusés, la pièce dessinée sans erreur JS et sans `layoutConflicts`.
- Un aperçu image (modèle : le script de rendu au début de `tests/test_physics_pieces.py` / les aperçus
  dans `instance/previews/`), regardé à l'œil.
- Toute la suite : `for t in tests/test_*.py; do .venv/bin/python $t > /dev/null 2>&1 || echo "FAIL $t"; done`
  → aucune ligne FAIL.
- Mettre à jour `docs/pieces/catalogue.json` (`etat: "fait"`, `couvert_par`), `docs/pieces/ORDRE.md`
  (colonne État) et le README (une phrase dans la section des pièces).

## Règles du projet à respecter

- Ne jamais commiter : l'utilisateur fait tous les commits ; proposer un message de commit.
- Pas de clé d'API en dur ; rien d'externe dans le rendu (pas de CDN, pas d'image générée).
- Couleurs en `#RRGGBB` ou variables du thème (`var(--ink)`, `var(--accent)`...).
- Le style du code : commentaires en anglais, phrases courtes, comme le code autour.
- Travailler dans une branche à soi ; ajouter ses pièces **en un bloc** (pas d'éparpillement dans
  les fichiers) pour que la fusion avec le travail de l'autre soit simple.
