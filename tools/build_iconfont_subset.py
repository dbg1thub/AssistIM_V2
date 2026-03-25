"""Build the project's local SVG icon library from one iconfont collection export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil


REQUIRED_ICON_NAMES = {
    "add",
    "paint_brush",
    "dismiss_circle",
    "chat",
    "dismiss",
    "checkmark_circle",
    "cut",
    "emoji",
    "folder",
    "globe",
    "home",
    "info",
    "local_language",
    "color",
    "people",
    "phone",
    "image",
    "bot",
    "send",
    "settings",
    "arrow_sync",
    "blur",
    "video",
    "zoom_in",
}


def _sanitize_icon_name(name: str) -> str:
    text = str(name or "").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "icon"


def _iter_unique_collection_icons(payload: dict) -> list[tuple[str, dict]]:
    icons_by_name: dict[str, dict] = {}
    for icon in payload["data"]["icons"]:
        sanitized_name = _sanitize_icon_name(str(icon["name"]))
        resolved_name = sanitized_name
        if resolved_name in icons_by_name:
            resolved_name = f"{resolved_name}_{icon['id']}"
        icons_by_name[resolved_name] = icon
    return sorted(icons_by_name.items(), key=lambda item: item[0])


def _prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def build_icon_assets(collection_json: Path, output_dir: Path) -> None:
    payload = json.loads(collection_json.read_text(encoding="utf-8-sig"))
    _prepare_output_dir(output_dir)

    manifest: list[dict[str, object]] = []
    available_names: set[str] = set()
    for target_name, icon in _iter_unique_collection_icons(payload):
        (output_dir / f"{target_name}.svg").write_text(str(icon["show_svg"]), encoding="utf-8")
        available_names.add(target_name)
        manifest.append(
            {
                "id": int(icon["id"]),
                "name": str(icon["name"]),
                "sanitized_name": target_name,
                "width": int(icon.get("width") or 0),
                "height": int(icon.get("height") or 0),
            }
        )

    missing = sorted(REQUIRED_ICON_NAMES - available_names)
    if missing:
        raise SystemExit(f"Missing iconfont entries: {', '.join(missing)}")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"count": len(manifest), "icons": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection-json",
        type=Path,
        default=Path("tmp/iconfont_collection_51777.json"),
        help="Path to the cached iconfont collection JSON payload.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("client/resources/icons/iconfont_51777"),
        help="Directory where raw SVG assets and the manifest will be written.",
    )
    args = parser.parse_args()

    build_icon_assets(args.collection_json, args.output_dir)


if __name__ == "__main__":
    main()
