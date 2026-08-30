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


def test_one_exact_pq_sample_contributes_to_exactly_one_density_bin() -> None:
    samples = json.dumps([
        {'phase_a': {'p': -10.0, 'q': 20.0}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); return [map.sampleCount, map.bins.reduce((sum, bin) => sum + bin.count, 0)]; }})()"
    )
    assert result == [1, 1]


def test_density_uses_fixed_32_by_32_grid_and_one_common_symmetric_limit() -> None:
    samples = json.dumps([
        {'phase_a': {'p': -8.0, 'q': 2.0}},
        {'phase_a': {'p': 3.0, 'q': 12.0}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); return [map.binCount, map.bins.length, map.limit, map.binWidth]; }})()"
    )
    assert result == [32, 1024, 12.0, 0.75]


def test_density_preserves_all_four_pq_sign_combinations() -> None:
    samples = json.dumps([
        {'phase_a': {'p': 10.0, 'q': 10.0}},
        {'phase_a': {'p': -10.0, 'q': 10.0}},
        {'phase_a': {'p': -10.0, 'q': -10.0}},
        {'phase_a': {'p': 10.0, 'q': -10.0}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); return map.bins.filter(bin => bin.count > 0).map(bin => [bin.pIndex, bin.qIndex, bin.count]); }})()"
    )
    assert result == [
        [0, 0, 1],
        [31, 0, 1],
        [0, 31, 1],
        [31, 31, 1],
    ]


def test_density_phase_selection_does_not_mix_phase_values() -> None:
    samples = json.dumps([
        {
            'phase_a': {'p': -1.0, 'q': -2.0},
            'phase_b': {'p': 100.0, 'q': 200.0},
            'phase_c': {'p': 300.0, 'q': 400.0},
            'total': {'p': 500.0, 'q': 600.0},
        }
    ])
    result = _run_density_module(
        f"(() => {{ const a = mod.buildDensityMap({samples}, 'phase_a'); const t = mod.buildDensityMap({samples}, 'total'); return [a.limit, t.limit, a.sampleCount, t.sampleCount]; }})()"
    )
    assert result == [2.0, 600.0, 1, 1]


def test_exact_zero_uses_deterministic_positive_side_half_open_bin_without_value_change() -> None:
    samples = json.dumps([
        {'phase_a': {'p': 0.0, 'q': 0.0}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); const hit = map.bins.find(bin => bin.count === 1); return [map.limit, map.fallbackRangeUsed, hit.pIndex, hit.qIndex, hit.pMin, hit.qMin]; }})()"
    )
    assert result == [1.0, True, 16, 16, 0.0, 0.0]


def test_invalid_pq_point_is_excluded_and_reported_not_fabricated() -> None:
    samples = json.dumps([
        {'phase_a': {'p': 1.0, 'q': 2.0}},
        {'phase_a': {'p': None, 'q': 3.0}},
        {'phase_a': {'p': 4.0, 'q': None}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); return [map.inputSampleCount, map.sampleCount, map.skippedSampleCount, map.bins.reduce((sum, bin) => sum + bin.count, 0)]; }})()"
    )
    assert result == [3, 1, 2, 1]


def test_density_bin_reports_exact_range_count_and_percentage() -> None:
    samples = json.dumps([
        {'phase_a': {'p': 1.0, 'q': 1.0}},
        {'phase_a': {'p': 1.0, 'q': 1.0}},
        {'phase_a': {'p': -1.0, 'q': -1.0}},
        {'phase_a': {'p': -1.0, 'q': -1.0}},
    ])
    result = _run_density_module(
        f"(() => {{ const map = mod.buildDensityMap({samples}, 'phase_a'); return map.bins.filter(bin => bin.count === 2).map(bin => [bin.count, bin.percentage, bin.pMin, bin.pMax, bin.qMin, bin.qMax, bin.band]); }})()"
    )
    assert result == [
        [2, 50.0, -1.0, -0.9375, -1.0, -0.9375, 2],
        [2, 50.0, 0.9375, 1.0, 0.9375, 1.0, 2],
    ]


def test_occupancy_bands_follow_deterministic_power_of_two_groups() -> None:
    result = _run_density_module(
        "[0,1,2,3,4,5,8,9,16,17,32,33].map(mod.occupancyBand)"
    )
    assert result == [0, 1, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7]


def test_empty_density_contains_no_fabricated_occupancy() -> None:
    result = _run_density_module(
        "(() => { const map = mod.buildDensityMap([], 'phase_a'); return [map.sampleCount, map.skippedSampleCount, map.limit, map.fallbackRangeUsed, map.bins.some(bin => bin.count !== 0)]; })()"
    )
    assert result == [0, 0, 1.0, True, False]
