import {
  configureRecordingMonitor,
  disableRecordingMonitor,
  enableRecordingMonitor,
  getRecordingStatus,
  getRuntimeConfig,
} from "./recording-monitor-api.js";

const CONDITIONS = new Set(["P_NEGATIVE", "Q_THRESHOLD"]);
const Q_DIRECTIONS = new Set(["POSITIVE", "NEGATIVE", "BOTH"]);
const STATES = new Set(["OFF", "WAITING", "RECORDING", "WAITING_FOR_CLEAR"]);
const PHASES = ["A", "B", "C"];

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function conditionLabel(condition, thresholdVar = null, qDirection = null) {
  if (condition === "P_NEGATIVE") return "P < 0";
  const threshold = finiteNumber(thresholdVar);
  if (condition !== "Q_THRESHOLD" || threshold === null || !Q_DIRECTIONS.has(qDirection)) return "—";
  if (qDirection === "POSITIVE") return `Q > +${threshold} var`;
  if (qDirection === "NEGATIVE") return `Q < -${threshold} var`;
  return `|Q| > ${threshold} var`;
}

export function normalizeMonitorStatus(record) {
  if (!record || typeof record.device_id !== "string" || !record.device_id) return null;
  if (!STATES.has(record.state)) return null;
  const config = record.config;
  if (!config || !CONDITIONS.has(config.condition)) return null;
  const phases = Array.isArray(config.phases)
    ? config.phases.filter((phase, index, source) => PHASES.includes(phase) && source.indexOf(phase) === index)
    : [];
  if (!phases.length) return null;
  const interval = finiteNumber(config.recording_interval_s);
  if (interval === null || interval <= 0) return null;

  const normalizedConfig = {
    condition: config.condition,
    phases: Object.freeze([...phases]),
    recording_interval_s: interval,
  };
  if (config.condition === "Q_THRESHOLD") {
    const threshold = finiteNumber(config.threshold_var);
    if (threshold === null || threshold < 0 || !Q_DIRECTIONS.has(config.q_direction)) return null;
    normalizedConfig.threshold_var = threshold;
    normalizedConfig.q_direction = config.q_direction;
  }

  const expectedMeasurement = config.condition === "Q_THRESHOLD" ? "Q" : "P";
  const active = [];
  for (const item of Array.isArray(record.active_conditions) ? record.active_conditions : []) {
    if (!item || !PHASES.includes(item.phase) || item.measurement !== expectedMeasurement) continue;
    const value = finiteNumber(item.value);
    active.push(Object.freeze({phase: item.phase, measurement: expectedMeasurement, value}));
  }

  const last = record.last_event;
  const lastEvent = last && typeof last.event === "string"
    ? Object.freeze({
        event: last.event,
        phase: PHASES.includes(last.phase) ? last.phase : "",
        measurement: last.measurement === expectedMeasurement ? expectedMeasurement : "",
        cycle_id: Number.isInteger(Number(last.cycle_id)) ? Number(last.cycle_id) : null,
        utc: typeof last.utc === "string" ? last.utc : "",
        value: finiteNumber(last.value),
        continuity: typeof last.continuity === "string" ? last.continuity : "",
      })
    : null;

  return Object.freeze({
    device_id: record.device_id,
    state: record.state,
    config: Object.freeze(normalizedConfig),
    active_conditions: Object.freeze(active),
    last_event: lastEvent,
  });
}

export function phaseStatusText(status, phase) {
  const active = status?.active_conditions?.find((item) => item.phase === phase) ?? null;
  if (!active) return `${phase}  NORMAL`;
  return active.measurement === "Q" ? `${phase}  Q THRESHOLD` : `${phase}  NEGATIVE P`;
}

