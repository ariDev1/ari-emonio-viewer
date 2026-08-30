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


def test_plot_model_exposes_four_selectable_phase_views() -> None:
    result = _run_quadrant_module("mod.PHASE_PLOTS")
    assert [(item["label"], item["key"]) for item in result] == [
        ("A", "phase_a"),
        ("B", "phase_b"),
        ("C", "phase_c"),
        ("TOTAL", "total"),
    ]


def test_phase_detail_rows_show_p_q_s_phi_pf_and_quadrant() -> None:
    result = _run_quadrant_module(
        "mod.buildPowerDetailRows(mod.computePowerVectorDetails({p: 3, q: 4, s: 5, pf: 0.6}, false))"
    )
    assert [row["label"] for row in result] == ["P", "Q", "S", "φ", "PF", "QUADRANT"]


def test_total_detail_rows_separate_sigma_s_from_resultant_vector() -> None:
    result = _run_quadrant_module(
        "mod.buildPowerDetailRows(mod.computePowerVectorDetails({p: -127.60646057128906, q: -1031.6353759765625, s: 1088.2021484375, pf: -0.117263562977314}, true))"
    )
    assert [row["label"] for row in result] == [
        "P",
        "Q",
        "ΣS",
        "|P+jQ|",
        "φPQ",
        "PF",
        "QUADRANT",
    ]


def test_near_vertical_label_layout_separates_components_from_resultant() -> None:
    result = _run_quadrant_module(
        "mod.computePowerLabelLayout(-174.1153, -7269.7627, 8200)"
    )
    assert result["orientation"] == "near-vertical"
    assert result["p"]["x"] < 190
    assert result["q"]["x"] < 190
    assert result["vector"]["x"] > 190
    assert result["angle"]["radius"] >= 58


def test_near_horizontal_label_layout_moves_q_and_angle_away_from_p_axis() -> None:
    result = _run_quadrant_module(
        "mod.computePowerLabelLayout(7200, 120, 8200)"
    )
    assert result["orientation"] == "near-horizontal"
    assert result["q"]["y"] < 225
    assert result["angle"]["radius"] >= 58
    assert result["p"]["y"] != result["q"]["y"]


def test_axis_state_uses_canonical_backend_quadrant_evidence() -> None:
    result = _run_quadrant_module(
        'mod.computePowerVectorDetails({p: 0, q: 4, s: 4, pf: 0, quadrant: "P_AXIS_POSITIVE_Q"}, false)'
    )
    assert result["quadrant"] == "P_AXIS_POSITIVE_Q"
