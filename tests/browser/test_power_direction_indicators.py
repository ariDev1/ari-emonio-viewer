from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_measurements_module(expression: str) -> object:
    source = Path("frontend/js/measurements.js").read_text(encoding="utf-8")
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


def test_power_direction_state_is_derived_only_from_canonical_p_sign() -> None:
    assert _run_measurements_module(
        "[-12.5, 8.0, 0.0, Number.NaN, undefined].map(mod.powerDirectionState)"
    ) == ["negative", "positive", "neutral", "neutral", "neutral"]


def test_frontend_initializer_defines_three_phase_indicators_after_title() -> None:
    source = Path("frontend/js/measurements.js").read_text(encoding="utf-8")
    assert 'power-direction-a' in source
    assert 'power-direction-b' in source
    assert 'power-direction-c' in source
    assert 'insertAdjacentElement("afterend", group)' in source


def test_backend_no_sample_state_resets_all_indicators_to_neutral() -> None:
    source = Path("frontend/js/measurements.js").read_text(encoding="utf-8")
    backend_start = source.index("export function renderBackendStatus(device)")
    backend_source = source[backend_start:]
    assert "renderPowerDirectionIndicators(null)" in backend_source


def test_power_direction_indicator_css_has_neutral_negative_and_positive_states() -> None:
    css = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert ".power-direction-indicator" in css
    assert ".power-direction-indicator.is-neutral" in css
    assert ".power-direction-indicator.is-negative" in css
    assert ".power-direction-indicator.is-positive" in css
