from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_scope_module(expression: str) -> object:
    api_source = Path("frontend/js/api.js").read_text(encoding="utf-8")
    api_url = "data:text/javascript;base64," + base64.b64encode(api_source.encode()).decode("ascii")
    source = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    source = source.replace('from "./api.js"', f'from "{api_url}"')
    encoded = base64.b64encode(source.encode()).decode("ascii")
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


def _capture() -> str:
    return json.dumps(
        {
            "capture_ms": 35.6,
            "sample_count": 3,
            "channels": {
                "0": {"samples": [-2.0, 0.0, 4.0]},
                "1": {"samples": [-300.0, 0.0, 330.0]},
                "2": {"samples": [-5.0, 1.0, 3.0]},
                "3": {"samples": [-320.0, 10.0, 310.0]},
                "4": {"samples": [-7.0, 2.0, 6.0]},
                "5": {"samples": [-340.0, 20.0, 335.0]},
            },
        }
    )


def test_scope_x_projection_uses_sample_index_across_reported_capture_axis() -> None:
    result = _run_scope_module(
        "[mod.projectScopeX(0, 3, 10, 110), mod.projectScopeX(1, 3, 10, 110), mod.projectScopeX(2, 3, 10, 110)]"
    )
    assert result == [10, 60, 110]


def test_scope_y_projection_is_symmetric_zero_centered_and_sign_preserving() -> None:
    result = _run_scope_module(
        "[mod.projectScopeY(10, 10, 20, 220), mod.projectScopeY(0, 10, 20, 220), mod.projectScopeY(-10, 10, 20, 220)]"
    )
    assert result == [20, 120, 220]


def test_scope_trace_selection_uses_field_qualified_channels_without_transforming_values() -> None:
    capture = _capture()
    result = _run_scope_module(
        f'''(() => {{
          const capture = {capture};
          return [
            mod.scopeTraceSpecs(capture, "A", "U+I").map(x => [x.phase, x.signal, x.channel, x.samples]),
            mod.scopeTraceSpecs(capture, "ABC", "U").map(x => x.channel),
            mod.scopeTraceSpecs(capture, "C", "I").map(x => x.samples),
          ];
        }})()'''
    )
    assert result[0] == [
        ["A", "U", 1, [-300.0, 0.0, 330.0]],
        ["A", "I", 0, [-2.0, 0.0, 4.0]],
    ]
    assert result[1] == [1, 3, 5]
    assert result[2] == [[-7.0, 2.0, 6.0]]


def test_scope_unit_magnitudes_use_visible_exact_samples_and_keep_u_i_separate() -> None:
    capture = _capture()
    result = _run_scope_module(
        f'''(() => {{
          const traces = mod.scopeTraceSpecs({capture}, "ABC", "U+I");
          return mod.scopeUnitMagnitudes(traces);
        }})()'''
    )
    assert result == {"U": 340, "I": 7}


def test_scope_trace_points_are_adjacent_measured_vertices_only() -> None:
    result = _run_scope_module(
        "mod.buildScopeTracePoints([-4, 0, 2], 4, {left:10,right:110,top:20,bottom:220})"
    )
    assert result == [[10, 220], [60, 120], [110, 70]]


def test_scope_grid_positions_are_deterministic_and_include_both_boundaries() -> None:
    result = _run_scope_module("mod.scopeGridPositions(100, 900, 4)")
    assert result == [100, 300, 500, 700, 900]


def test_scope_view_mode_is_isolated_per_emonio() -> None:
    result = _run_scope_module(
        '''(() => {
          mod.setScopeViewModeForDevice("emonio-a", "ABC", "U");
          mod.setScopeViewModeForDevice("emonio-b", "B", "I");
          return [
            mod.scopeViewModeForDevice("emonio-a"),
            mod.scopeViewModeForDevice("emonio-b"),
            mod.scopeViewModeForDevice("emonio-c"),
          ];
        })()'''
    )
    assert result == [
        {"phase": "ABC", "signal": "U"},
        {"phase": "B", "signal": "I"},
        {"phase": "A", "signal": "U+I"},
    ]