export function validateMonitorDraft(draft) {
  if (!CONDITIONS.has(draft?.condition)) return "Select a valid condition.";
  if (!Array.isArray(draft.phases) || !draft.phases.length) return "Select at least one phase.";
  if (draft.phases.some((phase) => !PHASES.includes(phase))) return "Select only Phase A, B, or C.";
  const interval = finiteNumber(draft.recording_interval_s);
  if (interval === null || interval <= 0) return "Select a valid recording interval.";
  if (draft.condition === "Q_THRESHOLD") {
    const threshold = finiteNumber(draft.threshold_var);
    if (threshold === null || threshold < 0) return "Enter a finite Q threshold magnitude of 0 var or greater.";
    if (!Q_DIRECTIONS.has(draft.q_direction)) return "Select POSITIVE, NEGATIVE, or BOTH for Q direction.";
  }
  return null;
}

function panelMarkup() {
  return `
    <div class="recording-monitor-header">
      <span class="recording-monitor-title">RECORDING CONDITION MONITOR</span>
      <strong id="recording-monitor-state" class="recording-monitor-state">OFF</strong>
    </div>
    <div class="recording-monitor-grid">
      <label class="recording-monitor-field">
        <span class="recording-monitor-label">CONDITION</span>
        <select id="recording-monitor-condition">
          <option value="P_NEGATIVE">P &lt; 0</option>
          <option value="Q_THRESHOLD">Q THRESHOLD</option>
        </select>
      </label>
      <fieldset class="recording-monitor-phases">
        <legend class="recording-monitor-label">PHASES</legend>
        <label><input id="recording-monitor-phase-a" type="checkbox" value="A" checked>A</label>
        <label><input id="recording-monitor-phase-b" type="checkbox" value="B" checked>B</label>
        <label><input id="recording-monitor-phase-c" type="checkbox" value="C" checked>C</label>
      </fieldset>
      <label class="recording-monitor-field">
        <span class="recording-monitor-label">RECORDING INTERVAL</span>
        <select id="recording-monitor-interval"></select>
      </label>
    </div>
    <div id="recording-monitor-q-options" class="recording-monitor-q-options" hidden>
      <label class="recording-monitor-field">
        <span class="recording-monitor-label">THRESHOLD [var]</span>
        <input id="recording-monitor-q-threshold" type="number" min="0" step="any" value="0" inputmode="decimal">
      </label>
      <label class="recording-monitor-field">
        <span class="recording-monitor-label">Q DIRECTION</span>
        <select id="recording-monitor-q-direction">
          <option value="POSITIVE">POSITIVE</option>
          <option value="NEGATIVE">NEGATIVE</option>
          <option value="BOTH" selected>BOTH</option>
        </select>
      </label>
    </div>
    <div class="recording-monitor-actions">
      <button id="recording-monitor-apply" type="button">APPLY</button>
      <button id="recording-monitor-enable" type="button">ENABLE MONITOR</button>
      <button id="recording-monitor-disable" type="button">DISABLE MONITOR</button>
    </div>
    <div id="recording-monitor-message" class="recording-monitor-message" aria-live="polite">Select a device, apply a configuration, then enable the monitor.</div>
    <div id="recording-monitor-phase-status" class="recording-monitor-phase-status" aria-label="Per-phase monitor state"></div>
    <div id="recording-monitor-last-event" class="recording-monitor-last-event">LAST EVENT —</div>`;
}

function selectedDeviceId() {
  return document.getElementById("device-selector")?.value || "";
}

function selectedPhases() {
  return PHASES.filter((phase) => document.getElementById(`recording-monitor-phase-${phase.toLowerCase()}`)?.checked);
}

function currentDraft() {
  const condition = document.getElementById("recording-monitor-condition")?.value ?? "";
  const draft = {
    condition,
    phases: selectedPhases(),
    recording_interval_s: finiteNumber(document.getElementById("recording-monitor-interval")?.value),
  };
  if (condition === "Q_THRESHOLD") {
    draft.threshold_var = finiteNumber(document.getElementById("recording-monitor-q-threshold")?.value);
    draft.q_direction = document.getElementById("recording-monitor-q-direction")?.value ?? "";
  }
  return draft;
}

function setMessage(text, isError = false) {
  const node = document.getElementById("recording-monitor-message");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("is-error", isError);
}

