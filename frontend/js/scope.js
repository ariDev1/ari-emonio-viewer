import {
  getScopeStatus,
  holdScope,
  liveScope,
  startScope,
  stopScope,
} from "./api.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const PHASE_CHANNELS = Object.freeze({
  A: Object.freeze({ U: 1, I: 0 }),
  B: Object.freeze({ U: 3, I: 2 }),
  C: Object.freeze({ U: 5, I: 4 }),
});
const VALID_PHASE_MODES = new Set(["A", "B", "C", "ABC"]);
const VALID_SIGNAL_MODES = new Set(["U", "I", "U+I", "P"]);
const ACTIVE_SCOPE_STATES = new Set(["CONNECTING", "LIVE", "HOLD"]);
const DEFAULT_VIEW_MODE = Object.freeze({ phase: "A", signal: "U+I" });

const viewModesByDevice = new Map();
let selectedDeviceReader = () => null;
let deviceLabelReader = (deviceId) => deviceId ?? "—";
let deviceOptionsReader = () => [];
let deviceSelectionWriter = async () => {};
let pollTimer = null;
let scopeStatusGeneration = 0;

export function projectScopeX(index, sampleCount, left, right) {
  if (sampleCount <= 1) return (left + right) / 2;
  return left + (index / (sampleCount - 1)) * (right - left);
}

export function projectScopeY(value, maxAbs, top, bottom) {
  if (!Number.isFinite(value)) return null;
  if (!Number.isFinite(maxAbs) || maxAbs <= 0) return (top + bottom) / 2;
  const center = (top + bottom) / 2;
  const half = (bottom - top) / 2;
  return center - (value / maxAbs) * half;
}

export function scopeGridPositions(start, end, divisions) {
  if (!Number.isInteger(divisions) || divisions <= 0) return [];
  return Array.from({ length: divisions + 1 }, (_, index) => start + (index / divisions) * (end - start));
}

export function scopeViewModeForDevice(deviceId) {
  const stored = deviceId ? viewModesByDevice.get(deviceId) : null;
  return stored ? { ...stored } : { ...DEFAULT_VIEW_MODE };
}

export function setScopeViewModeForDevice(deviceId, phase, signal) {
  if (!deviceId || !VALID_PHASE_MODES.has(phase) || !VALID_SIGNAL_MODES.has(signal)) return false;
  viewModesByDevice.set(deviceId, { phase, signal });
  return true;
}

export function scopeActiveOwners(activeSessions) {
  if (!Array.isArray(activeSessions)) return [];
  return activeSessions
    .filter((item) => item && typeof item.device_id === "string" && ACTIVE_SCOPE_STATES.has(item.state))
    .map((item) => ({ device_id: item.device_id, state: item.state }))
    .sort((a, b) => a.device_id.localeCompare(b.device_id));
}

export function scopeResponseIsCurrent(requestedDeviceId, selectedDeviceId) {
  return Boolean(requestedDeviceId) && requestedDeviceId === selectedDeviceId;
}

function invalidateScopeStatusResponses() {
  scopeStatusGeneration += 1;
  return scopeStatusGeneration;
}

function scopeStatusResponseIsCurrent(requestedDeviceId, requestGeneration) {
  return scopeResponseIsCurrent(requestedDeviceId, selectedDeviceReader())
    && requestGeneration === scopeStatusGeneration;
}

export function scopeObservedHeaderPrefixes(capture) {
  if (!capture || typeof capture !== "object") return [];
  const explicit = Array.isArray(capture.observed_header_prefixes)
    ? capture.observed_header_prefixes
    : [];
  const fallback = Object.values(capture.channels ?? {})
    .map((frame) => frame?.header_prefix_hex)
    .filter((value) => typeof value === "string" && value.length > 0);
  return [...new Set((explicit.length > 0 ? explicit : fallback).filter(
    (value) => typeof value === "string" && value.length > 0
  ))].sort();
}

export function scopeSelectableDevices(devices) {
  if (!Array.isArray(devices)) return [];
  return devices
    .filter((device) => device && device.enabled !== false && typeof device.id === "string" && device.id.length > 0)
    .map((device) => {
      const name = typeof device.name === "string" && device.name.length > 0 ? device.name : device.id;
      const host = typeof device.host === "string" && device.host.length > 0 ? device.host : "";
      return {
        id: device.id,
        label: host && host !== name ? `${name} · ${host}` : name,
      };
    });
}

