# breeze

One Python process, nine agents (all nine per channel, agent009 shared), four channels. Each channel picks a common misconception
in its domain and turns it into a 90–180 s animated video, narrated in French, that ends on an
"aha moment": `breeze_(electronics)`, `breeze_(physics)`, `breeze_(math)`, `breeze_(economics)`.

Third-party components kept in the repository (KaTeX, Lucide icons, the Inter / Fira Code / Space
Grotesk fonts) and their licenses: `THIRD_PARTY_NOTICES.md`.

| Order | Agent | Writes |
|-------|-------|--------|
| 1st, once per cycle | `agent009_analyticsreader` | `instance/analytics.json` |
| then per channel | `agent001_conceptresearcher` | `instance/<channel>/research.json` |
| | `agent002_curriculumsimplifier` | `outline.json` |
| | `agent003_scriptwriter` | `script.json` (narration per scene) |
| | `agent004_visualbriefgenerator` | `storyboard.json` (one validated visual brief per scene) |
| | `agent005_educationqa` | `qa.json`, and corrects `storyboard.json` (can send work back to 003 or 004, max 3 times) |
| | `agent010_html_renderer` (a browser draws each frame) | `video.mp4` + `render_manifest.json` |
| | `agent007_metadatagenerator` | `metadata.json` |
| | `agent008_platformpublisher` | rows in `schemas/rows.json` |

Each channel runs nine agents; agent010 renders every video. The Manim renderer (agent006) was
retired on 2026-10-31: its code is kept in `archive/manim/` (see its README), out of the pipeline.

`agent000_breeze.py` is the orchestrator. It is the only writer of `schemas/reports.json`,
`instance/breeze.db` and `instance/breeze.json`.

Statuses: `healthy` (green), `not_healthy` (finished with a warning, yellow),
`revision_needed` (QA sent it back, orange), `critical` (failed: the channel stops, red),
`not_run` (did not run because an earlier agent was critical, grey), `skipped` (left out on purpose
with `--skip-agents`, grey dashed outline; it does not lower the run's overall status).

## Install and run

System packages: **ffmpeg** (with `ffprobe`) and the DejaVu fonts (the error screen). The voice
(ElevenLabs or edge-tts) and the first download of KaTeX need internet access (the icons are in
`assets/icons`). The renderer (agent010) needs a Chromium for Playwright: run
`playwright install chromium` once after `pip install`.

```bash
cd L_breeze
python3 -m venv .venv && source .venv/bin/activate   # ./run calls `python`: keep the venv active
pip install -r requirements.txt
cp .env.example .env                # fill in only the keys you use

./run                               # one full cycle, all enabled channels
python web/app.py                   # dashboard on http://127.0.0.1:5000
```

The orchestrator takes three optional flags (without them it runs every enabled channel and every agent):

```bash
python app/agent/agent000_breeze.py --channel "breeze_(electronics)"            # only this channel
python app/agent/agent000_breeze.py --channel "breeze_(electronics)" --skip-agents agent008,agent009
python app/agent/agent000_breeze.py --channel "breeze_(physics)" --topic "Les saisons et l'inclinaison terrestre à 23,5°" --skip-agents agent008,agent009
```

**The web interface** (`python web/app.py`, read-only) is in English; what the channels produce (names, topics, titles, scenes, QA notes) stays in French. It has three pages. The dashboard
shows each channel's last video (it plays, muted, under the mouse), its QA scores and the state of
each agent at the last run. A channel's page has the video player with its plan: click a scene to jump
to it, and the scene being played is lit. It also shows the QA's verdict and issues, the last 10 runs,
the published videos, the QA rejections and the topics. The standup lists each agent's result for the
last run, channel by channel. Each channel keeps its video theme's accent colour (from agent010's
`THEMES`); the pages are dark, or light when the system asks for it. Files: `web/app.py` (routes; the
video comes from `/video/<channel_id>`, only for a channel of `routes.json`), `web/page.py` (reads
`breeze.db` and `instance/<channel_id>/*.json`, writes nothing), `web/templates/` (`base.html`,
`dashboard.html`, `channel.html`, `standup.html`, `partials/`), `static/css/breeze_master.css`,
`static/js/breeze.js`, `static/images/favicon.svg`; the fonts come from `assets/fonts/` (`/fonts/...`).
The previous version is in `archive/web_v1/`. Check: `python tests/test_web.py`.

`--channel` runs that channel only, even if `routes.json` disables it. `--skip-agents` takes a
comma-separated list of agents that are never called, e.g. to test the QA -> agent004 -> agent010
loop without publishing (008) or reading analytics (009). Each one is logged
`agent008: skipped (--skip-agents)` and gets the status `skipped` in `reports.json`, `breeze.db`
and `breeze.json`, rather than being left out, so a skipped agent never looks like one that did not
run because of a failure (`not_run`). `skipped` does not lower the run's overall status. An unknown
agent name is refused before anything runs. Skipping agent005 means no QA: the render then reads
whatever `qa.json` is already there.

