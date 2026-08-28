const ORDER = [
  "state",
  "sample_age_s",
  "cycles_total",
  "valid_cycles",
  "invalid_cycles",
  "timeouts",
  "protocol_errors",
  "decode_errors",
  "reconnects",
  "min_latency_ms",
  "mean_latency_ms",
  "p95_latency_ms",
  "max_latency_ms",
  "schedule_lag_ms",
];

function displayValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  return String(value);
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

export function renderDiagnosticsSummary(payload) {
  const state = payload?.state ? String(payload.state).toUpperCase() : "—";
  const validCycles = Number.isFinite(payload?.valid_cycles) ? Number(payload.valid_cycles) : 0;
  const errors = [payload?.invalid_cycles, payload?.timeouts, payload?.protocol_errors, payload?.decode_errors]
    .filter(Number.isFinite)
    .reduce((sum, value) => sum + Number(value), 0);
  setText("diagnostics-summary-state", state);
  setText("diagnostics-summary-cycles", `${validCycles} VALID`);
  setText("diagnostics-summary-errors", `${errors} ERRORS`);
}

export function renderDiagnostics(payload) {
  const target = document.getElementById("diagnostics-grid");
  target.replaceChildren();
  renderDiagnosticsSummary(payload ?? {});
  for (const key of ORDER) {
    const cell = document.createElement("div");
    cell.className = "diagnostic-cell";
    const term = document.createElement("dt");
    term.textContent = key.replaceAll("_", " ");
    const value = document.createElement("dd");
    value.textContent = displayValue(payload?.[key]);
    cell.append(term, value);
    target.appendChild(cell);
  }
}

export function renderDeviceList(devices) {
  const target = document.getElementById("device-list");
  if (!target) return;
  target.replaceChildren();
  for (const device of devices) {
    const entry = document.createElement("div");
    entry.className = "device-entry";
    entry.innerHTML = `<strong>${device.device_id}</strong><span class="state-${device.state}">${device.state}</span><span>${Number.isFinite(device.sample_age_s) ? `${device.sample_age_s.toFixed(2)} s` : "no sample"}</span>`;
    target.appendChild(entry);
  }
}
