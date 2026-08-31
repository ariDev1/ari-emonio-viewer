import { RecordingTriggerState } from "./recording-trigger.js";

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function integerNumber(value) {
  const number = finiteNumber(value);
  return Number.isInteger(number) ? number : null;
}

function textValue(value, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function normalizedRecord(record) {
  if (!record || typeof record.device_id !== "string" || !record.device_id) return null;
  return Object.freeze({
    device_id: record.device_id,
    device_name: typeof record.device_name === "string" && record.device_name ? record.device_name : record.device_id,
    state: textValue(record.state, "RECORDING") || "RECORDING",
    interval_s: finiteNumber(record.interval_s),
    acquisition_interval_s: finiteNumber(record.acquisition_interval_s),
    session_id: textValue(record.session_id),
    session_dir: textValue(record.session_dir),
    started_utc: textValue(record.started_utc),
    application_version: textValue(record.application_version),
    records_written: integerNumber(record.records_written),
    record_points_missed: integerNumber(record.record_points_missed),
    eligible_samples_seen: integerNumber(record.eligible_samples_seen),
    invalid_cycles_seen: integerNumber(record.invalid_cycles_seen),
    last_recorded_cycle_id: integerNumber(record.last_recorded_cycle_id),
    last_recorded_utc: textValue(record.last_recorded_utc),
    next_record_utc: textValue(record.next_record_utc),
  });
}

function normalizedError(record) {
  const base = normalizedRecord(record);
  if (!base) return null;
  return Object.freeze({
    ...base,
    state: "ERROR",
    failed_utc: textValue(record.failed_utc),
    failed_cycle_id: integerNumber(record.failed_cycle_id),
    error_type: typeof record.error_type === "string" && record.error_type ? record.error_type : "RecordingError",
    error_detail: typeof record.error_detail === "string" && record.error_detail ? record.error_detail : "recording failed",
  });
}

export class RecordingState {
  constructor() {
    this._active = new Map();
    this._errors = new Map();
    this._triggers = new RecordingTriggerState();
  }

  replaceActive(records) {
    const next = new Map();
    for (const record of Array.isArray(records) ? records : []) {
      const normalized = normalizedRecord(record);
      if (normalized) next.set(normalized.device_id, normalized);
    }
    this._active = next;
  }

  replaceStatus(activeRecords, errorRecords, triggerRecords = []) {
    this.replaceActive(activeRecords);
    const errors = new Map();
    for (const record of Array.isArray(errorRecords) ? errorRecords : []) {
      const normalized = normalizedError(record);
      if (normalized && !this._active.has(normalized.device_id)) {
        errors.set(normalized.device_id, normalized);
      }
    }
    this._errors = errors;
    this._triggers.replace(triggerRecords);
  }

  forDevice(deviceId) {
    return this._active.get(deviceId) ?? null;
  }

  errorForDevice(deviceId) {
    return this._errors.get(deviceId) ?? null;
  }

  triggerForDevice(deviceId) {
    return this._triggers.forDevice(deviceId);
  }

  isActive(deviceId) {
    return this._active.has(deviceId);
  }

  activeDeviceIds() {
    return [...this._active.keys()].sort();
  }

  activeRecordings() {
    return this.activeDeviceIds().map((deviceId) => this._active.get(deviceId));
  }

  recordingErrors() {
    return [...this._errors.keys()].sort().map((deviceId) => this._errors.get(deviceId));
  }

  summary() {
    const active = this.activeRecordings();
    return Object.freeze({
      active: active.length,
      errors: this._errors.size,
      records_written: active.reduce((sum, record) => sum + (record.records_written ?? 0), 0),
      record_points_missed: active.reduce(
        (sum, record) => sum + (record.record_points_missed ?? 0),
        0
      ),
    });
  }
}
