let currentLimit = null;
let shrinkVotes = 0;
let latestSample = null;
let selectedPhaseKey = "phase_a";
let selectorInitialized = false;

export const SCALE_MARGIN = 1.12;
export const SHRINK_THRESHOLD = 0.60;
export const SHRINK_CONFIRMATION_SAMPLES = 5;
export const POWER_ZERO_EPSILON = 1e-9;

const VIEWBOX_WIDTH = 430;
const VIEWBOX_HEIGHT = 430;
const PLOT_CENTER_X = 190;
const PLOT_CENTER_Y = 225;
const PLOT_RADIUS = 150;
const DETAIL_X = 350;
const DETAIL_VALUE_X = 418;
const DETAIL_START_Y = 250;
const DETAIL_ROW_HEIGHT = 18;
const ANGLE_RADIUS = 34;
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

export const PHASE_PLOTS = Object.freeze([
  Object.freeze({ label: "A", key: "phase_a", token: "A", isTotal: false }),
  Object.freeze({ label: "B", key: "phase_b", token: "B", isTotal: false }),
  Object.freeze({ label: "C", key: "phase_c", token: "C", isTotal: false }),
  Object.freeze({ label: "TOTAL", key: "total", token: "T", isTotal: true }),
]);

function niceScale(value) {
  if (!Number.isFinite(value) || value <= 0) return 1.0;
  const exponent = 10 ** Math.floor(Math.log10(value));
  const step = exponent / 10;
  return Math.ceil(value / step) * step;
}

export function computeAdaptiveLimit(limit, requiredMagnitude, confirmationCount) {
  const required = niceScale(Math.max(Number.EPSILON, requiredMagnitude) * SCALE_MARGIN);

  if (!Number.isFinite(limit) || limit <= 0) return [required, 0];
  if (required > limit) return [required, 0];

  if (required < limit * SHRINK_THRESHOLD) {
    const nextCount = confirmationCount + 1;
    if (nextCount >= SHRINK_CONFIRMATION_SAMPLES) return [required, 0];
    return [limit, nextCount];
  }

  return [limit, 0];
}

function quadrantFor(p, q) {
  if (p > 0 && q > 0) return "Q1";
  if (p < 0 && q > 0) return "Q2";
  if (p < 0 && q < 0) return "Q3";
  if (p > 0 && q < 0) return "Q4";
  return "AXIS";
}

export function computePowerVectorDetails(block, isTotal = false) {
  const p = Number(block?.p);
  const q = Number(block?.q);
  const canonicalS = Number(block?.s);
  const pf = Number(block?.pf);
  const finiteVector = Number.isFinite(p) && Number.isFinite(q);
  const resultantS = finiteVector ? Math.hypot(p, q) : Number.NaN;
  const angleMeaningful = finiteVector && resultantS > POWER_ZERO_EPSILON;
  const pfMeaningful = Number.isFinite(canonicalS)
    && Math.abs(canonicalS) > POWER_ZERO_EPSILON
    && Number.isFinite(pf);

  return {
    p,
    q,
    canonicalS,
    resultantS,
    pf,
    phiDeg: angleMeaningful ? Math.atan2(q, p) * 180 / Math.PI : null,
    quadrant: finiteVector ? quadrantFor(p, q) : "—",
    meaningful: angleMeaningful || pfMeaningful,
    angleMeaningful,
    pfMeaningful,
    isTotal: Boolean(isTotal),
  };
}

export function buildPowerDetailRows(details) {
  const rows = [
    { label: "P", value: details.p, unit: "W", kind: "power" },
    { label: "Q", value: details.q, unit: "var", kind: "power" },
  ];

  if (details.isTotal) {
    rows.push(
      { label: "ΣS", value: details.canonicalS, unit: "VA", kind: "power" },
      { label: "|P+jQ|", value: details.resultantS, unit: "VA", kind: "power" },
      { label: "φPQ", value: details.phiDeg, unit: "°", kind: "angle", meaningful: details.angleMeaningful },
    );
  } else {
    rows.push(
      { label: "S", value: details.canonicalS, unit: "VA", kind: "power" },
      { label: "φ", value: details.phiDeg, unit: "°", kind: "angle", meaningful: details.angleMeaningful },
    );
  }

  rows.push(
    { label: "PF", value: details.pf, unit: "", kind: "pf", meaningful: details.pfMeaningful },
    { label: "QUADRANT", value: details.quadrant, unit: "", kind: "text" },
  );
  return rows;
}

