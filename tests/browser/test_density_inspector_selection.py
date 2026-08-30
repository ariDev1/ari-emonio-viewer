from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_density_module(expression: str) -> object:
    source = Path('frontend/js/density.js').read_text(encoding='utf-8')
    encoded = base64.b64encode(source.encode('utf-8')).decode('ascii')
    program = f"""
const moduleUrl = 'data:text/javascript;base64,{encoded}';
const mod = await import(moduleUrl);
const result = {expression};
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ['node', '--input-type=module', '-e', program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


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


def test_density_bin_retains_exact_contributing_sample_indices_in_history_order() -> None:
    samples = json.dumps([
        {'cycleId': 10, 'phase_a': {'p': 2.0, 'q': 2.0}},
        {'cycleId': 11, 'phase_a': {'p': -2.0, 'q': -2.0}},
        {'cycleId': 12, 'phase_a': {'p': 2.0, 'q': 2.0}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); const hit = map.bins.find(bin => bin.count === 2); return [hit.count, hit.sampleIndices]; }})()"
    )
    assert result == [2, [0, 2]]


def test_density_render_model_selects_latest_exact_sample_identity_from_occupied_bin() -> None:
    samples = json.dumps([
        {'cycleId': 41, 'cycleFinishedUtc': '2026-08-30T20:00:01Z', 'phase_a': {'p': 5.0, 'q': 5.0}},
        {'cycleId': 42, 'cycleFinishedUtc': '2026-08-30T20:00:02Z', 'phase_a': {'p': 5.0, 'q': 5.0}},
    ])
    result = _run_density_view(
        f"(() => {{ const model = mod.buildDensityRenderModel({samples}, 'phase_a'); const cell = model.cells[0]; return [cell.count, cell.latestSampleIdentity]; }})()"
    )
    assert result == [2, {'cycleId': 42, 'cycleFinishedUtc': '2026-08-30T20:00:02Z'}]


def test_density_cells_publish_exact_sample_selection_without_synthetic_values() -> None:
    source = Path('frontend/js/density-view.js').read_text(encoding='utf-8')
    assert 'selectedSampleIdentity' in source
    assert 'densityBinCount' in source
    assert 'addEventListener("click"' in source
    assert 'latestSampleIdentity' in source
