"""Rasterize SVG avatars in an isolated subprocess so server worker threads never host Qt state."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


def ensure_rasterized_svg(svg_path: Path, cache_dir: Path, *, size: int = 256, timeout_seconds: int = 20) -> Path | None:
    """Rasterize one SVG into a cached PNG using a separate Python process."""
    source_path = Path(svg_path).resolve()
    if not source_path.is_file():
        return None

    try:
        stat = source_path.stat()
    except OSError:
        return None

    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(
        f"{source_path}|{stat.st_mtime_ns}|{stat.st_size}|{max(16, int(size or 256))}".encode("utf-8")
    ).hexdigest()
    target_path = cache_dir / f"{cache_key}.png"
    if target_path.is_file():
        return target_path

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(source_path),
        str(target_path),
        str(max(16, int(size or 256))),
    ]
    result = subprocess.run(
        command,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout_seconds)),
        check=False,
    )
    if result.returncode != 0 or not target_path.is_file():
        target_path.unlink(missing_ok=True)
        return None
    return target_path


def _render_svg(input_path: Path, output_path: Path, size: int) -> int:
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])
    del app

    renderer = QSvgRenderer(QByteArray(input_path.read_bytes()))
    if not renderer.isValid():
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(str(output_path), "PNG"):
        return 3
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return 64
    input_path = Path(argv[1]).resolve()
    output_path = Path(argv[2]).resolve()
    try:
        size = max(16, int(argv[3]))
    except ValueError:
        return 65
    return _render_svg(input_path, output_path, size)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
