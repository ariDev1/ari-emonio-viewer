export const HISTORY_WINDOW_MS = 10 * 60 * 1000;
export const HISTORY_DISPLAY_WINDOWS = Object.freeze([
  Object.freeze({ ms: 30 * 1000, label: "30 s" }),
  Object.freeze({ ms: 60 * 1000, label: "1 min" }),
  Object.freeze({ ms: 2 * 60 * 1000, label: "2 min" }),
  Object.freeze({ ms: 5 * 60 * 1000, label: "5 min" }),
  Object.freeze({ ms: HISTORY_WINDOW_MS, label: "10 min" }),
]);
export const HISTORY_PHASES = Object.freeze([
  Object.freeze({ key: "phase_a", label: "A" }),
  Object.freeze({ key: "phase_b", label: "B" }),
  Object.freeze({ key: "phase_c", label: "C" }),
  Object.freeze({ key: "total", label: "TOTAL" }),
]);
export const HISTORY_CHARTS = Object.freeze([
  Object.freeze({ svgId: "history-active-plot", field: "p", unit: "W", scale: "signed", title: "P(t)", scaleNote: "ACTIVE POWER · W · ZERO-CENTERED" }),
  Object.freeze({ svgId: "history-active-plot", field: "q", unit: "var", scale: "signed", title: "Q(t)", scaleNote: "REACTIVE POWER · var · ZERO-CENTERED" }),
  Object.freeze({ svgId: "history-active-plot", field: "vrms", unit: "V", scale: "observed", title: "U(t)", scaleNote: "RMS VOLTAGE · V · OBSERVED RANGE" }),
  Object.freeze({ svgId: "history-active-plot", field: "irms", unit: "A", scale: "observed", title: "I(t)", scaleNote: "RMS CURRENT · A · OBSERVED RANGE" }),
  Object.freeze({ svgId: "history-active-plot", field: "s", unit: "VA", scale: "observed", title: "S(t)", scaleNote: "APPARENT POWER · VA · OBSERVED RANGE" }),
  Object.freeze({ svgId: "history-active-plot", field: "pf", unit: "", scale: "observed", title: "PF(t)", scaleNote: "POWER FACTOR · DIMENSIONLESS · OBSERVED RANGE" }),
  Object.freeze({ svgId: "history-active-plot", field: "frequency", unit: "Hz", scale: "observed", title: "f(t)", scaleNote: "FREQUENCY · Hz · OBSERVED RANGE" }),
]);

const HISTORY_CHART_BY_FIELD = new Map(HISTORY_CHARTS.map((chart) => [chart.field, chart]));
const HISTORY_DISPLAY_WINDOW_BY_MS = new Map(HISTORY_DISPLAY_WINDOWS.map((window) => [window.ms, window]));
const SVG_NS = "http://www.w3.org/2000/svg";
const VIEWBOX = Object.freeze({ width: 760, height: 260 });
const PLOT = Object.freeze({ left: 70, right: 744, top: 30, bottom: 220 });
let activeHistoryField = "p";
let activeHistoryWindowMs = HISTORY_WINDOW_MS;

function finite(value) {
  return Number.isFinite(value) ? value : null;
}

function phasePoint(block) {
  return Object.freeze({
    vrms: finite(block?.vrms),
    irms: finite(block?.irms),
    p: finite(block?.p),
    q: finite(block?.q),
    s: finite(block?.s),
    pf: finite(block?.pf),
    frequency: finite(block?.frequency),
  });
}

function samplePoint(payload) {
  const sample = payload?.sample;
  const timestampMs = Date.parse(sample?.cycle_finished_utc ?? "");
  if (!payload?.device_id || !Number.isFinite(timestampMs) || !Number.isInteger(sample?.cycle_id)) {
    return null;
  }
  return Object.freeze({
    deviceId: payload.device_id,
    cycleId: sample.cycle_id,
    cycleFinishedUtc: sample.cycle_finished_utc,
    timestampMs,
    quality: payload.quality ?? null,
    phase_a: phasePoint(sample.phase_a),
    phase_b: phasePoint(sample.phase_b),
    phase_c: phasePoint(sample.phase_c),
    total: phasePoint(sample.total),
  });
}

export class MeasurementHistory {
  constructor(windowMs = HISTORY_WINDOW_MS) {
    if (!Number.isFinite(windowMs) || windowMs <= 0) throw new RangeError("windowMs must be > 0");
    this.windowMs = windowMs;
    this.byDevice = new Map();
  }

