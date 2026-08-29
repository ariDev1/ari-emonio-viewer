const MEASUREMENT_DECIMALS = 4;

const PANEL_FIELDS = [
  ["U", "vrms", "V"],
  ["I", "irms", "A"],
  ["P", "p", "W"],
  ["Q", "q", "var"],
  ["S", "s", "VA"],
  ["PF", "pf", ""],
  ["f", "frequency", "Hz"],
  ["E", "energy", "kWh"],
];

function createMeasurementRows(panel) {
  const target = panel.querySelector("[data-measurements]");
  if (target.childElementCount > 0) return;
  for (const [label, field, unit] of PANEL_FIELDS) {
    const row = document.createElement("div");
    row.className = "measurement-row";
    row.innerHTML = `<span class="measurement-label">${label}</span><strong class="measurement-value" data-field="${field}">—</strong><span class="measurement-unit">${unit}</span>`;
    target.appendChild(row);
  }
  for (const [label, field] of [["FLOW", "flow"], ["QUADRANT", "quadrant"]]) {
    const row = document.createElement("div");
    row.className = "measurement-row state-row";
    row.innerHTML = `<span class="measurement-label">${label}</span><strong class="measurement-value" data-field="${field}">—</strong>`;
    target.appendChild(row);
  }
}

export function initializeMeasurementPanels() {
  document.querySelectorAll(".phase-panel").forEach(createMeasurementRows);
}

function fixed(value, digits) {
  return Number.isFinite(value) ? value.toFixed(digits) : "INVALID";
}

function fixedMeasurement(value) {
  return Number.isFinite(value) ? value.toFixed(MEASUREMENT_DECIMALS) : "INVALID";
}

function signed(value, digits) {
  if (!Number.isFinite(value)) return "INVALID";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(digits)}`;
}

function formatField(field, value) {
  if (field === "p" || field === "q") return signed(value, MEASUREMENT_DECIMALS);
  if (["vrms", "irms", "s", "pf", "frequency", "energy"].includes(field)) {
    return fixedMeasurement(value);
  }
  return String(value ?? "—");
}

function renderBlock(panelId, block) {
  const panel = document.getElementById(panelId);
  if (!panel || !block) return;
  panel.querySelectorAll("[data-field]").forEach((element) => {
    const field = element.dataset.field;
    const value = block[field];
    if (field === "flow") {
      const flowLabels = {
        POSITIVE_FLOW: "POSITIVE_ACTIVE_POWER",
        NEGATIVE_FLOW: "NEGATIVE_ACTIVE_POWER",
        ZERO_ACTIVE_POWER: "ZERO_ACTIVE_POWER",
      };

      element.textContent = flowLabels[value] ?? String(value ?? "—");
    } else if (field === "quadrant") {
      element.textContent = String(value ?? "—");
    } else {
      element.textContent = formatField(field, value);
    }
    element.classList.toggle("signed-positive", (field === "p" || field === "q") && Number(value) > 0);
    element.classList.toggle("signed-negative", (field === "p" || field === "q") && Number(value) < 0);
  });
}

function renderDerived(derived) {
  if (!derived) return;
  const fields = {
    "derived-sum-p": [derived.sum_p, "W"],
    "derived-delta-p": [derived.delta_p, "W"],
    "derived-sum-q": [derived.sum_q, "var"],
    "derived-delta-q": [derived.delta_q, "var"],
    "derived-sum-s": [derived.sum_s, "VA"],
    "derived-delta-s": [derived.delta_s, "VA"],
  };
  for (const [id, [value, unit]] of Object.entries(fields)) {
    const node = document.getElementById(id);
    node.textContent = `${fixed(value, MEASUREMENT_DECIMALS)} ${unit}`;
  }
}

export function renderMeasurementPayload(payload) {
  renderBlock("phase-a", payload.sample.phase_a);
  renderBlock("phase-b", payload.sample.phase_b);
  renderBlock("phase-c", payload.sample.phase_c);
  renderBlock("phase-total", payload.sample.total);
  renderDerived(payload.sample.derived);

  document.getElementById("device-name").textContent = payload.device_name || payload.device_id;
  document.getElementById("device-ip").textContent = payload.device_ip || "—";
  document.getElementById("transport-state").textContent = payload.transport || "—";
  document.getElementById("device-state").textContent = payload.state || "—";
  document.getElementById("quality-state").textContent = payload.quality || "—";
  document.getElementById("sample-age").textContent = Number.isFinite(payload.sample_age_s) ? `${payload.sample_age_s.toFixed(2)} s` : "—";
  document.getElementById("firmware-version").textContent = payload.firmware_version || "—";
}

export function renderBackendStatus(device) {
  if (!device) return;
  document.getElementById("device-state").textContent = device.state || "—";
  document.getElementById("quality-state").textContent = device.quality || "NO SAMPLE";
  document.getElementById("sample-age").textContent = Number.isFinite(device.sample_age_s) ? `${device.sample_age_s.toFixed(2)} s` : "—";
}
