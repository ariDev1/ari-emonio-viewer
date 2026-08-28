function normalizedRecord(record) {
  if (!record || typeof record.device_id !== "string" || !record.device_id) return null;
  return Object.freeze({
    device_id: record.device_id,
    device_name: typeof record.device_name === "string" && record.device_name ? record.device_name : record.device_id,
    interval_s: Number.isFinite(Number(record.interval_s)) ? Number(record.interval_s) : null,
    session_dir: typeof record.session_dir === "string" ? record.session_dir : "",
    started_utc: typeof record.started_utc === "string" ? record.started_utc : "",
  });
}

export class RecordingState {
  constructor() {
    this._active = new Map();
  }

  replaceActive(records) {
    const next = new Map();
    for (const record of Array.isArray(records) ? records : []) {
      const normalized = normalizedRecord(record);
      if (normalized) next.set(normalized.device_id, normalized);
    }
    this._active = next;
  }

  forDevice(deviceId) {
    return this._active.get(deviceId) ?? null;
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
}