  append(payload) {
    const point = samplePoint(payload);
    if (!point) return false;
    const points = this.byDevice.get(point.deviceId) ?? [];
    if (points.some((existing) =>
      existing.cycleId === point.cycleId && existing.cycleFinishedUtc === point.cycleFinishedUtc
    )) return false;
    points.push(point);
    points.sort((a, b) => a.timestampMs - b.timestampMs || a.cycleId - b.cycleId);
    const newestMs = points[points.length - 1].timestampMs;
    const cutoffMs = newestMs - this.windowMs;
    while (points.length > 0 && points[0].timestampMs < cutoffMs) points.shift();
    this.byDevice.set(point.deviceId, points);
    return true;
  }

  get(deviceId) {
    return (this.byDevice.get(deviceId) ?? []).slice();
  }
}

const browserHistory = new MeasurementHistory();
const selectedByDevice = new Map();

export function appendHistoryPayload(payload) {
  return browserHistory.append(payload);
}

export function getHistorySamples(deviceId) {
  return browserHistory.get(deviceId);
}

export function historyChartForField(field) {
  return HISTORY_CHART_BY_FIELD.get(field) ?? null;
}

export function getActiveHistoryField() {
  return activeHistoryField;
}

export function getActiveHistoryWindowMs() {
  return activeHistoryWindowMs;
}

export function visibleHistorySamples(samples, windowMs = activeHistoryWindowMs) {
  if (!Array.isArray(samples) || samples.length === 0 || !Number.isFinite(windowMs) || windowMs <= 0) return [];
  const finiteSamples = samples.filter((sample) => Number.isFinite(sample?.timestampMs));
  if (finiteSamples.length === 0) return [];
  const endMs = finiteSamples[finiteSamples.length - 1].timestampMs;
  const startMs = endMs - windowMs;
  return finiteSamples.filter((sample) => sample.timestampMs >= startMs && sample.timestampMs <= endMs);
}

