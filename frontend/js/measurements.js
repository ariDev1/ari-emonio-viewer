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

const POWER_DIRECTION_PHASES = [
  ["A", "phase_a", "power-direction-a"],
  ["B", "phase_b", "power-direction-b"],
  ["C", "phase_c", "power-direction-c"],
];

export function powerDirectionState(value) {
  if (!Number.isFinite(value) || value === 0) return "neutral";
  return value < 0 ? "negative" : "positive";
}

function powerDirectionAriaLabel(phase, state) {
  if (state === "negative") return `Phase ${phase} active power is negative`;
  if (state === "positive") return `Phase ${phase} active power is positive`;
  return `Phase ${phase} active power is zero or unavailable`;
}

export function initializePowerDirectionIndicators() {
  if (typeof document === "undefined") return;
  const title = document.querySelector(".status-title .eyebrow");
  if (!title || document.getElementById("power-direction-a")) return;

  const group = document.createElement("span");
  group.className = "power-direction-indicators";
  group.setAttribute("aria-label", "Canonical active power direction by phase");

  for (const [phase, _field, id] of POWER_DIRECTION_PHASES) {
    const indicator = document.createElement("span");
    indicator.id = id;
    indicator.className = "power-direction-indicator is-neutral";
    indicator.dataset.phase = phase;
    indicator.setAttribute("aria-label", powerDirectionAriaLabel(phase, "neutral"));
    indicator.title = `Phase ${phase} canonical P direction`;
    group.appendChild(indicator);
  }

  title.insertAdjacentElement("afterend", group);
}

function renderPowerDirectionIndicators(sample) {
  for (const [phase, field, id] of POWER_DIRECTION_PHASES) {
    const node = document.getElementById(id);
    if (!node) continue;
    const state = powerDirectionState(sample?.[field]?.p);
    node.classList.remove("is-neutral", "is-negative", "is-positive");
    node.classList.add(`is-${state}`);
    node.setAttribute("aria-label", powerDirectionAriaLabel(phase, state));
  }
}

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
  initializePowerDirectionIndicators();
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
    element.textContent = field === "flow" || field === "quadrant" ? String(value ?? "—") : formatField(field, value);
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
  renderPowerDirectionIndicators(payload.sample);

  document.getElementById("device-name").textContent = payload.device_name || payload.device_id;
  document.getElementById("device-ip").textContent = payload.device_ip || "—";
  document.getElementById("transport-state").textContent = payload.transport || "—";
  document.getElementById("device-state").textContent = payload.state || "—";
  if (typeof payload.acquisition_state === "string" && payload.acquisition_state) {
    document.getElementById("acquisition-state").textContent = payload.acquisition_state;
  }
  document.getElementById("quality-state").textContent = payload.quality || "—";
  document.getElementById("sample-age").textContent = Number.isFinite(payload.sample_age_s) ? `${payload.sample_age_s.toFixed(2)} s` : "—";
  document.getElementById("firmware-version").textContent = payload.firmware_version || "—";
}

export function renderBackendStatus(device) {
  if (!device) return;
  document.getElementById("device-state").textContent = device.state || "—";
  if (typeof device.acquisition_state === "string" && device.acquisition_state) {
    document.getElementById("acquisition-state").textContent = device.acquisition_state;
  }
  document.getElementById("quality-state").textContent = device.quality || "NO SAMPLE";
  document.getElementById("sample-age").textContent = Number.isFinite(device.sample_age_s) ? `${device.sample_age_s.toFixed(2)} s` : "—";
}
