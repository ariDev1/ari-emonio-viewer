function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function integerNumber(value) {
  const number = finiteNumber(value);
  return Number.isInteger(number) ? number : null;
}

function textValue(value) {
  return typeof value === "string" ? value : "";
}

function normalizeConfig(config) {
  if (!config || typeof config !== "object") return null;
  const block = textValue(config.block);
  const measurement = textValue(config.measurement);
  const operator = textValue(config.operator);
  const mode = textValue(config.mode);
  const threshold = finiteNumber(config.threshold);
  const recordingInterval = finiteNumber(config.recording_interval_s);
  if (!["A", "B", "C", "TOTAL"].includes(block)) return null;
  if (!["U", "I", "P", "Q", "S", "PF", "F"].includes(measurement)) return null;
  if (!["GT", "GE", "LT", "LE"].includes(operator)) return null;
  if (!["LEVEL", "CROSSING"].includes(mode)) return null;
  if (threshold === null || recordingInterval === null || recordingInterval <= 0) return null;
  return Object.freeze({
    block,
    measurement,
    operator,
    threshold,
    mode,
    recording_interval_s: recordingInterval,
  });
}

function normalizeTrigger(record) {
  if (!record || typeof record.device_id !== "string" || !record.device_id) return null;
  if (!["ARMED", "DISARMED"].includes(record.state)) return null;
  const config = normalizeConfig(record.config);
  if (!config) return null;
  return Object.freeze({
    device_id: record.device_id,
    state: record.state,
    config,
    armed_utc: textValue(record.armed_utc),
    last_fired_cycle_id: integerNumber(record.last_fired_cycle_id),
    last_fired_utc: textValue(record.last_fired_utc),
    last_fired_value: finiteNumber(record.last_fired_value),
  });
}

export class RecordingTriggerState {
  constructor() {
    this._byDevice = new Map();
  }

  replace(records) {
    const next = new Map();
    for (const record of Array.isArray(records) ? records : []) {
      const normalized = normalizeTrigger(record);
      if (normalized) next.set(normalized.device_id, normalized);
    }
    this._byDevice = next;
  }

  forDevice(deviceId) {
    return this._byDevice.get(deviceId) ?? null;
  }
}
