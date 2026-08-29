import { getModbusEvidence, readModbusEvidence } from "./api.js";

const ENERGY_PHASES = ["A", "B", "C", "TOTAL"];
const CONNECTED_PHASES = ["A", "B", "C"];
let renderedDeviceId = null;

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setState(text, kind = "") {
  const node = document.getElementById("modbus-evidence-state");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("observed", kind === "observed");
  node.classList.toggle("partial", kind === "partial");
  node.classList.toggle("error", kind === "error");
}

function setMessage(text = "", error = false) {
  const node = document.getElementById("modbus-evidence-message");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", error);
}

function formatNumber(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(6).replace(/0+$/, "").replace(/\.$/, "") : "—";
}

function formatElapsedMs(value) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(3)} ms` : "—";
}

function energyNode(phase, field) {
  return document.querySelector(
    `[data-modbus-energy-phase="${phase}"] [data-modbus-energy-field="${field}"]`
  );
}

function connectedNode(phase) {
  return document.querySelector(`[data-modbus-connected-phase="${phase}"]`);
}

function appendProbeCell(row, value, className = "") {
  const cell = document.createElement("span");
  cell.textContent = value;
  if (className) cell.className = className;
  row.appendChild(cell);
}

function renderProbeDiagnostics(diagnostics) {
  const grid = document.getElementById("modbus-evidence-probe-grid");
  if (!grid) return;
  grid.replaceChildren();
  for (const item of Array.isArray(diagnostics) ? diagnostics : []) {
    const status = ["OK", "ERROR", "SKIPPED"].includes(item?.status)
      ? item.status
      : "ERROR";
    const row = document.createElement("div");
    row.className = `modbus-probe-row ${status.toLowerCase()}`;
    const functionCode = Number.isInteger(item?.function_code)
      ? `FC${String(item.function_code).padStart(2, "0")}`
      : "—";
    const detail = status === "OK"
      ? "—"
      : [item?.error_type, item?.error_detail].filter(Boolean).join(": ") || status;
    appendProbeCell(row, item?.key ?? "—");
    appendProbeCell(row, functionCode);
    appendProbeCell(row, Number.isInteger(item?.address) ? String(item.address) : "—");
    appendProbeCell(row, Number.isInteger(item?.count) ? String(item.count) : "—");
    appendProbeCell(row, status, "modbus-probe-result");
    appendProbeCell(row, formatElapsedMs(item?.elapsed_ms));
    appendProbeCell(row, detail, "modbus-probe-detail");
    grid.appendChild(row);
  }
}

function clearEvidence() {
  setText("modbus-evidence-source", "—");
  setText("modbus-evidence-observed", "—");
  for (const phase of ENERGY_PHASES) {
    const input = energyNode(phase, "kwh_in");
    const output = energyNode(phase, "kwh_out");
    if (input) input.textContent = "—";
    if (output) output.textContent = "—";
  }
  for (const phase of CONNECTED_PHASES) {
    const node = connectedNode(phase);
    if (node) node.textContent = "—";
  }
  setText("modbus-error-raw", "—");
  setText("modbus-warning-raw", "—");
  setText("modbus-error-flags", "—");
  setText("modbus-warning-flags", "—");
  renderProbeDiagnostics([]);
}

function renderFlags(id, flags) {
  if (flags === null || flags === undefined) {
    setText(id, "—");
  } else if (Array.isArray(flags) && flags.length) {
    setText(id, flags.join(" · "));
  } else if (Array.isArray(flags)) {
    setText(id, "NONE");
  } else {
    setText(id, "—");
  }
}

function renderReadState(readStatus, diagnostics) {
  const items = Array.isArray(diagnostics) ? diagnostics : [];
  const failedCount = items.filter((item) => item?.status === "ERROR").length;
  const skippedCount = items.filter((item) => item?.status === "SKIPPED").length;
  const okCount = items.filter((item) => item?.status === "OK").length;
  const summary = `${failedCount} failed · ${skippedCount} skipped · ${okCount} OK. Review probe diagnostics.`;
  if (readStatus === "PARTIAL") {
    setState("MODBUS EVIDENCE: PARTIAL", "partial");
    setMessage(summary, false);
  } else if (readStatus === "FAILED") {
    setState("MODBUS EVIDENCE: FAILED", "error");
    setMessage(summary, true);
  } else {
    setState("MODBUS EVIDENCE: OBSERVED", "observed");
    setMessage("");
  }
}

export function renderModbusEvidence(payload) {
  const deviceId = payload?.device_id ?? null;
  const evidence = payload?.evidence ?? null;
  renderedDeviceId = deviceId;
  if (!evidence) {
    clearEvidence();
    setState("MODBUS EVIDENCE: NOT READ");
    setMessage("");
    return;
  }

  const values = evidence.values ?? {};
  const diagnostics = values.read_diagnostics ?? [];
  const readStatus = evidence.read_status ?? payload?.status ?? "OBSERVED";
  renderReadState(readStatus, diagnostics);
  setText("modbus-evidence-source", evidence.source ?? "—");
  setText("modbus-evidence-observed", evidence.observed_utc ?? "—");

  for (const phase of ENERGY_PHASES) {
    const phaseValues = values.energy?.[phase] ?? null;
    const input = energyNode(phase, "kwh_in");
    const output = energyNode(phase, "kwh_out");
    if (input) input.textContent = formatNumber(phaseValues?.kwh_in);
    if (output) output.textContent = formatNumber(phaseValues?.kwh_out);
  }
  for (const phase of CONNECTED_PHASES) {
    const node = connectedNode(phase);
    if (node) {
      const value = values.connected?.[phase];
      node.textContent = value === true ? "1" : value === false ? "0" : "—";
    }
  }

  setText("modbus-error-raw", Number.isInteger(values.error_raw) ? String(values.error_raw) : "—");
  setText("modbus-warning-raw", Number.isInteger(values.warning_raw) ? String(values.warning_raw) : "—");
  renderFlags("modbus-error-flags", values.error_flags);
  renderFlags("modbus-warning-flags", values.warning_flags);
  renderProbeDiagnostics(diagnostics);
}

export async function refreshModbusEvidence(deviceId) {
  if (!deviceId) return false;
  if (renderedDeviceId !== deviceId) {
    renderModbusEvidence({ device_id: deviceId, status: "NOT_READ", evidence: null });
  }
  try {
    renderModbusEvidence(await getModbusEvidence(deviceId));
    return true;
  } catch (error) {
    if (renderedDeviceId !== deviceId) clearEvidence();
    setState("MODBUS EVIDENCE: READ ERROR", "error");
    setMessage(`Evidence status failed: ${error.message}`, true);
    return false;
  }
}

export function initializeModbusEvidenceControls(selectedDeviceReader) {
  const button = document.getElementById("modbus-evidence-read");
  if (!button) return;
  button.addEventListener("click", async () => {
    const deviceId = selectedDeviceReader();
    if (!deviceId) return;
    button.disabled = true;
    setMessage("Reading documented Modbus device evidence…");
    try {
      renderModbusEvidence(await readModbusEvidence(deviceId));
    } catch (error) {
      setState("MODBUS EVIDENCE: READ ERROR", "error");
      setMessage(`Evidence read failed: ${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  });
}
