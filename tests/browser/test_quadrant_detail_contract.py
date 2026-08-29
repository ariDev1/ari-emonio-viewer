from pathlib import Path


def test_quadrant_uses_existing_four_phase_legend_as_accessible_plot_selector() -> None:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    assert "plot-selector-item" in source
    assert 'setAttribute("aria-pressed"' in source
    assert 'setAttribute("role", "button")' in source
    assert 'setAttribute("tabindex", "0")' in source
    assert 'addEventListener("click"' in source
    assert 'addEventListener("keydown"' in source


def test_selected_phase_plot_contains_p_q_resultant_angle_and_exact_detail_rows() -> None:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    for token in (
        "plot-p-component",
        "plot-q-component",
        "plot-q-projection",
        "plot-resultant-vector",
        "plot-angle-arc",
        "plot-detail-label",
        "plot-detail-value",
    ):
        assert token in source
    assert 'replaceChildren(group)' in source


def test_total_resultant_is_not_labeled_as_canonical_sigma_s() -> None:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    assert 'details.isTotal ? "|P+jQ|" : "S"' in source
    assert 'label: "ΣS"' in source
    assert 'label: "|P+jQ|"' in source
    assert 'label: "φPQ"' in source


def test_quadrant_css_has_dedicated_styles_for_selector_triangle_and_details() -> None:
    css = Path("frontend/css/quadrant.css").read_text(encoding="utf-8")
    for selector in (
        ".plot-selector-item",
        ".plot-p-component",
        ".plot-q-component",
        ".plot-q-projection",
        ".plot-resultant-vector",
        ".plot-angle-arc",
        ".plot-detail-label",
        ".plot-detail-value",
    ):
        assert selector in css


def test_quadrant_detail_panel_starts_below_positive_p_axis_label() -> None:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    assert "const DETAIL_START_Y = 250;" in source
