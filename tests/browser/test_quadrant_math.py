from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_quadrant_module(expression: str) -> object:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
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


def test_adaptive_scale_expands_immediately_and_keeps_symmetric_limit() -> None:
    result = _run_quadrant_module(
        "mod.computeAdaptiveLimit(100, 1200, 0)"
    )
    assert result[0] >= 1200
    assert result[1] == 0


def test_adaptive_scale_does_not_shrink_on_one_small_sample() -> None:
    result = _run_quadrant_module(
        "mod.computeAdaptiveLimit(1200, 100, 0)"
    )
    assert result[0] == 1200
    assert result[1] == 1


def test_adaptive_scale_shrinks_only_after_confirmed_low_range() -> None:
    result = _run_quadrant_module(
        "mod.computeAdaptiveLimit(1200, 100, mod.SHRINK_CONFIRMATION_SAMPLES - 1)"
    )
    assert 100 <= result[0] < 1200
    assert result[1] == 0
