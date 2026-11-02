# The Manim renderer (agent006), retired

breeze renders every video with agent010, the HTML renderer (a browser draws each frame, see the
main README). The Manim renderer was retired on 2026-10-31: it is no longer called by the orchestrator,
no longer tested, and `manim` is no longer in `requirements.txt`. Its code is kept here, as it was on
that day, in the same folders as in the project:

| File here | Was |
|---|---|
| `app/agent/agent006_animationrenderer.py` | the agent: voice, Manim subprocess per scene, ffmpeg |
| `app/render/breeze_engine.py` | the engine playing a visual brief in Manim |
| `app/render/components/base.py` | the Manim components (battery, lamp, curve, vector, body...) |
| `test_single_scene.py` | renders one scene with the engine |

What agent010 still needed from agent006 (frame size and rate, encoding, error screen, picture +
voice per scene, concatenation, loudness to -14 LUFS, storyboard check) moved to
`app/render/video.py`.

To bring it back: move the files to the same places in the project, `pip install manim` (and its
system libraries: cairo, pango), add agent006 back to `AGENTS` in `app/agent/agent000_breeze.py`, and
point its imports from `app.render.video` where needed (the shared helpers above left agent006). The
features added later (OBJECT, BODY and move_along, anchors on a point of a graph...) were last kept in
step with it on 2026-10-31.
