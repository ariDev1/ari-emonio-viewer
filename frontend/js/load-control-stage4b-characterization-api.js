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

export function getCharacterizationStatus() {
  return requestJson("/api/v1/load-control/characterization/status");
}

export function captureCurrentDuty(selection) {
  return requestJson("/api/v1/load-control/characterization/manual-capture", {
    method: "POST",
    body: JSON.stringify(selection),
  });
}

export function runExplicitSweep(settings) {
  return requestJson("/api/v1/load-control/characterization/auto-sweep", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}