function setIntervals(values, selected) {
  const select = document.getElementById("recording-monitor-interval");
  if (!select) return;
  const unique = [...new Set(values.filter((value) => Number.isFinite(value) && value > 0))].sort((a, b) => a - b);
  select.replaceChildren(...unique.map((value) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = `${value} s`;
    return option;
  }));
  if (unique.includes(selected)) select.value = String(selected);
}

function setQOptionsVisible(condition) {
  const options = document.getElementById("recording-monitor-q-options");
  if (options) options.hidden = condition !== "Q_THRESHOLD";
}

function syncControls(status, runtimeConfig) {
  const deviceId = selectedDeviceId();
  const device = runtimeConfig?.devices?.find((item) => item.id === deviceId);
  const poll = finiteNumber(device?.poll_interval_s) ?? 1;
  const configuredInterval = status?.config?.recording_interval_s;
  const fallback = Math.max(poll, finiteNumber(runtimeConfig?.recording_default_interval_s) ?? poll);
  const interval = configuredInterval ?? fallback;
  const candidates = [poll, fallback, configuredInterval, 1, 2, 5, 10, 30, 60].filter((value) => value !== null && value >= poll);
  setIntervals(candidates, interval);

  const condition = status?.config?.condition ?? "P_NEGATIVE";
  document.getElementById("recording-monitor-condition").value = condition;
  setQOptionsVisible(condition);
  const threshold = finiteNumber(status?.config?.threshold_var) ?? 0;
  document.getElementById("recording-monitor-q-threshold").value = String(threshold);
  document.getElementById("recording-monitor-q-direction").value = status?.config?.q_direction ?? "BOTH";

  const phases = status?.config?.phases ?? PHASES;
  for (const phase of PHASES) {
    document.getElementById(`recording-monitor-phase-${phase.toLowerCase()}`).checked = phases.includes(phase);
  }
}

function renderStatus(status, dirty) {
  const state = status?.state ?? "OFF";
  const stateNode = document.getElementById("recording-monitor-state");
  if (stateNode) {
    stateNode.textContent = state.replaceAll("_", " ");
    stateNode.dataset.state = state;
  }
  const phaseNode = document.getElementById("recording-monitor-phase-status");
  if (phaseNode) {
    phaseNode.replaceChildren(...PHASES.map((phase) => {
      const line = document.createElement("span");
      line.textContent = phaseStatusText(status, phase);
      return line;
    }));
  }
  const lastNode = document.getElementById("recording-monitor-last-event");
  if (lastNode) {
    const event = status?.last_event;
    lastNode.textContent = event
      ? `LAST EVENT ${event.phase} · ${event.measurement} · ${event.event} · cycle ${event.cycle_id ?? "—"} · ${event.utc || "—"} · ${event.value ?? "—"}`
      : "LAST EVENT —";
  }
  const enable = document.getElementById("recording-monitor-enable");
  const disable = document.getElementById("recording-monitor-disable");
  if (enable) enable.disabled = !selectedDeviceId() || state !== "OFF" || dirty;
  if (disable) disable.disabled = !selectedDeviceId() || state === "OFF";
}

function installRecordingMonitorUi() {
  const oldPanel = document.querySelector(".recording-trigger-panel");
  const recordingBody = document.querySelector(".recording-drawer .recording-panel-body");
  if (!recordingBody) return false;
  const panel = document.createElement("section");
  panel.className = "recording-monitor-panel";
  panel.setAttribute("aria-label", "Continuous recording condition monitor");
  panel.innerHTML = panelMarkup();
  if (oldPanel) oldPanel.replaceWith(panel);
  else recordingBody.prepend(panel);
  return true;
}