export function computePowerLabelLayout(p, q, limit) {
  const safeLimit = Number.isFinite(limit) && limit > 0 ? limit : 1;
  const finiteP = Number.isFinite(p) ? p : 0;
  const finiteQ = Number.isFinite(q) ? q : 0;
  const dx = (finiteP / safeLimit) * PLOT_RADIUS;
  const dy = -(finiteQ / safeLimit) * PLOT_RADIUS;
  const tip = {
    x: PLOT_CENTER_X + dx,
    y: PLOT_CENTER_Y + dy,
  };
  const absP = Math.abs(finiteP);
  const absQ = Math.abs(finiteQ);
  const nearVertical = absQ > POWER_ZERO_EPSILON && absP <= absQ * 0.20;
  const nearHorizontal = absP > POWER_ZERO_EPSILON && absQ <= absP * 0.20;
  const phiDeg = Math.atan2(finiteQ, finiteP) * 180 / Math.PI;
  const midRadians = phiDeg * Math.PI / 360;

  let orientation = "general";
  let angleRadius = 48;
  let pLabel = {
    x: PLOT_CENTER_X + dx * 0.5,
    y: PLOT_CENTER_Y - 9,
    anchor: "middle",
  };
  let qLabel = {
    x: tip.x + (finiteP < 0 ? -10 : 10),
    y: PLOT_CENTER_Y + dy * 0.5,
    anchor: finiteP < 0 ? "end" : "start",
  };

  const vectorLength = Math.hypot(dx, dy);
  const perpendicularX = vectorLength > POWER_ZERO_EPSILON ? -dy / vectorLength : 0;
  const perpendicularY = vectorLength > POWER_ZERO_EPSILON ? dx / vectorLength : -1;
  let vectorLabel = {
    x: PLOT_CENTER_X + dx * 0.62 + perpendicularX * 14,
    y: PLOT_CENTER_Y + dy * 0.62 + perpendicularY * 14,
    anchor: "middle",
  };

  if (nearVertical) {
    orientation = "near-vertical";
    angleRadius = 60;
    const side = finiteP < 0 ? -1 : 1;
    pLabel = {
      x: PLOT_CENTER_X + side * 24,
      y: PLOT_CENTER_Y - 10,
      anchor: "middle",
    };
    qLabel = {
      x: tip.x + side * 14,
      y: PLOT_CENTER_Y + dy * 0.5,
      anchor: side < 0 ? "end" : "start",
    };
    vectorLabel = {
      x: PLOT_CENTER_X + dx * 0.62 - side * 22,
      y: PLOT_CENTER_Y + dy * 0.62,
      anchor: "middle",
    };
  } else if (nearHorizontal) {
    orientation = "near-horizontal";
    angleRadius = 60;
    pLabel = {
      x: PLOT_CENTER_X + dx * 0.5,
      y: PLOT_CENTER_Y - 10,
      anchor: "middle",
    };
    qLabel = {
      x: tip.x,
      y: PLOT_CENTER_Y + (finiteQ < 0 ? 18 : -18),
      anchor: "middle",
    };
    vectorLabel = {
      x: PLOT_CENTER_X + dx * 0.62 + perpendicularX * 16,
      y: PLOT_CENTER_Y + dy * 0.62 + perpendicularY * 16,
      anchor: "middle",
    };
  }

  return {
    orientation,
    p: pLabel,
    q: qLabel,
    vector: vectorLabel,
    angle: {
      x: PLOT_CENTER_X + angleRadius * Math.cos(midRadians),
      y: PLOT_CENTER_Y - angleRadius * Math.sin(midRadians),
      radius: angleRadius,
    },
  };
}

function sampleMagnitude(sample) {
  let maximum = 0;
  for (const plot of PHASE_PLOTS) {
    const block = sample[plot.key];
    maximum = Math.max(maximum, Math.abs(block.p), Math.abs(block.q));
  }
  return maximum;
}

function formatScale(value) {
  if (value >= 1000) return value.toFixed(0);
  if (value >= 100) return value.toFixed(1);
  if (value >= 10) return value.toFixed(2);
  return value.toFixed(3);
}

