import {
  armRecordingTrigger,
  changeRecordingInterval,
  configureRecordingTrigger,
  connectDevice,
  disarmRecordingTrigger,
  disconnectDevice,
  getDevice,
  getDevices,
  getDiagnostics,
  getRecordingStatus,
  getRuntimeConfig,
  reconnectDevice,
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
let triggerDraftDevice = null;
const backendDeviceState = new Map();

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

function cacheBackendDeviceState(device) {
  if (!device?.device_id) return;
  const previous = backendDeviceState.get(device.device_id) ?? {};
  backendDeviceState.set(device.device_id, { ...previous, ...device });
}

function lifecycleStateFor(deviceId) {
  return backendDeviceState.get(deviceId)?.acquisition_state ?? null;
}

function renderLifecycleControl(acquisitionState = lifecycleStateFor(selectedDevice)) {
  const button = document.getElementById("device-lifecycle-action");
  if (!button) return;
  const states = {
    RUNNING: ["DISCONNECT EMONIO", false],
    DISCONNECTED: ["RECONNECT EMONIO", false],
    DISCONNECTING: ["DISCONNECTING...", true],
    CONNECTING: ["CONNECTING...", true],
    ERROR: ["DISCONNECT ERROR", true],
  };
  const [label, disabled] = states[acquisitionState] ?? ["LIFECYCLE UNKNOWN", true];
  button.textContent = label;
  button.disabled = disabled;
}

async function executeSelectedDeviceLifecycle() {
  const deviceId = selectedDevice;
  const generation = selectionGeneration;
  const acquisitionState = lifecycleStateFor(deviceId);
  if (!deviceId || !["RUNNING", "DISCONNECTED"].includes(acquisitionState)) return false;

  const button = document.getElementById("device-lifecycle-action");
  if (button) {
    button.disabled = true;
    button.textContent = acquisitionState === "RUNNING" ? "DISCONNECTING..." : "CONNECTING...";
  }

  let lifecycleError = null;
  try {
    if (acquisitionState === "RUNNING") await disconnectDevice(deviceId);
    else await reconnectDevice(deviceId);
  } catch (error) {
    lifecycleError = error;
  }

  await Promise.all([
    refreshBackendState(),
    refreshRecordingState(),
    refreshScopeStatus(deviceId),
  ]);

  if (!selectionResponseIsCurrent(deviceId, generation)) return false;
  if (lifecycleError) {
    const result = lifecycleError.lifecycleResult;
    const stage = result?.failed_stage ?? "LIFECYCLE";
    const detail = result?.detail ?? lifecycleError.message;
    setTargetStatus(`${stage} ERROR: ${detail}`, "error");
  }
  applySelectedDeviceConfig();
  return lifecycleError === null;
}

function initializeDeviceLifecycleControl() {
  const button = document.getElementById("device-lifecycle-action");
  if (!button) return;
  button.addEventListener("click", executeSelectedDeviceLifecycle);
  renderLifecycleControl();
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

function createRecordingTriggerSelect(id, ariaLabel, options) {
  const select = createRecordingElement("select");
  select.id = id;
  select.setAttribute("aria-label", ariaLabel);
  for (const [value, label] of options) {
    const option = createRecordingElement("option", "", label);
    option.value = value;
    select.appendChild(option);
  }
  return select;
}

function createRecordingTriggerField(labelText, control) {
  const label = createRecordingElement("label", "recording-trigger-field");
  label.appendChild(createRecordingElement("span", "recording-trigger-label", labelText));
  label.appendChild(control);
  return label;
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

  const triggerPanel = createRecordingElement("section", "recording-trigger-panel");
  triggerPanel.setAttribute("aria-label", "Triggered recording controls");
  const triggerHeader = createRecordingElement("div", "recording-trigger-header");
  triggerHeader.appendChild(createRecordingElement("h3", "recording-trigger-title", "TRIGGERED RECORDING"));
  const triggerState = createRecordingElement("strong", "recording-trigger-state", "NOT CONFIGURED");
  triggerState.id = "recording-trigger-state";
  triggerHeader.appendChild(triggerState);

  const triggerGrid = createRecordingElement("div", "recording-trigger-grid");
  const triggerMode = createRecordingTriggerSelect(
    "recording-trigger-mode",
    "Trigger mode",
    [["LEVEL", "LEVEL"], ["CROSSING", "CROSSING"]]
  );
  const triggerBlock = createRecordingTriggerSelect(
    "recording-trigger-block",
    "Trigger phase",
    [["A", "A"], ["B", "B"], ["C", "C"], ["TOTAL", "TOTAL"]]
  );
  const triggerMeasurement = createRecordingTriggerSelect(
    "recording-trigger-measurement",
    "Trigger measurement",
    [["U", "U"], ["I", "I"], ["P", "P"], ["Q", "Q"], ["S", "S"], ["PF", "PF"], ["F", "f"]]
  );
  const triggerOperator = createRecordingTriggerSelect(
    "recording-trigger-operator",
    "Trigger operator",
    [["GT", ">"], ["GE", ">="], ["LT", "<"], ["LE", "<="]]
  );
  const triggerThreshold = createRecordingElement("input");
  triggerThreshold.id = "recording-trigger-threshold";
  triggerThreshold.type = "number";
  triggerThreshold.step = "any";
  triggerThreshold.inputMode = "decimal";
  triggerThreshold.setAttribute("aria-label", "Trigger threshold");
  const triggerInterval = createRecordingElement("select");
  triggerInterval.id = "recording-trigger-interval";
  triggerInterval.setAttribute("aria-label", "Triggered recording interval");
  triggerGrid.append(
    createRecordingTriggerField("MODE", triggerMode),
    createRecordingTriggerField("PHASE", triggerBlock),
    createRecordingTriggerField("MEASUREMENT", triggerMeasurement),
    createRecordingTriggerField("OPERATOR", triggerOperator),
    createRecordingTriggerField("THRESHOLD", triggerThreshold),
    createRecordingTriggerField("INTERVAL", triggerInterval)
  );

  const triggerActions = createRecordingElement("div", "recording-trigger-actions");
  const triggerConfigure = createRecordingElement("button", "", "CONFIGURE");
  triggerConfigure.id = "recording-trigger-configure";
  triggerConfigure.type = "button";
  const triggerArm = createRecordingElement("button", "", "ARM");
  triggerArm.id = "recording-trigger-arm";
  triggerArm.type = "button";
  const triggerDisarm = createRecordingElement("button", "", "DISARM");
  triggerDisarm.id = "recording-trigger-disarm";
  triggerDisarm.type = "button";
  triggerActions.append(triggerConfigure, triggerArm, triggerDisarm);
  const triggerLastFired = createRecordingElement("div", "recording-trigger-last-fired", "LAST FIRED · NONE");
  triggerLastFired.id = "recording-trigger-last-fired";
  triggerPanel.append(triggerHeader, triggerGrid, triggerActions, triggerLastFired);

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
  if (note) body.insertBefore(triggerPanel, note);
  else body.appendChild(triggerPanel);
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

function setRecordingTriggerControlValue(id, value) {
  const node = document.getElementById(id);
  if (node && document.activeElement !== node) node.value = String(value);
}

function renderRecordingTriggerPanel(selectedTrigger, selectedRecording) {
  const stateNode = document.getElementById("recording-trigger-state");
  if (!stateNode) return;
  const controlIds = [
    "recording-trigger-mode",
    "recording-trigger-block",
    "recording-trigger-measurement",
    "recording-trigger-operator",
    "recording-trigger-threshold",
    "recording-trigger-interval",
  ];
  const controls = controlIds.map((id) => document.getElementById(id)).filter(Boolean);
  const configureButton = document.getElementById("recording-trigger-configure");
  const armButton = document.getElementById("recording-trigger-arm");
  const disarmButton = document.getElementById("recording-trigger-disarm");
  const lastFired = document.getElementById("recording-trigger-last-fired");

  if (!recordingStatusKnown || !selectedDevice) {
    stateNode.textContent = "STATUS UNKNOWN";
    stateNode.classList.remove("is-armed");
    controls.forEach((node) => { node.disabled = true; });
    if (configureButton) configureButton.disabled = true;
    if (armButton) armButton.disabled = true;
    if (disarmButton) disarmButton.disabled = true;
    if (lastFired) lastFired.textContent = "LAST FIRED · UNAVAILABLE";
    return;
  }

  controls.forEach((node) => { node.disabled = false; });
  if (selectedTrigger?.config) {
    triggerDraftDevice = selectedDevice;
    setRecordingTriggerControlValue("recording-trigger-mode", selectedTrigger.config.mode);
    setRecordingTriggerControlValue("recording-trigger-block", selectedTrigger.config.block);
    setRecordingTriggerControlValue("recording-trigger-measurement", selectedTrigger.config.measurement);
    setRecordingTriggerControlValue("recording-trigger-operator", selectedTrigger.config.operator);
    setRecordingTriggerControlValue("recording-trigger-threshold", selectedTrigger.config.threshold);
    const triggerInterval = document.getElementById("recording-trigger-interval");
    const intervalValue = String(selectedTrigger.config.recording_interval_s);
    if (![...triggerInterval.options].some((option) => option.value === intervalValue)) {
      const option = createRecordingElement("option", "", formatInterval(selectedTrigger.config.recording_interval_s));
      option.value = intervalValue;
      triggerInterval.appendChild(option);
    }
    setRecordingTriggerControlValue("recording-trigger-interval", intervalValue);
  } else if (triggerDraftDevice !== selectedDevice) {
    triggerDraftDevice = selectedDevice;
    setRecordingTriggerControlValue("recording-trigger-mode", "LEVEL");
    setRecordingTriggerControlValue("recording-trigger-block", "A");
    setRecordingTriggerControlValue("recording-trigger-measurement", "P");
    setRecordingTriggerControlValue("recording-trigger-operator", "GT");
    setRecordingTriggerControlValue("recording-trigger-threshold", "");
  }

  const armed = selectedTrigger?.state === "ARMED";
  stateNode.textContent = armed ? "ARMED" : selectedTrigger ? "DISARMED" : "NOT CONFIGURED";
  stateNode.classList.toggle("is-armed", armed);
  if (configureButton) configureButton.disabled = false;
  if (armButton) armButton.disabled = Boolean(selectedRecording) || !selectedTrigger || armed;
  if (disarmButton) disarmButton.disabled = !armed;

  if (lastFired) {
    if (selectedTrigger?.last_fired_cycle_id !== null && selectedTrigger?.last_fired_cycle_id !== undefined) {
      lastFired.textContent = `LAST FIRED · CYCLE ${selectedTrigger.last_fired_cycle_id} · ${selectedTrigger.last_fired_utc || "UTC UNAVAILABLE"} · VALUE ${String(selectedTrigger.last_fired_value)}`;
    } else {
      lastFired.textContent = "LAST FIRED · NONE";
    }
  }
}

function renderRecordingPanel(message = "") {
  ensureRecordingDashboardStructure();
  const selectedName = displayDeviceName(selectedDevice);
  const selectedRecording = selectedDevice ? recordingState.forDevice(selectedDevice) : null;
  const selectedError = selectedDevice ? recordingState.errorForDevice(selectedDevice) : null;
  const selectedTrigger = selectedDevice ? recordingState.triggerForDevice(selectedDevice) : null;
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
  renderRecordingTriggerPanel(selectedTrigger, selectedRecording);

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
    setRecordingControlAvailability({ start: true, stop: selectedTrigger?.state === "ARMED", interval: true });
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
  setRecordingControlAvailability({ start: true, stop: selectedTrigger?.state === "ARMED", interval: true });
  document.getElementById("recording-detail").textContent = message || `No active recording for selected Emonio ${selectedName}.`;
}

async function refreshRecordingState(message = "") {
  try {
    const payload = await getRecordingStatus();
    recordingState.replaceStatus(
      payload?.active ?? [],
      payload?.errors ?? [],
      payload?.triggers ?? []
    );
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
  const triggerInterval = recordingState.triggerForDevice(config.id)?.config?.recording_interval_s;
  const profiles = [1, 2, 5, 10];
  const values = [...new Set([minimum, preferred, activeInterval, triggerInterval, ...profiles])]
    .filter((value) => Number.isFinite(value) && value >= minimum)
    .sort((a, b) => a - b);

  for (const id of ["recording-interval", "recording-drawer-interval", "recording-trigger-interval"]) {
    const select = document.getElementById(id);
    if (!select) continue;
    select.replaceChildren();
    for (const value of values) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = formatInterval(value);
      select.appendChild(option);
    }
    const selected = id === "recording-trigger-interval" && Number.isFinite(triggerInterval)
      ? triggerInterval
      : Number.isFinite(activeInterval)
        ? activeInterval
        : preferred >= minimum ? preferred : values[0];
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
  renderLifecycleControl();
}

function populateDeviceSelector() {
  const selector = document.getElementById("device-selector");
  const enabledDevices = (runtimeConfig?.devices ?? []).filter((device) => device.enabled);
  selector.replaceChildren();
  for (const device of enabledDevices) {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = lifecycleStateFor(device.id) === "DISCONNECTED"
      ? `${device.name} · DISCONNECTED`
      : device.name;
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
    for (const device of devices) cacheBackendDeviceState(device);
    const selected = devices.find((device) => device.device_id === deviceId);
    populateDeviceSelector();
    renderBackendStatus(selected);
    renderLifecycleControl(selected?.acquisition_state);
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
    if (typeof payload.acquisition_state === "string" && payload.acquisition_state) {
      cacheBackendDeviceState(payload);
      populateDeviceSelector();
      renderLifecycleControl(payload.acquisition_state);
    }
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
    cacheBackendDeviceState(payload);
    populateDeviceSelector();
    renderLifecycleControl(payload.acquisition_state);
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
      if (result.state === "EXISTING") {
      const evidenceState = result.acquisition_state === "DISCONNECTED"
        ? "DISCONNECTED"
        : result.measurement_state;
      setTargetStatus(`EXISTING / ${evidenceState ?? "UNKNOWN"}`, "");
    } else {
      setTargetStatus("CONNECTED / VERIFIED", "connected");
    }
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
    const canStop = recordingState.isActive(deviceId) || recordingState.triggerForDevice(deviceId)?.state === "ARMED";
    if (!recordingStatusKnown || !deviceId || !canStop) return;
    try {
      await stopRecording(deviceId);
      await refreshRecordingState(`Recording/trigger stopped for ${displayDeviceName(deviceId)}.`);
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

function initializeRecordingTriggerControls() {
  ensureRecordingDashboardStructure();
  const configurationIds = [
    "recording-trigger-mode",
    "recording-trigger-block",
    "recording-trigger-measurement",
    "recording-trigger-operator",
    "recording-trigger-threshold",
    "recording-trigger-interval",
  ];

  const configureSelectedTrigger = async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId) return;
    const thresholdText = document.getElementById("recording-trigger-threshold").value.trim();
    if (thresholdText === "") {
      document.getElementById("recording-detail").textContent = "Trigger threshold is required.";
      return;
    }
    const threshold = Number(thresholdText);
    const interval = Number(document.getElementById("recording-trigger-interval").value);
    if (!Number.isFinite(threshold) || !Number.isFinite(interval) || interval <= 0) {
      document.getElementById("recording-detail").textContent = "Trigger configuration requires a finite threshold and recording interval.";
      return;
    }
    const config = {
      mode: document.getElementById("recording-trigger-mode").value,
      block: document.getElementById("recording-trigger-block").value,
      measurement: document.getElementById("recording-trigger-measurement").value,
      operator: document.getElementById("recording-trigger-operator").value,
      threshold,
      recording_interval_s: interval,
    };
    try {
      await configureRecordingTrigger(deviceId, config);
      await refreshRecordingState(`Trigger configured and DISARMED for ${displayDeviceName(deviceId)}.`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Trigger configure failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  };

  const armSelectedTrigger = async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId || recordingState.isActive(deviceId)) return;
    try {
      await armRecordingTrigger(deviceId);
      await refreshRecordingState(`Trigger ARMED for ${displayDeviceName(deviceId)}.`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Trigger ARM failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  };

  const disarmSelectedTrigger = async () => {
    const deviceId = selectedDevice;
    if (!recordingStatusKnown || !deviceId || recordingState.triggerForDevice(deviceId)?.state !== "ARMED") return;
    try {
      await disarmRecordingTrigger(deviceId);
      await refreshRecordingState(`Trigger DISARMED for ${displayDeviceName(deviceId)}.`);
      applySelectedDeviceConfig();
    } catch (error) {
      await refreshRecordingState(`Trigger DISARM failed for ${displayDeviceName(deviceId)}: ${error.message}`);
    }
  };

  document.getElementById("recording-trigger-configure").addEventListener("click", configureSelectedTrigger);
  document.getElementById("recording-trigger-arm").addEventListener("click", armSelectedTrigger);
  document.getElementById("recording-trigger-disarm").addEventListener("click", disarmSelectedTrigger);
  for (const id of configurationIds) {
    document.getElementById(id).addEventListener("change", configureSelectedTrigger);
  }
}

async function main() {
  initializeMeasurementPanels();
  initializeTargetControls();
  initializeDeviceLifecycleControl();
  initializeRecordingControls();
  initializeRecordingTriggerControls();
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