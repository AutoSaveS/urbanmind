# Grasshopper segment — 30-second recording checklist

The supplementary video has two segments. Segment 1 (backend viewer,
`docs/media/urbanmind_backend_demo.mp4` source session) is already recorded.
Segment 2 shows the same backend driven from Grasshopper and must be recorded
on a machine with Rhino 8 installed.

## One-time setup (5 minutes)

1. Copy this repository onto the Rhino machine (or just `demo/` +
   `urbanmind/` + `gh_bridge/`), install deps: `pip install torch numpy`.
2. Train the synthetic reference model once: `python demo/train_synthetic.py`.
3. Start the backend: `python demo/serve_demo.py` — leave this terminal
   visible; it prints one line per request.
4. In Grasshopper, drop a **Python 3 Script** component. Give it inputs
   `canopy` (Number), `albedo` (Number), `run` (Boolean), and outputs
   `meshes`, `latency`, `log`. Paste `gh_bridge/UrbanMind_GH_component.py`
   into it.
5. Wire two number sliders (canopy: 0–0.30, albedo: 0–0.40) and a Boolean
   toggle. Connect `meshes` to a Custom Preview or directly view in Rhino.

## Shot list (aim for 25–35 s)

| Time | Action | What must be visible |
| --- | --- | --- |
| 0–5 s | Full screen: Rhino viewport + GH canvas + backend terminal side by side | The three windows together — this is the authenticity shot |
| 5–15 s | Drag the **canopy** slider up slowly | Four relief meshes update in the viewport; terminal prints a request line per drag step; `latency` panel shows ~15–40 ms |
| 15–25 s | Drag the **albedo** slider up | Building-energy and thermal panels respond; terminal keeps logging |
| 25–30 s | Zoom into the thermal mesh briefly, then cut | Vertex-colored relief, no post-processing |

## Framing rules (keep the video defensible)

- Record in one continuous take, no cuts within a slider drag.
- Keep the backend terminal in frame whenever a slider moves, so every
  geometry update is visibly paired with a logged request.
- Keep the "synthetic reference model" wording on screen (title slide or
  a text panel on the GH canvas). Do not imply these are the manuscript's
  empirical results.
- 1080p or higher, system audio off, no voiceover needed (captions are
  added afterwards).

Send the raw screen recording back; concatenation with segment 1, captions,
and compression are handled here (`ffmpeg` pipeline already set up).
