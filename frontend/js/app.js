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
  return config?.name
    ?? recordingState.forDevice(deviceId)?.device_name
    ?? recordingState.errorForDevice(deviceId)?.device_name
    ?? deviceId
    ?? "—";
}

function formatInterval(value) {
  if (!Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? `${value} s` : `${value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} s`;
}

function formatRecordingCount(value) {
  return Number.isInteger(value) && value >= 0 ? String(value) : "—";
}

function formatRecordingRuntime(startedUtc) {
  const startedMs = Date.parse(startedUtc ?? "");
  if (!Number.isFinite(startedMs)) return "—";
  const elapsedS = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
  const hours = Math.floor(elapsedS / 3600);
  const minutes = Math.floor((elapsedS % 3600) / 60);
  const seconds = elapsedS % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function createRecordingElement(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function createRecordingSummaryCell(label, id) {
  const cell = createRecordingElement("span", "recording-dashboard-summary-cell");
  cell.appendChild(createRecordingElement("small", "recording-dashboard-label", label));
  const value = createRecordingElement("strong", "recording-dashboard-value", "—");
  value.id = id;
  cell.appendChild(value);
  return cell;
}

function ensureRecordingDashboardStructure() {
  if (document.getElementById("recording-session-grid")) return;
  const body = document.querySelector(".recording-drawer .recording-panel-body");
  if (!body) return;

  const summary = createRecordingElement("section", "recording-dashboard-summary");
  summary.setAttribute("aria-label", "Recording session summary");
  summary.append(
    createRecordingSummaryCell("ACTIVE", "recording-dashboard-active"),
    createRecordingSummaryCell("RECORDS", "recording-dashboard-records"),
    createRecordingSummaryCell("MISSED", "recording-dashboard-missed"),
    createRecordingSummaryCell("ERRORS", "recording-dashboard-errors")
  );

  const activeSection = createRecordingElement("section", "recording-session-section");
  activeSection.appendChild(createRecordingElement("h3", "recording-session-section-title", "ACTIVE SESSIONS"));
  const activeGrid = createRecordingElement("div", "recording-session-grid");
  activeGrid.id = "recording-session-grid";
  activeSection.appendChild(activeGrid);

  const errorSection = createRecordingElement("section", "recording-session-section recording-error-section");
  errorSection.appendChild(createRecordingElement("h3", "recording-session-section-title", "RECORDING ERRORS"));
  const errorGrid = createRecordingElement("div", "recording-error-grid");
  errorGrid.id = "recording-error-grid";
  errorSection.appendChild(errorGrid);

  const selectedControls = createRecordingElement("section", "recording-selected-controls");
  selectedControls.setAttribute("aria-label", "Selected Emonio recording controls");
  const selectedState = createRecordingElement("strong", "recording-selected-control-state", "STATUS UNKNOWN");
  selectedState.id = "recording-drawer-selected-state";
  const intervalLabel = createRecordingElement("label", "recording-selected-interval", "INTERVAL");
  const interval = createRecordingElement("select");
  interval.id = "recording-drawer-interval";
  interval.setAttribute("aria-label", "Selected Emonio recording interval");
  intervalLabel.appendChild(interval);
  const start = createRecordingElement("button", "", "RECORD");
  start.id = "recording-drawer-start";
  start.type = "button";
  const stop = createRecordingElement("button", "", "STOP");
  stop.id = "recording-drawer-stop";
  stop.type = "button";
  selectedControls.append(selectedState, intervalLabel, start, stop);

  const legacySummary = body.querySelector(".recording-active-summary");
  const note = body.querySelector(".recording-note");
  if (legacySummary) legacySummary.hidden = true;
  if (legacySummary) body.insertBefore(summary, legacySummary);
  else body.prepend(summary);
  if (legacySummary) body.insertBefore(activeSection, legacySummary);
  else body.appendChild(activeSection);
  if (note) body.insertBefore(errorSection, note);
  else body.appendChild(errorSection);
  if (note) body.insertBefore(selectedControls, note);
  else body.appendChild(selectedControls);
}

function appendRecordingMetric(container, label, value, className = "") {
  const cell = createRecordingElement("span", `recording-session-metric${className ? ` ${className}` : ""}`);
  cell.appendChild(createRecordingElement("small", "recording-session-metric-label", label));
  cell.appendChild(createRecordingElement("strong", "recording-session-metric-value", value));
  container.appendChild(cell);
}

function renderRecordingSessionCards(records) {
  const target = document.getElementById("recording-session-grid");
  if (!target) return;
  target.replaceChildren();
  if (!records.length) {
    target.appendChild(createRecordingElement("div", "recording-session-empty", "NO ACTIVE RECORDING SESSIONS"));
    return;
  }

  for (const record of records) {
    const card = createRecordingElement("article", "recording-session-card");
    card.dataset.deviceId = record.device_id;
    card.classList.toggle("is-selected", record.device_id === selectedDevice);

    const header = createRecordingElement("div", "recording-session-card-header");
    const identity = createRecordingElement("div", "recording-session-card-identity");
    identity.append(
      createRecordingElement("strong", "recording-session-device", displayDeviceName(record.device_id)),
      createRecordingElement("span", "recording-session-device-id", record.device_id)
    );
    const state = createRecordingElement("strong", "recording-session-state", "RECORDING");
    const button = createRecordingElement("button", "recording-session-stop", "STOP");
    button.type = "button";
    button.dataset.recordingStopDevice = record.device_id;
    button.setAttribute("aria-label", `Stop recording for ${displayDeviceName(record.device_id)}`);
    button.addEventListener("click", async () => {
      const deviceId = button.dataset.recordingStopDevice;
      if (!deviceId || !recordingState.isActive(deviceId)) return;
      button.disabled = true;
      try {
        await stopRecording(deviceId);
        await refreshRecordingState(`Recording stopped for ${displayDeviceName(deviceId)}.`);
        applySelectedDeviceConfig();
      } catch (error) {
        await refreshRecordingState(`Stop failed for ${displayDeviceName(deviceId)}: ${error.message}`);
      }
    });
    header.append(identity, state, button);
    card.appendChild(header);

    const session = createRecordingElement("div", "recording-session-id", record.session_id || "SESSION ID UNAVAILABLE");
    card.appendChild(session);

    const metrics = createRecordingElement("div", "recording-session-metrics");
    appendRecordingMetric(metrics, "STARTED UTC", record.started_utc || "—");
    appendRecordingMetric(metrics, "RUNTIME", formatRecordingRuntime(record.started_utc));
    appendRecordingMetric(metrics, "RECORD INTERVAL", formatInterval(record.interval_s));
    appendRecordingMetric(metrics, "ACQ INTERVAL", formatInterval(record.acquisition_interval_s));
    appendRecordingMetric(metrics, "RECORDS", formatRecordingCount(record.records_written));
    appendRecordingMetric(
      metrics,
      "MISSED POINTS",
      formatRecordingCount(record.record_points_missed),
      (record.record_points_missed ?? 0) > 0 ? "has-warning" : ""
    );
    appendRecordingMetric(metrics, "VALID/DEGRADED SEEN", formatRecordingCount(record.eligible_samples_seen));
    appendRecordingMetric(
      metrics,
      "INVALID CYCLES",
      formatRecordingCount(record.invalid_cycles_seen),
      (record.invalid_cycles_seen ?? 0) > 0 ? "has-warning" : ""
    );
    appendRecordingMetric(metrics, "LAST RECORD UTC", record.last_recorded_utc || "—");
    appendRecordingMetric(metrics, "LAST CYCLE", formatRecordingCount(record.last_recorded_cycle_id));
    appendRecordingMetric(metrics, "NEXT BOUNDARY UTC", record.next_record_utc || "—");
    appendRecordingMetric(metrics, "VIEWER", record.application_version || "—");
    card.appendChild(metrics);

    const path = createRecordingElement("div", "recording-session-path");
    path.appendChild(createRecordingElement("small", "recording-session-metric-label", "SESSION DIRECTORY"));
    path.appendChild(createRecordingElement("code", "", record.session_dir || "—"));
    card.appendChild(path);
    target.appendChild(card);
  }
}

function renderRecordingErrorCards(records) {
  const target = document.getElementById("recording-error-grid");
  if (!target) return;
  target.replaceChildren();
  if (!records.length) {
    target.appendChild(createRecordingElement("div", "recording-session-empty", "NO RECORDING ERRORS"));
    return;
  }

  for (const record of records) {
    const card = createRecordingElement("article", "recording-session-card recording-session-error-card");
    const header = createRecordingElement("div", "recording-session-card-header");
    const identity = createRecordingElement("div", "recording-session-card-identity");
    identity.append(
      createRecordingElement("strong", "recording-session-device", displayDeviceName(record.device_id)),
      createRecordingElement("span", "recording-session-device-id", record.device_id)
    );
    header.append(identity, createRecordingElement("strong", "recording-session-state error", "ERROR"));
    card.appendChild(header);

    const metrics = createRecordingElement("div", "recording-session-metrics");
    appendRecordingMetric(metrics, "FAILED UTC", record.failed_utc || "—");
    appendRecordingMetric(metrics, "FAILED CYCLE", formatRecordingCount(record.failed_cycle_id));
    appendRecordingMetric(metrics, "ERROR TYPE", record.error_type || "RecordingError");
    appendRecordingMetric(metrics, "RECORDS BEFORE ERROR", formatRecordingCount(record.records_written));
    card.appendChild(metrics);
    card.appendChild(createRecordingElement("div", "recording-session-error-detail", record.error_detail || "recording failed"));

    const path = createRecordingElement("div", "recording-session-path");
    path.appendChild(createRecordingElement("small", "recording-session-metric-label", "SESSION DIRECTORY"));
    path.appendChild(createRecordingElement("code", "", record.session_dir || "—"));
    card.appendChild(path);
    target.appendChild(card);
  }
}

function setRecordingControlAvailability({ start, stop, interval }) {
  for (const id of ["record-start", "recording-drawer-start"]) {
    const node = document.getElementById(id);
    if (node) node.disabled = !start;
  }
  for (const id of ["record-stop", "recording-drawer-stop"]) {
    const node = document.getElementById(id);
    if (node) node.disabled = !stop;
  }
  for (const id of ["recording-interval", "recording-drawer-interval"]) {
    const node = document.getElementById(id);
    if (node) node.disabled = !interval;
  }
}

function setRecordingIntervalValue(value) {
  if (!Number.isFinite(value)) return;
  const optionValue = String(value);
  for (const id of ["recording-interval", "recording-drawer-interval"]) {
    const select = document.getElementById(id);
    if (!select) continue;
    if (![...select.options].some((option) => option.value === optionValue)) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = formatInterval(value);
      select.appendChild(option);
    }
    select.value = optionValue;
  }
}

function renderRecordingPanel(message = "") {
  ensureRecordingDashboardStructure();
  const selectedName = displayDeviceName(selectedDevice);
  const selectedRecording = selectedDevice ? recordingState.forDevice(selectedDevice) : null;
  const selectedError = selectedDevice ? recordingState.errorForDevice(selectedDevice) : null;
  const active = recordingState.activeRecordings();
  const errors = recordingState.recordingErrors();
  const summary = recordingState.summary();
  const state = document.getElementById("recording-state");

  setText("recording-selected-device", selectedName);
  setText("recording-strip-device", selectedName);
  setText("recording-control-device", selectedName);
  setText("recording-dashboard-active", recordingStatusKnown ? String(summary.active) : "—");
  setText("recording-dashboard-records", recordingStatusKnown ? String(summary.records_written) : "—");
  setText("recording-dashboard-missed", recordingStatusKnown ? String(summary.record_points_missed) : "—");
  setText("recording-dashboard-errors", recordingStatusKnown ? String(summary.errors) : "—");
  setText(
    "recording-summary-state",
    recordingStatusKnown
      ? errors.length ? `${active.length} ACTIVE · ${errors.length} ERROR` : `${active.length} ACTIVE`
      : "STATUS UNKNOWN"
  );
  setText(
    "recording-active-list",
    recordingStatusKnown && active.length
      ? active.map((record) => `${displayDeviceName(record.device_id)} · ${formatInterval(record.interval_s)}`).join(" | ")
      : recordingStatusKnown ? "NONE" : "UNAVAILABLE"
  );

  if (recordingStatusKnown) {
    renderRecordingSessionCards(active);
    renderRecordingErrorCards(errors);
  } else {
    renderRecordingSessionCards([]);
    renderRecordingErrorCards([]);
  }

  if (!recordingStatusKnown) {
    setText("recording-selected-state", "STATUS UNKNOWN");
    setText("recording-drawer-selected-state", "STATUS UNKNOWN");
    state.textContent = "STATUS UNKNOWN";
    state.classList.remove("active", "error");
    setRecordingControlAvailability({ start: false, stop: false, interval: false });
    document.getElementById("recording-detail").textContent = message || "Recording status is unavailable.";
    return;
  }

  if (selectedError) {
    setText("recording-selected-state", "REC ERROR");
    setText("recording-drawer-selected-state", "ERROR");
    state.textContent = "ERROR";
    state.classList.remove("active");
    state.classList.add("error");
    setRecordingControlAvailability({ start: true, stop: false, interval: true });
    const errorText = `${selectedError.error_type}: ${selectedError.error_detail}`;
    const sessionText = selectedError.session_dir ? ` Session: ${selectedError.session_dir}` : "";
    document.getElementById("recording-detail").textContent =
      message || `Recording failed for ${selectedName}: ${errorText}.${sessionText}`;
    return;
  }

  if (selectedRecording) {
    const selectedState = `REC ON · ${formatInterval(selectedRecording.interval_s)}`;
    setText("recording-selected-state", selectedState);
    setText("recording-drawer-selected-state", selectedState);
    state.textContent = "RECORDING";
    state.classList.remove("error");
    state.classList.add("active");
    setRecordingControlAvailability({ start: false, stop: true, interval: true });
    setRecordingIntervalValue(selectedRecording.interval_s);
    document.getElementById("recording-detail").textContent = message || `Recording selected Emonio: ${selectedRecording.session_dir}`;
    return;
  }

  setText("recording-selected-state", "REC OFF");
  setText("recording-drawer-selected-state", "STOPPED");
  state.textContent = "STOPPED";
  state.classList.remove("active", "error");
  setRecordingControlAvailability({ start: true, stop: false, interval: true });
  document.getElementById("recording-detail").textContent = message || `No active recording for selected Emonio ${selectedName}.`;
}

async function refreshRecordingState(message = "") {
  try {
    const payload = await getRecordingStatus();
    recordingState.replaceStatus(payload?.active ?? [], payload?.errors ?? []);
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
  const minimum = Number(config.poll_interval_s);
  const preferred = Number(runtimeConfig?.recording_default_interval_s ?? minimum);
  const activeInterval = recordingState.forDevice(config.id)?.interval_s;
  const profiles = [1, 2, 5, 10];
  const values = [...new Set([minimum, preferred, activeInterval, ...profiles])]
    .filter((value) => Number.isFinite(value) && value >= minimum)
    .sort((a, b) => a - b);

  for (const id of ["recording-interval", "recording-drawer-interval"]) {
    const select = document.getElementById(id);
    if (!select) continue;
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
  const enabledDevices = (runtimeConfig?.devices ?? []).filter((device) => device.enabled);
  selector.replaceChildren();
  for (const device of enabledDevices) {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = device.name;
    selector.appendChild(option);
  }
  selector.disabled = enabledDevices.length === 0;
  if (selectedDevice && enabledDevices.some((device) => device.id === selectedDevice)) {
    selector.value = selectedDevice;
  }
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
  const configuredDefault = runtimeConfig.devices.find(
    (device) => device.enabled && device.id === runtimeConfig.default_device
  );
  const firstEnabled = runtimeConfig.devices.find((device) => device.enabled);
  selectedDevice = configuredDefault?.id ?? firstEnabled?.id ?? null;
  populateDeviceSelector();
  selector.addEventListener("change", () => selectDevice(selector.value));

  if (!selectedDevice) {
    setStreamState("NO DEVICE SELECTED");
    setTargetStatus("TARGET REQUIRED");
    renderRecordingPanel();
    return;
  }

  selector.value = selectedDevice;
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
      const targetState = error?.targetState;
      const operatorState = targetState === "TARGET_UNAVAILABLE"
        ? "TARGET UNAVAILABLE"
        : targetState === "TARGET_INVALID"
          ? "TARGET INVALID"
          : "TARGET CONNECTION FAILED";
      setTargetStatus(operatorState, "error");
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
  ensureRecordingDashboardStructure();
  const stripInterval = document.getElementById("recording-interval");
  const drawerInterval = document.getElementById("recording-drawer-interval");
  const note = document.getElementById("session-note");

  const startSelected = async (interval) => {
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
  };

  const stopSelected = async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId || !recordingState.isActive(deviceId)) return;
    try {
      await stopRecording(deviceId);
      await refreshRecordingState(`Recording stopped for ${displayDeviceName(deviceId)}.`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Stop failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  };

  const changeSelectedInterval = async (interval) => {
    const deviceId = selectedDevice;
    const value = Number(interval.value);
    setRecordingIntervalValue(value);
    if (!recordingStatusKnown || !deviceId || !recordingState.isActive(deviceId)) return;
    try {
      await changeRecordingInterval(deviceId, value);
      await refreshRecordingState(`Recording interval for ${displayDeviceName(deviceId)}: ${interval.value} s`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Interval change failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  };

  document.getElementById("record-start").addEventListener("click", () => startSelected(stripInterval));
  document.getElementById("recording-drawer-start").addEventListener("click", () => startSelected(drawerInterval));
  document.getElementById("record-stop").addEventListener("click", stopSelected);
  document.getElementById("recording-drawer-stop").addEventListener("click", stopSelected);
  stripInterval.addEventListener("change", () => changeSelectedInterval(stripInterval));
  drawerInterval.addEventListener("change", () => changeSelectedInterval(drawerInterval));
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
  setInterval(() => {
    refreshBackendState();
    refreshRecordingState();
  }, 1000);
}

main().catch((error) => {
  setStreamState(`STARTUP ERROR: ${error.message}`);
});
