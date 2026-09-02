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

export function getSimulatedTestStatus() {
  return requestJson("/api/v1/load-control/lan-simulated-test/status");
}

export function runSimulatedCommandTest() {
  return requestJson("/api/v1/load-control/lan-simulated-test/send", {
    method: "POST",
    body: "{}",
  });
}
