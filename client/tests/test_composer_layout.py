from client.ui.widgets.composer_layout import centered_inline_object_top, inline_object_line_metrics


def test_inline_object_line_metrics_uses_single_line_bounds_when_next_cursor_wraps():
    top, bottom = inline_object_line_metrics(
        current_top=10.0,
        current_bottom=142.0,
        next_top=148.0,
        next_bottom=167.0,
        current_height=132.0,
    )

    assert top == 10.0
    assert bottom == 142.0


def test_inline_object_line_metrics_merges_bounds_when_next_cursor_stays_on_same_line():
    top, bottom = inline_object_line_metrics(
        current_top=10.0,
        current_bottom=142.0,
        next_top=11.0,
        next_bottom=141.0,
        current_height=132.0,
    )

    assert top == 10.0
    assert bottom == 142.0


def test_centered_inline_object_top_adds_vertical_breathing_room():
    top = centered_inline_object_top(
        line_top=20.0,
        line_bottom=172.0,
        render_height=132.0,
        minimum_line_height=152.0,
    )

    assert top == 30.0
