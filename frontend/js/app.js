import {
  changeRecordingInterval,
  connectDevice,
  getDevice,
  getDevices,
  getDiagnostics,
  getRecordingStatus,
  getRuntimeConfig,
  startRecording,
  stopRecording,
} from "./api.js";
import { renderDiagnostics } from "./diagnostics.js";
import { initializeCtEvidenceControls, refreshCtEvidence } from "./ct-evidence.js";
import { initializeModbusEvidenceControls, refreshModbusEvidence } from "./modbus-evidence.js";
import { initializeMeasurementPanels, renderBackendStatus, renderMeasurementPayload } from "./measurements.js";
import {
  appendHistoryPayload,
  initializeHistoryInspection,
  initializeHistoryInspectorCopy,
  initializeHistoryMetricSelector,
  initializeHistoryWindowSelector,
  renderMeasurementHistory,
} from "./history.js";
import { renderQuadrant, resetQuadrantScale } from "./quadrant.js";
import { RecordingState } from "./recording-state.js";
import { initializeUtilityDrawers } from "./workstation.js";
import { initializeScopeControls, refreshScopeStatus } from "./scope.js";

let runtimeConfig = null;
let selectedDevice = null;
let selectionGeneration = 0;
let socket = null;
let reconnectTimer = null;
const recordingState = new RecordingState();
let recordingStatusKnown = false;

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setStreamState(state) {
  document.getElementById("stream-state").textContent = state;
}

function setTargetStatus(state, kind = "") {
  const node = document.getElementById("target-status");
  node.textContent = state;
  node.classList.toggle("connected", kind === "connected");
  node.classList.toggle("error", kind === "error");
}

function selectionResponseIsCurrent(deviceId, generation) {
  return selectedDevice === deviceId && selectionGeneration === generation;
}

function configForSelectedDevice() {
  return runtimeConfig?.devices.find((device) => device.id === selectedDevice) ?? null;
}

function displayDeviceName(deviceId) {
  const config = runtimeConfig?.devices.find((device) => device.id === deviceId);
  return config?.name ?? recordingState.forDevice(deviceId)?.device_name ?? deviceId ?? "—";
}

function formatInterval(value) {
  if (!Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? `${value} s` : `${value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} s`;
}

function renderRecordingPanel(message = "") {
  const selectedName = displayDeviceName(selectedDevice);
  const selectedRecording = selectedDevice ? recordingState.forDevice(selectedDevice) : null;
  const active = recordingState.activeRecordings();
  const startButton = document.getElementById("record-start");
  const stopButton = document.getElementById("record-stop");
  const interval = document.getElementById("recording-interval");
  const state = document.getElementById("recording-state");

  setText("recording-selected-device", selectedName);
  setText("recording-strip-device", selectedName);
  setText("recording-control-device", selectedName);
  setText("recording-summary-state", recordingStatusKnown ? `${active.length} ACTIVE` : "STATUS UNKNOWN");
  setText(
    "recording-active-list",
    recordingStatusKnown && active.length
      ? active.map((record) => `${displayDeviceName(record.device_id)} · ${formatInterval(record.interval_s)}`).join(" | ")
      : recordingStatusKnown ? "NONE" : "UNAVAILABLE"
  );

  if (!recordingStatusKnown) {
    setText("recording-selected-state", "STATUS UNKNOWN");
    state.textContent = "STATUS UNKNOWN";
    state.classList.remove("active");
    startButton.disabled = true;
    stopButton.disabled = true;
    interval.disabled = true;
    document.getElementById("recording-detail").textContent = message || "Recording status is unavailable.";
    return;
  }

  if (selectedRecording) {
    const selectedState = `REC ON · ${formatInterval(selectedRecording.interval_s)}`;
    setText("recording-selected-state", selectedState);
    state.textContent = "RECORDING";
    state.classList.add("active");
    startButton.disabled = true;
    stopButton.disabled = false;
    interval.disabled = false;
    if (Number.isFinite(selectedRecording.interval_s)) {
      const value = String(selectedRecording.interval_s);
      if (![...interval.options].some((option) => option.value === value)) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = formatInterval(selectedRecording.interval_s);
        interval.appendChild(option);
      }
      interval.value = value;
    }
    document.getElementById("recording-detail").textContent = message || `Recording selected Emonio: ${selectedRecording.session_dir}`;
    return;
  }

  setText("recording-selected-state", "REC OFF");
  state.textContent = "STOPPED";
  state.classList.remove("active");
  startButton.disabled = false;
  stopButton.disabled = true;
  interval.disabled = false;
  document.getElementById("recording-detail").textContent = message || `No active recording for selected Emonio ${selectedName}.`;
}