def test_scope_view_mode_rejects_invalid_values_without_changing_device_state() -> None:
    result = _run_scope_module(
        '''(() => {
          mod.setScopeViewModeForDevice("emonio-a", "C", "U+I");
          const phaseAccepted = mod.setScopeViewModeForDevice("emonio-a", "INVALID", "U");
          const signalAccepted = mod.setScopeViewModeForDevice("emonio-a", "A", "INVALID");
          return [phaseAccepted, signalAccepted, mod.scopeViewModeForDevice("emonio-a")];
        })()'''
    )
    assert result == [False, False, {"phase": "C", "signal": "U+I"}]


def test_scope_active_owner_summary_keeps_live_connecting_and_hold_sessions() -> None:
    result = _run_scope_module(
        '''mod.scopeActiveOwners([
          {device_id:"b", state:"HOLD"},
          {device_id:"a", state:"LIVE"},
          {device_id:"c", state:"DISCONNECTED"},
          {device_id:"d", state:"ERROR"},
          {device_id:"e", state:"CONNECTING"}
        ])'''
    )
    assert result == [
        {"device_id": "a", "state": "LIVE"},
        {"device_id": "b", "state": "HOLD"},
        {"device_id": "e", "state": "CONNECTING"},
    ]


def test_scope_stale_response_guard_requires_requested_device_to_still_be_selected() -> None:
    result = _run_scope_module(
        '[mod.scopeResponseIsCurrent("a", "a"), mod.scopeResponseIsCurrent("a", "b")]'
    )
    assert result == [True, False]


def test_scope_observed_prefixes_use_capture_evidence_without_filtering_known_values() -> None:
    result = _run_scope_module(
        """(() => {
          const capture = {
            observed_header_prefixes: ["810400", "e5d200", "e90f00"],
            channels: {
              "0": {header_prefix_hex:"e5d200", samples:[0]},
              "1": {header_prefix_hex:"810400", samples:[0]}
            }
          };
          return mod.scopeObservedHeaderPrefixes(capture);
        })()"""
    )
    assert result == ["810400", "e5d200", "e90f00"]


def test_scope_selectable_devices_keeps_enabled_runtime_targets_in_config_order() -> None:
    result = _run_scope_module(
        """mod.scopeSelectableDevices([
          {id:\"emonio-a\", name:\"LAB A\", host:\"emonio-a.local\", enabled:true},
          {id:\"emonio-off\", name:\"OFF\", host:\"emonio-off.local\", enabled:false},
          {id:\"emonio-b\", name:\"LAB B\", host:\"192.0.2.42\", enabled:true},
          {id:\"\", name:\"INVALID\", host:\"invalid\", enabled:true}
        ])"""
    )
    assert result == [
        {"id": "emonio-a", "label": "LAB A · emonio-a.local"},
        {"id": "emonio-b", "label": "LAB B · 192.0.2.42"},
    ]


