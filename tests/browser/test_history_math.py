from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest


def _run_history_module(expression: str) -> object:
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    program = f"""
const moduleUrl = 'data:text/javascript;base64,{encoded}';
const mod = await import(moduleUrl);
const result = {expression};
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _payload(device_id: str, cycle_id: int, timestamp: str, p: float, q: float) -> str:
    payload = {
        "device_id": device_id,
        "sample": {
            "cycle_id": cycle_id,
            "cycle_finished_utc": timestamp,
            "phase_a": {"p": p, "q": q},
            "phase_b": {"p": p + 1.0, "q": q + 1.0},
            "phase_c": {"p": p + 2.0, "q": q + 2.0},
            "total": {"p": p + 3.0, "q": q + 3.0},
        },
    }
    return json.dumps(payload)


def test_history_preserves_signed_full_precision_samples_without_aggregation() -> None:
    first = _payload("dev-a", 1, "2026-08-27T20:00:00Z", -123.456789, 9.87654321)
    second = _payload("dev-a", 2, "2026-08-27T20:00:02Z", 0.000012345, -0.00006789)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); h.append({first}); h.append({second}); return h.get('dev-a'); }})()"
    )
    assert len(result) == 2
    assert result[0]["phase_a"]["p"] == -123.456789
    assert result[0]["phase_a"]["q"] == 9.87654321
    assert result[1]["phase_a"]["p"] == 0.000012345
    assert result[1]["phase_a"]["q"] == -0.00006789


def test_history_prunes_only_samples_older_than_fixed_ten_minute_window() -> None:
    old = _payload("dev-a", 1, "2026-08-27T20:00:00Z", 1.0, 2.0)
    boundary = _payload("dev-a", 2, "2026-08-27T20:00:01Z", 3.0, 4.0)
    latest = _payload("dev-a", 3, "2026-08-27T20:10:01Z", 5.0, 6.0)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); h.append({old}); h.append({boundary}); h.append({latest}); return h.get('dev-a').map(x => x.cycleId); }})()"
    )
    assert result == [2, 3]


def test_history_is_isolated_by_device() -> None:
    a = _payload("dev-a", 1, "2026-08-27T20:00:00Z", -10.0, 20.0)
    b = _payload("dev-b", 1, "2026-08-27T20:00:00Z", 30.0, -40.0)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); h.append({a}); h.append({b}); return [h.get('dev-a')[0].phase_a.p, h.get('dev-b')[0].phase_a.p]; }})()"
    )
    assert result == [-10.0, 30.0]


def test_duplicate_cycle_is_not_added_twice() -> None:
    sample = _payload("dev-a", 7, "2026-08-27T20:00:00Z", 12.0, 13.0)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); h.append({sample}); h.append({sample}); return h.get('dev-a').length; }})()"
    )
    assert result == 1


def test_time_projection_uses_exact_elapsed_time_not_sample_index() -> None:
    result = _run_history_module(
        "[mod.projectTimestamp(0, 0, 600000, 0, 100), mod.projectTimestamp(60000, 0, 600000, 0, 100), mod.projectTimestamp(600000, 0, 600000, 0, 100)]"
    )
    assert result == [0, 10, 100]


def test_value_projection_keeps_zero_centered_and_sign_direction() -> None:
    result = _run_history_module(
        "[mod.projectSignedValue(100, 100, 10, 210), mod.projectSignedValue(0, 100, 10, 210), mod.projectSignedValue(-100, 100, 10, 210)]"
    )
    assert result == [10, 110, 210]


def test_chart_series_returns_discrete_points_only() -> None:
    samples = json.dumps([
        {
            "timestampMs": 0,
            "phase_a": {"p": -1.0, "q": 2.0},
            "phase_b": {"p": 0.0, "q": 0.0},
            "phase_c": {"p": 0.0, "q": 0.0},
            "total": {"p": 0.0, "q": 0.0},
        },
        {
            "timestampMs": 600000,
            "phase_a": {"p": 3.0, "q": -4.0},
            "phase_b": {"p": 0.0, "q": 0.0},
            "phase_c": {"p": 0.0, "q": 0.0},
            "total": {"p": 0.0, "q": 0.0},
        },
    ])
    result = _run_history_module(
        f"mod.buildDiscreteSeries({samples}, 'p', 'phase_a', 600000, {{left: 0, right: 100, top: 0, bottom: 100}}, 3)"
    )
    assert result["points"] == [[0, 66.66666666666666], [100, 0]]
    assert "path" not in result
    assert "segments" not in result


def test_history_preserves_extended_canonical_fields_without_transformation() -> None:
    payload = json.dumps(
        {
            "device_id": "dev-a",
            "sample": {
                "cycle_id": 91,
                "cycle_finished_utc": "2026-08-27T21:00:00.123456Z",
                "phase_a": {
                    "vrms": 230.123456789,
                    "irms": 1.234567891,
                    "p": -123.456789012,
                    "q": 98.765432109,
                    "s": 158.113883008,
                    "pf": -0.780868809,
                    "frequency": 49.987654321,
                },
                "phase_b": {
                    "vrms": 231.0,
                    "irms": 2.0,
                    "p": 3.0,
                    "q": 4.0,
                    "s": 5.0,
                    "pf": 0.6,
                    "frequency": 50.0,
                },
                "phase_c": {
                    "vrms": 232.0,
                    "irms": 3.0,
                    "p": 4.0,
                    "q": 5.0,
                    "s": 6.0,
                    "pf": 0.7,
                    "frequency": 50.01,
                },
                "total": {
                    "vrms": 233.0,
                    "irms": 4.0,
                    "p": 5.0,
                    "q": 6.0,
                    "s": 7.0,
                    "pf": 0.8,
                    "frequency": 49.99,
                },
            },
        }
    )
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); h.append({payload}); return h.get('dev-a')[0].phase_a; }})()"
    )
    assert result == {
        "vrms": 230.123456789,
        "irms": 1.234567891,
        "p": -123.456789012,
        "q": 98.765432109,
        "s": 158.113883008,
        "pf": -0.780868809,
        "frequency": 49.987654321,
    }


def test_history_chart_contract_covers_all_requested_canonical_fields() -> None:
    result = _run_history_module(
        "mod.HISTORY_CHARTS.map(({field, unit, scale}) => [field, unit, scale])"
    )
    assert result == [
        ["p", "W", "signed"],
        ["q", "var", "signed"],
        ["vrms", "V", "observed"],
        ["irms", "A", "observed"],
        ["s", "VA", "observed"],
        ["pf", "", "observed"],
        ["frequency", "Hz", "observed"],
    ]


def test_observed_bounds_are_exact_and_do_not_force_zero_into_range() -> None:
    samples = json.dumps(
        [
            {
                "phase_a": {"vrms": 229.95},
                "phase_b": {"vrms": 230.05},
                "phase_c": {"vrms": 230.15},
                "total": {"vrms": 230.25},
            },
            {
                "phase_a": {"vrms": 229.75},
                "phase_b": {"vrms": 230.35},
                "phase_c": {"vrms": 230.45},
                "total": {"vrms": 230.55},
            },
        ]
    )
    result = _run_history_module(f"mod.observedBounds({samples}, 'vrms')")
    assert result == {"min": 229.75, "max": 230.55}


def test_observed_projection_uses_exact_minimum_and_maximum() -> None:
    result = _run_history_module(
        "[mod.projectObservedValue(10, 10, 20, 0, 100), mod.projectObservedValue(15, 10, 20, 0, 100), mod.projectObservedValue(20, 10, 20, 0, 100)]"
    )
    assert result == [100, 50, 0]


def test_observed_projection_of_constant_series_is_centered_without_modifying_value() -> None:
    result = _run_history_module("mod.projectObservedValue(50, 50, 50, 10, 210)")
    assert result == 110


def test_observed_chart_series_returns_discrete_points_only() -> None:
    samples = json.dumps(
        [
            {
                "timestampMs": 0,
                "phase_a": {"frequency": 49.9},
                "phase_b": {"frequency": 50.0},
                "phase_c": {"frequency": 50.1},
                "total": {"frequency": 50.2},
            },
            {
                "timestampMs": 600000,
                "phase_a": {"frequency": 50.1},
                "phase_b": {"frequency": 50.2},
                "phase_c": {"frequency": 50.3},
                "total": {"frequency": 50.4},
            },
        ]
    )
    result = _run_history_module(
        f"mod.buildObservedDiscreteSeries({samples}, 'frequency', 'phase_a', 600000, {{left: 0, right: 100, top: 0, bottom: 100}}, {{min: 49.9, max: 50.4}})"
    )
    assert result["points"][0] == [0, 100]
    assert result["points"][1][0] == 100
    assert result["points"][1][1] == pytest.approx(60.0, abs=1e-12)
    assert "path" not in result
    assert "segments" not in result


def test_history_preserves_exact_canonical_cycle_finished_utc_string() -> None:
    payload = _payload("dev-a", 8, "2026-08-27T21:00:00.123456Z", -1.0, 2.0)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); h.append({payload}); const x = h.get('dev-a')[0]; return [x.cycleFinishedUtc, x.timestampMs]; }})()"
    )
    assert result == ["2026-08-27T21:00:00.123456Z", 1787864400123]


def test_same_cycle_id_with_different_canonical_timestamp_is_not_rejected() -> None:
    before_restart = _payload("dev-a", 1, "2026-08-27T21:00:00Z", 10.0, 20.0)
    after_restart = _payload("dev-a", 1, "2026-08-27T21:00:02Z", 30.0, 40.0)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); return [h.append({before_restart}), h.append({after_restart}), h.get('dev-a').map(x => [x.cycleId, x.cycleFinishedUtc])]; }})()"
    )
    assert result == [True, True, [[1, "2026-08-27T21:00:00Z"], [1, "2026-08-27T21:00:02Z"]]]


def test_exact_duplicate_sample_identity_is_rejected() -> None:
    sample = _payload("dev-a", 3, "2026-08-27T21:00:04.123456Z", 10.0, 20.0)
    result = _run_history_module(
        f"(() => {{ const h = new mod.MeasurementHistory(); return [h.append({sample}), h.append({sample}), h.get('dev-a').length]; }})()"
    )
    assert result == [True, False, 1]


def test_nearest_history_sample_returns_real_sample_without_interpolation() -> None:
    samples = json.dumps(
        [
            {"cycleId": 1, "cycleFinishedUtc": "2026-08-27T21:00:00Z", "timestampMs": 1000, "phase_a": {"p": -10.125}},
            {"cycleId": 2, "cycleFinishedUtc": "2026-08-27T21:00:02Z", "timestampMs": 3000, "phase_a": {"p": 99.875}},
        ]
    )
    result = _run_history_module(
        f"(() => {{ const x = mod.nearestHistorySample({samples}, 2600); return [x.cycleId, x.cycleFinishedUtc, x.phase_a.p]; }})()"
    )
    assert result == [2, "2026-08-27T21:00:02Z", 99.875]


def test_nearest_history_sample_tie_prefers_earlier_measured_sample() -> None:
    samples = json.dumps(
        [
            {"cycleId": 10, "cycleFinishedUtc": "2026-08-27T21:00:00Z", "timestampMs": 1000},
            {"cycleId": 11, "cycleFinishedUtc": "2026-08-27T21:00:02Z", "timestampMs": 3000},
        ]
    )
    result = _run_history_module(f"mod.nearestHistorySample({samples}, 2000).cycleId")
    assert result == 10


def test_adjacent_history_sample_steps_by_exact_identity_and_stored_order() -> None:
    samples = json.dumps(
        [
            {"cycleId": 1, "cycleFinishedUtc": "2026-08-27T21:00:00Z", "timestampMs": 1000},
            {"cycleId": 1, "cycleFinishedUtc": "2026-08-27T21:00:05Z", "timestampMs": 6000},
            {"cycleId": 9, "cycleFinishedUtc": "2026-08-27T21:00:05.500Z", "timestampMs": 6500},
        ]
    )
    result = _run_history_module(
        f'''(() => {{
          const samples = {samples};
          const middle = {{cycleId: 1, cycleFinishedUtc: "2026-08-27T21:00:05Z"}};
          const previous = mod.adjacentHistorySample(samples, middle, -1);
          const next = mod.adjacentHistorySample(samples, middle, 1);
          return [
            [previous.cycleId, previous.cycleFinishedUtc],
            [next.cycleId, next.cycleFinishedUtc],
          ];
        }})()'''
    )
    assert result == [
        [1, "2026-08-27T21:00:00Z"],
        [9, "2026-08-27T21:00:05.500Z"],
    ]


def test_adjacent_history_sample_stops_at_boundaries_and_rejects_missing_identity() -> None:
    samples = json.dumps(
        [
            {"cycleId": 4, "cycleFinishedUtc": "2026-08-27T21:00:01Z", "timestampMs": 1000},
            {"cycleId": 5, "cycleFinishedUtc": "2026-08-27T21:00:11Z", "timestampMs": 11000},
        ]
    )
    result = _run_history_module(
        f'''(() => {{
          const samples = {samples};
          return [
            mod.adjacentHistorySample(samples, samples[0], -1),
            mod.adjacentHistorySample(samples, samples[1], 1),
            mod.adjacentHistorySample(samples, {{cycleId: 99, cycleFinishedUtc: "missing"}}, 1),
            mod.adjacentHistorySample(samples, samples[0], 2),
            mod.adjacentHistorySample(samples, null, 1),
          ];
        }})()'''
    )
    assert result == [None, None, None, None, None]

def test_history_keyboard_handler_steps_selected_real_sample_and_does_not_wrap() -> None:
    first = _payload("dev-a", 1, "2026-08-27T21:00:00Z", 10.0, 20.0)
    middle = _payload("dev-a", 2, "2026-08-27T21:05:00Z", 30.0, 40.0)
    last = _payload("dev-a", 3, "2026-08-27T21:10:00Z", 50.0, 60.0)
    result = _run_history_module(
        f'''(() => {{
          const handlers = {{}};
          const nodes = new Map();
          function genericNode() {{
            return {{
              dataset: {{}},
              textContent: "",
              setAttribute() {{}},
              appendChild() {{}},
              replaceChildren() {{}},
              querySelector() {{ return null; }},
              classList: {{ toggle() {{}} }},
            }};
          }}
          const svg = genericNode();
          svg.addEventListener = (name, handler) => {{ handlers[name] = handler; }};
          svg.getScreenCTM = () => ({{ inverse: () => ({{}}) }});
          svg.createSVGPoint = () => ({{
            x: 0,
            y: 0,
            matrixTransform() {{ return {{ x: this.x, y: this.y }}; }},
          }});
          let focusCount = 0;
          svg.focus = () => {{ focusCount += 1; }};
          nodes.set("history-active-plot", svg);
          const cycleNode = genericNode();
          nodes.set("history-inspector-cycle", cycleNode);
          globalThis.document = {{
            getElementById(id) {{
              if (!nodes.has(id)) nodes.set(id, genericNode());
              return nodes.get(id);
            }},
            querySelectorAll() {{ return []; }},
            querySelector() {{ return null; }},
            createElementNS() {{ return genericNode(); }},
          }};

          mod.appendHistoryPayload({first});
          mod.appendHistoryPayload({middle});
          mod.appendHistoryPayload({last});
          mod.initializeHistoryInspection(() => "dev-a");
          handlers.click({{clientX: 407, clientY: 120}});
          const afterClick = cycleNode.textContent;

          let prevented = 0;
          handlers.keydown({{key: "ArrowRight", preventDefault() {{ prevented += 1; }}}});
          const afterRight = cycleNode.textContent;
          handlers.keydown({{key: "ArrowRight", preventDefault() {{ prevented += 1; }}}});
          const afterBoundary = cycleNode.textContent;
          handlers.keydown({{key: "ArrowLeft", preventDefault() {{ prevented += 1; }}}});
          const afterLeft = cycleNode.textContent;
          handlers.keydown({{key: "Enter", preventDefault() {{ prevented += 100; }}}});

          return [afterClick, afterRight, afterBoundary, afterLeft, prevented, focusCount];
        }})()'''
    )
    assert result == ["2", "3", "3", "2", 3, 1]


def test_history_plot_x_maps_to_timestamp_without_resampling() -> None:
    result = _run_history_module(
        "[mod.historyTimestampForPlotX(70, 1000000), mod.historyTimestampForPlotX(407, 1000000), mod.historyTimestampForPlotX(744, 1000000)]"
    )
    assert result == [400000, 700000, 1000000]


def test_history_inspector_uses_four_decimal_display_without_changing_canonical_export() -> None:
    result = _run_history_module(
        "[mod.formatCanonicalHistoryValue(-123.456789012), mod.formatCanonicalHistoryValue(0.000012345), mod.formatHistoryInspectorValue(-123.456789012), mod.formatHistoryInspectorValue(0.000012345), mod.formatHistoryInspectorValue(5.2), mod.formatHistoryInspectorValue(null)]"
    )
    assert result == ["-123.456789012", "0.000012345", "-123.4568", "0.0000", "5.2000", "—"]



def test_active_history_metric_defaults_to_active_power() -> None:
    result = _run_history_module("mod.getActiveHistoryField()")
    assert result == "p"


def test_history_metric_selection_accepts_only_known_canonical_fields() -> None:
    result = _run_history_module(
        '(() => [mod.setActiveHistoryField("frequency"), mod.getActiveHistoryField(), mod.setActiveHistoryField("unknown"), mod.getActiveHistoryField()])()'
    )
    assert result == [True, "frequency", False, "frequency"]


def test_history_chart_lookup_returns_active_metric_contract() -> None:
    result = _run_history_module(
        '(() => { const c = mod.historyChartForField("vrms"); return [c.svgId, c.field, c.unit, c.scale, c.title, c.scaleNote]; })()'
    )
    assert result == [
        "history-active-plot",
        "vrms",
        "V",
        "observed",
        "U(t)",
        "RMS VOLTAGE · V · OBSERVED RANGE",
    ]


def test_history_display_window_presets_are_fixed_and_default_to_ten_minutes() -> None:
    result = _run_history_module(
        "[mod.HISTORY_DISPLAY_WINDOWS.map(x => [x.ms, x.label]), mod.getActiveHistoryWindowMs()]"
    )
    assert result == [
        [[30000, "30 s"], [60000, "1 min"], [120000, "2 min"], [300000, "5 min"], [600000, "10 min"]],
        600000,
    ]


def test_visible_history_samples_selects_exact_timestamp_subset_without_resampling() -> None:
    samples = json.dumps(
        [
            {"cycleId": 1, "cycleFinishedUtc": "t1", "timestampMs": 0, "phase_a": {"p": 1.125}},
            {"cycleId": 2, "cycleFinishedUtc": "t2", "timestampMs": 569999, "phase_a": {"p": -2.25}},
            {"cycleId": 3, "cycleFinishedUtc": "t3", "timestampMs": 570000, "phase_a": {"p": 3.5}},
            {"cycleId": 4, "cycleFinishedUtc": "t4", "timestampMs": 587321, "phase_a": {"p": -4.75}},
            {"cycleId": 5, "cycleFinishedUtc": "t5", "timestampMs": 600000, "phase_a": {"p": 5.875}},
        ]
    )
    result = _run_history_module(
        f"mod.visibleHistorySamples({samples}, 30000).map(x => [x.cycleId, x.cycleFinishedUtc, x.timestampMs, x.phase_a.p])"
    )
    assert result == [
        [3, "t3", 570000, 3.5],
        [4, "t4", 587321, -4.75],
        [5, "t5", 600000, 5.875],
    ]


def test_history_display_window_selection_accepts_only_supported_presets() -> None:
    result = _run_history_module(
        "(() => [mod.setActiveHistoryWindowMs(30000), mod.getActiveHistoryWindowMs(), mod.setActiveHistoryWindowMs(45000), mod.getActiveHistoryWindowMs(), mod.setActiveHistoryWindowMs(600000), mod.getActiveHistoryWindowMs()])()"
    )
    assert result == [True, 30000, False, 30000, True, 600000]


def test_display_window_does_not_change_fixed_ten_minute_storage_retention() -> None:
    boundary = _payload("dev-a", 1, "2026-08-27T20:00:01Z", 1.0, 2.0)
    latest = _payload("dev-a", 2, "2026-08-27T20:10:01Z", 3.0, 4.0)
    result = _run_history_module(
        f"(() => {{ mod.setActiveHistoryWindowMs(30000); const h = new mod.MeasurementHistory(); h.append({boundary}); h.append({latest}); return [mod.getActiveHistoryWindowMs(), h.windowMs, h.get('dev-a').map(x => x.cycleId)]; }})()"
    )
    assert result == [30000, 600000, [1, 2]]


def test_plot_x_mapping_uses_requested_display_window_without_resampling() -> None:
    result = _run_history_module(
        "[mod.historyTimestampForPlotX(70, 1000000, 30000), mod.historyTimestampForPlotX(407, 1000000, 30000), mod.historyTimestampForPlotX(744, 1000000, 30000)]"
    )
    assert result == [970000, 985000, 1000000]


def test_discrete_series_projection_uses_requested_display_window_exactly() -> None:
    samples = json.dumps(
        [
            {"timestampMs": 570000, "phase_a": {"p": -1.0}},
            {"timestampMs": 587321, "phase_a": {"p": 2.0}},
            {"timestampMs": 600000, "phase_a": {"p": 3.0}},
        ]
    )
    result = _run_history_module(
        f"mod.buildDiscreteSeries({samples}, 'p', 'phase_a', 600000, {{left: 0, right: 100, top: 0, bottom: 100}}, 3, 30000)"
    )
    assert result["points"][0] == [0, 66.66666666666666]
    assert result["points"][1][0] == pytest.approx(57.736666666666665, abs=1e-12)
    assert result["points"][2] == [100, 0]


def test_history_window_selector_click_sets_exact_supported_window_once() -> None:
    result = _run_history_module(
        '''(() => {
          const handlers = {};
          let addCount = 0;
          const attrs = {};
          const button = {
            dataset: {historyWindowMs: "30000"},
            classList: {toggle() {}},
            setAttribute(name, value) { attrs[name] = value; },
            addEventListener(name, handler) { addCount += 1; handlers[name] = handler; },
          };
          const display = {textContent: ""};
          globalThis.document = {
            querySelectorAll(selector) {
              return selector === "[data-history-window-ms]" ? [button] : [];
            },
            getElementById(id) { return id === "history-display-window" ? display : null; },
          };
          mod.initializeHistoryWindowSelector(() => null);
          mod.initializeHistoryWindowSelector(() => null);
          handlers.click();
          return [mod.getActiveHistoryWindowMs(), display.textContent, button.dataset.historyWindowBound, attrs["aria-pressed"], addCount];
        })()'''
    )
    assert result == [30000, "30 s", "true", "true", 1]
