from pathlib import Path


def test_science_workspace_gives_vector_instrument_more_workstation_width() -> None:
    css = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert "grid-template-columns: clamp(480px, 30vw, 560px) minmax(0, 1fr);" in css


def test_power_plot_uses_distinct_semantic_colors_for_p_q_angle_resultant_and_helpers() -> None:
    css = Path("frontend/css/quadrant.css").read_text(encoding="utf-8")
    for token in (
        "--plot-phase-color:",
        "--plot-p-color:",
        "--plot-q-color:",
        "--plot-angle-color:",
        "--plot-helper-color:",
        ".plot-p-component",
        ".plot-p-label",
        ".plot-q-component",
        ".plot-q-label",
        ".plot-angle-arc",
        ".plot-angle-label",
        ".plot-resultant-vector",
        ".plot-q-projection",
    ):
        assert token in css

    assert "stroke: var(--plot-p-color);" in css
    assert "stroke: var(--plot-q-color);" in css
    assert "stroke: var(--plot-angle-color);" in css
    assert "stroke: var(--plot-phase-color);" in css
    assert "stroke: var(--plot-helper-color);" in css


def test_power_plot_assigns_metric_specific_label_classes() -> None:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    assert '"plot-component-label plot-p-label"' in source
    assert '"plot-component-label plot-q-label"' in source
    assert "computePowerLabelLayout" in source