function renderScopeDeviceSelector(selectedDeviceId = selectedDeviceReader()) {
  const selector = document.getElementById("scope-device-selector");
  if (!selector) return [];
  const devices = scopeSelectableDevices(deviceOptionsReader());
  selector.replaceChildren();
  for (const device of devices) {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = device.label;
    selector.appendChild(option);
  }
  if (selectedDeviceId && devices.some((device) => device.id === selectedDeviceId)) {
    selector.value = selectedDeviceId;
  }
  selector.disabled = devices.length === 0;
  return devices;
}

export function scopeMetadataRows(capture) {
  const labels = ["A", "B", "C"];
  if (!capture || typeof capture !== "object") return [];
  const rows = [];
  for (let phase = 0; phase < 3; phase += 1) {
    const metadata = capture.metadata?.[String(phase)] ?? capture.metadata?.[phase];
    if (!metadata || typeof metadata !== "object" || metadata.phase !== phase) continue;
    rows.push({
      phase: labels[phase],
      connected: metadata.connected,
      vrms: metadata.vrms,
      irms: metadata.irms,
      frequency: metadata.frequency,
      pf: metadata.pf,
    });
  }
  return rows;
}

export function scopePowerSamples(capture, phase) {
  const mapping = PHASE_CHANNELS[phase];
  if (!capture || !mapping) return [];
  const voltageFrame = capture.channels?.[String(mapping.U)] ?? capture.channels?.[mapping.U];
  const currentFrame = capture.channels?.[String(mapping.I)] ?? capture.channels?.[mapping.I];
  const voltage = voltageFrame?.samples;
  const current = currentFrame?.samples;
  if (!Array.isArray(voltage) || !Array.isArray(current) || voltage.length === 0 || voltage.length !== current.length) {
    return [];
  }
  if (voltage.some((value) => !Number.isFinite(value)) || current.some((value) => !Number.isFinite(value))) {
    return [];
  }
  return voltage.map((value, index) => value * current[index]);
}

export function scopeTraceSpecs(capture, phaseMode, signalMode) {
  if (!capture || !VALID_PHASE_MODES.has(phaseMode) || !VALID_SIGNAL_MODES.has(signalMode)) return [];
  const phases = phaseMode === "ABC" ? ["A", "B", "C"] : [phaseMode];
  if (signalMode === "P") {
    const traces = [];
    for (const phase of phases) {
      const samples = scopePowerSamples(capture, phase);
      if (samples.length === 0) continue;
      traces.push({
        phase,
        signal: "P",
        unit: "W",
        channels: [PHASE_CHANNELS[phase].U, PHASE_CHANNELS[phase].I],
        samples,
      });
    }
    return traces;
  }

  const signals = signalMode === "U+I" ? ["U", "I"] : [signalMode];
  const traces = [];
  for (const phase of phases) {
    for (const signal of signals) {
      const channel = PHASE_CHANNELS[phase][signal];
      const source = capture.channels?.[String(channel)] ?? capture.channels?.[channel];
      if (!source || !Array.isArray(source.samples)) continue;
      traces.push({
        phase,
        signal,
        unit: signal === "U" ? "V" : "A",
        channel,
        samples: source.samples,
      });
    }
  }
  return traces;
}

export function scopeUnitMagnitudes(traces) {
  const magnitudes = {};
  for (const trace of traces) {
    if (!VALID_SIGNAL_MODES.has(trace.signal) || trace.signal === "U+I") continue;
    if (!(trace.signal in magnitudes)) magnitudes[trace.signal] = 0;
    for (const value of trace.samples) {
      if (!Number.isFinite(value)) continue;
      magnitudes[trace.signal] = Math.max(magnitudes[trace.signal], Math.abs(value));
    }
  }
  return magnitudes;
}

export function buildScopeTracePoints(samples, maxAbs, box) {
  if (!Array.isArray(samples) || samples.some((value) => !Number.isFinite(value))) return [];
  return samples.map((value, index) => [
    projectScopeX(index, samples.length, box.left, box.right),
    projectScopeY(value, maxAbs, box.top, box.bottom),
  ]);
}

