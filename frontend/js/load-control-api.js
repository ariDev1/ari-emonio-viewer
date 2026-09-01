async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      payload = text;
    }
  }
  if (!response.ok) {
    const message = typeof payload === "string" ? payload : JSON.stringify(payload);
    throw new Error(message || `HTTP ${response.status}`);
  }
  return payload;
}

export function getLoadControlStatus() {
  return requestJson("/api/v1/load-control/status");
}

export function getDiscoveredActuators() {
  return requestJson("/api/v1/load-control/discovered-actuators");
}

export function scanLanActuators(values) {
  return requestJson("/api/v1/load-control/lan-discovery/scan", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function connectLanQualification(nodeId) {
  return requestJson("/api/v1/load-control/lan-qualification/connect", {
    method: "POST",
    body: JSON.stringify({ node_id: nodeId }),
  });
}

export function getLanQualificationStatus() {
  return requestJson("/api/v1/load-control/lan-qualification/status");
}

export function disconnectLanQualification() {
  return requestJson("/api/v1/load-control/lan-qualification/disconnect", {
    method: "POST",
    body: "{}",
  });
}

export function getLanDiagnosticLog(afterSequence = 0, limit = 200) {
  return requestJson(
    `/api/v1/load-control/lan-diagnostics/log?after=${encodeURIComponent(afterSequence)}&limit=${encodeURIComponent(limit)}`,
  );
}

export function getSafeTestSources() {
  return requestJson("/api/v1/load-control/lan-safe-test/sources");
}

export function getSafeTestStatus() {
  return requestJson("/api/v1/load-control/lan-safe-test/status");
}

export function selectSafeTestSource(emonioDeviceId) {
  return requestJson("/api/v1/load-control/lan-safe-test/source", {
    method: "POST",
    body: JSON.stringify({ emonio_device_id: emonioDeviceId }),
  });
}

export function runSafeCommandTest() {
  return requestJson("/api/v1/load-control/lan-safe-test/send", {
    method: "POST",
    body: "{}",
  });
}

export function getRecentLoadControlEvidence(limit = 20) {
  return requestJson(`/api/v1/load-control/evidence/recent?limit=${encodeURIComponent(limit)}`);
}

export function setLoadControlBinding(emonioDeviceId, actuatorNodeId) {
  return requestJson("/api/v1/load-control/binding", {
    method: "POST",
    body: JSON.stringify({
      emonio_device_id: emonioDeviceId,
      actuator_node_id: actuatorNodeId,
    }),
  });
}

export function setLoadControlLimits(values) {
  return requestJson("/api/v1/load-control/config", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function setLoadControlTiming(values) {
  return requestJson("/api/v1/load-control/timing", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function enableLoadControl() {
  return requestJson("/api/v1/load-control/enable", {
    method: "POST",
    body: "{}",
  });
}

export function disableLoadControl() {
  return requestJson("/api/v1/load-control/disable", {
    method: "POST",
    body: "{}",
  });
}
