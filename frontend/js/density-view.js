export const DENSITY_PHASES = Object.freeze([
  Object.freeze({ key: "phase_a", label: "A" }),
  Object.freeze({ key: "phase_b", label: "B" }),
  Object.freeze({ key: "phase_c", label: "C" }),
  Object.freeze({ key: "total", label: "TOTAL" }),
]);

const DENSITY_PHASE_KEYS = new Set(DENSITY_PHASES.map((phase) => phase.key));
let densityViewActive = false;
let densityPhaseKey = "phase_a";

export function isDensityViewActive() {
  return densityViewActive;
}

export function setDensityViewActive(active) {
  if (typeof active !== "boolean") return false;
  densityViewActive = active;
  return true;
}

export function getDensityPhaseKey() {
  return densityPhaseKey;
}

export function setDensityPhaseKey(phaseKey) {
  if (!DENSITY_PHASE_KEYS.has(phaseKey)) return false;
  densityPhaseKey = phaseKey;
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
