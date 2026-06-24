from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_clip.manifest.loader import read_json_model  # noqa: E402
from ai_clip.manifest.schemas import TruthFile  # noqa: E402


def main() -> int:
    fixture_root = ROOT / "tests" / "golden_windows"
    paths = sorted(fixture_root.glob("*.truth.json"))
    if not paths:
        print(f"No truth fixtures found in {fixture_root}", file=sys.stderr)
        return 1

    failures = 0
    for path in paths:
        try:
            read_json_model(path, TruthFile)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {path}: {exc}", file=sys.stderr)
        else:
            print(f"OK   {path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
