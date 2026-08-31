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


def test_recording_drawer_contains_stable_trigger_controls_without_replacing_main_strip() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    for control_id in (
        "recording-trigger-state",
        "recording-trigger-mode",
        "recording-trigger-block",
        "recording-trigger-measurement",
        "recording-trigger-operator",
        "recording-trigger-threshold",
        "recording-trigger-interval",
        "recording-trigger-configure",
        "recording-trigger-arm",
        "recording-trigger-disarm",
        "recording-trigger-last-fired",
    ):
        assert control_id in source
    assert 'document.getElementById("record-start").addEventListener' in source
    assert 'document.getElementById("record-stop").addEventListener' in source


def test_recording_status_refresh_is_backend_authoritative_for_trigger_state() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert "payload?.triggers ?? []" in source
    assert "recordingState.replaceStatus(" in source
    assert "configureRecordingTrigger" in source
    assert "armRecordingTrigger" in source
    assert "disarmRecordingTrigger" in source
    assert "await refreshRecordingState(" in source


def test_trigger_controls_encode_recording_and_armed_ownership_rules() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert "selectedTrigger = selectedDevice ? recordingState.triggerForDevice(selectedDevice) : null" in source
    assert 'selectedTrigger?.state === "ARMED"' in source
    assert "renderRecordingTriggerPanel" in source
    assert "configureSelectedTrigger" in source
    assert "armSelectedTrigger" in source
    assert "disarmSelectedTrigger" in source
    assert "recordingState.isActive(deviceId) || recordingState.triggerForDevice(deviceId)?.state === \"ARMED\"" in source


def test_trigger_configuration_changes_are_sent_to_backend_not_only_simulated_locally() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    handler = source[source.index("function initializeRecordingTriggerControls"):source.index("async function main")]
    for control_id in (
        "recording-trigger-mode",
        "recording-trigger-block",
        "recording-trigger-measurement",
        "recording-trigger-operator",
        "recording-trigger-threshold",
        "recording-trigger-interval",
    ):
        assert f'"{control_id}"' in handler
    assert 'addEventListener("change", configureSelectedTrigger)' in handler


def test_trigger_threshold_requires_explicit_value_and_active_edit_is_not_overwritten() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert "triggerDraftDevice" in source
    assert "document.activeElement !== node" in source
    handler = source[source.index("function initializeRecordingTriggerControls"):source.index("async function main")]
    assert 'const thresholdText = document.getElementById("recording-trigger-threshold").value.trim();' in handler
    assert 'if (thresholdText === "")' in handler
    assert "const threshold = Number(thresholdText);" in handler


def test_trigger_css_is_structured_and_scoped() -> None:
    recording_css = Path("frontend/css/recording.css").read_text(encoding="utf-8")
    trigger_css = Path("frontend/css/recording-trigger.css").read_text(encoding="utf-8")
    assert recording_css.startswith('@import url("./recording-trigger.css");')
    assert ".recording-trigger-" not in recording_css.replace('@import url("./recording-trigger.css");', "")
    assert ".recording-trigger-panel" in trigger_css
    assert ".recording-trigger-grid" in trigger_css
    assert "style=" not in trigger_css
