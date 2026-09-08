from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest


MODULE_PATH = Path("frontend/js/load-control-stage4c-history.js")


def _run_module(expression: str) -> object:
    if not MODULE_PATH.exists():
        pytest.fail("Stage4C control history module is not implemented")
    source = MODULE_PATH.read_text(encoding="utf-8")
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


def _event(sequence: int, utc: str, event: str, fields: dict | None = None) -> dict:
    return {
        "sequence": sequence,
        "utc": utc,
        "event": event,
        "line": f"{utc} {event}",
        "fields": fields or {},
    }


def test_history_keeps_only_stage4c_and_stage4c_owned_pwm_evidence_in_sequence_order() -> None:
    events = [
        _event(10, "2026-09-08T07:00:00.000Z", "LAN_SCAN_COMPLETE", {"count": 1}),
        _event(11, "2026-09-08T07:00:00.010Z", "ZERO_EXPORT_ENABLED", {"source_id": "emonio-a"}),
        _event(12, "2026-09-08T07:00:00.020Z", "PWM_COMMAND_SENT", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 0.0}),
        _event(13, "2026-09-08T07:00:00.030Z", "PWM_ACK_QUALIFIED", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 0.0, "actual_duty_percent": 0.0, "compare_ticks": 0}),
        _event(14, "2026-09-08T07:00:00.040Z", "PWM_COMMAND_SENT", {"owner": None, "requested_duty_percent": 30.0}),
        _event(15, "2026-09-08T07:00:00.050Z", "ZERO_EXPORT_SETTLING_SAMPLE", {"cycle_id": 101, "cycle_finished_utc": "2026-09-08T07:00:00.045Z"}),
    ]
    payload = json.dumps({"latest_sequence": 15, "events": events})
    result = _run_module(
        f"(() => {{ const h = new mod.Stage4CControlHistory(); h.ingest({payload}, Date.parse('2026-09-08T07:00:00.100Z')); return h.events().map(x => x.sequence); }})()"
    )
    assert result == [11, 12, 13, 15]


def test_history_detects_missing_diagnostic_sequences_without_inventing_controller_events() -> None:
    first = json.dumps({
        "latest_sequence": 20,
        "events": [_event(20, "2026-09-08T07:00:00Z", "LAN_SCAN_COMPLETE")],
    })
    second = json.dumps({
        "latest_sequence": 23,
        "events": [
            _event(22, "2026-09-08T07:00:01Z", "ZERO_EXPORT_ENABLED"),
            _event(23, "2026-09-08T07:00:02Z", "ZERO_EXPORT_DISABLED"),
        ],
    })
    result = _run_module(
        f"(() => {{ const h = new mod.Stage4CControlHistory(); h.ingest({first}, Date.parse('2026-09-08T07:00:00Z')); h.ingest({second}, Date.parse('2026-09-08T07:00:02Z')); return {{gaps:h.sequenceGaps(), events:h.events().map(x => x.event)}}; }})()"
    )
    assert result == {
        "gaps": [{"afterSequence": 20, "beforeSequence": 22, "missingCount": 1}],
        "events": ["ZERO_EXPORT_ENABLED", "ZERO_EXPORT_DISABLED"],
    }


def test_history_has_deterministic_ten_minute_and_1200_record_bounds() -> None:
    time_result = _run_module(
        "(() => { const h = new mod.Stage4CControlHistory(); const e = (sequence, utc) => ({sequence, utc, event:'ZERO_EXPORT_ENABLED', line:'x', fields:{}}); h.ingest({latest_sequence:3, events:[e(1,'2026-09-08T07:00:00Z'), e(2,'2026-09-08T07:00:01Z'), e(3,'2026-09-08T07:10:01Z')]}, Date.parse('2026-09-08T07:10:01Z')); return h.events().map(x => x.sequence); })()"
    )
    assert time_result == [2, 3]

    count_result = _run_module(
        "(() => { const h = new mod.Stage4CControlHistory(); const events = Array.from({length:1201}, (_,i) => ({sequence:i+1, utc:'2026-09-08T07:10:00Z', event:'ZERO_EXPORT_ENABLED', line:'x', fields:{}})); h.ingest({latest_sequence:1201, events}, Date.parse('2026-09-08T07:10:00Z')); const out=h.events(); return [out.length, out[0].sequence, out.at(-1).sequence, mod.CONTROL_HISTORY_WINDOW_MS, mod.CONTROL_HISTORY_MAX_RECORDS]; })()"
    )
    assert count_result == [1200, 2, 1201, 600000, 1200]


