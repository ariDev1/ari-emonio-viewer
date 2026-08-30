from pathlib import Path


def _history_source() -> str:
    return Path('frontend/js/history.js').read_text(encoding='utf-8')


def test_history_lazy_loads_density_view_without_new_backend_or_transport_path() -> None:
    source = _history_source()
    assert 'from "./density-view.js"' not in source
    assert 'import("./density-view.js")' in source
    assert 'let densityViewApi = null;' in source
    for name in ['initializeDensityView', 'isDensityViewActive', 'renderDensityView', 'setDensityViewActive']:
        assert name in source


def test_density_receives_the_same_visible_history_window_not_full_storage() -> None:
    source = _history_source()
    assert 'renderDensityView(visibleSamples)' in source
    assert 'renderDensityView(storedSamples)' not in source


def test_time_history_render_path_remains_present_and_density_class_is_removed_on_return() -> None:
    source = _history_source()
    assert 'renderChart(config, visibleSamples, selectedSample, activeHistoryWindowMs)' in source
    assert 'classList.remove("density-plot-active")' in source


def test_metric_selection_explicitly_returns_to_time_history() -> None:
    source = _history_source()
    metric_handler = source[source.index('export function initializeHistoryMetricSelector'):source.index('export function initializeHistoryWindowSelector')]
    assert 'setDensityViewActive(false);' in metric_handler


def test_density_control_callback_preserves_time_sample_selection_and_accepts_density_bin_selection() -> None:
    source = _history_source()
    metric_handler = source[source.index('export function initializeHistoryMetricSelector'):source.index('export function initializeHistoryWindowSelector')]
    assert 'initializeDensityView' in metric_handler
    assert 'selectedByDevice.delete(deviceId)' not in metric_handler
    assert 'selectedSampleIdentity' in metric_handler
    assert 'densityBinCount' in metric_handler
    assert 'source: "density_bin"' in metric_handler
    assert 'renderMeasurementHistory(deviceId)' in metric_handler


def test_time_axis_click_and_arrow_inspection_fail_closed_while_density_is_active() -> None:
    source = _history_source()
    inspection = source[source.index('export function initializeHistoryInspection'):]
    assert inspection.count('if (isDensityViewActive()) return;') == 2


def test_exact_sample_inspector_does_not_invite_time_clicks_in_density_mode() -> None:
    source = _history_source()
    assert 'DENSITY VIEW ACTIVE · SELECT TIME HISTORY FOR EXACT SAMPLE INSPECTION' in source


def test_history_module_remains_data_url_importable_for_existing_math_tests() -> None:
    import base64
    import subprocess

    source = Path('frontend/js/history.js').read_text(encoding='utf-8')
    encoded = base64.b64encode(source.encode('utf-8')).decode('ascii')
    program = f"""
const moduleUrl = 'data:text/javascript;base64,{encoded}';
const mod = await import(moduleUrl);
console.log(JSON.stringify([mod.HISTORY_WINDOW_MS, mod.HISTORY_PHASES.map(x => x.key)]));
"""
    completed = subprocess.run(
        ['node', '--input-type=module', '-e', program],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == '[600000,["phase_a","phase_b","phase_c","total"]]'


def test_density_bin_inspector_state_reports_latest_exact_sample_and_bin_count() -> None:
    source = _history_source()
    assert 'DENSITY BIN · ${selectionIdentity.densityBinCount} SAMPLES · SHOWING LATEST EXACT SAMPLE' in source
