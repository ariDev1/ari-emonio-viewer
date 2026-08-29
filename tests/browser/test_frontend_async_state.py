from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess


def _run_app_module(expression: str, *, api_mode: str) -> object:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    source = re.sub(r'import[\s\S]*?from "\./[^\"]+";\n', "", source)
    source = source[: source.index("main().catch")]
    source = source.replace("async function selectDevice(deviceId)", "export async function selectDevice(deviceId)")
    source = source.replace("async function refreshBackendState()", "export async function refreshBackendState()")
    source = source.replace(
        "let selectedDevice = null;",
        "let selectedDevice = null;\nexport function __setSelectedDeviceForTest(value) { selectedDevice = value; }",
    )

    common_stubs = r'''
class RecordingState {
  replaceActive() {}
  forDevice() { return null; }
  activeRecordings() { return []; }
  isActive() { return false; }
}
const __noop = () => {};
const __asyncTrue = async () => true;
const changeRecordingInterval = __asyncTrue;
const connectDevice = __asyncTrue;
const getRecordingStatus = async () => ({active:[]});
const getRuntimeConfig = async () => ({devices:[]});
const startRecording = __asyncTrue;
const stopRecording = __asyncTrue;
const initializeCtEvidenceControls = __noop;
const refreshCtEvidence = __asyncTrue;
const initializeModbusEvidenceControls = __noop;
const refreshModbusEvidence = __asyncTrue;
const initializeMeasurementPanels = __noop;
const initializeHistoryInspection = __noop;
const initializeHistoryMetricSelector = __noop;
const initializeHistoryWindowSelector = __noop;
const initializeUtilityDrawers = __noop;
const initializeScopeControls = __noop;
const refreshScopeStatus = __asyncTrue;
globalThis.__measurementRenders = [];
globalThis.__backendRenders = [];
globalThis.__diagnosticRenders = [];
globalThis.__historyAppends = [];
const renderMeasurementPayload = (payload) => globalThis.__measurementRenders.push(payload?.device_id ?? null);
const renderBackendStatus = (payload) => globalThis.__backendRenders.push(payload?.device_id ?? null);
const renderDiagnostics = (payload) => globalThis.__diagnosticRenders.push(payload?.device_id ?? null);
const appendHistoryPayload = (payload) => globalThis.__historyAppends.push(payload?.device_id ?? null);
const renderMeasurementHistory = __noop;
const renderQuadrant = __noop;
const resetQuadrantScale = __noop;
const nodes = new Map();
function nodeFor(id) {
  if (!nodes.has(id)) nodes.set(id, {
    id, textContent:"", value:"", disabled:false, dataset:{}, options:[],
    classList:{toggle(){},add(){},remove(){}},
    replaceChildren(){ this.options = []; },
    appendChild(child){ this.options.push(child); },
    addEventListener(){},
  });
  return nodes.get(id);
}
globalThis.document = {
  getElementById: nodeFor,
  createElement: () => nodeFor(`created-${Math.random()}`),
  querySelectorAll: () => [],
};
globalThis.location = {protocol:"http:", host:"localhost"};
globalThis.WebSocket = class { addEventListener(){} close(){} };
globalThis.setInterval = () => 1;
globalThis.clearTimeout = () => {};
globalThis.setTimeout = () => 1;
'''

    if api_mode == "device":
        api_stubs = r'''
globalThis.__deviceResolvers = {};
const getDevice = (deviceId) => new Promise((resolve) => { globalThis.__deviceResolvers[deviceId] = resolve; });
const getDevices = async () => [];
const getDiagnostics = async (deviceId) => ({device_id: deviceId});
'''
    elif api_mode == "backend":
        api_stubs = r'''
globalThis.__deviceListRequests = [];
globalThis.__diagnosticRequests = [];
const getDevice = async (deviceId) => ({device_id:deviceId, sample:null});
const getDevices = () => new Promise((resolve) => { globalThis.__deviceListRequests.push(resolve); });
const getDiagnostics = (deviceId) => new Promise((resolve) => { globalThis.__diagnosticRequests.push({deviceId, resolve}); });
'''
    else:
        raise ValueError(api_mode)

    encoded = base64.b64encode((common_stubs + api_stubs + source).encode()).decode("ascii")
    program = f'''
const mod = await import("data:text/javascript;base64,{encoded}");
const result = await ({expression});
console.log(JSON.stringify(result));
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_delayed_old_device_selection_cannot_overwrite_new_selected_measurement() -> None:
    result = _run_app_module(
        r'''(async () => {
          const first = mod.selectDevice("A");
          await Promise.resolve();
          const second = mod.selectDevice("B");
          await Promise.resolve();
          globalThis.__deviceResolvers.B({device_id:"B", sample:{device:"B"}});
          await second;
          globalThis.__deviceResolvers.A({device_id:"A", sample:{device:"A"}});
          await first;
          return {
            renders: globalThis.__measurementRenders,
            history: globalThis.__historyAppends,
          };
        })()''',
        api_mode="device",
    )
    assert result["renders"] == ["B"]
    assert sorted(result["history"]) == ["A", "B"]


def test_delayed_backend_diagnostics_response_cannot_cross_device_selection_generation() -> None:
    result = _run_app_module(
        r'''(async () => {
          mod.__setSelectedDeviceForTest("A");
          const first = mod.refreshBackendState();
          await Promise.resolve();
          mod.__setSelectedDeviceForTest("B");
          const second = mod.refreshBackendState();
          await Promise.resolve();

          globalThis.__deviceListRequests[1]([{device_id:"B"}]);
          globalThis.__diagnosticRequests[1].resolve({device_id:"B"});
          await second;

          globalThis.__deviceListRequests[0]([{device_id:"A"}]);
          globalThis.__diagnosticRequests[0].resolve({device_id:"A"});
          await first;
          return {
            backends: globalThis.__backendRenders,
            diagnostics: globalThis.__diagnosticRenders,
          };
        })()''',
        api_mode="backend",
    )
    assert result["backends"] == ["B"]
    assert result["diagnostics"] == ["B"]
