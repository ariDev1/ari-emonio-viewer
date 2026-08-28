let currentLimit = null;
let shrinkVotes = 0;

export const SCALE_MARGIN = 1.12;
export const SHRINK_THRESHOLD = 0.60;
export const SHRINK_CONFIRMATION_SAMPLES = 5;

const VIEWBOX_WIDTH = 430;
const VIEWBOX_HEIGHT = 430;
const PLOT_CENTER_X = 190;
const PLOT_CENTER_Y = 225;
const PLOT_RADIUS = 150;
const LABEL_MARGIN = 14;
const LABEL_FLOOR_X = 18;
const LABEL_CEILING_X = VIEWBOX_WIDTH - 20;
const LABEL_FLOOR_Y = 18;
const LABEL_CEILING_Y = VIEWBOX_HEIGHT - 18;

const PHASES = [
  ["A", "phase_a"],
  ["B", "phase_b"],
  ["C", "phase_c"],
  ["T", "total"],
];

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

function sampleMagnitude(sample) {
  let maximum = 0;
  for (const [, key] of PHASES) {
    const block = sample[key];
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

function vectorElement(label) {
  const namespace = "http://www.w3.org/2000/svg";
  const group = document.createElementNS(namespace, "g");
  group.classList.add("plot-vector-group");
  group.dataset.phase = label;
  group.dataset.vector = label;

  const line = document.createElementNS(namespace, "line");
  line.classList.add("plot-vector");
  line.setAttribute("x1", String(PLOT_CENTER_X));
  line.setAttribute("y1", String(PLOT_CENTER_Y));

  const arrow = document.createElementNS(namespace, "polygon");
  arrow.classList.add("plot-arrowhead");

  const circle = document.createElementNS(namespace, "circle");
  circle.classList.add("plot-vector-tip");
  circle.setAttribute("r", "4.5");

  const text = document.createElementNS(namespace, "text");
  text.classList.add("plot-vector-label");
  text.textContent = label;

  group.append(line, arrow, circle, text);
  document.getElementById("pq-vectors").appendChild(group);
  return group;
}

function vectorTip(p, q) {
  return {
    x: PLOT_CENTER_X + (p / currentLimit) * PLOT_RADIUS,
    y: PLOT_CENTER_Y - (q / currentLimit) * PLOT_RADIUS,
  };
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function setVector(group, p, q) {
  const { x, y } = vectorTip(p, q);
  const line = group.querySelector(".plot-vector");
  const arrow = group.querySelector(".plot-arrowhead");
  const circle = group.querySelector(".plot-vector-tip");
  const text = group.querySelector(".plot-vector-label");

  line.setAttribute("x2", String(x));
  line.setAttribute("y2", String(y));
  circle.setAttribute("cx", String(x));
  circle.setAttribute("cy", String(y));

  const dx = x - PLOT_CENTER_X;
  const dy = y - PLOT_CENTER_Y;
  const length = Math.hypot(dx, dy);

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
    arrow.setAttribute("visibility", "visible");
  } else {
    arrow.setAttribute("points", "");
    arrow.setAttribute("visibility", "hidden");
  }

  const rawLabelX = x + (dx >= 0 ? LABEL_MARGIN : -LABEL_MARGIN);
  const rawLabelY = y + (dy >= 0 ? LABEL_MARGIN : -LABEL_MARGIN);
  const anchor = dx >= 0 ? "start" : "end";
  text.setAttribute("text-anchor", anchor);
  text.setAttribute("x", String(clamp(rawLabelX, LABEL_FLOOR_X, LABEL_CEILING_X)));
  text.setAttribute("y", String(clamp(rawLabelY, LABEL_FLOOR_Y, LABEL_CEILING_Y)));
}

export function resetQuadrantScale() {
  currentLimit = null;
  shrinkVotes = 0;
  document.getElementById("pq-scale").textContent = "SCALE waiting for data";
  document.getElementById("pq-vectors").replaceChildren();
}

export function renderQuadrant(sample) {
  updateScale(sample);
  for (const [label, key] of PHASES) {
    const block = sample[key];
    let group = document.querySelector(`[data-vector="${label}"]`);
    if (!group || group.tagName.toLowerCase() !== "g") group = vectorElement(label);
    setVector(group, block.p, block.q);
  }
}
