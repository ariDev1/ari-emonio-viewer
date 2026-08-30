from __future__ import annotations

import json
from pathlib import Path
import subprocess


def _run_density_view(expression: str) -> object:
    program = f"""
const mod = await import('./frontend/js/density-view.js');
const result = {expression};
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ['node', '--input-type=module', '-e', program],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_density_view_defaults_to_time_history_and_phase_a() -> None:
    result = _run_density_view(
        "[mod.isDensityViewActive(), mod.getDensityPhaseKey(), mod.DENSITY_PHASES.map(x => x.key)]"
    )
    assert result == [False, 'phase_a', ['phase_a', 'phase_b', 'phase_c', 'total']]


def test_density_view_state_changes_are_explicit_and_invalid_phase_is_rejected() -> None:
    result = _run_density_view(
        "(() => { const a = mod.setDensityViewActive(true); const p = mod.setDensityPhaseKey('total'); const bad = mod.setDensityPhaseKey('not-a-phase'); return [a, p, bad, mod.isDensityViewActive(), mod.getDensityPhaseKey()]; })()"
    )
    assert result == [True, True, False, True, 'total']


def test_density_geometry_keeps_positive_p_right_and_positive_q_up() -> None:
    result = _run_density_view(
        "(() => { const plot = {left:10,right:330,top:20,bottom:340}; const neg = mod.densityCellGeometry({pIndex:0,qIndex:0}, plot, 32); const pos = mod.densityCellGeometry({pIndex:31,qIndex:31}, plot, 32); return [neg.x, neg.y, pos.x, pos.y, neg.width, neg.height]; })()"
    )
    assert result == [10, 330, 320, 20, 10, 10]


def test_density_bin_detail_text_reports_exact_ranges_count_and_percentage() -> None:
    result = _run_density_view(
        "mod.formatDensityBinDetails({pMin:-12.5,pMax:-10,qMin:2.5,qMax:5,count:7,percentage:12.5})"
    )
    assert result == 'P -12.5…-10 W | Q 2.5…5 var | 7 samples | 12.500 %'


def test_density_view_source_has_no_trajectory_or_interpolation_primitive() -> None:
    source = Path('frontend/js/density-view.js').read_text(encoding='utf-8').lower()
    forbidden = ['polyline', 'path d=', 'interpolat', 'smooth', 'resampl']
    assert not any(token in source for token in forbidden)


def test_density_render_model_uses_only_occupied_cells_and_preserves_exact_counts() -> None:
    samples = json.dumps([
        {'phase_a': {'p': -10.0, 'q': 10.0}},
        {'phase_a': {'p': -10.0, 'q': 10.0}},
        {'phase_a': {'p': 5.0, 'q': -5.0}},
    ])
    result = _run_density_view(
        f"(() => {{ const model = mod.buildDensityRenderModel({samples}, 'phase_a'); return [model.sampleCount, model.cells.length, model.cells.reduce((sum, cell) => sum + cell.count, 0), model.plot.right - model.plot.left, model.plot.bottom - model.plot.top]; }})()"
    )
    assert result == [3, 2, 3, 300, 300]


def test_density_render_model_reports_selected_phase_scale_and_skipped_samples() -> None:
    samples = json.dumps([
        {'total': {'p': 12.0, 'q': -6.0}},
        {'total': {'p': None, 'q': 3.0}},
    ])
    result = _run_density_view(
        f"(() => {{ const model = mod.buildDensityRenderModel({samples}, 'total'); return [model.phaseLabel, model.limit, model.sampleCount, model.skippedSampleCount, model.scaleNote]; }})()"
    )
    assert result == ['TOTAL', 12.0, 1, 1, 'P-Q DENSITY · TOTAL · 32×32 · 1 SAMPLE · 1 SKIPPED']


def test_density_render_model_cell_keeps_exact_evidence_text() -> None:
    samples = json.dumps([
        {'phase_a': {'p': 1.0, 'q': 1.0}},
    ])
    result = _run_density_view(
        f"(() => {{ const model = mod.buildDensityRenderModel({samples}, 'phase_a'); const cell = model.cells[0]; return [cell.count, cell.percentage, cell.detail, cell.geometry.x, cell.geometry.y]; }})()"
    )
    assert result == [1, 100.0, 'P 0.9375…1 W | Q 0.9375…1 var | 1 samples | 100.000 %', 360.625, 30]


def test_density_renderer_targets_existing_history_svg_and_uses_rectangles_with_titles() -> None:
    source = Path('frontend/js/density-view.js').read_text(encoding='utf-8')
    assert 'history-active-plot' in source
    assert 'replaceChildren' in source
    assert 'svgElement("rect"' in source
    assert 'svgElement("title"' in source
    assert 'buildDensityMap' in source


def test_density_controls_are_explicit_time_density_and_phase_controls() -> None:
    source = Path('frontend/js/density-view.js').read_text(encoding='utf-8')
    for token in ['TIME HISTORY', 'P-Q DENSITY', 'DENSITY PHASE', 'TOTAL']:
        assert token in source