function updateScale(sample) {
  [currentLimit, shrinkVotes] = computeAdaptiveLimit(currentLimit, sampleMagnitude(sample), shrinkVotes);
  document.getElementById("pq-scale").textContent = `SCALE ±${formatScale(currentLimit)} W/var`;
}

function svgElement(name, className = "") {
  const element = document.createElementNS(SVG_NAMESPACE, name);
  if (className) element.setAttribute("class", className);
  return element;
}

function appendLine(group, className, x1, y1, x2, y2) {
  const line = svgElement("line", className);
  line.setAttribute("x1", String(x1));
  line.setAttribute("y1", String(y1));
  line.setAttribute("x2", String(x2));
  line.setAttribute("y2", String(y2));
  group.appendChild(line);
  return line;
}

function appendText(group, className, x, y, text, anchor = "start") {
  const element = svgElement("text", className);
  element.setAttribute("x", String(x));
  element.setAttribute("y", String(y));
  element.setAttribute("text-anchor", anchor);
  element.textContent = text;
  group.appendChild(element);
  return element;
}

function vectorTip(p, q) {
  return {
    x: PLOT_CENTER_X + (p / currentLimit) * PLOT_RADIUS,
    y: PLOT_CENTER_Y - (q / currentLimit) * PLOT_RADIUS,
  };
}

function appendArrowhead(group, x, y) {
  const dx = x - PLOT_CENTER_X;
  const dy = y - PLOT_CENTER_Y;
  const length = Math.hypot(dx, dy);
  const arrow = svgElement("polygon", "plot-arrowhead");

  if (length >= 10) {
    const ux = dx / length;
    const uy = dy / length;
    const px = -uy;
    const py = ux;
    const backX = x - ux * 11;
    const backY = y - uy * 11;
    arrow.setAttribute(
      "points",
      `${x},${y} ${backX + px * 4.5},${backY + py * 4.5} ${backX - px * 4.5},${backY - py * 4.5}`,
    );
  } else {
    arrow.setAttribute("visibility", "hidden");
  }

  group.appendChild(arrow);
}

function angleArcPath(phiDeg) {
  const radians = phiDeg * Math.PI / 180;
  const endX = PLOT_CENTER_X + ANGLE_RADIUS * Math.cos(radians);
  const endY = PLOT_CENTER_Y - ANGLE_RADIUS * Math.sin(radians);
  const sweepFlag = phiDeg < 0 ? 1 : 0;
  return `M ${PLOT_CENTER_X + ANGLE_RADIUS} ${PLOT_CENTER_Y} A ${ANGLE_RADIUS} ${ANGLE_RADIUS} 0 0 ${sweepFlag} ${endX} ${endY}`;
}

function detailValueText(row) {
  if (row.meaningful === false) return "not meaningful";
  if (row.kind === "text") return String(row.value);
  if (!Number.isFinite(row.value)) return "—";
  if (row.kind === "angle") return `${row.value.toFixed(2)}${row.unit}`;
  if (row.kind === "pf") return row.value.toFixed(4);
  return `${row.value.toFixed(4)} ${row.unit}`;
}

function appendDetailPanel(group, config, details) {
  appendText(group, "plot-detail-title", DETAIL_X, DETAIL_START_Y - 14, `PLOT ${config.label}`);
  const rows = buildPowerDetailRows(details);
  rows.forEach((row, index) => {
    const y = DETAIL_START_Y + index * DETAIL_ROW_HEIGHT;
    appendText(group, "plot-detail-label", DETAIL_X, y, row.label);
    appendText(group, "plot-detail-value", DETAIL_VALUE_X, y, detailValueText(row), "end");
  });
}

function appendAngle(group, details, layout) {
  if (!details.angleMeaningful) return;

  const arc = svgElement("path", "plot-angle-arc");
  arc.setAttribute("d", angleArcPath(details.phiDeg));
  group.appendChild(arc);

  appendText(
    group,
    "plot-angle-label",
    layout.angle.x,
    layout.angle.y,
    details.isTotal ? "φPQ" : "φ",
    "middle",
  );
}

