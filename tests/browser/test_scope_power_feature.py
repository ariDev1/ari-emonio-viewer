from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import subprocess

from emonio_viewer import __version__
from emonio_viewer.server.app import create_app


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
            "channels": {
                "0": {"samples": [-2.0, 0.0, 4.0]},
                "1": {"samples": [-300.0, 0.0, 330.0]},
                "2": {"samples": [-5.0, 1.0, 3.0]},
                "3": {"samples": [-320.0, 10.0, 310.0]},
                "4": {"samples": [-7.0, 2.0, 6.0]},
                "5": {"samples": [-340.0, 20.0, 335.0]},
            }
        }
    )


def test_scope_p_mode_derives_exact_same_index_power_for_all_three_phases() -> None:
    result = _run_scope_module(
        f'''(() => {{
          const traces = mod.scopeTraceSpecs({_capture()}, "ABC", "P");
          return traces.map(trace => [trace.phase, trace.signal, trace.unit, trace.samples]);
        }})()'''
    )
    assert result == [
        ["A", "P", "W", [600.0, 0.0, 1320.0]],
        ["B", "P", "W", [1600.0, 10.0, 930.0]],
        ["C", "P", "W", [2380.0, 40.0, 2010.0]],
    ]


def test_scope_p_mode_uses_one_common_symmetric_watt_magnitude() -> None:
    result = _run_scope_module(
        f'''(() => {{
          const traces = mod.scopeTraceSpecs({_capture()}, "ABC", "P");
          return mod.scopeUnitMagnitudes(traces);
        }})()'''
    )
    assert result == {"P": 2380}


def test_scope_p_view_mode_is_device_local_and_selectable() -> None:
    result = _run_scope_module(
        '''(() => {
          const accepted = mod.setScopeViewModeForDevice("emonio-a", "ABC", "P");
          return [accepted, mod.scopeViewModeForDevice("emonio-a")];
        })()'''
    )
    assert result == [True, {"phase": "ABC", "signal": "P"}]


def test_scope_p_mode_fails_closed_for_mismatched_or_nonfinite_ui_samples() -> None:
    result = _run_scope_module(
        '''(() => {
          const capture = {
            channels: {
              "0": {samples:[1, 2, 3]}, "1": {samples:[10, 20]},
              "2": {samples:[1, 2, 3]}, "3": {samples:[10, NaN, 30]},
              "4": {samples:[1, 2, 3]}, "5": {samples:[10, 20, 30]}
            }
          };
          return [
            mod.scopeTraceSpecs(capture, "A", "P"),
            mod.scopeTraceSpecs(capture, "B", "P"),
            mod.scopeTraceSpecs(capture, "C", "P").map(trace => trace.samples)
          ];
        })()'''
    )
    assert result == [[], [], [[10, 40, 90]]]


def test_scope_markup_exposes_p_as_a_single_plot_signal_mode() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'data-scope-signal="P"' in html
    assert html.count('id="scope-plot"') == 1


def test_index_response_exposes_authoritative_application_version(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<span class="eyebrow">ARI EMONIO VIEWER</span>'
        '<script type="module" src="/static/js/app.js"></script>',
        encoding="utf-8",
    )
    app = create_app(object(), object(), object(), object(), tmp_path)
    index_route = next(route for route in app.router.routes() if route.method == "GET" and route.resource.canonical == "/")
    response = asyncio.run(index_route.handler(None))
    assert f"ARI EMONIO VIEWER · v{__version__}" in response.text
    assert f'/static/{__version__}/js/app.js' in response.text
