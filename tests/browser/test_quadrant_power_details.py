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


def test_phase_power_details_keep_canonical_s_and_compute_resultant_angle() -> None:
    result = _run_quadrant_module(
        "mod.computePowerVectorDetails({p: 3, q: 4, s: 5, pf: 0.6}, false)"
    )
    assert result["canonicalS"] == 5
    assert abs(result["resultantS"] - 5) < 1e-12
    assert abs(result["phiDeg"] - 53.13010235415598) < 1e-12
    assert result["pf"] == 0.6
    assert result["quadrant"] == "Q1"
    assert result["isTotal"] is False


def test_power_details_preserve_signed_quadrant_with_atan2() -> None:
    result = _run_quadrant_module(
        "mod.computePowerVectorDetails({p: -3, q: -4, s: 5, pf: -0.6}, false)"
    )
    assert abs(result["phiDeg"] - (-126.86989764584402)) < 1e-12
    assert result["quadrant"] == "Q3"


def test_total_keeps_canonical_sigma_s_distinct_from_resultant_pq_magnitude() -> None:
    result = _run_quadrant_module(
        "mod.computePowerVectorDetails({p: -127.60646057128906, q: -1031.6353759765625, s: 1088.2021484375, pf: -0.117263562977314}, true)"
    )
    assert abs(result["canonicalS"] - 1088.2021484375) < 1e-9
    assert abs(result["resultantS"] - 1039.4974544200843) < 1e-9
    assert result["canonicalS"] != result["resultantS"]
    assert result["isTotal"] is True
    assert result["quadrant"] == "Q3"


def test_zero_power_marks_angle_as_not_meaningful() -> None:
    result = _run_quadrant_module(
        "mod.computePowerVectorDetails({p: 0, q: 0, s: 0, pf: 0}, false)"
    )
    assert result["meaningful"] is False
    assert result["phiDeg"] is None
