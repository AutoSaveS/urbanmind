# Demo video shot list (supplementary material)

Goal: one unedited screen recording (5–7 min) that documents the live backend
chain end to end, complementing the released per-run logs. No cuts inside a timing
run; keep the system clock visible throughout (menu bar).

## Setup shown on screen

1. Terminal 1: start the backend — `python -m urbanmind.gh_bridge.server --port 8787`
   with the model checkpoint path visible in the startup log.
2. Terminal 2: `tail -f runs/<case>.jsonl` so every request appends a visible
   timestamped log line during the session.
3. Rhino/Grasshopper with the case canvas open (pick one case, e.g. NYC).

## Sequence

| # | Action | What it proves |
|---|--------|----------------|
| 1 | Show `git log -1` and `pip show urbanmind` / repo folder | code identity matches the GitHub release |
| 2 | Start server; show hardware snapshot line in the log | hardware/caching conditions match the manuscript table |
| 3 | Two warm-up edits (say aloud/subtitle that these are discarded) | warm-up protocol matches Section 5.4 |
| 4 | Slider edit: canopy fraction. Wait, without cuts, until four-domain maps + uncertainty layer return | end-to-end latency, wall clock visible |
| 5 | Show the new JSONL line: timestamp, elapsed_s | video and released logs are the same evidence chain |
| 6 | Repeat for roof albedo and building height edits (3–5 timed edits total) | latency is typical, not cherry-picked |
| 7 | Toggle uncertainty layer and BCI summary | Stage-3 outputs are model-returned, not precomputed |
| 8 | Kill the server, repeat one edit, show the Grasshopper error | the canvas genuinely depends on the backend |
| 9 | Close-up of `runs/<case>.jsonl` and `bench.summary()` output | summary statistics derive from the logged runs |

## Framing rules

- State on screen (subtitle or title card): "The web interface mock-up is a concept
  illustration only; this video shows the live backend."
- Do not speed up or trim any interval between an edit and the returned output.
- Publish the exact log file produced during the recording with the supplementary
  data, named to match the video (e.g. `runs/video_session_nyc.jsonl`).