export function scopeCaptureValidationError(capture) {
  if (!capture || typeof capture !== "object") return "capture must be an object";
  if (capture.sample_count !== 232) return "capture sample_count must be 232";
  if (!Number.isFinite(capture.capture_ms) || capture.capture_ms <= 0) return "capture_ms must be finite and greater than zero";
  if (!Number.isFinite(capture.sample_interval_ms) || capture.sample_interval_ms <= 0) return "sample_interval_ms must be finite and greater than zero";
  if (!Number.isFinite(capture.sample_rate_hz) || capture.sample_rate_hz <= 0) return "sample_rate_hz must be finite and greater than zero";
  if (!Array.isArray(capture.channel_order) || capture.channel_order.length !== 6
      || capture.channel_order.some((value, index) => value !== index)) {
    return "channel_order must be exactly 0,1,2,3,4,5";
  }
  if (!Array.isArray(capture.metadata_order) || capture.metadata_order.length !== 3
      || capture.metadata_order.some((value, index) => value !== index)) {
    return "metadata_order must be exactly 0,1,2";
  }
  for (let channel = 0; channel < 6; channel += 1) {
    const frame = capture.channels?.[String(channel)] ?? capture.channels?.[channel];
    if (!frame || typeof frame !== "object" || frame.channel !== channel) {
      return `channel ${channel} does not match its channel ID`;
    }
    if (frame.frame_bytes !== 932) return `channel ${channel} frame_bytes must be 932`;
    if (frame.sample_count !== 232) return `channel ${channel} sample_count must be 232`;
    if (frame.nonfinite_count !== 0) return `channel ${channel} reports non-finite samples`;
    if (!Array.isArray(frame.samples) || frame.samples.length !== 232) {
      return `channel ${channel} must contain exactly 232 samples`;
    }
    if (frame.samples.some((value) => !Number.isFinite(value))) {
      return `channel ${channel} samples must be finite`;
    }
  }
  for (let phase = 0; phase < 3; phase += 1) {
    const metadata = capture.metadata?.[String(phase)] ?? capture.metadata?.[phase];
    if (!metadata || typeof metadata !== "object" || metadata.phase !== phase) {
      return `metadata phase ${phase} does not match its key`;
    }
    if (!Number.isFinite(metadata.capture_ms) || metadata.capture_ms !== capture.capture_ms) {
      return `metadata phase ${phase} capture_ms must match capture_ms`;
    }
  }
  return null;
}