def _run_scope_module_with_deferred_status(expression: str) -> object:
    api_source = r'''
globalThis.__scopeStatusResolvers = [];
export function getScopeStatus(deviceId) {
  return new Promise((resolve) => globalThis.__scopeStatusResolvers.push({deviceId, resolve}));
}
export async function holdScope() { return {}; }
export async function liveScope() { return {}; }
export async function startScope() { return {}; }
export async function stopScope() { return {}; }
'''
    api_url = "data:text/javascript;base64," + base64.b64encode(api_source.encode()).decode("ascii")
    source = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    source = source.replace('from "./api.js"', f'from "{api_url}"')
    source = source.replace('let selectedDeviceReader = () => null;', 'let selectedDeviceReader = () => "a";')
    encoded = base64.b64encode(source.encode()).decode("ascii")
    program = f"""
const nodes = new Map();
function nodeFor(id) {{
  if (!nodes.has(id)) nodes.set(id, {{
    id, textContent:"", value:"", disabled:false, dataset:{{}},
    className:"", classList:{{toggle(){{}},add(){{}},remove(){{}}}},
    replaceChildren(){{}}, appendChild(){{}}, setAttribute(){{}}, addEventListener(){{}},
  }});
  return nodes.get(id);
}}
globalThis.document = {{
  getElementById(id) {{ return id === "scope-plot" || id === "scope-device-selector" || id === "scope-active-owners" ? null : nodeFor(id); }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return nodeFor(`created-${{Math.random()}}`); }},
  createElementNS() {{ return nodeFor(`svg-${{Math.random()}}`); }},
}};
const mod = await import('data:text/javascript;base64,{encoded}');
const result = await ({expression});
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True, capture_output=True, text=True,
    )
    return json.loads(completed.stdout)


def test_same_device_scope_status_rejects_older_response_that_arrives_last() -> None:
    result = _run_scope_module_with_deferred_status(
        r'''(async () => {
          const first = mod.refreshScopeStatus("a");
          const second = mod.refreshScopeStatus("a");
          await Promise.resolve();
          globalThis.__scopeStatusResolvers[1].resolve({device_id:"a", state:"HOLD", capture:null});
          await second;
          globalThis.__scopeStatusResolvers[0].resolve({device_id:"a", state:"LIVE", capture:null});
          await first;
          return document.getElementById("scope-state").textContent;
        })()'''
    )
    assert result == "HOLD"


def test_scope_polling_uses_one_awaited_request_before_scheduling_the_next() -> None:
    source = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    assert "setInterval(() => refreshScopeStatus(), 1000)" not in source
    assert "async function pollScopeStatus" in source
    poll = source[source.index("async function pollScopeStatus"):source.index("export function initializeScopeControls")]
    assert "await refreshScopeStatus()" in poll
    assert "setTimeout(pollScopeStatus, 1000)" in poll


def test_scope_control_response_invalidates_older_inflight_status_response() -> None:
    source = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    block = source[source.index("function renderControlResponse"):source.index("export function initializeScopeControls") ]
    assert "invalidateScopeStatusResponses" in block


def test_scope_trace_points_fail_closed_when_any_sample_is_not_finite() -> None:
    result = _run_scope_module(
        "mod.buildScopeTracePoints([1, null, 2], 2, {left:10,right:110,top:20,bottom:220})"
    )
    assert result == []


def test_scope_capture_validation_rejects_wrong_sample_count_channel_shape_and_nonfinite_samples() -> None:
    result = _run_scope_module(
        r'''(() => {
          const make = () => ({
            sequence: 1, received_utc: "2026-08-28T10:00:00+00:00", source: "EMONIO_WEBSOCKET_SCOPE",
            capture_ms: 35.6, sample_count: 232, sample_interval_ms: 35.6 / 231, sample_rate_hz: 231 / 0.0356,
            channel_order: [0,1,2,3,4,5], metadata_order: [0,1,2],
            channels: Object.fromEntries(Array.from({length:6}, (_, channel) => [String(channel), {
              channel, frame_bytes:932, sample_count:232, nonfinite_count:0, samples:Array(232).fill(channel + 0.25)
            }])),
            metadata: Object.fromEntries(Array.from({length:3}, (_, phase) => [String(phase), {
              phase, capture_ms:35.6
            }]))
          });
          if (typeof mod.scopeCaptureValidationError !== "function") return ["MISSING"];
          const valid = make();
          const short = make(); short.channels["2"].samples = [1,2];
          const wrongCount = make(); wrongCount.sample_count = 231;
          const wrongPhase = make(); wrongPhase.metadata["1"].phase = 2;
          const nonfinite = make(); nonfinite.channels["4"].samples[20] = NaN;
          return [valid, short, wrongCount, wrongPhase, nonfinite].map(mod.scopeCaptureValidationError);
        })()'''
    )
    assert result[0] is None
    assert "232 samples" in result[1]
    assert "sample_count" in result[2]
    assert "metadata phase" in result[3]
    assert "finite" in result[4]


def test_render_scope_status_rejects_malformed_capture_before_any_waveform_evidence_is_shown() -> None:
    result = _run_scope_module_with_deferred_status(
        r'''(() => {
          mod.renderScopeStatus({
            device_id:"a", state:"LIVE", error:null,
            capture:{
              sequence:9, received_utc:"2026-08-28T10:00:00+00:00",
              capture_ms:35.6, sample_count:2, sample_interval_ms:35.6, sample_rate_hz:28.09,
              channel_order:[0,1,2,3,4,5], metadata_order:[0,1,2],
              channels:{"0":{channel:0,frame_bytes:932,sample_count:2,nonfinite_count:0,samples:[1,2]}},
              metadata:{}
            }
          });
          return {
            sequence: document.getElementById("scope-capture-sequence").textContent,
            samples: document.getElementById("scope-samples").textContent,
            error: document.getElementById("scope-error").textContent,
          };
        })()'''
    )
    assert result["sequence"] == "—"
    assert result["samples"] == "—"
    assert result["error"].startswith("INVALID CAPTURE:")
