from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools" / "annotator"
PROJECTS_DIR = ROOT / "projects"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_clip.manifest.loader import load_project_manifest, read_json_model  # noqa: E402
from ai_clip.manifest.schemas import ShotSpec, TruthFile  # noqa: E402


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_TAKE_RE = re.compile(r"^take_\d{3}$")
SAFE_ANNOTATOR_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def project_root(project_id: str) -> Path:
    if not SAFE_ID_RE.match(project_id):
        raise ValueError("invalid project_id")
    root = (PROJECTS_DIR / project_id).resolve()
    if not is_relative_to(root, PROJECTS_DIR):
        raise ValueError("invalid project path")
    return root


def truth_filename(take_name: str, annotator: str) -> str:
    if not SAFE_TAKE_RE.match(take_name):
        raise ValueError("invalid take name")
    if annotator and annotator != "primary":
        if not SAFE_ANNOTATOR_RE.match(annotator):
            raise ValueError("invalid annotator")
        return f"{take_name}.{annotator}.truth.json"
    return f"{take_name}.truth.json"


class AnnotatorHandler(BaseHTTPRequestHandler):
    server_version = "AIClipAnnotator/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"", "/"}:
                self.serve_static(TOOLS_DIR / "index.html")
            elif parsed.path.startswith("/static/"):
                rel = parsed.path.removeprefix("/static/")
                self.serve_static((TOOLS_DIR / rel).resolve())
            elif parsed.path == "/api/projects":
                self.handle_projects()
            elif parsed.path == "/api/project":
                self.handle_project(parsed.query)
            elif parsed.path == "/api/shot_spec":
                self.handle_shot_spec(parsed.query)
            elif parsed.path == "/api/truth":
                self.handle_get_truth(parsed.query)
            elif parsed.path == "/media":
                self.handle_media(parsed.query)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/truth":
                self.handle_save_truth()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", file=sys.stderr)

    def read_body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path: Path) -> None:
        path = path.resolve()
        if not is_relative_to(path, TOOLS_DIR) or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type, _ = mimetypes.guess_type(str(path))
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_projects(self) -> None:
        projects = []
        if PROJECTS_DIR.exists():
            for manifest_path in sorted(PROJECTS_DIR.glob("*/manifest.json")):
                try:
                    manifest = load_project_manifest(manifest_path.parent)
                except Exception as exc:  # noqa: BLE001
                    projects.append(
                        {
                            "project_id": manifest_path.parent.name,
                            "product": "",
                            "error": str(exc),
                        }
                    )
                    continue
                projects.append(
                    {
                        "project_id": manifest.project_id,
                        "product": manifest.product,
                    }
                )
        self.send_json({"projects": projects})

    def handle_project(self, query: str) -> None:
        params = parse_qs(query)
        project_id = params.get("project_id", [""])[0]
        root = project_root(project_id)
        manifest = load_project_manifest(root)

        shots = []
        for shot_id in manifest.shot_ids:
            shot_dir = root / manifest.shots_root / shot_id
            truth_dir = root / manifest.truth_root / shot_id
            takes = []
            if shot_dir.exists():
                for video_path in sorted(shot_dir.iterdir()):
                    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    take_name = video_path.stem
                    if not SAFE_TAKE_RE.match(take_name):
                        continue
                    truth_files = []
                    if truth_dir.exists():
                        truth_files = sorted(path.name for path in truth_dir.glob(f"{take_name}*.truth.json"))
                    takes.append(
                        {
                            "shot_id": shot_id,
                            "take_name": take_name,
                            "asset_id": f"{shot_id}/{take_name}",
                            "filename": video_path.name,
                            "truth_files": truth_files,
                            "video_url": (
                                f"/media?project_id={quote(project_id)}&shot_id={quote(shot_id)}"
                                f"&take={quote(video_path.name)}"
                            ),
                        }
                    )
            shots.append(
                {
                    "shot_id": shot_id,
                    "shot_spec_exists": (shot_dir / "shot_spec.json").exists(),
                    "takes": takes,
                }
            )
        self.send_json({"manifest": manifest.model_dump(mode="json"), "shots": shots})

    def handle_shot_spec(self, query: str) -> None:
        params = parse_qs(query)
        root = project_root(params.get("project_id", [""])[0])
        shot_id = params.get("shot_id", [""])[0]
        manifest = load_project_manifest(root)
        spec_path = root / manifest.shots_root / shot_id / "shot_spec.json"
        spec = read_json_model(spec_path, ShotSpec)
        self.send_json(spec.model_dump(mode="json"))

    def handle_get_truth(self, query: str) -> None:
        params = parse_qs(query)
        root = project_root(params.get("project_id", [""])[0])
        shot_id = params.get("shot_id", [""])[0]
        take_name = params.get("take_name", [""])[0]
        annotator = params.get("annotator", ["primary"])[0] or "primary"
        manifest = load_project_manifest(root)
        path = root / manifest.truth_root / shot_id / truth_filename(take_name, annotator)
        if not path.exists() and annotator != "primary":
            path = root / manifest.truth_root / shot_id / truth_filename(take_name, "primary")
        if not path.exists():
            self.send_json({"truth": None}, HTTPStatus.NOT_FOUND)
            return
        truth = read_json_model(path, TruthFile)
        self.send_json({"truth": truth.model_dump(mode="json"), "path": str(path.relative_to(ROOT))})

    def handle_save_truth(self) -> None:
        payload = self.read_body_json()
        project_id = payload["project_id"]
        root = project_root(project_id)
        manifest = load_project_manifest(root)
        truth = TruthFile.model_validate(payload["truth"])
        if truth.shot_id not in manifest.shot_ids:
            raise ValueError("truth shot_id is not declared in manifest")
        take_name = truth.asset_id.split("/", 1)[1]
        annotator = payload.get("save_as", truth.annotator) or "primary"
        path = root / manifest.truth_root / truth.shot_id / truth_filename(take_name, annotator)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(truth.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.send_json({"ok": True, "path": str(path.relative_to(ROOT))})

    def handle_media(self, query: str) -> None:
        params = parse_qs(query)
        root = project_root(params.get("project_id", [""])[0])
        shot_id = params.get("shot_id", [""])[0]
        take = params.get("take", [""])[0]
        if "/" in take or "\\" in take:
            raise ValueError("invalid take")
        manifest = load_project_manifest(root)
        media_path = (root / manifest.shots_root / shot_id / take).resolve()
        if not is_relative_to(media_path, root) or media_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError("invalid media path")
        if not media_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.serve_media_file(media_path)

    def serve_media_file(self, path: Path) -> None:
        size = path.stat().st_size
        content_type, _ = mimetypes.guess_type(str(path))
        range_header = self.headers.get("Range")
        if not range_header:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "video/mp4")
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with path.open("rb") as handle:
                self.wfile.write(handle.read())
            return

        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if not match:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            return
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            return
        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", content_type or "video/mp4")
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            self.wfile.write(handle.read(length))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local truth annotator.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), AnnotatorHandler)
    print(f"Annotator running at http://{args.host}:{args.port}")
    print(f"Workspace: {ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping annotator.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