function svgNode(name, attributes = {}, text = null) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== null) node.textContent = text;
  return node;
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function formatNumber(value, digits = 6) {
  if (!Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}

export function renderScopeMetadata(capture) {
  const rows = scopeMetadataRows(capture);
  const byPhase = new Map(rows.map((row) => [row.phase, row]));
  for (const phase of ["A", "B", "C"]) {
    const row = byPhase.get(phase);
    const prefix = `scope-meta-${phase.toLowerCase()}-`;
    setText(`${prefix}connected`, row ? String(row.connected) : "—");
    setText(`${prefix}vrms`, row ? `${formatNumber(row.vrms, 6)} V` : "—");
    setText(`${prefix}irms`, row ? `${formatNumber(row.irms, 6)} A` : "—");
    setText(`${prefix}frequency`, row ? `${formatNumber(row.frequency, 6)} Hz` : "—");
    setText(`${prefix}pf`, row ? formatNumber(row.pf, 6) : "—");
  }
}

function setActiveButtons(selector, dataKey, value) {
  for (const button of document.querySelectorAll(selector)) {
    const active = button.dataset[dataKey] === value;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
}

function applyViewButtons(deviceId) {
  const view = scopeViewModeForDevice(deviceId);
  setActiveButtons("[data-scope-phase]", "scopePhase", view.phase);
  setActiveButtons("[data-scope-signal]", "scopeSignal", view.signal);
}

function renderScopeLegend(view) {
  const visiblePhases = view.phase === "ABC" ? new Set(["A", "B", "C"]) : new Set([view.phase]);
  const visibleSignals = view.signal === "U+I" ? new Set(["U", "I"]) : new Set([view.signal]);
  for (const item of document.querySelectorAll("[data-scope-legend-phase]")) {
    item.hidden = !visiblePhases.has(item.dataset.scopeLegendPhase);
  }
  for (const item of document.querySelectorAll("[data-scope-legend-signal]")) {
    item.hidden = !visibleSignals.has(item.dataset.scopeLegendSignal);
  }
}

function renderScopeOwners(payload) {
  const owners = scopeActiveOwners(payload?.active_sessions);
  setText("scope-active-count", `${owners.length} ACTIVE`);
  setText("scope-summary-state", `${owners.length} ACTIVE`);

  const list = document.getElementById("scope-active-owners");
  if (!list) return owners;
  list.replaceChildren();
  if (owners.length === 0) {
    list.textContent = "NONE";
    return owners;
  }

  const selected = selectedDeviceReader();
  for (const owner of owners) {
    const chip = document.createElement("span");
    chip.className = "scope-owner-chip";
    if (owner.device_id === selected) chip.classList.add("is-selected");
    chip.dataset.scopeOwnerState = owner.state;
    chip.textContent = `${deviceLabelReader(owner.device_id)} · ${owner.state}`;
    list.appendChild(chip);
  }
  return owners;
}

function renderGrid(svg, box, captureMs, magnitudes, traces) {
  const vertical = scopeGridPositions(box.left, box.right, 10);
  const horizontal = scopeGridPositions(box.top, box.bottom, 8);

  vertical.forEach((x, index) => {
    svg.appendChild(svgNode("line", {
      class: index === 0 || index === 10 || index === 5 ? "scope-grid-major" : "scope-grid-minor",
      x1: x,
      y1: box.top,
      x2: x,
      y2: box.bottom,
    }));
    if (index % 2 === 0) {
      const timeMs = (captureMs * index) / 10;
      svg.appendChild(svgNode("text", {
        class: index === 10 ? "scope-axis-label scope-axis-label-end" : "scope-axis-label",
        x,
        y: box.bottom + 32,
      }, `${formatNumber(timeMs, 2)} ms`));
    }
  });

  horizontal.forEach((y, index) => {
    const isZero = index === 4;
    svg.appendChild(svgNode("line", {
      class: isZero ? "scope-grid-major scope-zero-axis" : index % 2 === 0 ? "scope-grid-major" : "scope-grid-minor",
      x1: box.left,
      y1: y,
      x2: box.right,
      y2: y,
    }));
  });

  const scaleFractions = [1, 0.5, 0, -0.5, -1];
  const scalePositions = scopeGridPositions(box.top, box.bottom, 4);
  if (traces.some((trace) => trace.signal === "U")) {
    scaleFractions.forEach((fraction, index) => {
      svg.appendChild(svgNode("text", {
        class: "scope-y-label scope-y-label-voltage",
        x: box.left - 12,
        y: scalePositions[index] + 4,
      }, `${formatNumber(magnitudes.U * fraction, 1)} V`));
    });
  }
  if (traces.some((trace) => trace.signal === "I")) {
    scaleFractions.forEach((fraction, index) => {
      svg.appendChild(svgNode("text", {
        class: "scope-y-label scope-y-label-current",
        x: box.right + 12,
        y: scalePositions[index] + 4,
      }, `${formatNumber(magnitudes.I * fraction, 2)} A`));
    });
  }
  if (traces.some((trace) => trace.signal === "P")) {
    scaleFractions.forEach((fraction, index) => {
      svg.appendChild(svgNode("text", {
        class: "scope-y-label scope-y-label-power",
        x: box.left - 12,
        y: scalePositions[index] + 4,
      }, `${formatNumber(magnitudes.P * fraction, 1)} W`));
    });
  }
}

function renderScopePlot(capture, deviceId = selectedDeviceReader()) {
  const svg = document.getElementById("scope-plot");
  if (!svg) return;
  svg.replaceChildren();
  const view = scopeViewModeForDevice(deviceId);
  renderScopeLegend(view);
  if (!capture) return;

  const traces = scopeTraceSpecs(capture, view.phase, view.signal);
  const magnitudes = scopeUnitMagnitudes(traces);
  const box = { left: 92, right: 908, top: 56, bottom: 500 };
  const captureMs = Number(capture.capture_ms);

  renderGrid(svg, box, captureMs, magnitudes, traces);

  for (const trace of traces) {
    const magnitude = Math.max(magnitudes[trace.signal], Number.EPSILON);
    const points = buildScopeTracePoints(trace.samples, magnitude, box);
    const polyline = svgNode("polyline", {
      class: `scope-trace scope-phase-${trace.phase.toLowerCase()} scope-signal-${trace.signal.toLowerCase()}`,
      "data-scope-phase": trace.phase,
      "data-scope-signal": trace.signal,
      points: points.map(([x, y]) => `${x},${y}`).join(" "),
    });
    svg.appendChild(polyline);
  }
}

function setScopeStateBadge(state) {
  const node = document.getElementById("scope-state");
  if (!node) return;
  node.textContent = state;
  node.dataset.state = state;
}

export function renderScopeStatus(payload) {
  const state = payload?.state ?? "DISCONNECTED";
  const deviceId = payload?.device_id ?? selectedDeviceReader();
  const capture = payload?.capture ?? null;
  const owners = renderScopeOwners(payload);
  const deviceLabel = deviceLabelReader(deviceId);

  setScopeStateBadge(state);
  renderScopeDeviceSelector(deviceId);
  setText("scope-summary-device", `${deviceLabel ?? "—"} · ${state}`);
  setText("scope-error", payload?.error ? `ERROR: ${payload.error}` : "");
  applyViewButtons(deviceId);

  const username = document.getElementById("scope-username");
  const password = document.getElementById("scope-password");
  const start = document.getElementById("scope-start");
  const live = document.getElementById("scope-live");
  const hold = document.getElementById("scope-hold");
  const stop = document.getElementById("scope-stop");
  const sessionOwnsTransport = ACTIVE_SCOPE_STATES.has(state);
  if (username) username.disabled = sessionOwnsTransport;
  if (password) password.disabled = sessionOwnsTransport;
  if (start) start.disabled = !["DISCONNECTED", "ERROR"].includes(state);
  if (live) live.disabled = state !== "HOLD";
  if (hold) hold.disabled = state !== "LIVE";
  if (stop) stop.disabled = state === "DISCONNECTED";

  if (!capture) {
    setText("scope-received-utc", "—");
    setText("scope-capture-sequence", "—");
    setText("scope-capture-ms", "—");
    setText("scope-samples", "—");
    setText("scope-rate", "—");
    setText("scope-prefix", "—");
    renderScopeMetadata(null);
    renderScopePlot(null, deviceId);
    return owners;
  }

  const captureError = scopeCaptureValidationError(capture);
  if (captureError) {
    setText("scope-received-utc", "—");
    setText("scope-capture-sequence", "—");
    setText("scope-capture-ms", "—");
    setText("scope-samples", "—");
    setText("scope-rate", "—");
    setText("scope-prefix", "—");
    setText("scope-error", `INVALID CAPTURE: ${captureError}`);
    renderScopeMetadata(null);
    renderScopePlot(null, deviceId);
    return owners;
  }

  setText("scope-received-utc", capture.received_utc ?? "—");
  setText("scope-capture-sequence", String(capture.sequence ?? "—"));
  setText("scope-capture-ms", `${formatNumber(capture.capture_ms, 3)} ms`);
  setText("scope-samples", `${capture.sample_count ?? "—"}/ch`);
  setText("scope-rate", `${formatNumber(capture.sample_rate_hz, 3)} Hz · DERIVED`);
  const prefixes = scopeObservedHeaderPrefixes(capture);
  setText("scope-prefix", prefixes.length > 0 ? `${prefixes.join(",")} · OBSERVED` : "—");
  renderScopeMetadata(capture);
  renderScopePlot(capture, deviceId);
  return owners;
}

export async function refreshScopeStatus(deviceId = selectedDeviceReader()) {
  if (!deviceId) return false;
  const requestGeneration = invalidateScopeStatusResponses();
  try {
    const payload = await getScopeStatus(deviceId);
    if (!scopeStatusResponseIsCurrent(deviceId, requestGeneration)) return false;
    renderScopeStatus(payload);
    return true;
  } catch (error) {
    if (!scopeStatusResponseIsCurrent(deviceId, requestGeneration)) return false;
    setText("scope-summary-state", "UNAVAILABLE");
    setScopeStateBadge("UNAVAILABLE");
    setText("scope-error", `Status unavailable: ${error.message}`);
    return false;
  }
}

function renderControlResponse(deviceId, payload) {
  if (!scopeResponseIsCurrent(deviceId, selectedDeviceReader())) return false;
  invalidateScopeStatusResponses();
  renderScopeStatus(payload);
  return true;
}

async function pollScopeStatus() {
  pollTimer = null;
  await refreshScopeStatus();
  pollTimer = setTimeout(pollScopeStatus, 1000);
}

export function initializeScopeControls(
  getSelectedDevice,
  getDeviceLabel = (deviceId) => deviceId ?? "—",
  getDevices = () => [],
  selectScopeDevice = async () => {}
) {
  selectedDeviceReader = getSelectedDevice;
  deviceLabelReader = getDeviceLabel;
  deviceOptionsReader = getDevices;
  deviceSelectionWriter = selectScopeDevice;
  const scopeDeviceSelector = document.getElementById("scope-device-selector");
  const username = document.getElementById("scope-username");
  const password = document.getElementById("scope-password");
  const start = document.getElementById("scope-start");
  const live = document.getElementById("scope-live");
  const hold = document.getElementById("scope-hold");
  const stop = document.getElementById("scope-stop");

  scopeDeviceSelector?.addEventListener("change", async () => {
    const requestedDeviceId = scopeDeviceSelector.value;
    const currentDeviceId = selectedDeviceReader();
    if (!requestedDeviceId || requestedDeviceId === currentDeviceId) return;
    if (username) username.value = "";
    if (password) password.value = "";
    scopeDeviceSelector.disabled = true;
    setText("scope-error", "");
    try {
      await deviceSelectionWriter(requestedDeviceId);
    } catch (error) {
      setText("scope-error", `Device switch failed: ${error.message}`);
    } finally {
      renderScopeDeviceSelector(selectedDeviceReader());
    }
  });

  renderScopeDeviceSelector(selectedDeviceReader());

  start?.addEventListener("click", async () => {
    const deviceId = selectedDeviceReader();
    const userValue = username?.value.trim() ?? "";
    const passwordValue = password?.value ?? "";
    if (!deviceId || !userValue || !passwordValue) {
      setText("scope-error", "USERNAME AND PASSWORD ARE REQUIRED");
      return;
    }
    try {
      const payload = await startScope(deviceId, userValue, passwordValue);
      renderControlResponse(deviceId, payload);
      if (username) username.value = "";
    } catch (error) {
      if (scopeResponseIsCurrent(deviceId, selectedDeviceReader())) {
        setText("scope-error", `Start failed: ${error.message}`);
      }
    } finally {
      if (password) password.value = "";
    }
  });

  live?.addEventListener("click", async () => {
    const deviceId = selectedDeviceReader();
    if (!deviceId) return;
    try {
      renderControlResponse(deviceId, await liveScope(deviceId));
    } catch (error) {
      if (scopeResponseIsCurrent(deviceId, selectedDeviceReader())) setText("scope-error", `LIVE failed: ${error.message}`);
    }
  });

  hold?.addEventListener("click", async () => {
    const deviceId = selectedDeviceReader();
    if (!deviceId) return;
    try {
      renderControlResponse(deviceId, await holdScope(deviceId));
    } catch (error) {
      if (scopeResponseIsCurrent(deviceId, selectedDeviceReader())) setText("scope-error", `HOLD failed: ${error.message}`);
    }
  });

  stop?.addEventListener("click", async () => {
    const deviceId = selectedDeviceReader();
    if (!deviceId) return;
    try {
      renderControlResponse(deviceId, await stopScope(deviceId));
    } catch (error) {
      if (scopeResponseIsCurrent(deviceId, selectedDeviceReader())) setText("scope-error", `STOP failed: ${error.message}`);
    }
  });

  for (const button of document.querySelectorAll("[data-scope-phase]")) {
    button.addEventListener("click", () => {
      const deviceId = selectedDeviceReader();
      if (!deviceId) return;
      const current = scopeViewModeForDevice(deviceId);
      if (!setScopeViewModeForDevice(deviceId, button.dataset.scopePhase, current.signal)) return;
      applyViewButtons(deviceId);
      refreshScopeStatus(deviceId);
    });
  }
  for (const button of document.querySelectorAll("[data-scope-signal]")) {
    button.addEventListener("click", () => {
      const deviceId = selectedDeviceReader();
      if (!deviceId) return;
      const current = scopeViewModeForDevice(deviceId);
      if (!setScopeViewModeForDevice(deviceId, current.phase, button.dataset.scopeSignal)) return;
      applyViewButtons(deviceId);
      refreshScopeStatus(deviceId);
    });
  }

  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = setTimeout(pollScopeStatus, 1000);
}
