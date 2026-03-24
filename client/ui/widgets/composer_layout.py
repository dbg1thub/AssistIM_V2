"""Shared layout helpers for composer inline object positioning."""

from __future__ import annotations


def inline_object_line_metrics(
    current_top: float,
    current_bottom: float,
    next_top: float,
    next_bottom: float,
    current_height: float,
) -> tuple[float, float]:
    """Return stable line metrics for an inline object from adjacent cursor rects."""
    same_line = abs(((next_top + next_bottom) / 2.0) - ((current_top + current_bottom) / 2.0)) < max(
        2.0,
        current_height / 2.0,
    )
    if same_line:
        return float(min(current_top, next_top)), float(max(current_bottom, next_bottom))
    return float(current_top), float(current_bottom)


def centered_inline_object_top(
    line_top: float,
    line_bottom: float,
    render_height: float,
    *,
    minimum_line_height: float = 0.0,
) -> float:
    """Return a centered top coordinate for an object rendered inside a line box."""
    line_height = max(float(minimum_line_height), float(line_bottom) - float(line_top))
    return float(line_top) + max(0.0, (line_height - float(render_height)) / 2.0)
