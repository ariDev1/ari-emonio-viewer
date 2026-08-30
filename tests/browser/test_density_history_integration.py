from pathlib import Path


def _history_source() -> str:
    return Path('frontend/js/history.js').read_text(encoding='utf-8')


def test_history_imports_density_view_without_new_backend_or_transport_path() -> None:
    source = _history_source()
    assert 'from "./density-view.js"' in source
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


def test_density_control_callback_clears_time_sample_selection_and_rerenders() -> None:
    source = _history_source()
    metric_handler = source[source.index('export function initializeHistoryMetricSelector'):source.index('export function initializeHistoryWindowSelector')]
    assert 'initializeDensityView' in metric_handler
    assert 'selectedByDevice.delete(deviceId)' in metric_handler
    assert 'renderMeasurementHistory(deviceId)' in metric_handler


def test_time_axis_click_and_arrow_inspection_fail_closed_while_density_is_active() -> None:
    source = _history_source()
    inspection = source[source.index('export function initializeHistoryInspection'):]
    assert inspection.count('if (isDensityViewActive()) return;') == 2


def test_exact_sample_inspector_does_not_invite_time_clicks_in_density_mode() -> None:
    source = _history_source()
    assert 'DENSITY VIEW ACTIVE · SELECT TIME HISTORY FOR EXACT SAMPLE INSPECTION' in source