async function runController() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (installRecordingMonitorUi()) break;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  if (!document.getElementById("recording-monitor-state")) return;

  let runtimeConfig = null;
  let lastDeviceId = "";
  let dirty = false;
  let actionPending = false;
  let currentStatus = null;

  try {
    runtimeConfig = await getRuntimeConfig();
  } catch (error) {
    setMessage(`MONITOR CONFIG ERROR: ${error.message}`, true);
  }

  const markDirty = () => {
    dirty = true;
    setMessage("UNAPPLIED CHANGES · press APPLY before ENABLE MONITOR");
    renderStatus(currentStatus, dirty);
  };

  const conditionControl = document.getElementById("recording-monitor-condition");
  conditionControl?.addEventListener("change", () => {
    setQOptionsVisible(conditionControl.value);
    markDirty();
  });
  for (const id of [
    "recording-monitor-phase-a",
    "recording-monitor-phase-b",
    "recording-monitor-phase-c",
    "recording-monitor-interval",
    "recording-monitor-q-threshold",
    "recording-monitor-q-direction",
  ]) {
    document.getElementById(id)?.addEventListener("change", markDirty);
  }

  async function refresh({forceControls = false} = {}) {
    if (actionPending) return;
    const deviceId = selectedDeviceId();
    try {
      const payload = await getRecordingStatus();
      const status = normalizeMonitorStatus((payload.monitors ?? []).find((item) => item.device_id === deviceId));
      currentStatus = status;
      if (deviceId !== lastDeviceId) {
        lastDeviceId = deviceId;
        dirty = false;
        forceControls = true;
      }
      if (forceControls || !dirty) syncControls(status, runtimeConfig);
      renderStatus(status, dirty);
      if (!deviceId) setMessage("Select an Emonio device.");
      else if (!status) setMessage("Monitor not configured. Select parameters and press APPLY.");
      else if (!dirty) {
        const label = conditionLabel(
          status.config.condition,
          status.config.threshold_var,
          status.config.q_direction,
        );
        setMessage(`MONITOR ${status.state.replaceAll("_", " ")} · ${label} · ${status.config.phases.join("/")}`);
      }
    } catch (error) {
      setMessage(`MONITOR STATUS ERROR: ${error.message}`, true);
    }
  }

  document.getElementById("recording-monitor-apply")?.addEventListener("click", async () => {
    const deviceId = selectedDeviceId();
    const draft = currentDraft();
    const error = validateMonitorDraft(draft);
    if (!deviceId) return setMessage("Select an Emonio device.", true);
    if (error) return setMessage(error, true);
    actionPending = true;
    try {
      await configureRecordingMonitor(deviceId, draft);
      dirty = false;
      setMessage("CONFIGURATION APPLIED · monitor is OFF until ENABLE MONITOR.");
    } catch (cause) {
      setMessage(`APPLY FAILED: ${cause.message}`, true);
    } finally {
      actionPending = false;
      await refresh({forceControls: true});
    }
  });

  document.getElementById("recording-monitor-enable")?.addEventListener("click", async () => {
    const deviceId = selectedDeviceId();
    if (!deviceId) return setMessage("Select an Emonio device.", true);
    if (dirty) return setMessage("Apply changes before enabling the monitor.", true);
    actionPending = true;
    try {
      await enableRecordingMonitor(deviceId);
      setMessage("MONITOR ENABLED · waiting for exact canonical condition evidence.");
    } catch (cause) {
      setMessage(`ENABLE FAILED: ${cause.message}`, true);
    } finally {
      actionPending = false;
      await refresh({forceControls: true});
    }
  });

  document.getElementById("recording-monitor-disable")?.addEventListener("click", async () => {
    const deviceId = selectedDeviceId();
    if (!deviceId) return setMessage("Select an Emonio device.", true);
    actionPending = true;
    try {
      await disableRecordingMonitor(deviceId);
      setMessage("MONITOR DISABLED.");
    } catch (cause) {
      setMessage(`DISABLE FAILED: ${cause.message}`, true);
    } finally {
      actionPending = false;
      await refresh({forceControls: true});
    }
  });

  await refresh({forceControls: true});
  setInterval(() => void refresh(), 1000);
}

if (typeof document !== "undefined") {
  setTimeout(() => void runController(), 0);
}
