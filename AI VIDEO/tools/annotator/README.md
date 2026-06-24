# Local Truth Annotator

The annotator is a local single-page tool backed by a small Python server. It
reads projects from `projects/`, streams take videos, and saves truth JSON under
`projects/<project_id>/truth/<shot_id>/`.

## Run

```powershell
python tools/annotator/server.py --port 8765
```

Open `http://127.0.0.1:8765`.

## Input Layout

```text
projects/<project_id>/
  manifest.json
  shots/<shot_id>/
    shot_spec.json
    take_001.mp4
    take_002.mp4
  truth/<shot_id>/
```

## Controls

- Left / Right: step one frame.
- Shift + Left / Right: step ten frames.
- I / O: set `source_in_ms` / `source_out_ms`.
- A / R / E: set `action_start_ms`, `result_first_visible_ms`, and `result_hold_end_ms`.
- N / D: add or delete the current window.
- X: toggle usable versus rejected.
- G: cycle the current window grade.
- S: save the current truth file.

The annotator validates event ordering before saving. Result-hold duration below
`shot_spec.timing.min_result_hold_ms` is shown as a warning so the human
annotator can still decide whether the window should be grade D.
