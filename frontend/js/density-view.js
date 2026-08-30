import { buildDensityMap, DENSITY_BIN_COUNT } from "./density.js";

export const DENSITY_PHASES = Object.freeze([
  Object.freeze({ key: "phase_a", label: "A" }),
  Object.freeze({ key: "phase_b", label: "B" }),
  Object.freeze({ key: "phase_c", label: "C" }),
  Object.freeze({ key: "total", label: "TOTAL" }),
]);

const DENSITY_PHASE_KEYS = new Set(DENSITY_PHASES.map((phase) => phase.key));
const SVG_NS = "http://www.w3.org/2000/svg";
const DENSITY_VIEWBOX = Object.freeze({ width: 520, height: 360 });
const DENSITY_PLOT = Object.freeze({ left: 70, right: 370, top: 30, bottom: 330 });
let densityViewActive = false;
let densityPhaseKey = "phase_a";
let densityChangeCallback = null;

export function isDensityViewActive() {
  return densityViewActive;
}

export function setDensityViewActive(active) {
  if (typeof active !== "boolean") return false;
  densityViewActive = active;
  updateDensityControlState();
  return true;
}

export function getDensityPhaseKey() {
  return densityPhaseKey;
}

export function setDensityPhaseKey(phaseKey) {
  if (!DENSITY_PHASE_KEYS.has(phaseKey)) return false;
  densityPhaseKey = phaseKey;
  updateDensityControlState();
  return true;
}

export function densityCellGeometry(bin, plot, binCount) {
  if (!bin || !plot || !Number.isInteger(binCount) || binCount <= 0) return null;
  const width = (plot.right - plot.left) / binCount;
  const height = (plot.bottom - plot.top) / binCount;
  return Object.freeze({
    x: plot.left + bin.pIndex * width,
    y: plot.bottom - (bin.qIndex + 1) * height,
    width,
    height,
  });
}

function canonicalNumber(value) {
  return Number.isFinite(value) ? String(value) : "—";
}

export function formatDensityBinDetails(bin) {
  if (!bin) return "NO DENSITY BIN";
  const percentage = Number.isFinite(bin.percentage) ? `${bin.percentage.toFixed(3)} %` : "—";
  const count = Number.isInteger(bin.count) ? bin.count : 0;
  return `P ${canonicalNumber(bin.pMin)}…${canonicalNumber(bin.pMax)} W | Q ${canonicalNumber(bin.qMin)}…${canonicalNumber(bin.qMax)} var | ${count} samples | ${percentage}`;
}

function phaseLabelFor(phaseKey) {
  return DENSITY_PHASES.find((phase) => phase.key === phaseKey)?.label ?? null;
}

function sampleWord(count) {
  return count === 1 ? "SAMPLE" : "SAMPLES";
}