async function refreshRecordingState(message = "") {
  try {
    const payload = await getRecordingStatus();
    recordingState.replaceActive(payload?.active ?? []);
    recordingStatusKnown = true;
    renderRecordingPanel(message);
    return true;
  } catch (error) {
    recordingStatusKnown = false;
    renderRecordingPanel(message || `Recording status unavailable: ${error.message}`);
    return false;
  }
}

function configureRecordingIntervals(config) {
  const select = document.getElementById("recording-interval");
  const minimum = Number(config.poll_interval_s);
  const preferred = Number(runtimeConfig?.recording_default_interval_s ?? minimum);
  const activeInterval = recordingState.forDevice(config.id)?.interval_s;
  const profiles = [1, 2, 5, 10];
  const values = [...new Set([minimum, preferred, activeInterval, ...profiles])]
    .filter((value) => Number.isFinite(value) && value >= minimum)
    .sort((a, b) => a - b);

  select.replaceChildren();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = formatInterval(value);
    select.appendChild(option);
  }

  const selected = Number.isFinite(activeInterval) ? activeInterval : preferred >= minimum ? preferred : values[0];
  select.value = String(selected);
}

function applySelectedDeviceConfig() {
  const config = configForSelectedDevice();
  if (!config) return;
  document.getElementById("device-name").textContent = config.name;
  document.getElementById("device-ip").textContent = config.host;
  document.getElementById("poll-interval").textContent = `${config.poll_interval_s.toFixed(2)} s`;
  document.getElementById("firmware-version").textContent = config.firmware_version;
  configureRecordingIntervals(config);
  renderRecordingPanel();
}

function populateDeviceSelector() {
  const selector = document.getElementById("device-selector");
  selector.replaceChildren();
  for (const device of runtimeConfig?.devices ?? []) {
    if (!device.enabled) continue;
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = device.name;
    selector.appendChild(option);
  }
  if (selectedDevice) selector.value = selectedDevice;
}

async function refreshBackendState() {
  const deviceId = selectedDevice;
  const generation = selectionGeneration;
  if (!deviceId) return false;
  try {
    const [devices, diagnostics] = await Promise.all([getDevices(), getDiagnostics(deviceId)]);
    if (!selectionResponseIsCurrent(deviceId, generation)) return false;
    const selected = devices.find((device) => device.device_id === deviceId);
    renderBackendStatus(selected);
    renderDiagnostics(diagnostics);
    return true;
  } catch (error) {
    if (!selectionResponseIsCurrent(deviceId, generation)) return false;
    document.getElementById("diagnostics-grid").textContent = `Backend status unavailable: ${error.message}`;
    return false;
  }
}