`--topic` imposes agent001's topic, for reproducible test runs (it needs `--channel`: one topic suits
one channel). The orchestrator puts it in the `LBREEZE_TOPIC` environment variable just before
agent001 runs and clears it right after, so no other agent and no other run sees it. agent001's
prompt then says "Le sujet est imposé : <topic>. Ne pas en choisir un autre." instead of letting the
LLM choose, skips the saturated-topics check (the topic was asked for), and records it in
`research.json` as `imposed_topic` (`concept` stays the LLM's wording of the idea to explain).
Without `--topic` (and with `LBREEZE_TOPIC` unset), the LLM chooses freely, as before. agent001
alone takes it too: `python app/agent/agent001_conceptresearcher.py --channel "breeze_(physics)"
--topic "..."`, or `LBREEZE_TOPIC="..."` in front of the command. Check: `python tests/test_orchestrator_topic.py`.

Run a single agent on one channel (it reads the previous agent's file from `instance/<channel>/`):

```bash
python app/agent/agent004_visualbriefgenerator.py --channel "breeze_(electronics)"
python app/agent/agent010_html_renderer.py --channel "breeze_(electronics)"   # the renderer
python app/agent/agent009_analyticsreader.py          # global agent, no --channel
```

Running agents one by one does not re-run the ones after them: after changing a script, run
004, 005 and 010 again, or the video is made from an old storyboard.

The tests are in `tests/`, one script each, run from the project folder (each prints PASS or FAIL
per case and exits 1 on a failure); all of them:
`for f in tests/test_*.py; do .venv/bin/python "$f" > /dev/null || echo "FAIL $f"; done`.

`python tests/test_html_scene.py` renders hard-coded scenes with the renderer (agent010) only, the
quickest way to check a change to it: six scenes
(a circuit, graphs with a vector and a formula, 1/x, a voltmeter measuring with its probes, ground symbols and probe polarity,
annotation badges), saved as PNG stills and `.html` pages in
`media/test_html_scene/` (no internet needed). Add `--video` for the full video with the voice.

There is no scheduler inside the app. `schedule_cron` in `routes.json` is shown on the
dashboard only. `./run` processes every enabled channel, so schedule it **once** a day with the
system cron, e.g. `0 9 * * * /path/to/L_breeze/run`.

## Settings (`schemas/settings.json`)

| Key | Meaning |
|-----|---------|
| `llm_provider` | `bedrock`, `anthropic`, `openai`, `deepseek`, `gemini`, `openrouter` or `ollama` (local) |
| `llm_model` | model id for that provider (for Bedrock, the inference profile id, e.g. `eu.anthropic...`) |
| `ollama_model`, `ollama_base_url` | used only when `llm_provider` is `ollama` (default `http://localhost:11434/v1`) |
| `render_backend_by_channel` | `html` (render, the default) or `skip` (no video) for each channel; an old `manim` is read as `html` |
| `dry_run` | `true`: placeholder video, nothing uploaded, no YouTube statistics |
| `enabled_platforms` | `["youtube"]` to publish; `[]` to make videos without publishing |
| `qa_strict_mode` | `true`: QA must score accuracy, simplicity and clarity >= 7 to pass |
| `max_revisions` | how many times QA may send work back before the channel is `critical` |

Keys for each provider, in `.env`: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` +
`AWS_DEFAULT_REGION` (bedrock), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`,
`GEMINI_API_KEY`, `OPENROUTER_API_KEY` (and `ELEVENLABS_API_KEY` for the voice, optional). Ollama needs none. A missing key makes the agent
`critical`; there is no automatic fallback to another provider.

## How a video is made

1. **agent003** writes the narration, scene by scene (at least 15–20 words per scene, so the
   voice lasts long enough for the animations).
2. **agent004** turns each scene into a **visual brief** (`models/visual_brief_schema.py`):
   components on stage, wires between their named ports, timed actions, a text overlay. The LLM's
   JSON is validated with Pydantic plus topology checks (real ports, known ids, no shared
   positions); on errors it is sent back to the LLM, up to 3 attempts.
3. **agent005** scores the plan against the channel domain's rules and corrects the storyboard:
   ammeters in series, closed circuits, switches closed before current flows, lamps lit only with
   current... What the components cannot show is listed in `qa.json` under `unsupported`.
   Then the spatial arbiter (`app/layout_solver.py`, no LLM) works on boxes estimated
   in 1920 × 1080 px: instruments to a right-hand column, arrows that point at nothing snapped to a
   component (or removed), stacked formulas put side by side in a band under the title, nothing in
   the title zone (y < 150 px, 200 with a subtitle), overlapping boxes pushed apart with room left
   for the wires. What it cannot fix is listed in `qa.json` under `layout_conflicts`; agent010
   measures the real boxes again and lists what still overlaps per scene in `render_manifest.json`.
4. **agent010** renders each scene: French voice-over first (see "Voice-over" below), then a web
   page per scene drawn frame by frame by a browser (see "HTML renderer" below), then ffmpeg joins
   voice and picture and concatenates the scenes (H.264, yuv420p, BT.709 tags; `app/render/video.py`),
   and brings the whole video's audio to -16 LUFS (`LOUDNESS_TARGET`; YouTube plays at -14 and does
   not raise quieter videos, -16 was judged less loud by ear; two-pass `loudnorm`, linear, true peak
   -1.5 dBTP; the picture is copied, not re-encoded). The voices come out near -28 LUFS: without it
   the video sounds weak next to others. Check: `python tests/test_loudnorm.py`.

The LLM never writes drawing code: it picks components and actions; the renderer draws them with
fixed HTML/JavaScript code.

### Components

| Family | Types | Ports | States / `initial_state` |
|--------|-------|-------|---------------------------|
| Electronics | `BATTERY` | `negative`, `positive` | `active` |
| | `LAMP` | `left_terminal`, `right_terminal` | `on` |
| | `SWITCH` | `in`, `out` | `closed` |
| | `AMMETER` | `in`, `out` | `reading` (amps); set automatically while current flows |
| | `WIRE_BUS` | `in`, `out` | — |
| | `VOLTMETER_PROBES` | — (never wired) | reads a voltage with the `measure` action; `label` |
| | `CHASSIS_MASS`, `EARTH_GROUND` | `terminal` | — (ground / 0 V reference, protective earth) |
| Mechanics | `PEDAL_CRANK`, `SPROCKET` | `center`, `rim` | `spinning` |
| | `CHAIN_LINK` | `in`, `out` | — |
| Icons (Lucide SVG) | `WATER_TANK`, `PIPE_VALVE`, `COINS`, `SCALE`, `BANK`, `CART`, `TRENDING_UP`, `TRENDING_DOWN`, `GAUGE` | `left`, `right`, `top`, `bottom` | `active` (green outline) |
| Maths / physics | `AXES_GRAPH` | — | `x_range`, `y_range`, `x_label`, `y_label` |
| | `CURVE_PLOT` | — | `func` (e.g. `"np.sin(x)"`) or `x_func` + `y_func` (parametric, see below), `axes` (id of an `AXES_GRAPH`), `label` |
| | `VECTOR_ARROW` | — | `direction` (see below), `length`, `label` |
| Any object | `OBJECT` | `left`, `right`, `top`, `bottom` | `icon` (one of `OBJECT_ICONS`, default `box`), `label`; `active` (green outline) |
| | `BODY` | — | `label`, `anchor` (on a curve, a point of a graph, or another body), `size`, `color`; moves with `move_along` or `move` |
| | `TEX_FORMULA` | — | `latex` (MathTex if LaTeX is installed, else readable text: `E=mc^2` → `E=mc²`) |
| Annotation | `ARROW_ANNOTATION` | — | `text`, `direction` (see below), `target` (id it points at), `kind` (`pointer` / `status`; default: `status` from 20 characters) |

A `CURVE_PLOT` is either y = f(x) (`"func"`, an expression of x) or a parametric curve: `"x_func"`
and `"y_func"`, expressions of t, for t from `"t_min"` to `"t_max"` (default 0 and 2π, one full
turn), never both forms. That draws what y = f(x) cannot: a circle of radius 2 is `"2*np.cos(t)"`,
`"2*np.sin(t)"`, an elliptic orbit `"3*np.cos(t)"`, `"2*np.sin(t)"`. The expressions follow the
same safety rules as `func` (only t, numbers, pi, e and the listed `np.` functions), and are
evaluated in Python, never in the page. A curve that ends where it starts is drawn closed. agent010
keeps one unit as long on x as on y on axes that carry a parametric curve (a circle stays round,
the axes' ranges grow if needed). agent005 knows an orbit is drawable, so a sine standing for
one is an error to fix, not a renderer limit. Check: `python tests/test_renderer_parametric_curve.py`.

A `VECTOR_ARROW` can start on a curve: `"anchor": {"curve": "<CURVE_PLOT id>", "t": <t>}` on a
parametric curve (t within its `t_min`..`t_max`), `{"curve": ..., "x": <x>}` on y = f(x). Its
`position` is then ignored, and its `direction` may be, besides a cardinal or `[dx, dy]`, `"TANGENT"`
(along the curve, the way t or x grows: a velocity), `"CENTER"` (towards the middle of the curve's
drawing, an orbit's centre: gravity) or `"OUTWARD"`, worked out from the curve
(`app/curve_math.py`) by agent010. A satellite at 45° on the orbit
`3*np.cos(t)`, `3*np.sin(t)`: velocity `{"anchor": {"curve": "orbit", "t": 0.785}, "direction":
"TANGENT"}`, gravity the same with `"CENTER"`. The schema refuses an anchor on an unknown curve, `x`
on a parametric curve (or `t` on y = f(x)), a `t` outside its range, and TANGENT / CENTER / OUTWARD
without an anchor. agent005 can anchor a floating vector by patch. Check: `python tests/test_vector_anchor.py`.

An `OBJECT` is any concrete thing that has no type of its own (an elevator, a rocket, a person, the
Sun, a house...), drawn like the icon types, ports included, from its `icon`: one of a closed list of
80 (`OBJECT_ICONS` in `models/visual_brief_schema.py`, by theme: things, buildings, transport,
people, nature and sky, living, money, other). The list keeps the vocabulary checkable (the schema
refuses another name) and is all on disk in `assets/icons` (Lucide, pinned version), so it draws
offline; `elevator` and `cannon` are breeze's own drawings, Lucide has neither. agent004's prompt lists the icons and
forbids borrowing another type's (a CART is a shopping cart, never an elevator); agent005 can change
an OBJECT's icon by patch. Check: `python tests/test_object_component.py`.

An `OBJECT`, a `BODY` or a `VECTOR_ARROW` that belongs to a graph (the Earth at the centre of an
orbit, the Sun at a focus) sits on a point of it, in the graph's units:
`"anchor": {"axes": "<AXES_GRAPH id>", "x": 0, "y": 0}` (its `position` is then ignored; TANGENT /
CENTER need a curve or a body anchor). agent010 centres its drawing there once the graphs are laid
out, before the wires, and its guessed position pushes nothing away.
agent005 fixes a planet beside its orbit by anchoring it, never by moving the orbit. Vectors riding on
one body get one colour each (unless the brief gives one), their label in it, and the label tries
past the tip, then beside the arrow, then behind its start, so it is never hidden by the planet it
points at. Check: `python tests/test_point_anchor.py`.

A `BODY` is a disc (a satellite, a planet, a ball) with its label; anchored on a curve like a vector
(`"anchor": {"curve": "orbit", "t": 0}`), it sits on it, and the action
`{"action": "move_along", "target": "sat", "to": 6.2832, "duration": 4}` makes it travel along the
curve at an even pace, from where it is (its anchor, or where its last move_along left it) to `to`
(t, or x on y = f(x); past `t_max` is another lap). A `VECTOR_ARROW` with `"anchor": {"body": "sat"}`
rides on the body: it starts on it, follows it, and a TANGENT / CENTER / OUTWARD direction turns with
it (velocity along the orbit, gravity to its centre). agent010 samples each trip in Python (30 points
a second, `motion_tracks`) and the page only interpolates at `seek(t)`; a riding vector's label sits
past its tip, so it names its own arrow whichever way it turns, and a badge pointing at the body
goes with it. A vector may also start on an OBJECT (`{"body": "<OBJECT id>"}`, a cardinal or
`[dx, dy]` direction): in line with the object's centre, where it leaves the object, label included
(a weight starts under the elevator, not through its label). A trip cued too late to be seen whole is made to
end with the scene (starting earlier if it would last under 1.5 s; `planned_duration` keeps what was
asked), and agent004 sends such a move back to the LLM; a move without a cue planned at the same time
as a cued one starts with it, and moves on one cue start together (other actions on one cue stay
0.4 s apart). A `CENTER` vector (gravity) stops short of what sits at the curve's centre (the
planet's drawing), else at 80 % of the way. Check: `python tests/test_move_along.py`,
`python tests/test_motion_followups.py`.

A thing that moves in a straight line (an elevator falling, a car, a ball dropped) needs no graph:
an `OBJECT` or a `BODY` with no anchor, and `{"action": "move", "target": "lift", "to": [0, -2.5],
"duration": 2.5, "easing": "fall"}`: it goes from its `position` to `to` (scene units; agent010 adds
that shift to where the layout put it, kept in the frame). `easing` is `"smooth"` (eases in and out,
the default), `"fall"` (faster and faster, as gravity does) or `"linear"`. Things that travel
together are never two bodies at one point (they would hide each other, their labels too): a `BODY`
or an `OBJECT` with `"anchor": {"body": "<BODY or OBJECT id>"}` rides in that one, drawn beside its
drawing (on its right, its left if there is no room, one under the other, its label on its side),
and goes with it, on a curve or in a straight line; the vectors starting on it and the badges at it
follow too. A passenger rides in a thing that rides in nothing. agent004 sends back two bodies
anchored on one point (ride, or make them one body); agent005 can fix them by patch. An `OBJECT`
anchored in a graph, or riding, is drawn compact (a 60 px icon), to scale with the graph. A straight
move keeps in the frame (and in its panel, on a comparison page) everything that goes with the thing:
its passengers, its vectors and their labels, the badges at them; if they would leave it, the whole
move is shortened, still eased as asked. Vectors starting on one object the same way (its weight and
its acceleration) are drawn side by side, 48 px apart, never one over the other; a badge at a vector
goes along when the vector's object moves; a badge is never laid over another arrow, and one at a
passenger points at its label's side. Passengers stay in their host's panel and below the titles,
past the host's label if their stack reaches it. agent004 sends back a VECTOR_ARROW that starts on
nothing in a scene with an OBJECT or a BODY (a force acts on something: anchor it), and a
"comparison" with nothing of its own in one panel (badges and anchored things do not count).
A vector starting on an object stops 40 px short of the titles and the frame's edges, and 14 px
short of another component in its way (a weight over the ground); a free object whose vector would
have no room moves away from that edge first, so at least 100 px of the arrow show. A badge at a body
going along a curve is re-placed at every frame outside the curve, past the body and its passengers
(kept at a fixed offset, it would cross the planet half a lap later); a badge at a thing with
passengers points at the group. agent004 also sends back a `move` in a scene with a graph (its
`to` is in scene units: a trajectory there is a CURVE_PLOT with `move_along`) and two icons anchored
closer than 12 % of the graph's range; its prompt says a contact force starts at the contact (the
ground's reaction on the ground) and that an icon must show the thing (a BODY disc rather than an
unrelated icon). The icon types (a SCALE, a BANK...) ride too, with `"anchor": {"body": id}` as
their only anchor (a scale in a falling elevator); an anchor on a type that takes none is refused,
never ignored. Spreading things out treats a host and its passengers as one block, so a passenger
never lands on the host's neighbour. A badge with no clear side tries a longer arrow (110, then
170 px) before covering anything; a badge at an orbiting body also tries tilted directions to keep
off the legend. agent004 compares every BODY and OBJECT anchored on one graph, on a point or on a
curve (its point there): two closer than 12 % of the graph's range are sent back, with "ride in it"
when both move (a station and its astronaut 0.2 apart on the orbit), not when only one does (a
cannonball leaving its cannon). Its prompt asks for one-way trajectories (a curve's own "x_range")
and, when the planet's size matters, its surface drawn as a circle. A vector on a passenger of a body
on a curve may be TANGENT / CENTER (worked out from the host's point, drawn from the passenger), so
agent005's fix "make the astronaut ride in the station" is valid; when one of its patches is refused,
the remove_action on that entity that went with it is skipped (a fix is never half applied). The
passengers of a body on a curve sit on the curve's outer side at every frame (their label on that
side too), and the vectors and badges at them follow; a passenger's vectors share its host's colours.
A vector shows a short symbol by its arrow, as on a physics diagram ("P"), and its label goes in the
scene's legend ("P : Poids", with the colour of each arrow it names): under the graph when the scene
has one, else in a row at the bottom of the frame, the diagram kept above it. The symbol is the
brief's "symbol" (1 to 3 letters or digits, checked by the schema; agent004 asks for one, agent005
can patch it), else the label's first letter ("Gravité" -> "G", "Gr" if another label has "G"); a
label of 3 characters or less ("v") is its own symbol, with no legend line. agent004 also merges
travellers itself (in "sync_fixes"): two BODYs moving along one curve closer than 20 % of the graph's
range (a station and its astronaut, which the LLM spaces out however it is told) become a body and its
passenger, the second's moves dropped, what rode in it moved to the first. Passengers with a downward
arrow go under the others (a weight over a scale would hit it); on a curve, a passenger with no room
outward (near the legend) goes just beside its host along the curve, never far from it. A CENTER vector
on a passenger points at the curve's centre from the passenger, at every frame. agent005 applies
consecutive set_initial_state patches on one scene together, checked once (a parabola turned into an
orbit: "func": null, "x_func", "y_func"..., and the body on it re-anchored from "x" to "t"), then one
by one if together they fail; "value": null removes a key. Graph legends wrap, one entry per line
piece. A symbol "F_g" is written F with a g below (subscript), on the arrow and in the legend. Two
bodies whose moves along one curve are exactly the same (when, cue, duration, how far) are merged up
to half the graph's range, whatever gap the LLM left. agent004 sends back a scene whose narration says
"autour" while its bodies only fall in a straight line (no closed curve). A badge at a thing moved in
a straight line is placed for where that thing ends, and kept under the titles before. Spreading
things out counts a thing moved in a straight line with its whole way (start to end) and the arrows
starting on it, so nothing still stands on its path. The counters' row is measured with its values'
line from the start (the diagram starts under it), and on an analogy page things stay inside the
backdrop. A graph shares the frame with the icons and formulas beside it (55 % x 48 % instead of
70 % x 60 %), and spreading things out tries the other axis when the frame stops a push. An AXES_GRAPH
with no curve and no y label, whose points sit at y = 0, is drawn as a number line (one graduated
line, its BODYs as dots). agent004 sends back bodies set off one after the other on one curve that
catch each other up. Check: `python tests/test_free_motion.py`.

The channels' domains (`schemas/routes.json`) set what agent001 may pick: each domain gets a scope in
its prompt (`DOMAIN_SCOPES`: a "math" channel stays in mathematics, never the seasons), and agent005
checks a "math" channel with the maths rules alone.

`direction` (where a `VECTOR_ARROW` or an `ARROW_ANNOTATION` points, scene axes: x right, y up) is
either a cardinal, `"UP"` / `"DOWN"` / `"LEFT"` / `"RIGHT"` (case-insensitive, drawn exactly as
before), or a vector `[x, y]` of two real numbers, of any length but not `[0, 0]`: both renderers
normalise it and draw at the angle `atan2(y, x)`. `[0.4, 0.9]` is an axis tilted about 23.5° from the
vertical (the Earth's), `[1, 1]` points up-right at 45°. Anything else (`"DIAGONAL"`, `[1, 2, 3]`) is
refused by the schema (`models/visual_brief_schema.py`, `direction_problem`), so agent004 sends it back
to the LLM. Check: `.venv/bin/python tests/test_schema_direction.py`.

In the HTML renderer an annotation is a pill badge: a `pointer` gets a 50 px arrow onto what its
`target` names, on whichever side keeps the badge and arrow off the wires; a `status` badge
("Tension présente, courant nul") has no arrow and sits in the instrument column on the right.
The arrow ends on the component's edge, on a curve (the point of it where the badge fits best,
near the brief's position, off the other curves, the legend and the axis titles), on a vector's
shaft, or on a graph's plot (not its legend). A badge with no target and nothing near it is
reported `<id> points at nothing` in `layout_conflicts`. Check: `python tests/test_annotation_targets.py`.
A vector's label goes beside its arrow, where it touches nothing (another label, an arrow, a
component, an axis or its title, a curve, the frame): beside the middle first (its place when there
is room), then nearer an end, then in line behind the start or past the tip, shifted up or down by
whole lines if needed, never far from its arrow. Several forces drawn from one point keep their
arrows there, and their labels stack beside them. Check: `python tests/test_vector_labels.py`.
Narration and picture stay in step. Every action has a `cue`, the narration's words it happens on:
agent004 times it from where those words fall in the text, and agent010 starts it when the voice
actually says them (the word timings ElevenLabs or edge-tts return). agent004 also sends back to the LLM, for a retry,
briefs that drift from the narration (tension/volts without a `measure`, courant/débit without a
flow, an opening without an open switch), mix an analogy with a circuit, fade an analogy out early,
or label one quantity with another's name (an arrow at the formula of I saying "U"), draw a curve
too small for its graph (under 15 % of its span: Newton's throws piled at the top of the tower), or
give numbers in the narration with only icons and labels on screen (its prompt asks for a graph of
the main quantity, always in economics). A "comparison" with an empty panel or a circuit wired across
the two panels is sent back too, and if it is still so after the retries it goes back to "circuit"
(and a missing comparison is only forced on a scene that fills both panels). These rules are
advisory: if the LLM still breaks them after 3 attempts, the best answer is kept, agent004 ends
`not_healthy` and lists them in `coherence_left` (agent005's QA judges the result); only schema and
topology errors stop it. It also repairs the mechanical parts: a flow stops when its switch opens,
ammeters light up when the current starts. A `WATER_TANK` has a
`level` (0 to 1) that rises and falls, and its water ripples while a flow runs through it.

Target first: an annotation never spawns before the entity it points at. agent004 asks for it and
repairs any brief that breaks it (the arrow then spawns with its target; listed in `timing_fixes`),
and agent005 checks it again once the layout knows what each arrow really points at.

Every component also accepts `initial_state.label` (a short French name), and the states
`highlighted` and `dimmed`. A `CURVE_PLOT` `func` may only use `x`, numbers, `pi`, `e`, arithmetic
and a list of `np.` maths functions: it is checked before it is ever evaluated.

Actions, timed in seconds of the script's planned scene length:

```json
{"at": 0.5, "action": "spawn", "target": "battery_1"}
{"at": 3.0, "action": "set_state", "target": "switch_1", "state": {"closed": true}}
{"at": 3.5, "action": "start_flow", "path": ["battery_1", "switch_1", "lamp_1", "battery_1"], "current": 0.5}
{"at": 8.0, "action": "stop_flow", "path": ["battery_1", "switch_1", "lamp_1", "battery_1"]}
{"at": 9.0, "action": "fade_out", "target": "lamp_1"}
{"at": 5.0, "action": "set_value", "target": "bank_1", "value": 300, "unit": "Md€", "tone": "negative"}
{"at": 6.0, "action": "measure", "target": "voltmeter_1", "target_pin_a": "lamp_1.left_terminal",
 "target_pin_b": "lamp_1.right_terminal", "value": 4.5, "unit": "V"}
```

`measure`: the red probe (V+) goes to `target_pin_a`, the black one (COM) to `target_pin_b`
(`"<id>.<port>"`, real ports only), then the meter shows `value` = V(a) − V(b), negative when the
red probe is on the lower potential. A connection with `"dashed": true` is an optional link
(e.g. earth to chassis), drawn dashed. agent004 asks for dense scenes: 5 to 8 actions per
8 s of narration, measurements on instruments rather than floating text.

Components no action spawns appear when the scene opens; a wire is drawn as soon as both its
ends are on screen; `start_flow` closes any open switch on its path first.

### Render details

- **Layout:** components go on a 3×3 grid (`LEFT`, `TOP_RIGHT`...) or at `[x, y, 0]`; overlapping
  components are moved apart; labels go where there is room, never over a port; everything stays
  0.8 units inside the frame. Wires are routed with right angles around components and labels.
- **Timing:** an action with a `cue` starts when the voice says those words; the others have their
  time stretched to the real voice length.
- **Icons:** downloaded once from the Lucide CDN (version pinned) into `assets/icons/`, then read
  from there. Put your own `<icon>.svg` there to replace one; edit `ICON_ALIASES` in
  `app/render/asset_resolver.py` to change which icon a type uses. `BREEZE_OFFLINE=1` disables
  downloads (a question-mark icon is drawn for a missing one).
- **Errors:** a scene that fails to render becomes a black screen showing the error, so the video
  still gets made; the details are in the manifest and on stderr.

### HTML renderer (agent010)

Each channel has its theme (`THEMES` and `CHANNEL_THEMES` in agent010, fixed in code, never from the
LLM): electronics "lab" (dark, a printed-circuit grid with faint traces and pulses running along
them, glowing parts, a Fira Code step line "// étape 02 : ..."), physics "space" (dark, stars in three
layers drifting at three speeds, faint nebulae), math "notebook" (light, squared paper, the title
appearing word by word), economics "data" (dark, a data grid, Space Grotesk titles, an upper-case
accent line). A theme sets the design tokens (light or dark: cards, ink, wires, the icons' colour),
the background (built once, moved by `seek(t)` so every frame is exact: glows on slow ellipses, a
sliding grid, the stars, the pulses; radial gradients, not a CSS blur, which tripled the render
time), and the fonts. Inter, Fira Code and Space Grotesk come from their npm packages (@fontsource,
SIL Open Font License), pinned and checked against their sha512, cached in `assets/fonts/` and
inlined into each page (`app/render/fonts.py`): the page never fetches anything. Effects: an OBJECT
"earth" / "globe", "moon" or "sun" is drawn as a lit sphere (its atmosphere, craters, its light), not
an icon card; a BODY is a disc lit from the top left. On the dark themes ("glow"), curves get a
faint wide halo drawn with them (a second stroke, cheaper than an SVG blur), bodies glow in their
colour, and the battery, the meters, the voltmeter's screen and the cards are lit; on "data"
("area"), the space under a y = f(x) curve is filled with its colour, fading downwards, once the
curve is drawn. Meaning in colour: a TEX_FORMULA or an ARROW_ANNOTATION may have a "tone" (`TONES`:
"result" green, "warning" amber, "wrong" red, "key" the theme's accent; the schema refuses it
elsewhere), and the action `{"action": "emphasize", "target": id, "effect": "shake" | "pulse"}` makes a
contradiction shake (0.9 s, fading, flashing red) or a result pulse (two beats, a ring in its tone),
moved by `seek(t)`. agent004's prompt asks for them, once or twice a video; agent005 can patch a tone
and add an emphasis. Check: `python tests/test_themes.py`.

**The plan.** Right after the hook (scene 1), agent010 adds a scene of its own, "Au programme": its
voice ("Au programme. D'abord, <titre>. Ensuite, ... Et enfin, <titre>.") and its list are built from
the scenes' titles (no LLM); each chapter slides in when the voice names it, the one being named lit
in the accent colour. Every scene after it shows where it is in the plan, top right ("02 / 05" and
one bar per chapter). No plan for a video of fewer than three scenes (`PLAN_MIN_CHAPTERS`). The plan
is a scene of `render_manifest.json` (`"scene_id": "plan"`), so agent007's YouTube chapters, built
from the rendered start times, include it. agent003 is told not to announce the plan itself.
A title, a subtitle, a label or an axis name written in LaTeX ("10^{-n}", "t_n") is shown with
Unicode exponents and indices ("10⁻ⁿ", "tₙ") when every character has one (`plain_math`).
A scene whose free components sit high or low (no graph, no straight move) is moved to the middle of
the frame, between the titles and the legend (`centre_vertically`). Check: `python tests/test_plan.py`.

agent010 draws each scene as a web page:

- One HTML page per scene: SVG wires, curves and vectors, HTML components, Lucide icons.
  Text written by the LLM is inserted with `textContent`, so it never runs as code.
- Headless Chromium (Playwright) opens the page and calls `seek(t)` for every frame (30 fps).
  `seek` draws the scene at time t, so frames are exact whatever the machine's speed. Each frame is
  piped as a JPEG into ffmpeg, then muxed with the voice.
- **Wires:** right-angle paths, routed after layout, around the components and their labels.
  Each side of a component carries at most one wire; crossings and wires running side by side are
  avoided when another path exists.
- **Graphs:** `AXES_GRAPH` draws SVG axes (70 % of the frame's width, 60 % of its height) with numbered ticks; `CURVE_PLOT` points are computed in Python
  (expression checked by `check_function_expression`, evaluated with numpy, no builtins), with
  gaps where the function leaves the y range (e.g. 1/x at 0), a color and a legend per curve;
  `VECTOR_ARROW` grows from its start point.
- **Ammeter:** shows its reading in the dial and jumps to it as soon as the current flows
  (the flow's `current`, else the next `set_value`, else 1.5 A); back to 0 when it stops.
- **Look:** cards with rounded corners, a light border and a soft shadow; the lamp glows (radial
  gradient) and fades in and out over 0.4 s; electrons glow and pulse; every component pops in
  with a spring (`@keyframes popIn`, scale 0.9 → 1). `THEME` in the agent switches to `"dark"`.
  Animations are paused and set from `seek(t)`, never left running, so each frame is exact.
- **Formulas:** rendered with KaTeX 0.16.11, downloaded once from npm, checked against its
  sha512 and cached in `assets/katex/`; without it (offline first run, `BREEZE_OFFLINE=1`)
  formulas are plain text.
- **Wires** keep at least 40 px between parallel runs (`LANE` in the page script).
- `renderer_used` in `render_manifest.json` is `html_playwright` (or `dry_run`).

On the dashboard, the render step is agent010's (older runs rendered by agent006 still show it).

### Voice-over (`app/tts_manager.py`)

agent010 makes each scene's voice with `generate_voice(text, mp3_path, spoken)`:

1. **ElevenLabs** when `ELEVENLABS_API_KEY` is in `.env`: model `eleven_multilingual_v2`, voice
   "Charlotte" (`XB0fDUnXU5powFXDhCwa`) by default. Change them with `ELEVENLABS_VOICE_ID` (in the
   ElevenLabs app: Voices -> the voice -> "Copy voice ID"; a native French voice from the Voice Library
   sounds the most natural) and `ELEVENLABS_MODEL_ID`. It calls the `with-timestamps` endpoint (plain
   `requests`, no extra package), which also says when each word is spoken, for agent010's cues.
2. **edge-tts** (`fr-FR-VivienneMultilingualNeural`, rate +3%, pitch +0Hz) without a key, or when
   ElevenLabs fails (network, timeout, invalid key, quota): a `WARNING tts: ElevenLabs failed (...)`
   line on stderr and that scene gets the edge-tts voice, so the render goes on. A network error, a
   429 or a 5xx is tried once more before falling back.

Before either engine, the narration goes through `normalize_text_for_tts`, for the voice only
(`script.json`, the storyboard and the text on screen keep `10x` and `0,999...`): `10x = 0,999...` is
read "10 ixe égal 0 virgule neuf neuf neuf à l'infini". A decimal ending in an ellipsis is said digit
by digit, "à l'infini" (said "999" it would be a finite number), "+ …" is "et ainsi de suite", other
ellipses become a pause; exponents are "puissance" ("10⁻ⁿ", "10^(-n)"; 2 and 3 "au carré", "au cube");
the maths minus "−" is "moins"; a digit and a letter stuck together are split; a decimal comma is
"virgule"; a unit after a number is its name ("6 V" -> "6 volts", "12 Ω" -> "12 ohms"); `= + × * / -`
are "égal", "plus", "fois", "sur", "moins" (`/` and `-` only in a calculation, brackets included:
"1/(1 − 1/10)", so "c'est-à-dire", "a-t-il", "Covid-19", "km/h", "1er", "10h30" are read as before); a
capital letter alone, and x or n, is said by its French name ("I = U / R" -> "i égal u sur erre", never
the English "aï"); 2 to 4 capitals are spelled ("l'IPC" -> "l'i pé cé"), except the acronyms said as
words (`SPOKEN_ACRONYMS`: NASA, ONU...). agent010 normalizes each action's `cue` the same way, so a cue
written "10x" still meets the spoken "10 ixe". The maths a script may still write is said too: an
index "t_n" is "t indice n", "10^{-n}" "10 puissance moins n", `< > ≤ ≥ ≠ ≈ →` "inférieur à",
"supérieur à", "inférieur ou égal à"..., and a truncation "0,999…9" "0 virgule neuf neuf neuf, et
ainsi de suite jusqu'à un dernier neuf" (it ends: not "à l'infini"); agent003 is asked to write the
narration in words anyway. Check: `python tests/test_tts_normalization.py` (offline).

`render_manifest.json` records which engine spoke: `voice_engine` per scene (`"elevenlabs"` or
`"edge-tts"`, and `voice_fallback`: why ElevenLabs failed, when edge-tts stood in), and for the video
(`"elevenlabs"`, `"edge-tts"`, `"mixed"`; `null` in a dry run). A fallback is also a render warning
(`voice: ElevenLabs failed for scene(s) 2, edge-tts stood in (mixed voices in the video)`), so the
renderer ends `not_healthy`; no key at all is not a fallback (edge-tts by choice, no warning).

The duration is measured with ffprobe on the file, whatever the engine. Check (needs internet, uses a
few dozen characters of the ElevenLabs quota): `python tests/test_elevenlabs_tts.py` (`--keep` keeps the
.mp3 files in `media/test_elevenlabs_tts/`).

### Provenance (`instance/<channel>/manifest.json`)

Each channel's run gets a run id (`2026-10-30T16-19-05-electronics`) and a `manifest.json` listing
every file the run wrote, with the agent that wrote it and when (and the history of writers for a
file written twice, like `storyboard.json` corrected by agent005). The orchestrator starts it and
passes the run id in the `LBREEZE_RUN_ID` environment variable; each agent adds its files as it
writes them. A new run copies the previous manifest to `manifests/<run_id>.json` first.

Observation mode: when an agent starts, each input file that is not in the current run's manifest
gets a warning, `artefact non tracé dans le manifeste : script.json`, and the agent carries on.
Nothing is ever moved or blocked. An agent run alone continues the run in the manifest, or uses
`--run-id X` (or `LBREEZE_RUN_ID=X`): with no manifest for X it starts an empty one, with a warning.
`python tests/test_provenance.py` checks this behaviour in a temporary folder.

### QA feedback (`LBREEZE_QA_FEEDBACK`)

When agent005 rejects a run, the orchestrator redoes agent004 (or agent003 + agent004 when the
script itself is wrong) and hands them the QA's feedback in the `LBREEZE_QA_FEEDBACK` environment
variable, as JSON:

```json
{"rejection_notes": "...", "blocking_issues": [{"scene_id": "5", "text": "...", "severity": "blocking"}], "revision": 1}
```

`blocking_issues` are the issues of `qa.json` whose `severity` is `blocking`. The variable is set
just before the redo and cleared right after it; it is only set when `qa.json` names `reject_to`
explicitly. The log line reads `revision 1 -> agent004: feedback transmis (1 blocking issues)`.
agent004 turns it into a "Corrections demandées par le QA (révision N)" section of its LLM prompt
(rejection notes, then each blocking issue with its scene); it never reads `qa.json` itself, so a
standalone run can be given feedback the same way:
`LBREEZE_QA_FEEDBACK='{"rejection_notes": "...", "blocking_issues": [], "revision": 1}' .venv/bin/python app/agent/agent004_visualbriefgenerator.py --channel "breeze_(electronics)"`.
A value that is not valid JSON is ignored, with a warning.
agent003 reads it the same way (`app/qa_feedback.py`) when the QA sends the script back, with a
reminder of what the animation can show, so a rewrite avoids what made the QA reject it.

A reject to agent004 that agent004 cannot fix is not redone: when the rejection notes or a blocking
issue say the renderer cannot show what the narration needs ("n'est pas représentable", "aucun
composant", "ne peuvent pas être rendus", "cannot draw", "not representable"...; `RENDERER_LIMIT` in
`agent000_breeze.py`), the channel stops at once, agent005 `critical` with
`Renderer limitation: <reason> (unsupported: ...)`, instead of up to 3 useless storyboard rewrites.
`unsupported` alone does not stop it (the QA lists it even when it passes), and a reject to agent003
still gets its rewrite. Check: `python tests/test_orchestrator_unsupported_loop.py`.

### Recurring defects (`app/defect_report.py`)

What goes wrong again and again, run after run, per channel, from `schemas/rows.json` and
`schemas/reports.json` (read only):

```bash
python app/defect_report.py                                   # every channel, last 10 runs each
python app/defect_report.py --channel "breeze_(math)" --last 5
python app/defect_report.py --json --out instance/defects.json
```

It lists the runs (topic, worst status, video or not, QA revisions, why it stopped), then every
defect seen in at least `--min-runs` runs (default 2), most frequent first, with an example. A defect
counts once per run (a QA revision repeating it does not count twice). Messages our code writes
(layout conflicts, render warnings, agent004's rules, why a run stopped) are grouped by template,
entity ids becoming their role (`arrow_slow overlaps arrow_earth` -> `badge chevauche badge`); the
QA's free-text issues by theme; its `unsupported` list by what is missing to draw (the vocabulary to
add). Themes and roles are keyword heuristics: each line shows a real example. Standalone runs are
left out. Check: `python tests/test_defect_report.py`.

## Add a channel

1. Add one object to `schemas/routes.json`:

   ```json
   {"channel_id": "breeze_(chemistry)", "name": "Chimie facile", "domain": "physics_math",
    "target_age_band": "14-18", "persona": "lycéen curieux", "publish_platforms": ["youtube"],
    "schedule_cron": "0 13 * * *", "enabled": true}
   ```

   `channel_id` must match `breeze_(...)` with lowercase letters or `_` inside the parentheses.
   Its folder `instance/breeze_(chemistry)/` is created on the first run. `domain` picks the QA
   rules agent005 applies: `electronics`, `physics_math` or `economics` (any other value: all rules).
2. Add the same id to `render_backend_by_channel` in `schemas/settings.json`
   (`"html"`, the default, or `"skip"`).
3. For live publishing, add `YOUTUBE_REFRESH_TOKEN_BREEZE_CHEMISTRY=` to `.env`
   (the variable name is the channel id without parentheses, in upper case).

To pause a channel, set `"enabled": false`.

## Switch from dry run to live

`dry_run: true` runs every agent but renders a placeholder file instead of a video, uploads
nothing and reads no YouTube statistics. The LLM is always called, so the pipeline needs a
working provider to get past agent001.

1. **LLM:** set `llm_provider` and `llm_model` (see Settings) and the matching key in `.env`.
   For Bedrock, check that the model is enabled in your region in the Bedrock console.
2. **Check one dry run end to end** and read the files in `instance/<channel>/`.
   The LLM proposes the source URLs in `research.json` without browsing the web,
   so **a human must open every URL** before a video goes out.
3. **Videos without publishing:** set `"dry_run": false` and `"enabled_platforms": []`, run, and
   watch `instance/<channel>/video.mp4`.
4. **YouTube:** create an OAuth client (`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`) and one
   refresh token per channel with the scopes `youtube.upload`, `youtube.readonly` and
   `yt-analytics.readonly`, then set `"enabled_platforms": ["youtube"]`.
5. Videos are uploaded as **private**: review them in YouTube Studio, then make them public.
   Each upload costs 1,600 of the 10,000 daily quota units, and agent008 refuses to upload when
   the quota would be exceeded.
6. To publish through Upload-Post instead, set `"publisher": "uploadpost"` and `UPLOADPOST_API_KEY`.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `Error code: 429` | The provider's rate or daily quota is used up: wait or raise it; re-run only the failed channels (`"enabled": false` on the others). |
| `answer cut off at max_tokens` / `no JSON object in LLM answer` | A reasoning model spent its output budget thinking: raise `MAX_OUTPUT_TOKENS` in `app/agent/__init__.py`. |
| agent010: `has no visual_brief (older storyboard)` | The storyboard predates the current format: run agent004 (and 005) again. |
| agent010: `QA verdict is not pass` | `qa.json` rejected the plan: run agent005 again, or the full cycle. |
| White or washed-out picture in VLC | Disable hardware decoding in VLC (Tools → Preferences → Input/Codecs), or try another video output. |
| Formula shown as plain text | KaTeX could not be downloaded (offline first run): expected, the formula is still readable. |
| agent010: `playwright is not installed` | `pip install -r requirements.txt`, then `playwright install chromium`. |
| agent010: `Executable doesn't exist` | Playwright's Chromium is missing: `playwright install chromium`. |

## Quoting `channel_id`

The parentheses are part of the id.

| Where | How |
|-------|-----|
| JSON | literal: `"breeze_(math)"` |
| file paths | literal: `instance/breeze_(math)/script.json` |
| shell | always quote: `--channel "breeze_(math)"`, `ls "instance/breeze_(math)"`. Unquoted, bash reads `(` as syntax |
| URLs | percent-encode: `/channel/breeze_%28math%29` (Python: `urllib.parse.quote("breeze_(math)", safe="")`, decoded with `unquote`) |
