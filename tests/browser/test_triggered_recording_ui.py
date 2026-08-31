import base64
from pathlib import Path
import subprocess


def _run_module(source: str, program_body: str) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    program = f"""
const moduleUrl = 'data:text/javascript;base64,{encoded}';
const mod = await import(moduleUrl);
{program_body}
"""
    return subprocess.run(
        ["node", "--input-type=module", "-e", program],
        capture_output=True,
        text=True,
    )


def test_recording_trigger_state_normalizes_exact_backend_values() -> None:
    source = Path("frontend/js/recording-trigger.js").read_text(encoding="utf-8")
    completed = _run_module(
        source,
        """
const state = new mod.RecordingTriggerState();
state.replace([{
  device_id: 'emonio-a',
  state: 'ARMED',
  config: {
    block: 'TOTAL', measurement: 'PF', operator: 'LE', threshold: -0.000123456789,
    mode: 'CROSSING', recording_interval_s: 2.5
  },
  armed_utc: '2026-08-31T06:00:00+00:00',
  last_fired_cycle_id: 123,
  last_fired_utc: '2026-08-31T05:00:00+00:00',
  last_fired_value: -0.000987654321
}]);
console.log(JSON.stringify(state.forDevice('emonio-a')));
""",
    )
    assert completed.returncode == 0, completed.stderr
    payload = completed.stdout.strip()
    assert '"threshold":-0.000123456789' in payload
    assert '"last_fired_value":-0.000987654321' in payload
    assert '"state":"ARMED"' in payload
    assert '"block":"TOTAL"' in payload


def test_recording_trigger_state_fails_closed_for_malformed_records() -> None:
    source = Path("frontend/js/recording-trigger.js").read_text(encoding="utf-8")
    completed = _run_module(
        source,
        """
const state = new mod.RecordingTriggerState();
state.replace([
  null,
  {device_id: '', state: 'ARMED'},
  {device_id: 'bad-state', state: 'UNKNOWN'},
  {device_id: 'bad-threshold', state: 'DISARMED', config: {block:'A',measurement:'P',operator:'GT',threshold:'x',mode:'LEVEL',recording_interval_s:2}}
]);
console.log(JSON.stringify([state.forDevice('bad-state'), state.forDevice('bad-threshold')]));
""",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[null,null]"


def test_api_client_exposes_trigger_commands() -> None:
    source = Path("frontend/js/api.js").read_text(encoding="utf-8")
    assert "export function configureRecordingTrigger" in source
    assert "export function armRecordingTrigger" in source
    assert "export function disarmRecordingTrigger" in source
    assert '"/api/v1/recording/trigger/configure"' in source
    assert '"/api/v1/recording/trigger/arm"' in source
    assert '"/api/v1/recording/trigger/disarm"' in source


def test_recording_state_keeps_trigger_state_separate_from_active_recording_state() -> None:
    source = Path("frontend/js/recording-state.js").read_text(encoding="utf-8")
    assert 'from "./recording-trigger.js"' in source
    assert "this._triggers = new RecordingTriggerState();" in source
    assert "replaceStatus(activeRecords, errorRecords, triggerRecords = [])" in source
    assert "this._triggers.replace(triggerRecords);" in source
    assert "triggerForDevice(deviceId)" in source
    assert "return this._triggers.forDevice(deviceId);" in source