function appendPowerTriangle(group, details) {
  const tip = vectorTip(details.p, details.q);
  const pPoint = { x: tip.x, y: PLOT_CENTER_Y };
  const qPoint = { x: PLOT_CENTER_X, y: tip.y };
  const layout = computePowerLabelLayout(details.p, details.q, currentLimit);

  appendLine(group, "plot-p-component", PLOT_CENTER_X, PLOT_CENTER_Y, pPoint.x, pPoint.y);
  appendLine(group, "plot-q-component", pPoint.x, pPoint.y, tip.x, tip.y);
  appendLine(group, "plot-q-projection", qPoint.x, qPoint.y, tip.x, tip.y);
  appendLine(group, "plot-resultant-vector plot-vector", PLOT_CENTER_X, PLOT_CENTER_Y, tip.x, tip.y);

  appendArrowhead(group, tip.x, tip.y);

  const tipCircle = svgElement("circle", "plot-vector-tip");
  tipCircle.setAttribute("cx", String(tip.x));
  tipCircle.setAttribute("cy", String(tip.y));
  tipCircle.setAttribute("r", "4.5");
  group.appendChild(tipCircle);

  appendText(
    group,
    "plot-component-label plot-p-label",
    layout.p.x,
    layout.p.y,
    "P",
    layout.p.anchor,
  );
  appendText(
    group,
    "plot-component-label plot-q-label",
    layout.q.x,
    layout.q.y,
    "Q",
    layout.q.anchor,
  );

  const vectorLabel = details.isTotal ? "|P+jQ|" : "S";
  appendText(
    group,
    "plot-vector-label",
    layout.vector.x,
    layout.vector.y,
    vectorLabel,
    layout.vector.anchor,
  );

  appendAngle(group, details, layout);
}

function selectedPlot() {
  return PHASE_PLOTS.find((plot) => plot.key === selectedPhaseKey) ?? PHASE_PLOTS[0];
}

function updateSelectorState() {
  const active = selectedPlot();
  for (const plot of PHASE_PLOTS) {
    const item = document.querySelector(`#pq-legend [data-phase="${plot.token}"]`);
    if (!item) continue;
    const selected = plot.key === active.key;
    item.classList.toggle("is-active", selected);
    item.setAttribute("aria-pressed", selected ? "true" : "false");
  }

  const title = document.getElementById("quadrant-title");
  if (title) title.textContent = active.isTotal ? "Total power vector" : `Phase ${active.label} power vector`;
  const plot = document.getElementById("pq-plot");
  if (plot) plot.setAttribute("aria-label", `${active.label} active and reactive power triangle with signed P, Q, apparent power, power factor, and phase angle`);
}

function selectPhase(key) {
  if (!PHASE_PLOTS.some((plot) => plot.key === key)) return;
  selectedPhaseKey = key;
  updateSelectorState();
  if (latestSample) renderSelectedPhase(latestSample);
}

function initializePhaseSelector() {
  if (selectorInitialized) return;
  selectorInitialized = true;

  for (const plot of PHASE_PLOTS) {
    const item = document.querySelector(`#pq-legend [data-phase="${plot.token}"]`);
    if (!item) continue;
    item.classList.add("plot-selector-item");
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");
    item.setAttribute("aria-label", `Show ${plot.label} power vector plot`);
    item.addEventListener("click", () => selectPhase(plot.key));
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectPhase(plot.key);
    });
  }

  updateSelectorState();
}

function renderSelectedPhase(sample) {
  const config = selectedPlot();
  const block = sample[config.key];
  const details = computePowerVectorDetails(block, config.isTotal);
  const group = svgElement("g", "plot-vector-group");
  const label = config.label;
  group.dataset.phase = config.token;
  // data-vector remains the stable DOM contract for plot inspection.
  group.dataset.vector = label;

  appendPowerTriangle(group, details);
  appendDetailPanel(group, config, details);
  document.getElementById("pq-vectors").replaceChildren(group);
}

export function resetQuadrantScale() {
  currentLimit = null;
  shrinkVotes = 0;
  latestSample = null;
  document.getElementById("pq-scale").textContent = "SCALE waiting for data";
  document.getElementById("pq-vectors").replaceChildren();
  updateSelectorState();
}

export function renderQuadrant(sample) {
  latestSample = sample;
  initializePhaseSelector();
  updateScale(sample);
  renderSelectedPhase(sample);
}