def test_series_preserve_measurement_command_and_ack_timestamps_as_distinct_evidence() -> None:
    events = [
        _event(
            31,
            "2026-09-08T07:00:02.100Z",
            "ZERO_EXPORT_DECISION",
            {
                "cycle_id": 501,
                "cycle_finished_utc": "2026-09-08T07:00:02.000Z",
                "cycle_finished_monotonic_ns": 123456789,
                "source_id": "emonio-a",
                "phase": "A",
                "measured_p_w": -40.125,
                "p_deadband_w": 2.0,
                "action": "INCREASE",
                "controller_state": "CONTROLLING",
                "reason": None,
                "confirmed_requested_duty_percent": 0.0,
                "next_requested_duty_percent": 5.0,
            },
        ),
        _event(32, "2026-09-08T07:00:02.200Z", "PWM_COMMAND_SENT", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 5.0, "sequence": 81}),
        _event(33, "2026-09-08T07:00:02.260Z", "PWM_ACK_QUALIFIED", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 5.0, "actual_duty_percent": 4.98, "compare_ticks": 33, "period_ticks": 653, "sequence": 81}),
        _event(34, "2026-09-08T07:00:02.510Z", "ZERO_EXPORT_SETTLING_SAMPLE", {"cycle_id": 502, "cycle_finished_utc": "2026-09-08T07:00:02.500Z", "cycle_finished_monotonic_ns": 123956789, "controller_state": "SETTLING"}),
    ]
    result = _run_module(f"mod.deriveControlHistorySeries({json.dumps(events)})")
    assert result["p"][0]["utc"] == "2026-09-08T07:00:02.000Z"
    assert result["p"][0]["diagnosticUtc"] == "2026-09-08T07:00:02.100Z"
    assert result["p"][0]["pW"] == -40.125
    assert result["commands"][0]["utc"] == "2026-09-08T07:00:02.200Z"
    assert result["acks"][0]["utc"] == "2026-09-08T07:00:02.260Z"
    assert result["settling"][0]["utc"] == "2026-09-08T07:00:02.500Z"
    assert result["settling"][0]["diagnosticUtc"] == "2026-09-08T07:00:02.510Z"


def test_pwm_series_keeps_off_distinct_from_active_minimum_and_missing_optional_evidence_null() -> None:
    events = [
        _event(40, "2026-09-08T07:00:00Z", "PWM_ACK_QUALIFIED", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 0.0, "actual_duty_percent": 0.0, "compare_ticks": 0}),
        _event(41, "2026-09-08T07:00:01Z", "PWM_ACK_QUALIFIED", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 5.0}),
    ]
    result = _run_module(f"mod.deriveControlHistorySeries({json.dumps(events)}).acks")
    assert result == [
        {
            "sequence": 40,
            "utc": "2026-09-08T07:00:00Z",
            "requestedDutyPercent": 0,
            "actualDutyPercent": 0,
            "compareTicks": 0,
            "periodTicks": None,
            "isOff": True,
        },
        {
            "sequence": 41,
            "utc": "2026-09-08T07:00:01Z",
            "requestedDutyPercent": 5,
            "actualDutyPercent": None,
            "compareTicks": None,
            "periodTicks": None,
            "isOff": False,
        },
    ]


def test_controller_timeline_uses_exact_existing_state_vocabulary() -> None:
    events = [
        _event(50, "2026-09-08T07:00:00Z", "ZERO_EXPORT_DECISION", {"controller_state": "LIMIT_HIGH", "action": "LIMIT_HIGH", "reason": None}),
        _event(51, "2026-09-08T07:00:01Z", "ZERO_EXPORT_LIMIT_LOW", {"reason": "LOW_AUTHORITY_LIMIT"}),
        _event(52, "2026-09-08T07:00:02Z", "ZERO_EXPORT_RESOLUTION_LIMIT", {"direction": "INCREASE"}),
        _event(53, "2026-09-08T07:00:03Z", "ZERO_EXPORT_SAFE_BLOCK", {"state": "BLOCKED_SAFE", "reason": "SAMPLE_STALE"}),
    ]
    result = _run_module(f"mod.deriveControlHistorySeries({json.dumps(events)}).timeline.map(x => [x.event, x.state, x.reason])")
    assert result == [
        ["ZERO_EXPORT_DECISION", "LIMIT_HIGH", None],
        ["ZERO_EXPORT_LIMIT_LOW", "LIMIT_LOW", "LOW_AUTHORITY_LIMIT"],
        ["ZERO_EXPORT_RESOLUTION_LIMIT", "RESOLUTION_LIMIT", None],
        ["ZERO_EXPORT_SAFE_BLOCK", "BLOCKED_SAFE", "SAMPLE_STALE"],
    ]


def test_nearest_evidence_selection_uses_each_records_real_display_timestamp() -> None:
    events = [
        _event(60, "2026-09-08T07:00:02.100Z", "ZERO_EXPORT_DECISION", {"cycle_finished_utc": "2026-09-08T07:00:02.000Z", "measured_p_w": -20.0}),
        _event(61, "2026-09-08T07:00:02.200Z", "PWM_COMMAND_SENT", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 5.0}),
        _event(62, "2026-09-08T07:00:02.260Z", "PWM_ACK_QUALIFIED", {"owner": "STAGE4C_ZERO_EXPORT", "requested_duty_percent": 5.0, "actual_duty_percent": 4.98}),
    ]
    payload = json.dumps(events)
    result = _run_module(
        f"[mod.nearestControlEvidence({payload}, Date.parse('2026-09-08T07:00:02.010Z')), mod.nearestControlEvidence({payload}, Date.parse('2026-09-08T07:00:02.215Z'))]"
    )
    assert result[0]["sequence"] == 60
    assert result[0]["utc"] == "2026-09-08T07:00:02.000Z"
    assert result[0]["diagnosticUtc"] == "2026-09-08T07:00:02.100Z"
    assert result[0]["fields"]["measured_p_w"] == -20.0
    assert result[1]["sequence"] == 61
    assert result[1]["utc"] == "2026-09-08T07:00:02.200Z"
    assert result[1]["diagnosticUtc"] == "2026-09-08T07:00:02.200Z"