export function buildDensityRenderModel(samples, phaseKey = densityPhaseKey) {
  const phaseLabel = phaseLabelFor(phaseKey);
  if (!phaseLabel) throw new RangeError("unsupported density phase");
  const density = buildDensityMap(samples, phaseKey);
  const cells = density.bins
    .filter((bin) => bin.count > 0)
    .map((bin) => Object.freeze({
      ...bin,
      geometry: densityCellGeometry(bin, DENSITY_PLOT, DENSITY_BIN_COUNT),
      detail: formatDensityBinDetails(bin),
    }));
  const skipped = density.skippedSampleCount > 0 ? ` · ${density.skippedSampleCount} SKIPPED` : "";
  return Object.freeze({
    viewBox: DENSITY_VIEWBOX,
    plot: DENSITY_PLOT,
    phaseKey,
    phaseLabel,
    limit: density.limit,
    fallbackRangeUsed: density.fallbackRangeUsed,
    sampleCount: density.sampleCount,
    skippedSampleCount: density.skippedSampleCount,
    scaleNote: `P-Q DENSITY · ${phaseLabel} · ${DENSITY_BIN_COUNT}×${DENSITY_BIN_COUNT} · ${density.sampleCount} ${sampleWord(density.sampleCount)}${skipped}`,
    cells: Object.freeze(cells),
  });
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function appendText(svg, text, attributes) {
  const node = svgElement("text", attributes);
  node.textContent = text;
  svg.appendChild(node);
}

function renderDensityAxes(svg, model) {
  const centerX = (model.plot.left + model.plot.right) / 2;
  const centerY = (model.plot.top + model.plot.bottom) / 2;
  svg.appendChild(svgElement("line", {
    class: "density-axis density-zero-axis",
    x1: model.plot.left,
    y1: centerY,
    x2: model.plot.right,
    y2: centerY,
  }));
  svg.appendChild(svgElement("line", {
    class: "density-axis density-zero-axis",
    x1: centerX,
    y1: model.plot.top,
    x2: centerX,
    y2: model.plot.bottom,
  }));
  appendText(svg, "+P", { class: "density-axis-label", x: model.plot.right + 8, y: centerY - 5 });
  appendText(svg, "−P", { class: "density-axis-label", x: model.plot.left - 8, y: centerY - 5, "text-anchor": "end" });
  appendText(svg, "+Q", { class: "density-axis-label", x: centerX + 6, y: model.plot.top - 8 });
  appendText(svg, "−Q", { class: "density-axis-label", x: centerX + 6, y: model.plot.bottom + 18 });
  appendText(svg, `±${canonicalNumber(model.limit)} W / var`, {
    class: "density-scale-label",
    x: 405,
    y: 48,
  });
}

function renderDensityCells(svg, model) {
  for (const cell of model.cells) {
    const visualBand = Math.min(cell.band, 8);
    const rect = svgElement("rect", {
      class: `density-cell density-band-${visualBand}`,
      x: cell.geometry.x,
      y: cell.geometry.y,
      width: cell.geometry.width,
      height: cell.geometry.height,
      "data-count": cell.count,
      "data-p-index": cell.pIndex,
      "data-q-index": cell.qIndex,
      tabindex: 0,
      "aria-label": cell.detail,
    });
    const title = svgElement("title");
    title.textContent = cell.detail;
    rect.appendChild(title);
    svg.appendChild(rect);
  }
}

export function renderDensityView(samples) {
  if (typeof document === "undefined") return null;
  const svg = document.getElementById("history-active-plot");
  if (!svg) return null;
  const model = buildDensityRenderModel(samples, densityPhaseKey);
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${model.viewBox.width} ${model.viewBox.height}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.classList.add("density-plot-active");
  const title = document.getElementById("history-active-title");
  const note = document.getElementById("history-active-scale-note");
  if (title) title.textContent = "P-Q density";
  if (note) note.textContent = model.scaleNote;
  renderDensityCells(svg, model);
  renderDensityAxes(svg, model);
  if (model.sampleCount === 0) {
    appendText(svg, "WAITING FOR FINITE P-Q SAMPLES", {
      class: "density-waiting",
      x: (model.plot.left + model.plot.right) / 2,
      y: (model.plot.top + model.plot.bottom) / 2 - 12,
      "text-anchor": "middle",
    });
  }
  return model;
}

function createButton(label, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  return button;
}

function updateDensityControlState() {
  if (typeof document === "undefined") return;
  const timeButton = document.getElementById("history-view-time");
  const densityButton = document.getElementById("history-view-density");
  if (timeButton) {
    timeButton.classList.toggle("is-active", !densityViewActive);
    timeButton.setAttribute("aria-pressed", densityViewActive ? "false" : "true");
  }
  if (densityButton) {
    densityButton.classList.toggle("is-active", densityViewActive);
    densityButton.setAttribute("aria-pressed", densityViewActive ? "true" : "false");
  }
  const phaseGroup = document.getElementById("density-phase-selector");
  if (phaseGroup) phaseGroup.hidden = !densityViewActive;
  for (const button of document.querySelectorAll("[data-density-phase]")) {
    const active = button.dataset.densityPhase === densityPhaseKey;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
}

function notifyDensityChange() {
  if (typeof densityChangeCallback === "function") {
    densityChangeCallback(Object.freeze({ active: densityViewActive, phaseKey: densityPhaseKey }));
  }
}

export function initializeDensityView(onChange) {
  if (typeof document === "undefined") return;
  densityChangeCallback = typeof onChange === "function" ? onChange : null;
  if (document.getElementById("density-view-controls")) {
    updateDensityControlState();
    return;
  }
  const controls = document.querySelector(".history-controls");
  if (!controls) return;

  const wrapper = document.createElement("div");
  wrapper.id = "density-view-controls";
  wrapper.className = "density-view-controls";
  wrapper.setAttribute("role", "group");
  wrapper.setAttribute("aria-label", "History visualization mode");

  const timeButton = createButton("TIME HISTORY", "history-selector-button density-view-button is-active");
  timeButton.id = "history-view-time";
  timeButton.setAttribute("aria-pressed", "true");
  timeButton.addEventListener("click", () => {
    setDensityViewActive(false);
    notifyDensityChange();
  });

  const densityButton = createButton("P-Q DENSITY", "history-selector-button density-view-button");
  densityButton.id = "history-view-density";
  densityButton.setAttribute("aria-pressed", "false");
  densityButton.addEventListener("click", () => {
    setDensityViewActive(true);
    notifyDensityChange();
  });
  wrapper.append(timeButton, densityButton);

  const phaseGroup = document.createElement("div");
  phaseGroup.id = "density-phase-selector";
  phaseGroup.className = "density-phase-selector";
  phaseGroup.hidden = true;
  const phaseLabel = document.createElement("span");
  phaseLabel.className = "density-phase-label";
  phaseLabel.textContent = "DENSITY PHASE";
  phaseGroup.appendChild(phaseLabel);
  for (const phase of DENSITY_PHASES) {
    const button = createButton(phase.label, "history-selector-button density-phase-button");
    button.dataset.densityPhase = phase.key;
    button.setAttribute("aria-pressed", phase.key === densityPhaseKey ? "true" : "false");
    button.addEventListener("click", () => {
      if (!setDensityPhaseKey(phase.key)) return;
      notifyDensityChange();
    });
    phaseGroup.appendChild(button);
  }
  wrapper.appendChild(phaseGroup);

  const windowSelector = controls.querySelector(".history-window-selector");
  if (windowSelector) controls.insertBefore(wrapper, windowSelector);
  else controls.appendChild(wrapper);
  updateDensityControlState();
}
