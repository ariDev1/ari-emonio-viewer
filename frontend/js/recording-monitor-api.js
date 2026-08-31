async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = (await response.text()).trim();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export function getRecordingStatus() {
  return requestJson("/api/v1/recording/status");
}

export function getRuntimeConfig() {
  return requestJson("/api/v1/config/runtime");
}

export function configureRecordingMonitor(deviceId, config) {
  return requestJson("/api/v1/recording/monitor/configure", {
    method: "POST",
    body: JSON.stringify({device_id: deviceId, ...config}),
  });
}

export function enableRecordingMonitor(deviceId) {
  return requestJson("/api/v1/recording/monitor/enable", {
    method: "POST",
    body: JSON.stringify({device_id: deviceId}),
  });
}

export function disableRecordingMonitor(deviceId) {
  return requestJson("/api/v1/recording/monitor/disable", {
    method: "POST",
    body: JSON.stringify({device_id: deviceId}),
  });
}
