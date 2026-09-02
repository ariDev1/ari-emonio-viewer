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

export function getZeroExportStatus() {
  return requestJson("/api/v1/load-control/zero-export/status");
}

export function configureZeroExport(settings) {
  return requestJson("/api/v1/load-control/zero-export/configure", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function enableZeroExport() {
  return requestJson("/api/v1/load-control/zero-export/enable", {
    method: "POST",
    body: "{}",
  });
}

export function disableZeroExport() {
  return requestJson("/api/v1/load-control/zero-export/disable", {
    method: "POST",
    body: "{}",
  });
}
