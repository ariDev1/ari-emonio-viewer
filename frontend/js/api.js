async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${detail || response.statusText}`);
  }
  return response.json();
}

export function getDevices() {
  return requestJson("/api/v1/devices");
}

export function getDevice(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}`);
}

export function getDiagnostics(deviceId) {
  return requestJson(`/api/v1/diagnostics/${encodeURIComponent(deviceId)}`);
}

export function getRuntimeConfig() {
  return requestJson("/api/v1/config/runtime");
}

export function getCtConfiguration(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/ct-config`);
}

export async function readCtConfiguration(deviceId, password) {
  const response = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/ct-config/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    let detail = null;
    try {
      detail = await response.json();
    } catch (_error) {
      detail = null;
    }
    const error = new Error(detail?.message ?? `${response.status} ${response.statusText}`);
    error.ctStatus = detail?.status ?? "READ_ERROR";
    error.ctStage = detail?.stage ?? "READ";
    throw error;
  }
  return response.json();
}

export function connectDevice(target) {
  return requestJson("/api/v1/devices/connect", {
    method: "POST",
    body: JSON.stringify({ target }),
  });
}

export function getRecordingStatus() {
  return requestJson("/api/v1/recording/status");
}

export function startRecording(deviceId, intervalS, sessionNote) {
  return requestJson("/api/v1/recording/start", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, interval_s: intervalS, session_note: sessionNote }),
  });
}

export function stopRecording(deviceId) {
  return requestJson("/api/v1/recording/stop", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId }),
  });
}

export function changeRecordingInterval(deviceId, intervalS) {
  return requestJson("/api/v1/recording/interval", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, interval_s: intervalS }),
  });
}

export function getScopeStatus(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/scope`);
}

export function startScope(deviceId, username, password) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/scope/start`, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function holdScope(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/scope/hold`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function liveScope(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/scope/live`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function stopScope(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/scope/stop`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getModbusEvidence(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/modbus-evidence`);
}

export function readModbusEvidence(deviceId) {
  return requestJson(`/api/v1/devices/${encodeURIComponent(deviceId)}/modbus-evidence/read`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
