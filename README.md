# breeze

One Python process, nine agents (all nine per channel, agent009 shared), four channels. Each channel picks a common misconception
in its domain and turns it into a 90–180 s animated video, narrated in French, that ends on an
"aha moment": `breeze_(electronics)`, `breeze_(physics)`, `breeze_(math)`, `breeze_(economics)`.

## Demo video

[Watch the French electronics lesson (MP4)](https://github.com/Fil37/breeze.edu-pipeline/blob/main/assets/breeze-demo-electronics.mp4)

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
| | `agent010_html_renderer` (a browser draws each frame) | `video.mp4` + `render_manifest.json` + `subtitles.srt` |
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
| `burn_subtitles` | `true` (default): the subtitles are drawn in the video; `false`: only `subtitles.srt` |
| `max_revisions` | how many times QA may send work back before the channel is `critical` |

Keys for each provider, in `.env`: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` +
`AWS_DEFAULT_REGION` (bedrock), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`,
`GEMINI_API_KEY`, `OPENROUTER_API_KEY` (and `ELEVENLABS_API_KEY` for the voice, `PIXABAY_API_KEY` for the hook's film, both optional). Ollama needs none. A missing key makes the agent
`critical`; there is no automatic fallback to another provider.

## How a video is made

1. **agent003** writes the narration, scene by scene (at least 15–20 words per scene, so the
   voice lasts long enough for the animations; 280 to 520 words in all, the narrator speaking about
   3.1 words a second: a script under 280 words is asked again once, `MIN_WORDS`).
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
| Speeds | `SPEED_RACE` | — | `distance`, `distance_unit`, `runners` (`{"label", "speed", "unit", "icon"}`, 2 or 3); `go` |
| Logic | `LOGIC_CIRCUIT` | — | `inputs` (1 to 4 `{"id", "label"}`), `gates` (1 to 6 `{"id", "type", "in"}`: AND, OR, XOR, NAND, NOR two inputs, NOT one), `outputs` (1 to 3 `{"id", "label", "from"}`), `values`; `<input id>` (0 / 1), `mode` (`sequential` / `parallel`) |
| FPGA | `FPGA_GRID` | — | `cols` (2 to 6), `rows` (2 to 4), `design`, `design2` (functions, short texts); `configure`, `run`, `reconfigure` |
| Schematic parts | `RESISTOR`, `POTENTIOMETER`, `THERMISTOR`, `OPAMP`, `MOSFET`, `DIODE`, `LED`, `HEATER`, `SUPPLY_RAIL` | their leads (`left`/`right`, `wiper`, `in_plus`/`in_minus`/`out`/`vcc`/`gnd`, `gate`/`drain`/`source`, `anode`/`cathode`, `terminal`) | `label` (its value: "R1 10 kΩ"); LED / HEATER / MOSFET `on`, OPAMP `high`, THERMISTOR `hot` |
| Breadboard | `BREADBOARD` | — | `parts` (`id`, `kind`, `label`), `nets` (leads joined, a supply name first for a rail); `step`, `on` |
| Microcontroller | `MICROCONTROLLER` | — | `label`, `instructions` (1 to 8 short texts); `run` |
| Table | `TABLE` | — | `columns`, `rows` (short cells); `fill`, `row`, `column`, `total` (summed by the program) |
| Chain of steps | `CHAIN` | — | `steps` (2 to 6), `loop`; `step`, `focus` |
| Simple catalogue pieces | `TIMELINE`, `FRACTION_BAR`, `PIE_CHART`, `UNIT_CONVERTER`, `TREE`, `SET_DIAGRAM`, `GAME_MATRIX`, `BAR_CHART`, `EQUATION_STEPS`, `POWER_SUPPLY` (ports `negative`, `positive`) | see `models/visual_brief_schema.py` | their data only; every figure worked out |
| Mechanical wave | `WAVE` | — | `mode` (`rope`, `water`, `crowd`, `spring`), `kind` (`pulse`, `continuous`); `go`, `mark`, `energy` |
| Tunnel effect | `TUNNEL` | — | `particle`, `barrier` (short texts), `zoom` (true); `bounce`, `tunnel` |
| Tides | `TIDES` | — | nothing to give (all drawn and labelled); `points`, `forces`, `relative`, `stretch`, `spin`, `sun` (`aligned` / `square`) |
| Shares of people | `POPULATION` | — | `total` (10 to 1000 dots), `per` (people a dot stands for), `unit`, `groups` (1 to 4 `{"id", "label", "count", "color"}`), `rest`; `show` (a group's id), `focus` (ids) |
| Weights | `SEESAW` | — | `left`, `right` (`{"label", "weight", "value"}`), `unit`; `left` / `right` (drop a load), `balanced` |
| Queues | `LANES` | — | `lanes` (2 to 4 `{"label", "rate"}`), `icon` (car, bus, truck, bike, user, users, person-standing, shopping-bag), `label`; `active` (false stops them) |
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
118 (`OBJECT_ICONS` in `models/visual_brief_schema.py`, by theme, as agent004's prompt lists them:
things, energy, buildings, transport, people, nature and sky, living, health, food and farming,
money and trade, society, other). The list keeps the vocabulary checkable (the schema
refuses another name) and is all on disk in `assets/icons` (Lucide, pinned version), so it draws
offline; `elevator`, `cannon` and `spring` are breeze's own drawings, Lucide has none of them. agent004's prompt lists the icons and
forbids borrowing another type's (a CART is a shopping cart, never an elevator); agent005 can change
an OBJECT's icon by patch. Check: `python tests/test_object_component.py`.

`LANES` draws queues side by side, the analogy of parallel branches (lanes at a toll, checkouts):
each lane delimited (solid edges, dashed between two lanes), its label on its left, its vehicles or
people (one `icon`) standing up to the gate and, once on screen, rolling through it at the lane's
`rate` (how many per second, 0.2 to 3), and on the right how many went through. Positions and counts
are worked out from t (`seekLanes`). `set_state {"active": false}` stops the lanes, `true` sets them
off again. agent004 sends back a scene that moves three or more cars or people one by one
(`queues_by_hand`): they piled up and left the frame. Check: `python tests/test_subtitles_lanes.py`.

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

**No topic twice.** agent001's prompt lists the channel's topics already made into a video (`breeze.db`,
runs that ended `healthy` or `not_healthy`) and forbids them, in other words too. Then the topic it
picked is checked: first by its key words (4 letters or more, accents and endings dropped: most of
them found in a topic already made), then by the LLM, asked whether it is the same subject or the
same misconception from another angle. A repeat is sent back with the reason, up to 3 answers
(`TOPIC_ATTEMPTS`); if all of them repeat, agent001 is `critical` and no video is made. An imposed
topic (`--topic`) is checked too but kept: agent001 ends `not_healthy`. `research.json` records the
check in `"novelty"` (`verdict`: `new`, `duplicate` or `unchecked` when the LLM could not be asked;
the topics refused and why). Check: `python tests/test_plan.py` (case 6).

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

**The plan.** Right after the hook (scene 1), agent010 adds a scene of its own, "Au programme". agent003
writes it in `script.json` (`"plan"`): a spoken narration of 2 or 3 natural sentences, as a teacher
tells the class where the lesson goes (never a list read aloud), and for each later scene what it
will show, as written on screen ("Pourquoi une pile a 6 volts sans courant"), with the words of the
narration that announce it (`cue`). Each line slides in when the voice says them, the one being
announced lit in the accent colour; the list is centred under the titles. agent003 keeps the plan
only if it has one line per later scene, in order (`checked_plan`), else `"plan": null`, and agent010
then builds one from the scenes' titles ("Au programme. D'abord, <titre>. ... Et enfin, <titre>.");
`render_manifest.json` says which (`plan_source`: `script` or `titles`). Every scene after it shows
where it is in the plan, top right ("02 / 05" and one bar per chapter). No plan for a video of fewer
than three scenes (`PLAN_MIN_CHAPTERS`). The plan is a scene of `render_manifest.json`
(`"scene_id": "plan"`), so agent007's YouTube chapters, built from the rendered start times, include it.
A title, a subtitle, a label or an axis name written in LaTeX ("10^{-n}", "t_n") is shown with
Unicode exponents and indices ("10⁻ⁿ", "tₙ") when every character has one (`plain_math`).
A scene whose free components sit in a corner (no graph, no straight move) is moved to the middle of
the frame: vertically between the titles and the legend, and horizontally (left of the side column
when there is one; on a comparison, each panel's drawing in its panel, `PANEL_ROOM`) (`centre_content`).
agent004 sends back a battery standing in the column of the branches it feeds (one above it, one
below: its wires ran over them and their labels, `battery_in_column`). A counter
shows the decimals of its value, up to 3 (0,96, not 1,0). The video does not stop on a cut: its
last scene is held 2 s after the voice (`END_HOLD`), the last 1.2 s fading to the background
(`END_FADE`). agent003 is asked to close the video (answer the hook's question, sum up, a closing
sentence; never end on a question or an example left unexplained) and to keep one example's values
all along (a 6 V battery stays 6 V); agent005 checks both on the whole video and sends an unfinished
ending back to agent003. agent004 reports a BODY that neither moves nor sits on a graph (a disc
standing for "Prix du pain"). Check: `python tests/test_plan.py`.

**Fixes from the evaluation of 2026-11-02.** A vector or a curve named by its colour ("Bleu diffusé",
"Lumière rouge") is drawn in that colour whatever the brief says, and the arrows of one legend line
share one colour (`colour_by_name`). agent004 sends back a GAUGE that never gets a value
(`gauges_without_value`), and measures each scene's page before keeping a storyboard
(`app/render/layout_check.py`): the page is built and laid out by Chromium as agent010 will (theme,
subtitles' room), and what still overlaps, leaves the frame or enters the title zone goes back to the
LLM with the other advisory problems (about 2 s a video; without Chromium the check is skipped and
logged). A badge in a graph's empty margin is not a conflict. The axis titles are drawn over the
curves, outlined in the background colour, and every badge keeps off every graph's axis titles; a
badge over a formula or an icon costs more than one over a graph's empty plot. A graph with three
or more things beside it takes 48 % x 42 % of the frame. Check: `python tests/test_eval_fixes.py`.

**Pictures that demonstrate (reactive, to scale).** agent004's prompt asks for every key idea as an
action the viewer sees happen, in proportion to the numbers said:
- a VECTOR_ARROW with `"value"` (and `"unit"`) is drawn to scale with the other vectors of its unit
  (the largest 2.6 units long, `vectors_to_scale`); `set_value` on it later shrinks or grows it before
  the eyes with an elastic overshoot (588 N on the Earth to 96 N on the Moon), its label following;
- `set_state {"floating": true}` on an OBJECT or a BODY: it rises slowly (100 px over 3 s) and
  drifts, the vectors starting on it going along;
- SEESAW (`initial_state {"left": {"label", "weight", "value"}, "right": {...}, "unit"}`): each load
  drops onto its end (`set_state {"left": true}` / `{"right": true}`; a side never set is there from
  the start), the beam tips towards the heavier side on a damped spring (it overshoots, then settles),
  and `{"balanced": true}` slides the pivot under the beam until it balances: it then stands at the
  weighted mean of the two values,
  shown under it (30 x 15 + 5 x 10 over 35: 14,29 /20);
- SPEED_RACE (`initial_state {"distance": 1, "distance_unit": "m", "runners": [{"label": "Électron",
  "speed": 0.1, "unit": "mm/s", "icon": "atom"}, {"label": "Signal", "speed": 200000, "unit": "km/s",
  "icon": "zap"}]}`): the runners set off together (at the pop, or `set_state {"go": true}`) on one
  track, to one scale: the fastest crosses it in 2.5 s, the others at their share of its speed (the
  electron does not move a pixel); each lane then shows its runner's real time ("5 ns", "2 h 47 min")
  and the fastest how many times faster it goes ("2 000 milliards de fois plus rapide"). agent004 sends
  back a narration opposing a slow and a fast thing drawn with nothing showing the gap
  (`speeds_by_badges`);
- `start_flow` with `"carriers": "electrons"`: discs marked "−" going from − to + (slower than the
  conventional current's dots, the other way round); agent004 sends back BODY discs standing for
  electrons on a circuit (`electrons_as_discs`);
- a curve draws itself over 2.2 s with a dot at its head; a formula writes itself left to right.
agent004 also sends back a graph running 0 to 10 on both axes with no unit (`placeholder_graphs`:
"temps" / "PIB", a line over made-up numbers) and, on the electronics, physics and economics channels
(`FOOTAGE_DOMAINS`), a hook without a film. agent005's layout arbiter only squeezes a "circuit" scene
left of its instrument column, and keeps a comparison's things in their panel.
agent004 also sends back a scene of at least 8 s where nothing happens but things appearing and
being highlighted (`still_scenes`: no move, set_state, set_value, flow or measure, no formula written
or graph traced; a hook over a film excepted). On the page, what is wider than its room (its panel,
the main area) is made smaller (`fitToRoom`): a formula by its font size, a seesaw or toll lanes
scaled down. agent003 has each acronym said in full the first time it is spoken (hook, plan, then the
scenes: "le Bureau international du travail, le BIT"); a script using one before is asked again once
(`undefined_acronyms`), and agent003 is `not_healthy` if one is still left.
Check: `python tests/test_run_fixes.py`.

**Fixes from the evaluation of 2026-11-02 (16:05).** The videos had come out short (82 to 116 s): the
narrator speaks faster since ElevenLabs runs at speed 1.12 (3.0 to 3.3 words a second), so agent003
counts 3.1 and asks again once for a script under 280 words (see above). A probability
"P(chien | animal)" is no longer taken for a power or a pressure P (`formula_symbol`). agent004 gives
each scene the words the plan announced it by (`"announced"`, `announce`): its title says the same
idea and what it names is drawn (a spring: the new `spring` icon); agent005 gets the plan too and
treats an announced part its scene never shows as a factual issue. Axes named with no measure
("orbite", "hauteur": `measured_axis`) are a sketch, drawn without ticks nor numbers. POPULATION
(`initial_state {"total": 1000, "per": 10, "unit": "personnes", "groups": [{"id": "sick", "label":
"Malades", "count": 10, "color": "#DC2626"}, ...], "rest": "Bien portants"}`) draws a population as
a grid of dots to scale (10 000 people: 1000 dots of 10), each group coloured in, dot after dot, at
`set_state {"show": "<id>"}` (a group never shown is coloured from the start), `{"focus": [ids]}`
dimming every other dot ("parmi les positifs") and `{"focus": []}` bringing them back; the legend
gives each group's people (count x per). agent004 sends back GAUGEs counting people
(`people_by_gauges`: a fixed dial per group, the shares never seen). On a comparison page, what is
in a panel stays under its title (two dials stacked went over it), and a badge with a diagonal
direction also tries the four straight sides (it lay over a formula). agent004 sends back an icon in
total contradiction with its label (`icons_against_labels`): the label names a kind of thing
(`KIND_WORDS`: people, animals, vehicles, buildings, fire, water, plants, the sky) and the icon shows
another (`ICON_KINDS`: "Animaux" drawn as people), coins or a bank labelled with people, or a thing
with a component of its own drawn as an icon ("Pile" as a zap: a BATTERY); a battery shown alone
(no wire, no other circuit part) is no longer an open circuit, which had sent the LLM to the zap. A
badge's hyphen ("Qu'est-ce") is no longer read as the battery's "−" terminal. Animals in general have
the `paw-print` icon (36 content icons were added from Lucide: cat, snail, turtle, pill, syringe,
stethoscope, dice, vote, handshake, price tag, shopping basket, plug, fuel, tractor, wheat, milk...;
no decorative ones: no maths symbols, charts or interface icons, which formulas, graphs and
components already show), and a conditional probability read both ways ("chien sachant animal") is asked
as a POPULATION.
Check: `python tests/test_population_fixes.py`.

**Fixes from the evaluation of 2026-11-02 (21:02).** TIDES draws the Earth in its ocean and the Moon,
each step on the words that say it: the three points of the Earth-Moon line, labelled ("Point
proche", "Centre", "Point opposé"); the Moon's pull on each, to scale (strongest near); what is left
once the centre's pull is taken away (the water moves away from the centre on both sides); the ocean
stretched into two bulges, high tide, with low tide between and the word explained ("Bourrelet : la
bosse d'eau"); the Earth turning with a port that passes under both bulges ("En un jour : 2 marées
hautes"); the Sun in line (bigger bulges, vives-eaux) or at a right angle (mortes-eaux). Never given a
state, it plays them in turn. agent004 sends back tides drawn as droplets beside an Earth
(`tides_by_icons`). A technical word is explained in plain words the first time it is spoken
(agent003's prompt; agent005 sends the script back otherwise), and no title uses one before.
agent003 writes the video's question in everyday words (`"question"`, `checked_question`: "La
monnaie, ce n'est que des pièces et des billets ?"), which agent004 makes the hook's title
(`ask_the_question`, the LLM's title kept as the subtitle). On the voltmeter, a probe on a battery
terminal touches its sign, and the meter says where each probe is ("Rouge : GND (0 V)", "Noire : Pile
6 V (−)"). A formula is cut on its right only while it writes itself, then not at all: a formula on
several rows (cases) was shown with its middle row only.
Check: `python tests/test_tides_fixes.py`.

**What a run costs.** Every LLM call records its tokens (input, of which cached, and output, thinking
included: `tracked` in `app/agent/__init__.py`), every voice-over the characters sent to its engine
(`app/tts_manager.py`). When an agent finishes, its records are priced with `settings.json`
`"prices"` (per million tokens, cached input at its own price; per thousand characters) and added to
`instance/{channel}/costs.json`, the ledger of the channel's current run, per agent and in total;
the agent's row in `rows.json` gets its own `"cost"`. At the end of a channel's run the orchestrator
prints one line ("breeze_(math): cost 0,62 $ (LLM 0,14 $, 23 calls...; voice 0,48 $, 2 180
characters)"), appends the run to `instance/costs_history.json` (with the video's length and each
agent's share) and keeps the total in `instance/breeze.json`. A provider or engine with no price is
counted and named (`unpriced`), its cost left out. The prices are written by hand, from memory: check
them on DeepSeek's and ElevenLabs' price pages (an ElevenLabs subscription's real price per character
depends on the plan and how much of it is used). Check: `python tests/test_costs.py`.

**Logic and FPGA (the FPGA run of 2026-11-03, rejected three times for want of them).**
LOGIC_CIRCUIT draws a small logic diagram from what feeds what: the inputs (a box showing 0 or 1),
the gates in their standard shapes with their French names (ET, OU, NON, OU exclusif, NON-ET,
NON-OU) and their value, the outputs as lamps; laid out in Python by depth (`logic_data`), computed
by the page: a wire at 1 glows green. `set_state {"a": 1}` sets an input; `{"mode": "sequential"}`
makes the gates work one after the other (a program's steps, 0.8 s each, the gate at work outlined),
`"parallel"` all at once (a circuit). FPGA_GRID draws the logic blocks and the routing channels:
`configure` slides the bitstream in and places the design block by block, the routes between them
lit, what has no block listed in red ("Ressources insuffisantes"); `run` sends signals along every
route at once; `reconfigure` clears the blocks and places the second design. agent004 sends back gates
or blocks drawn as other components labelled so (`gates_by_hand`: a WIRE_BUS "Porte ET").
The orchestrator stops a channel whose QA rejects to agent004 listing what cannot be drawn
("unsupported") for the second time in the run (`UNSUPPORTED_ROUNDS`): the FPGA run paid three
redos for nothing. Every such list goes to `instance/missing_components.json`, the components to
build next. Check: `python tests/test_logic_fpga.py`, `python tests/test_orchestrator_unsupported_loop.py`.

**Fixes from the hard-topic runs of 2026-11-03.** TUNNEL draws the tunnel effect: a small circuit
first, a dashed frame on its wire ("Vue agrandie du fil"); the view zooms into the frame, which
becomes a tube, a blue dot in it, the wall a vertical line across the tube; `bounce` takes the dot to
the wall and back (what we expect), `tunnel` takes it through: at the wall the dot becomes a wave, a
weaker part of it beyond the wall ("Une onde, pas une bille"), then it comes out whole on the other side. agent004 sends back the effect drawn as icons (`tunnel_by_icons`: an atom
beside a door). The voice spells an acronym as one hyphenated word, each letter as it sounds
("FPGA" -> "èf-pé-jé-a"): the letter names written out ("effe pé gé a") came out garbled. The logic
gates' words in capitals (ET, OU, NON, NON-ET) are said as words, not spelled (`CAPITAL_WORDS`). agent003
takes ET, OU, NON for words, and an English acronym said with what it is ("un FPGA, c'est-à-dire
une puce...") as explained. An FPGA block's name may take 18 characters, on two lines. A
LOGIC_CIRCUIT input may also be set as `{"values": {"b": 1}}` (as the QA writes it). FPGA_GRID
`{"zoom": "ET"}` zooms on the block holding that function and draws its inside (the gate, or a small
table, a LUT, for another function), `{"zoom": false}` zooms back out; `{"wire": true}` shows the
interconnect: a switch at each channel crossing closes, route after route, the signal runs along.
The bitstream is drawn as a file of bits beside the grid; while it configures, a packet of its bits
flies to each block just before it gets its function, under the note "Le bitstream : le fichier qui
dit à chaque bloc quelle fonction faire".

**The camera: going inside a thing.** Wherever the narration goes into a thing ("à l'intérieur de la
puce", "de plus près", "au cœur de la cellule"), the camera shows it: `{"action": "zoom_in", "target":
id}` frames the thing with a dashed line and dives into it, then the scene fades; the next scene, its
inside, grows in from the middle (it arrives from the zoom). `{"action": "zoom_out", "target": id}` at
a scene's start begins on the thing and pulls back to the whole. Everything drawn moves (`#world`), the
titles, subtitles and background never do. agent004 sends back a narration going inside a thing with
no zoom before it, a zoom_in followed by seconds of narration, a zoom_out late in its scene
(`zoom_problems`; TUNNEL and an FPGA_GRID's own zoom count). Check: `python tests/test_zoom.py`.

**A program at work.** A LOGIC_CIRCUIT set to `"sequential"` shows, on its right, the same circuit as a
program: one line per gate ("r1 = Bouton 1 ET Bouton 2"), then the outputs, a pointer on the line at
work in step with the gates; in `"parallel"` the lines dim (`with_program` sets `"program": true`,
`logic_size` makes room). MICROCONTROLLER draws a chip with its program memory (numbered
instructions) and ONE unit: `run` takes the instructions one after the other along the bus into the
unit ("Une instruction à la fois : 2 / 4"); beside an FPGA_GRID it shows the difference with blocks
working all at once. agent004 sends back a cpu icon labelled "Microcontrôleur" or "Processeur".
Check: `python tests/test_program_mcu.py`.

**Building a circuit for real (the temperature-regulation bench).** The schematic parts are the
standard symbols (IEC, as in French schools), wired by their named leads: a resistor, a
potentiometer (its wiper a setpoint), a CTN, an AOP (+ and − inputs, output, supply), an N-channel
MOSFET, a diode, an LED (lit on `on`), a heating resistor (red, heat rising, on `on`). As on a real
schematic, each part fed by the supply has its own `SUPPLY_RAIL` ("+12 V") and each part to 0 V its
own `CHASSIS_MASS`, never long wires back to the battery; a junction dot marks a lead where two
wires meet. A schematic scene (4 such parts or more) may hold 16 entities (8 otherwise). Built step
by step: each scene adds a stage, each part spawns on its words and its wires draw themselves when
both ends are there, or on `{"action": "connect", "source_id", "target_id"}`. BREADBOARD builds the
same circuit on a breadboard from its parts and nets only (`app/breadboard.py` lays it out: the
DIP-8 op-amp across the gap, each part plugged into the column strips of what it joins, its body over
no other part, a jumper where a net must reach another strip, every strip of "+12 V" / "0 V" jumpered
to the red / blue rail fed by the supply); `{"step": n}` plugs the parts in, in their order. A
voltmeter measures on the board too: a probe on "<board id>.<part id>.<lead>" lands on that lead's hole. Two entities given the same named place
("RIGHT") are no longer sent back: the second is put beside it (`spread_shared_places`), a schematic
of a dozen parts having more than the 9 places. A ground or supply symbol the LLM wired to several parts is split
into one symbol beside each part, coming in with it (`split_rails`, in the layout and on the page). A
schematic's parts are laid out by the program (`place_schematic`), not where the LLM put them: one
column per stage of the signal at a fixed x (sensors and setpoint, divider, AOP, gate, MOSFET, load: a
part keeps its place from one build step to the next), a resistor or diode at the stage between what
it joins, in a column the parts ordered by what they are wired to (the AOP's − input above its +),
each ground or supply symbol at the end of its lead. Wires of one node (leads joined) share their way and part at a
junction dot, rather than running side by side (`wireNets`, `sharedLength`); "37 °C" is said "37
degrés Celsius", "90°" "90 degrés"; agent003 writes a temperature in digits with "degrés Celsius"
(the voice garbled "trente-sept degrés" written in words).

**WAVE.** A mechanical wave drawn as the medium it travels in: a rope (a smooth curve, a bump
crossing it), the sea (its surface over blue water, a buoy), a crowd (an ola: spectators in a row
standing up and sitting down in turn), a spring (coils squeezed and spread, a longitudinal wave as
sound, "Compression" and "Dilatation" named where they are). `mark`: one point (the buoy, a spectator,
a coil) picked out with its path, only up and down (or back and forth), never along; `energy`: an
arrow "Énergie" going with the bump or the wave's front. `kind: "standing"`: a rope tied at both ends
("Fixée"), its nodes still (green, named), its antinodes swinging, `loops` 1 to 6 antinodes (the
harmonic); `parts` the two waves going opposite ways it is the sum of, each on its own rope over it
("Onde qui va →" blue, "← Onde qui revient" pink), then "=" the rope. agent004 sends back a standing
wave drawn travelling, and the two waves spoken of but not shown (`standing_waves`); a standing wave
has no energy arrow (its energy does not travel). One wide drawing set alike in more than 3 scenes is
sent back (`repeated_drawings`): each scene shows its own point (another harmonic, the two waves...).

**Formulas in physics and maths.** agent003 says the key relation of the topic at least once, in
words with the example's values (`FORMULA_RULES`, for the "math" and "physics_math" domains); agent004
writes a relation said as a TEX_FORMULA in that scene and sends back a physics or maths video with
none (`formulas_said`). Check: `python tests/test_formulas.py`.

**The pieces catalogue.** `docs/pieces/` holds the user's 131 piece specifications (the four CSV files,
their columns one to the left of their header: `catalogue.json` reads them right), grouped into 76
pieces to build and ordered simplest first (`ORDRE.md`); each entry's "etat" says "fait", "partiel" or
"à faire". Built: every simple piece, each figure on it worked out by the program, never given by the brief:
TABLE (its total summed, French figures, a unit kept), CHAIN (steps and arrows, a loop around them),
TIMELINE (to scale when the dates are years), FRACTION_BAR (the sum as a fraction and a percentage),
PIE_CHART (shares adding up to 100 %), UNIT_CONVERTER (the units' ladder, the factor, the result),
TREE (a path's probability, the product), SET_DIAGRAM (two sets, each region counted, its probability),
GAME_MATRIX (best answers, the Nash equilibrium), BAR_CHART (one scale, negatives below, a reference
line), EQUATION_STEPS (LaTeX lines, what is done on each arrow), POWER_SUPPLY (a bench supply wired
like a battery: CV / CC), and the multimeter as an ohmmeter (a "measure" in Ω: its mode, a beep under
30 Ω, its range as on a real one: 4,700 kΩ). The reading is checked against the circuit drawn: agent004
works out the resistance between the probes from the labels (`ohmmeter_problems`: two 1 kΩ across the
same pins read 500 Ω, a part faded out is gone) and sends back a wrong value, a supply drawn as "the
ohmmeter's source" or left on. Units are written with their prefix (`si_prefixes`: "1 000 Ω" -> "1 kΩ",
"0,01 A" -> "10 mA"), the voice says "kilo-ohms" (`tests/test_ohmmeter.py`). Check:
`python tests/test_table_chain.py`, `python tests/test_simple_pieces.py`. Physics, worked out by the program from the data
(exact motions, conservation laws): FREE_BODY (forces to scale, components along the slope, the
resultant, a = ΣF / m), KINEMATICS (a projectile, a uniform, accelerated or free fall: strobe images,
v and a, x(t) and v(t)), COLLISION (velocities after an elastic or inelastic collision, momentum and
energy before / after), OSCILLATOR (a damped spring or a pendulum: the motion, Ec / Ep, x(t), the
period), ORBIT (Kepler's equation solved each frame: faster near the centre, the pull in 1/r², equal
areas; P and A always named, {"ratio": true} their distances r_P, r_A and v_P / v_A = (1 + e) / (1 − e)
worked out). Check: `python tests/test_physics_pieces.py`. agent004 sends back a wave drawn as discs or
icons (`waves_by_hand`: the rope of five scattered discs, the ola of icons all over).
A scene with a drawing as wide as the screen (WAVE, TIDES, TUNNEL, BREADBOARD, LOGIC_CIRCUIT...) stays
"circuit", never a comparison's half panel (`WIDE_DRAWINGS`, `needs_circuit`). Check: `python tests/test_wave.py`.

A circuit built step by step keeps what is built: a schematic scene sharing most of the last one's parts
(60 %, a preview of the whole circuit then a first step is not one) gets back every part, ground / supply symbol and wire of it left out (`carry_circuit`; a part of the same type and label under another id is
the same part, not put back twice);
a schematic's 0 V / +12 V symbols do not count in its 16 entities, and its parts' positions are not
checked (the program lays them out). A project's hook starts from what
it is for in everyday life (an incubator, an aquarium, a 3D printer's bed) before naming what is built.
Check: `python tests/test_schematic.py`.

**Keeping the frame clear.** A plan of many chapters goes over pages of `PLAN_PAGE` (6) rows, the next
page in place of the last when its first chapter is named. Things still overlapping once spread out
(the frame too small for them all): the bigger one, never a graph, is made 15 % smaller and they are
spread again, up to four times (`shrinkToFit`). A badge may take a longer arrow (up to `ARROW_MAX` +
300 px) rather than sit on another. The conflict check counts a graph by its drawn part (its empty
margins may hold anything) and leaves out two things never on screen together.
Check: `python tests/test_overlaps.py`.

**The project format.** A topic to build ("réaliser", "construire", "monter", "banc", "projet",
"pas à pas") is a project made step by step, not one concept explained: agent001 researches its build
stages (research "format": "project", the topic as its concept), agent002 plans one beat per stage in
the order it is built (`PROJECT_PROMPT`), agent003 writes one stage a scene (the parts it adds with
their values, what is connected to what, how to check it), the breadboard build then the power-up
last (`PROJECT_RULES`); agent004 is given the wiring of an AOP comparator with hysteresis.
Check: `python tests/test_project_format.py`. Words the voice
says wrong are written as they sound in `PRONUNCIATIONS` (`app/tts_manager.py`: "quantum" ->
"kwantome"); add any other there. A hook clip seen to be wrong goes, by hand, in
`assets/footage/index.json` "rejected" (`{"pixabay:<id>": "why"}`): never offered again nor taken from
the cache (the electrician at a panel picked for "usine de puces"); the chooser is told that an
electrical panel or power cables are not electronics.
Check: `python tests/test_tunnel.py`, `python tests/test_logic_fpga.py`.

A badge naming one terminal of a battery ("borne +", "pôle négatif") points at that terminal's sign
on the drawing, not at the battery as a whole (`batteryTerminal`); no badge's arrow runs through
another badge. A number line's graduations are 1, 2 or 5 times a power of ten (0 to 10 000: every 1 000), never "-0", and a number
under a dot's label, or too close to the previous one, is hidden. Counters roll in 0.8 s.
Check: `python tests/test_reactive.py`.

**Film behind the hook.** agent004 may give the first scene a real film clip: `"footage": {"query":
"ciel bleu nuages"}` on the storyboard scene (1 to 4 French words, letters only; people far off, never a face in close-up), with at
most 3 things drawn over it. agent010 finds the clip (`app/render/footage.py`): a clip of
`assets/footage/local/` whose file name shares a word with the query first, then one already fetched
for that query (`assets/footage/index.json`), then Pixabay's video search (`PIXABAY_API_KEY`; only the
query is sent). A Pixabay clip is taken only if rated for everyone, not low quality, at least 6 s long,
on Pixabay's CDN, with no face in the foreground (portrait, close-up, selfie) or brand in its tags, and not a made-up picture (AI-generated, 3D
render, animation, exoplanet, fiction). agent004 looks for the hook's clip as soon as the storyboard is
settled: the LLM reads the tags of the first 8 allowed clips against the hook's narration and picks the
one that shows the subject, or none (an oil lamp for an electric lamp, Titan for the Moon); none: the
hook is drawn without a film (agent004's report, `footage`). A clip fetched without that choice is
searched again. It is downloaded once (at most 80 MB, 1920 wide when there is one) and indexed with its
id, page, author, query and date, the queries chosen for a narration under `checked`. ffmpeg cuts it into
the scene's frames (looped if short, cropped to fill 1920 x 1080), which the page shows full-frame
behind the scene, darkened, the titles in white; `seek` waits until each frame is decoded.
`render_manifest.json` records the clip of each scene (`footage`), agent007 credits each Pixabay clip in
the description ("Images : <author> sur Pixabay (<page>)"), agent005 is told a film plays behind the
scene. No clip found (no match, no key, network): the scene is drawn without one, agent010
`not_healthy`. The clips are git-ignored, `index.json` is kept. Check: `python tests/test_footage.py`.

**Music and sound effects.** Everything under the voice is made by the code (`app/render/soundtrack.py`,
numpy): no clip, no licence, no Content ID claim. A music bed the length of the video, in the channel's
mood (electronics: A minor, brisk; physics: D minor, slow; maths: C major; economics: F major) and the
style of the settings (`"music_style_by_channel"`: cinematic for electronics and physics, ambient for
maths and economics; else `"music_style"`): `"ambient"` (soft chords, a bass note, a light arpeggio),
`"lofi"` (electric piano chords, a soft kick, hats and rim, a little vinyl hiss) or `"cinematic"` (a
slow string pad, low piano notes, a quiet pulse); faded in and out, the same for the same channel. Sound effects on
the animation: a soft "pop" when a thing appears (spawn, and each line of the plan), a "tick" when a
value changes (set_value), a "whoosh" between two scenes; effects closer than 0.25 s are one.
`app/render/video.py` mixes them under the voice before the loudness pass (still -16 LUFS): the music
21 LU below the voice and ducked while someone speaks (sidechain), the effects' peaks 6 dB above the
voice's loudness. `render_manifest.json` says what was added (`soundtrack`).
`"background_music": false` / `"sound_effects": false` in the settings leave either out.
Check: `python tests/test_soundtrack.py`.

**Subtitles.** Each scene's narration (the plan's too) is cut into short lines (`app/render/subtitles.py`:
at most about 62 characters, cut at a sentence's end or a comma, a long sentence into lines of even
length), each timed on the voice's word timings, found through the text as the voice reads it
(numbers and units spelled out), and shown as written ("0,96 A"). The page draws the line being said
at the bottom (`#subs`); the diagram, the vectors' legend and a comparison's panels stay above it.
The whole video's lines go to `instance/<channel>/subtitles.srt` (`subtitles_path` in
`render_manifest.json`), which agent008 sends to YouTube as the French captions.
`"burn_subtitles": false` in the settings keeps them out of the picture (the file is still written).
Check: `python tests/test_subtitles_lanes.py`.

agent010 draws each scene as a web page:

- One HTML page per scene: SVG wires, curves and vectors, HTML components, Lucide icons.
  Text written by the LLM is inserted with `textContent`, so it never runs as code.
- Headless Chromium (Playwright) opens the page and calls `seek(t)` for every frame (30 fps).
  `seek` draws the scene at time t, so frames are exact whatever the machine's speed. Each frame is
  piped as a JPEG into ffmpeg, then muxed with the voice.
- **Wires:** right-angle paths, routed after layout, around the components and their labels.
  Each side of a component carries at most one wire; crossings and wires running side by side are
  avoided when another path exists.
- **Graphs:** `AXES_GRAPH` draws SVG axes (70 % of the frame's width, 60 % of its height) with numbered ticks (none along an axis named with no measure); `CURVE_PLOT` points are computed in Python
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

agent010 makes each scene's voice with `generate_voice(text, mp3_path, spoken, engine, voice_id)`:

1. **ElevenLabs** when `ELEVENLABS_API_KEY` is in `.env`: model `eleven_multilingual_v2`, a voice per
   channel (`"voice_by_channel"` in `schemas/settings.json`: Nicolas - Narrator for electronics and
   physics, Anaïs - Instructor for maths and economics; Voice Library voices, used by their id alone).
   A channel without one gets `ELEVENLABS_VOICE_ID`, else "Olivier D" (`GFj5Qf6cNQ3Lgp8VKBwc`).
   Settings: stability 0.5 (below, the voice now and then restarts a sentence), style 0.2, speed 1.12
   (the pace and short pauses of the educators it was compared with: 5.5 to 6.9 syllables a second
   while speaking, pauses of 0.2 to 0.3 s). `ELEVENLABS_MODEL_ID` changes the model. It calls the `with-timestamps` endpoint (plain
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
   refresh token per channel with the scopes `youtube.upload`, `youtube.readonly`,
   `yt-analytics.readonly` and `youtube.force-ssl` (the captions), then set `"enabled_platforms": ["youtube"]`.
5. Videos are uploaded as **private**: review them in YouTube Studio, then make them public.
   Each upload costs 1,600 of the 10,000 daily quota units (400 more for its captions,
   `subtitles.srt`), and agent008 refuses to upload when the quota would be exceeded. Captions that
   fail to go up (a token without `youtube.force-ssl`) leave the video published, agent008 `not_healthy`.
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

## Agent count clarification

The repository has ten agent modules: `agent000` is the orchestrator and nine processing modules are `agent001`-`agent005` and `agent007`-`agent010` (`agent006` is retired). `agent009` runs once per full cycle; the other eight processing agents run once per channel, including `agent010` for rendering. The introductory phrase “all nine per channel” counts the shared `agent009` role, not nine separate executions on every channel.