function connectStream() {
  if (socket) socket.close();
  clearTimeout(reconnectTimer);
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws/v1/measurements`);
  setStreamState("CONNECTING");

  socket.addEventListener("open", () => setStreamState("CONNECTED"));
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    appendHistoryPayload(payload);
    if (payload.device_id !== selectedDevice) return;
    renderMeasurementPayload(payload);
    renderQuadrant(payload.sample);
    renderMeasurementHistory(selectedDevice);
  });
  socket.addEventListener("close", () => {
    setStreamState("DISCONNECTED");
    reconnectTimer = setTimeout(connectStream, 1500);
  });
  socket.addEventListener("error", () => setStreamState("ERROR"));
}

async function selectDevice(deviceId) {
  const deviceChanged = selectedDevice !== deviceId;
  const generation = ++selectionGeneration;
  selectedDevice = deviceId;
  if (deviceChanged) resetQuadrantScale();
  populateDeviceSelector();
  applySelectedDeviceConfig();
  try {
    const payload = await getDevice(deviceId);
    if (payload.sample) appendHistoryPayload(payload);
    if (!selectionResponseIsCurrent(deviceId, generation)) return false;
    if (payload.sample) {
      renderMeasurementPayload(payload);
      renderQuadrant(payload.sample);
    } else {
      renderBackendStatus(payload);
    }
  } catch (error) {
    if (!selectionResponseIsCurrent(deviceId, generation)) return false;
    setStreamState(`ERROR: ${error.message}`);
  }
  if (!selectionResponseIsCurrent(deviceId, generation)) return false;
  renderMeasurementHistory(deviceId);
  await Promise.all([
    refreshBackendState(),
    refreshCtEvidence(deviceId),
    refreshModbusEvidence(deviceId),
    refreshRecordingState(),
    refreshScopeStatus(deviceId),
  ]);
  if (!selectionResponseIsCurrent(deviceId, generation)) return false;
  applySelectedDeviceConfig();
  return true;
}

async function reloadRuntimeConfig() {
  runtimeConfig = await getRuntimeConfig();
  populateDeviceSelector();
}

async function initializeDevices() {
  await reloadRuntimeConfig();
  const selector = document.getElementById("device-selector");
  selectedDevice = runtimeConfig.default_device;
  populateDeviceSelector();
  selector.value = selectedDevice;
  selector.addEventListener("change", () => selectDevice(selector.value));
  await selectDevice(selectedDevice);
  const config = configForSelectedDevice();
  if (config) document.getElementById("device-target").value = config.name;
}

function initializeTargetControls() {
  const input = document.getElementById("device-target");
  const button = document.getElementById("device-connect");

  const connect = async () => {
    const target = input.value.trim();
    if (!target) {
      setTargetStatus("TARGET REQUIRED", "error");
      return;
    }
    button.disabled = true;
    setTargetStatus("QUALIFYING...", "");
    try {
      const result = await connectDevice(target);
      await reloadRuntimeConfig();
      await selectDevice(result.device_id);
      setTargetStatus(result.already_connected ? "CONNECTED / EXISTING" : "CONNECTED / VERIFIED", "connected");
    } catch (error) {
      setTargetStatus(`FAILED: ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  };

  button.addEventListener("click", connect);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") connect();
  });
}

function initializeRecordingControls() {
  const interval = document.getElementById("recording-interval");
  const note = document.getElementById("session-note");
  document.getElementById("record-start").addEventListener("click", async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId || recordingState.isActive(deviceId)) return;
    try {
      await startRecording(deviceId, Number(interval.value), note.value);
      note.value = "";
      await refreshRecordingState(`Recording started for ${displayDeviceName(deviceId)}.`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Start failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  });
  document.getElementById("record-stop").addEventListener("click", async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId || !recordingState.isActive(deviceId)) return;
    try {
      await stopRecording(deviceId);
      await refreshRecordingState(`Recording stopped for ${displayDeviceName(deviceId)}.`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Stop failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  });
  interval.addEventListener("change", async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId || !recordingState.isActive(deviceId)) return;
    try {
      await changeRecordingInterval(deviceId, Number(interval.value));
      await refreshRecordingState(`Recording interval for ${displayDeviceName(deviceId)}: ${interval.value} s`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Interval change failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  });
}

async function main() {
  initializeMeasurementPanels();
  initializeTargetControls();
  initializeRecordingControls();
  initializeUtilityDrawers();
  initializeCtEvidenceControls(() => selectedDevice);
  initializeModbusEvidenceControls(() => selectedDevice);
  initializeHistoryMetricSelector(() => selectedDevice);
  initializeHistoryWindowSelector(() => selectedDevice);
  initializeHistoryInspection(() => selectedDevice);
  initializeHistoryInspectorCopy(() => selectedDevice);
  initializeScopeControls(
    () => selectedDevice,
    displayDeviceName,
    () => runtimeConfig?.devices ?? [],
    selectDevice
  );
  renderRecordingPanel();
  await initializeDevices();
  connectStream();
  setInterval(refreshBackendState, 1000);
}

main().catch((error) => {
  setStreamState(`STARTUP ERROR: ${error.message}`);
});