function updateHistorySelectorState() {
  if (typeof document === "undefined") return;
  for (const button of document.querySelectorAll("[data-history-select-field]")) {
    const active = button.dataset.historySelectField === activeHistoryField;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
}

function updateActiveHistoryHeading() {
  if (typeof document === "undefined") return;
  const chart = historyChartForField(activeHistoryField) ?? HISTORY_CHARTS[0];
  const title = document.getElementById("history-active-title");
  const note = document.getElementById("history-active-scale-note");
  if (title) title.textContent = chart.title;
  if (note) note.textContent = chart.scaleNote;
}

export function setActiveHistoryField(field) {
  if (!HISTORY_CHART_BY_FIELD.has(field)) return false;
  activeHistoryField = field;
  updateHistorySelectorState();
  updateActiveHistoryHeading();
  return true;
}

function updateHistoryWindowSelectorState() {
  if (typeof document === "undefined") return;
  for (const button of document.querySelectorAll("[data-history-window-ms]")) {
    const active = Number(button.dataset.historyWindowMs) === activeHistoryWindowMs;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
  const display = document.getElementById("history-display-window");
  const window = HISTORY_DISPLAY_WINDOW_BY_MS.get(activeHistoryWindowMs);
  if (display) display.textContent = window?.label ?? "—";
}

export function setActiveHistoryWindowMs(windowMs) {
  if (!HISTORY_DISPLAY_WINDOW_BY_MS.has(windowMs)) return false;
  activeHistoryWindowMs = windowMs;
  updateHistoryWindowSelectorState();
  return true;
}

export function nearestHistorySample(samples, targetTimestampMs) {
  if (!Array.isArray(samples) || !Number.isFinite(targetTimestampMs)) return null;
  let nearest = null;
  let nearestDistance = Infinity;
  for (const sample of samples) {
    if (!Number.isFinite(sample?.timestampMs)) continue;
    const distance = Math.abs(sample.timestampMs - targetTimestampMs);
    const earlier = nearest === null || sample.timestampMs < nearest.timestampMs;
    const sameTimestampLowerCycle = nearest !== null
      && sample.timestampMs === nearest.timestampMs
      && Number.isInteger(sample.cycleId)
      && Number.isInteger(nearest.cycleId)
      && sample.cycleId < nearest.cycleId;
    if (distance < nearestDistance || (distance === nearestDistance && (earlier || sameTimestampLowerCycle))) {
      nearest = sample;
      nearestDistance = distance;
    }
  }
  return nearest;
}

export function adjacentHistorySample(samples, selectedIdentity, direction) {
  if (!Array.isArray(samples) || !selectedIdentity || ![-1, 1].includes(direction)) return null;
  const index = samples.findIndex((sample) =>
    sample?.cycleId === selectedIdentity.cycleId
    && sample?.cycleFinishedUtc === selectedIdentity.cycleFinishedUtc
  );
  if (index < 0) return null;
  return samples[index + direction] ?? null;
}

export function historyTimestampForPlotX(plotX, endMs, windowMs = HISTORY_WINDOW_MS) {
  if (!Number.isFinite(plotX) || !Number.isFinite(endMs) || !Number.isFinite(windowMs) || windowMs <= 0) return null;
  const boundedX = Math.min(PLOT.right, Math.max(PLOT.left, plotX));
  const ratio = (boundedX - PLOT.left) / (PLOT.right - PLOT.left);
  return endMs - windowMs + ratio * windowMs;
}

export function formatCanonicalHistoryValue(value) {
  return Number.isFinite(value) ? String(value) : "—";
}

export function projectTimestamp(timestampMs, startMs, endMs, left, right) {
  if (endMs <= startMs) return right;
  return left + ((timestampMs - startMs) / (endMs - startMs)) * (right - left);
}

export function projectSignedValue(value, limit, top, bottom) {
  const center = (top + bottom) / 2;
  if (!Number.isFinite(value) || !Number.isFinite(limit) || limit <= 0) return center;
  return center - (value / limit) * ((bottom - top) / 2);
}

export function projectObservedValue(value, minimum, maximum, top, bottom) {
  const center = (top + bottom) / 2;
  if (!Number.isFinite(value) || !Number.isFinite(minimum) || !Number.isFinite(maximum)) return center;
  if (maximum === minimum) return center;
  return bottom - ((value - minimum) / (maximum - minimum)) * (bottom - top);
}

export function observedLimit(samples, field) {
  let limit = 0;
  for (const sample of samples) {
    for (const phase of HISTORY_PHASES) {
      const value = sample?.[phase.key]?.[field];
      if (Number.isFinite(value)) limit = Math.max(limit, Math.abs(value));
    }
  }
  return limit > 0 ? limit : 1;
}

export function observedBounds(samples, field) {
  let min = Infinity;
  let max = -Infinity;
  for (const sample of samples) {
    for (const phase of HISTORY_PHASES) {
      const value = sample?.[phase.key]?.[field];
      if (!Number.isFinite(value)) continue;
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  }
  if (min === Infinity || max === -Infinity) return { min: null, max: null };
  return { min, max };
}

export function buildDiscreteSeries(samples, field, phaseKey, endMs, plot, limit, windowMs = HISTORY_WINDOW_MS) {
  const startMs = endMs - windowMs;
  return {
    points: samples
      .filter((sample) => Number.isFinite(sample?.timestampMs) && Number.isFinite(sample?.[phaseKey]?.[field]))
      .map((sample) => [
        projectTimestamp(sample.timestampMs, startMs, endMs, plot.left, plot.right),
        projectSignedValue(sample[phaseKey][field], limit, plot.top, plot.bottom),
      ]),
  };
}

export function buildObservedDiscreteSeries(samples, field, phaseKey, endMs, plot, range, windowMs = HISTORY_WINDOW_MS) {
  const startMs = endMs - windowMs;
  return {
    points: samples
      .filter((sample) => Number.isFinite(sample?.timestampMs) && Number.isFinite(sample?.[phaseKey]?.[field]))
      .map((sample) => [
        projectTimestamp(sample.timestampMs, startMs, endMs, plot.left, plot.right),
        projectObservedValue(sample[phaseKey][field], range.min, range.max, plot.top, plot.bottom),
      ]),
  };
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function utcTime(timestampMs) {
  if (!Number.isFinite(timestampMs)) return "—";
  return new Date(timestampMs).toISOString().slice(11, 19) + " UTC";
}

function fixedAxis(value, unit, signed = false) {
  if (!Number.isFinite(value)) return unit ? `— ${unit}` : "—";
  const prefix = signed && value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(4)}${unit ? ` ${unit}` : ""}`;
}

function renderLegend(svg) {
  const legend = svgElement("g", { class: "history-legend", transform: "translate(82 18)" });
  HISTORY_PHASES.forEach((phase, index) => {
    const item = svgElement("g", {
      class: "history-legend-item",
      "data-phase": phase.label === "TOTAL" ? "T" : phase.label,
      transform: `translate(${index * 92} 0)`,
    });
    item.appendChild(svgElement("circle", { class: "history-legend-dot", cx: 0, cy: 0, r: 3.4 }));
    const text = svgElement("text", { class: "history-legend-label", x: 9, y: 4 });
    text.textContent = phase.label;
    item.appendChild(text);
    legend.appendChild(item);
  });
  svg.appendChild(legend);
}

function renderTimeGrid(svg, startMs, endMs) {
  const grid = svgElement("g", { class: "history-grid-lines" });
  for (const ratio of [0, 0.25, 0.5, 0.75, 1]) {
    const x = PLOT.left + ratio * (PLOT.right - PLOT.left);
    grid.appendChild(svgElement("line", { x1: x, y1: PLOT.top, x2: x, y2: PLOT.bottom }));
  }
  svg.appendChild(grid);

  const axisLabels = [
    [PLOT.left, PLOT.bottom + 22, utcTime(startMs), "start"],
    [(PLOT.left + PLOT.right) / 2, PLOT.bottom + 22, utcTime((startMs + endMs) / 2), "middle"],
    [PLOT.right, PLOT.bottom + 22, utcTime(endMs), "end"],
  ];
  for (const [x, y, value, anchor] of axisLabels) {
    const label = svgElement("text", { class: "history-axis-label", x, y, "text-anchor": anchor });
    label.textContent = value;
    svg.appendChild(label);
  }
}

function renderSignedAxes(svg, startMs, endMs, limit, unit) {
  renderTimeGrid(svg, startMs, endMs);
  const centerY = (PLOT.top + PLOT.bottom) / 2;
  const grid = svgElement("g", { class: "history-grid-lines" });
  for (const y of [PLOT.top, centerY, PLOT.bottom]) {
    grid.appendChild(svgElement("line", {
      class: y === centerY ? "history-zero-line" : "",
      x1: PLOT.left,
      y1: y,
      x2: PLOT.right,
      y2: y,
    }));
  }
  svg.appendChild(grid);

  const labels = [
    [PLOT.top + 4, fixedAxis(limit, unit, true)],
    [centerY + 4, fixedAxis(0, unit)],
    [PLOT.bottom + 4, fixedAxis(-limit, unit)],
  ];
  for (const [y, text] of labels) {
    const label = svgElement("text", { class: "history-axis-label", x: PLOT.left - 8, y, "text-anchor": "end" });
    label.textContent = text;
    svg.appendChild(label);
  }
}

function renderObservedAxes(svg, startMs, endMs, range, unit) {
  renderTimeGrid(svg, startMs, endMs);
  const centerY = (PLOT.top + PLOT.bottom) / 2;
  const grid = svgElement("g", { class: "history-grid-lines" });
  for (const y of [PLOT.top, centerY, PLOT.bottom]) {
    grid.appendChild(svgElement("line", { x1: PLOT.left, y1: y, x2: PLOT.right, y2: y }));
  }
  if (Number.isFinite(range.min) && Number.isFinite(range.max) && range.min < 0 && range.max > 0) {
    const zeroY = projectObservedValue(0, range.min, range.max, PLOT.top, PLOT.bottom);
    grid.appendChild(svgElement("line", {
      class: "history-zero-line",
      x1: PLOT.left,
      y1: zeroY,
      x2: PLOT.right,
      y2: zeroY,
    }));
  }
  svg.appendChild(grid);

  const middle = Number.isFinite(range.min) && Number.isFinite(range.max) ? (range.min + range.max) / 2 : null;
  const labels = [
    [PLOT.top + 4, fixedAxis(range.max, unit)],
    [centerY + 4, fixedAxis(middle, unit)],
    [PLOT.bottom + 4, fixedAxis(range.min, unit)],
  ];
  for (const [y, text] of labels) {
    const label = svgElement("text", { class: "history-axis-label", x: PLOT.left - 8, y, "text-anchor": "end" });
    label.textContent = text;
    svg.appendChild(label);
  }
}

function renderWaiting(svg, message = "WAITING FOR CANONICAL SAMPLES") {
  const text = svgElement("text", { class: "history-waiting", x: VIEWBOX.width / 2, y: VIEWBOX.height / 2, "text-anchor": "middle" });
  text.textContent = message;
  svg.appendChild(text);
}

function selectedHistorySample(deviceId, samples) {
  const identity = selectedByDevice.get(deviceId);
  if (!identity) return null;
  const selected = samples.find((sample) =>
    sample.cycleId === identity.cycleId && sample.cycleFinishedUtc === identity.cycleFinishedUtc
  ) ?? null;
  if (!selected) selectedByDevice.delete(deviceId);
  return selected;
}

function renderSelectionCursor(svg, selectedSample, endMs, windowMs) {
  if (!selectedSample) return;
  const startMs = endMs - windowMs;
  if (selectedSample.timestampMs < startMs || selectedSample.timestampMs > endMs) return;
  const x = projectTimestamp(selectedSample.timestampMs, startMs, endMs, PLOT.left, PLOT.right);
  svg.appendChild(svgElement("line", {
    class: "history-inspection-cursor",
    x1: x,
    y1: PLOT.top,
    x2: x,
    y2: PLOT.bottom,
    "data-cycle-id": selectedSample.cycleId,
    "data-cycle-finished-utc": selectedSample.cycleFinishedUtc,
  }));
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function renderInspector(deviceId, samples, selectedSample) {
  setText("history-inspector-device", selectedSample ? deviceId : "—");
  setText("history-inspector-cycle", selectedSample ? String(selectedSample.cycleId) : "—");
  setText("history-inspector-timestamp", selectedSample?.cycleFinishedUtc ?? "—");
  setText("history-inspector-quality", selectedSample?.quality ?? "—");
  setText(
    "history-inspector-state",
    selectedSample
      ? "SELECTED MEASURED SAMPLE"
      : samples.length
        ? "NO SAMPLE SELECTED · CLICK THE ACTIVE HISTORY PLOT"
        : "WAITING FOR CANONICAL SAMPLES"
  );

  for (const phase of HISTORY_PHASES) {
    const row = document.querySelector(`[data-history-inspector-phase="${phase.label}"]`);
    if (!row) continue;
    for (const field of ["vrms", "irms", "p", "q", "s", "pf", "frequency"]) {
      const cell = row.querySelector(`[data-history-field="${field}"]`);
      if (cell) cell.textContent = formatCanonicalHistoryValue(selectedSample?.[phase.key]?.[field]);
    }
  }
}

function renderChart(config, samples, selectedSample, windowMs) {
  const svg = document.getElementById(config.svgId);
  if (!svg) return;
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${VIEWBOX.width} ${VIEWBOX.height}`);

  if (samples.length === 0) {
    renderWaiting(svg);
    return;
  }

  const endMs = samples[samples.length - 1].timestampMs;
  const startMs = endMs - windowMs;

  if (config.scale === "signed") {
    const limit = observedLimit(samples, config.field);
    renderSignedAxes(svg, startMs, endMs, limit, config.unit);
    renderLegend(svg);
    for (const phase of HISTORY_PHASES) {
      const series = buildDiscreteSeries(samples, config.field, phase.key, endMs, PLOT, limit, windowMs);
      renderSeries(svg, series.points, phase.label);
    }
    renderSelectionCursor(svg, selectedSample, endMs, windowMs);
    return;
  }

  const range = observedBounds(samples, config.field);
  if (!Number.isFinite(range.min) || !Number.isFinite(range.max)) {
    renderWaiting(svg, "NO FINITE CANONICAL SAMPLES");
    return;
  }
  renderObservedAxes(svg, startMs, endMs, range, config.unit);
  renderLegend(svg);
  for (const phase of HISTORY_PHASES) {
    const series = buildObservedDiscreteSeries(samples, config.field, phase.key, endMs, PLOT, range, windowMs);
    renderSeries(svg, series.points, phase.label);
  }
  renderSelectionCursor(svg, selectedSample, endMs, windowMs);
}

function renderSeries(svg, points, phaseLabel) {
  const group = svgElement("g", {
    class: "history-series",
    "data-phase": phaseLabel === "TOTAL" ? "T" : phaseLabel,
  });
  for (const [x, y] of points) {
    group.appendChild(svgElement("circle", { class: "history-sample-point", cx: x, cy: y, r: 2.1 }));
  }
  svg.appendChild(group);
}

export function renderMeasurementHistory(deviceId) {
  const storedSamples = browserHistory.get(deviceId);
  const visibleSamples = visibleHistorySamples(storedSamples, activeHistoryWindowMs);
  const selectedSample = selectedHistorySample(deviceId, storedSamples);
  const config = historyChartForField(activeHistoryField) ?? HISTORY_CHARTS[0];
  updateActiveHistoryHeading();
  updateHistorySelectorState();
  updateHistoryWindowSelectorState();
  renderChart(config, visibleSamples, selectedSample, activeHistoryWindowMs);
  renderInspector(deviceId, storedSamples, selectedSample);
  const count = document.getElementById("history-sample-count");
  if (count) count.textContent = `${visibleSamples.length} / ${storedSamples.length}`;
  const last = document.getElementById("history-last-utc");
  if (last) last.textContent = storedSamples.length ? utcTime(storedSamples[storedSamples.length - 1].timestampMs) : "—";
}

export function initializeHistoryMetricSelector(getActiveDeviceId) {
  if (typeof document === "undefined") return;
  for (const button of document.querySelectorAll("[data-history-select-field]")) {
    if (button.dataset.historyMetricBound === "true") continue;
    button.dataset.historyMetricBound = "true";
    button.addEventListener("click", () => {
      const field = button.dataset.historySelectField;
      if (!setActiveHistoryField(field)) return;
      const deviceId = getActiveDeviceId?.();
      if (deviceId) renderMeasurementHistory(deviceId);
    });
  }
  updateHistorySelectorState();
  updateActiveHistoryHeading();
}

export function initializeHistoryWindowSelector(getActiveDeviceId) {
  if (typeof document === "undefined") return;
  for (const button of document.querySelectorAll("[data-history-window-ms]")) {
    if (button.dataset.historyWindowBound === "true") continue;
    button.dataset.historyWindowBound = "true";
    button.addEventListener("click", () => {
      const windowMs = Number(button.dataset.historyWindowMs);
      if (!setActiveHistoryWindowMs(windowMs)) return;
      const deviceId = getActiveDeviceId?.();
      if (deviceId) renderMeasurementHistory(deviceId);
    });
  }
  updateHistoryWindowSelectorState();
}

export function initializeHistoryInspection(getActiveDeviceId) {
  const svg = document.getElementById("history-active-plot");
  if (!svg || svg.dataset.historyInspectionBound === "true") return;
  svg.dataset.historyInspectionBound = "true";
  svg.addEventListener("click", (event) => {
    const deviceId = getActiveDeviceId?.();
    const samples = visibleHistorySamples(browserHistory.get(deviceId), activeHistoryWindowMs);
    if (!deviceId || samples.length === 0) return;
    const screenMatrix = svg.getScreenCTM();
    if (!screenMatrix) return;
    const pointer = svg.createSVGPoint();
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    const plotX = pointer.matrixTransform(screenMatrix.inverse()).x;
    if (plotX < PLOT.left || plotX > PLOT.right) return;
    const endMs = samples[samples.length - 1].timestampMs;
    const targetTimestampMs = historyTimestampForPlotX(plotX, endMs, activeHistoryWindowMs);
    const selected = nearestHistorySample(samples, targetTimestampMs);
    if (!selected) return;
    selectedByDevice.set(deviceId, {
      cycleId: selected.cycleId,
      cycleFinishedUtc: selected.cycleFinishedUtc,
    });
    renderMeasurementHistory(deviceId);
    svg.focus({ preventScroll: true });
  });
  svg.addEventListener("keydown", (event) => {
    const direction = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
    if (direction === 0) return;
    const deviceId = getActiveDeviceId?.();
    if (!deviceId) return;
    const samples = browserHistory.get(deviceId);
    const selectedIdentity = selectedByDevice.get(deviceId);
    if (!selectedIdentity || samples.length === 0) return;
    event.preventDefault();
    const selected = adjacentHistorySample(samples, selectedIdentity, direction);
    if (!selected) return;
    selectedByDevice.set(deviceId, {
      cycleId: selected.cycleId,
      cycleFinishedUtc: selected.cycleFinishedUtc,
    });
    renderMeasurementHistory(deviceId);
  });
}
