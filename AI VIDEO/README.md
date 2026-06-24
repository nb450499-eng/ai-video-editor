# AI Clip Step 0 Scaffold

This repository is being rebuilt around step 0 of the execution plan:
truth annotation for single-take valid-window extraction.

## What Is Implemented

- Pydantic v2 schemas for `shot_spec.json`, `*.truth.json`, timeline items, take analysis, and valid windows.
- A sample project scaffold under `projects/example_wirestripper/`.
- Golden truth fixtures under `tests/golden_windows/`.
- A local browser annotator under `tools/annotator/`.
- CLI validation for project manifests and truth fixtures.

## Project Layout

```text
projects/<project_id>/
  manifest.json
  shots/<shot_id>/
    shot_spec.json
    take_001.mp4
  truth/<shot_id>/
    take_001.truth.json
  truth/split.json
```

Keep raw take videos read-only. The annotator writes only to `truth/`.

## Commands

Validate the example project:

```powershell
python -m ai_clip.manifest.validator projects/example_wirestripper
```

Validate sample truth fixtures:

```powershell
python tools/validate_golden_windows.py
```

Run the local annotator:

```powershell
python tools/annotator/server.py --port 8765
```

Then open `http://127.0.0.1:8765`.
