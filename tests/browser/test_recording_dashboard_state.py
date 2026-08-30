from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_module(expression: str) -> object:
    source = Path("frontend/js/recording-state.js").read_text(encoding="utf-8")
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    program = f"const moduleUrl='data:text/javascript;base64,{encoded}'; const mod=await import(moduleUrl); console.log(JSON.stringify({expression}));"
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_recording_state_preserves_dashboard_fields() -> None:
    result = _run_module("""(() => { const state=new mod.RecordingState(); state.replaceStatus([{device_id:'a',state:'RECORDING',records_written:12,record_points_missed:2,eligible_samples_seen:15,invalid_cycles_seen:1,last_recorded_cycle_id:91,last_recorded_utc:'2026-08-30T11:20:21+00:00',next_record_utc:'2026-08-30T11:20:23+00:00',session_id:'session-a',application_version:'0.4.13',acquisition_interval_s:2}], []); return state.forDevice('a'); })()""")
    assert result["state"] == "RECORDING"
    assert result["records_written"] == 12
    assert result["record_points_missed"] == 2
    assert result["eligible_samples_seen"] == 15
    assert result["invalid_cycles_seen"] == 1
    assert result["last_recorded_cycle_id"] == 91
    assert result["session_id"] == "session-a"
    assert result["application_version"] == "0.4.13"
    assert result["acquisition_interval_s"] == 2


def test_recording_state_summary_aggregates_all_sessions() -> None:
    result = _run_module("""(() => { const state=new mod.RecordingState(); state.replaceStatus([{device_id:'a',records_written:10,record_points_missed:1},{device_id:'b',records_written:20,record_points_missed:2}], [{device_id:'c',state:'ERROR',error_type:'OSError',error_detail:'write failed'}]); return state.summary(); })()""")
    assert result == {"active": 2, "errors": 1, "records_written": 30, "record_points_missed": 3}
