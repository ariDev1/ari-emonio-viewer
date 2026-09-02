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

export function getPObserverStatus() {
  return requestJson("/api/v1/load-control/p-observer/status");
}

export function configurePObserver(settings) {
  return requestJson("/api/v1/load-control/p-observer/configure", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function enablePObserver() {
  return requestJson("/api/v1/load-control/p-observer/enable", {
    method: "POST",
    body: "{}",
  });
}

export function disablePObserver() {
  return requestJson("/api/v1/load-control/p-observer/disable", {
    method: "POST",
    body: "{}",
  });
}

export function getPObserverDiagnostics(afterSequence = 0) {
  return requestJson(
    `/api/v1/load-control/p-observer/diagnostics?after_sequence=${encodeURIComponent(afterSequence)}`,
  );
}
