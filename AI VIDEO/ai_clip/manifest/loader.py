from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .schemas import ProjectManifest, ShotSpec, TruthFile


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ProjectBundle:
    root: Path
    manifest: ProjectManifest
    shot_specs: dict[str, ShotSpec]
    truth_files: list[TruthFile]


def read_json_model(path: Path, model: type[T]) -> T:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_json_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_project_manifest(project_root: Path) -> ProjectManifest:
    return read_json_model(project_root / "manifest.json", ProjectManifest)


def load_shot_spec(project_root: Path, manifest: ProjectManifest, shot_id: str) -> ShotSpec:
    path = project_root / manifest.shots_root / shot_id / "shot_spec.json"
    return read_json_model(path, ShotSpec)


def iter_truth_paths(project_root: Path, manifest: ProjectManifest) -> list[Path]:
    truth_root = project_root / manifest.truth_root
    if not truth_root.exists():
        return []
    return sorted(set(truth_root.glob("*/*.truth.json")) | set(truth_root.glob("*/*.*.truth.json")))


def load_truth_files(project_root: Path, manifest: ProjectManifest) -> list[TruthFile]:
    return [read_json_model(path, TruthFile) for path in iter_truth_paths(project_root, manifest)]


def load_project(project_root: Path) -> ProjectBundle:
    manifest = load_project_manifest(project_root)
    shot_specs = {
        shot_id: load_shot_spec(project_root, manifest, shot_id)
        for shot_id in manifest.shot_ids
        if (project_root / manifest.shots_root / shot_id / "shot_spec.json").exists()
    }
    truth_files = load_truth_files(project_root, manifest)
    return ProjectBundle(
        root=project_root,
        manifest=manifest,
        shot_specs=shot_specs,
        truth_files=truth_files,
    )
