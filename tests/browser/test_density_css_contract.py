from pathlib import Path


def test_history_css_imports_density_css_as_a_separate_structured_file() -> None:
    history_css = Path('frontend/css/history.css').read_text(encoding='utf-8')
    assert history_css.startswith('@import url("./density.css");\n')


def test_density_css_uses_scoped_density_classes_and_all_visual_bands() -> None:
    css = Path('frontend/css/density.css').read_text(encoding='utf-8')
    for selector in [
        '.density-view-controls',
        '.density-phase-selector',
        '.density-cell',
        '.density-axis',
        '.density-axis-label',
        '.density-scale-label',
        '.density-waiting',
    ]:
        assert selector in css
    for band in range(1, 9):
        assert f'.density-band-{band}' in css
    assert 'body {' not in css
    assert 'html {' not in css


def test_density_cells_remain_visible_and_focusable_at_low_occupancy() -> None:
    css = Path('frontend/css/density.css').read_text(encoding='utf-8')
    assert '.density-band-1' in css
    assert 'opacity: 0;' not in css
    assert '.density-cell:focus' in css


def test_density_mode_disables_time_crosshair_without_changing_time_history_default() -> None:
    css = Path('frontend/css/density.css').read_text(encoding='utf-8')
    assert '.history-plot.density-plot-active' in css
    assert 'cursor: default;' in css
