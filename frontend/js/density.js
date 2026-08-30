export const DENSITY_BIN_COUNT = 32;

function validPoint(sample, phaseKey) {
  const p = sample?.[phaseKey]?.p;
  const q = sample?.[phaseKey]?.q;
  if (!Number.isFinite(p) || !Number.isFinite(q)) return null;
  return Object.freeze({ p, q });
}

function observedDensityLimit(points) {
  let limit = 0;
  for (const point of points) {
    limit = Math.max(limit, Math.abs(point.p), Math.abs(point.q));
  }
  return limit;
}

function binIndex(value, limit) {
  const width = (2 * limit) / DENSITY_BIN_COUNT;
  const raw = Math.floor((value + limit) / width);
  return Math.min(DENSITY_BIN_COUNT - 1, Math.max(0, raw));
}

export function occupancyBand(count) {
  if (!Number.isInteger(count) || count <= 0) return 0;
  return 1 + Math.ceil(Math.log2(count));
}

export function buildDensityMap(samples, phaseKey) {
  const inputSamples = Array.isArray(samples) ? samples : [];
  const points = inputSamples
    .map((sample) => validPoint(sample, phaseKey))
    .filter((point) => point !== null);
  const observedLimit = observedDensityLimit(points);
  const fallbackRangeUsed = observedLimit === 0;
  const limit = fallbackRangeUsed ? 1 : observedLimit;
  const binWidth = (2 * limit) / DENSITY_BIN_COUNT;
  const bins = Array.from({ length: DENSITY_BIN_COUNT * DENSITY_BIN_COUNT }, (_, index) => {
    const pIndex = index % DENSITY_BIN_COUNT;
    const qIndex = Math.floor(index / DENSITY_BIN_COUNT);
    return {
      pIndex,
      qIndex,
      count: 0,
      percentage: 0,
      band: 0,
      pMin: -limit + pIndex * binWidth,
      pMax: -limit + (pIndex + 1) * binWidth,
      qMin: -limit + qIndex * binWidth,
      qMax: -limit + (qIndex + 1) * binWidth,
    };
  });

  for (const point of points) {
    const pIndex = binIndex(point.p, limit);
    const qIndex = binIndex(point.q, limit);
    bins[qIndex * DENSITY_BIN_COUNT + pIndex].count += 1;
  }

  for (const bin of bins) {
    bin.percentage = points.length > 0 ? (bin.count / points.length) * 100 : 0;
    bin.band = occupancyBand(bin.count);
    Object.freeze(bin);
  }

  return Object.freeze({
    binCount: DENSITY_BIN_COUNT,
    observedLimit,
    limit,
    binWidth,
    fallbackRangeUsed,
    inputSampleCount: inputSamples.length,
    sampleCount: points.length,
    skippedSampleCount: inputSamples.length - points.length,
    bins: Object.freeze(bins),
  });
}
