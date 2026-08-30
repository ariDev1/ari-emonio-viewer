from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_module(expression: str) -> object:
    source = Path("frontend/js/recording-state.js").read_text(encoding="utf-8")
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


def test_recording_state_is_keyed_by_emonio_device() -> None:
    result = _run_module(
        """(() => {
          const state = new mod.RecordingState();
          state.replaceActive([{device_id:'emonio-a', device_name:'emonio-a', interval_s:10, session_dir:'/a'}]);
          return [state.isActive('emonio-a'), state.isActive('emonio-b'), state.activeDeviceIds()];
        })()"""
    )
    assert result == [True, False, ["emonio-a"]]


def test_switching_selected_device_does_not_change_recording_owner() -> None:
    result = _run_module(
        """(() => {
          const state = new mod.RecordingState();
          state.replaceActive([{device_id:'emonio-a', device_name:'Meter A', interval_s:5, session_dir:'/a'}]);
          const before = state.forDevice('emonio-a');
          const selectedB = state.forDevice('emonio-b');
          const after = state.forDevice('emonio-a');
          return [before.device_id, selectedB, after.device_id, state.activeDeviceIds()];
        })()"""
    )
    assert result == ["emonio-a", None, "emonio-a", ["emonio-a"]]


def test_recording_state_replaces_stale_browser_memory_from_backend_status() -> None:
    result = _run_module(
        """(() => {
          const state = new mod.RecordingState();
          state.replaceActive([{device_id:'emonio-a', device_name:'A', interval_s:10, session_dir:'/old'}]);
          state.replaceActive([{device_id:'emonio-b', device_name:'B', interval_s:2, session_dir:'/new'}]);
          return [state.isActive('emonio-a'), state.forDevice('emonio-b').interval_s, state.activeDeviceIds()];
        })()"""
    )
    assert result == [False, 2, ["emonio-b"]]


def test_recording_error_is_separate_from_active_recording_state() -> None:
    result = _run_module(
        """(() => {
          const state = new mod.RecordingState();
          state.replaceStatus(
            [{device_id:'emonio-a', device_name:'A', interval_s:10, session_dir:'/active'}],
            [{device_id:'emonio-b', device_name:'B', state:'ERROR', interval_s:5, session_dir:'/failed', error_type:'OSError', error_detail:'disk full'}]
          );
          const failure = state.errorForDevice('emonio-b');
          return [state.isActive('emonio-a'), state.isActive('emonio-b'), failure.state, failure.error_type, failure.error_detail];
        })()"""
    )
    assert result == [True, False, "ERROR", "OSError", "disk full"]
