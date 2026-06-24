from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .loader import iter_truth_paths, load_project_manifest, read_json_model
from .schemas import ProjectManifest, ShotSpec, TruthFile


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def validate_project(project_root: Path) -> list[str]:
    issues: list[str] = []

    manifest_path = project_root / "manifest.json"
    try:
        manifest = read_json_model(manifest_path, ProjectManifest)
    except Exception as exc:  # noqa: BLE001 - return validation diagnostics to CLI users.
        return [f"{manifest_path}: {exc}"]

    for shot_id in manifest.shot_ids:
        shot_dir = project_root / manifest.shots_root / shot_id
        spec_path = shot_dir / "shot_spec.json"
        if not shot_dir.exists():
            issues.append(f"{shot_dir}: shot directory is missing")
            continue
        if not spec_path.exists():
            issues.append(f"{spec_path}: shot_spec.json is missing")
        else:
            try:
                spec = read_json_model(spec_path, ShotSpec)
                if spec.shot_id != shot_id:
                    issues.append(f"{spec_path}: shot_id does not match folder name")
                if spec.folder.replace("\\", "/") != f"{manifest.shots_root}/{shot_id}":
                    issues.append(f"{spec_path}: folder should be '{manifest.shots_root}/{shot_id}'")
            except ValidationError as exc:
                issues.append(f"{spec_path}: {exc}")

        for video_path in shot_dir.iterdir() if shot_dir.exists() else []:
            if video_path.suffix.lower() in VIDEO_EXTENSIONS and not video_path.stem.startswith("take_"):
                issues.append(f"{video_path}: take video must be named take_NNN{video_path.suffix.lower()}")

    truth_paths = iter_truth_paths(project_root, manifest)
    for truth_path in truth_paths:
        try:
            truth = read_json_model(truth_path, TruthFile)
        except ValidationError as exc:
            issues.append(f"{truth_path}: {exc}")
            continue

        shot_dir = project_root / manifest.shots_root / truth.shot_id
        take_name = truth.asset_id.split("/", 1)[1]
        if not any((shot_dir / f"{take_name}{ext}").exists() for ext in VIDEO_EXTENSIONS):
            issues.append(f"{truth_path}: source video for {truth.asset_id} is not present")

    split_path = project_root / manifest.truth_root / "split.json"
    if split_path.exists():
        try:
            split = json.loads(split_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"{split_path}: {exc}")
        else:
            for key in ("dev", "val", "locked_test"):
                if key not in split:
                    issues.append(f"{split_path}: missing '{key}' split")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an ai-clip project manifest and truth files.")
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    if not project_root.exists():
        print(f"{project_root}: project does not exist", file=sys.stderr)
        return 2

    try:
        load_project_manifest(project_root)
    except Exception as exc:  # noqa: BLE001
        print(f"{project_root / 'manifest.json'}: {exc}", file=sys.stderr)
        return 1

    issues = validate_project(project_root)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1

    print(f"OK: {project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
