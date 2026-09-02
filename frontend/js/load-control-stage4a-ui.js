import { getSafeTestSources } from "./load-control-api.js";
import {
  configurePObserver,
  disablePObserver,
  enablePObserver,
  getPObserverStatus,
} from "./load-control-stage4a-api.js";

const REFRESH_MS = 1000;

const state = {
  status: null,
  sources: [],
  timer: null,
  busy: false,
};

function element(id) {
  return document.getElementById(id);
}

function panelVisible() {
  const panel = element("load-control-panel");
  return Boolean(panel && !panel.hidden);
}

function formatPower(value, unit) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(3)} ${unit}`;
}

function formatAge(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(3)} s`;
}

function formatDuty(value) {
  const text = value == null ? "—" : `${Number(value).toFixed(6)} %`;
  if (value != null && Number(value) === 0) return "0.000000 %";
  return Number.isFinite(Number(value)) ? text : "—";
}

function setText(id, value) {
  const node = element(id);
  if (node) node.textContent = value;
}

function configInputs() {
  return [
    element("lc-pobs-source"),
    element("lc-pobs-phase"),
    element("lc-pobs-target"),
    element("lc-pobs-deadband"),
    element("lc-pobs-step"),
  ].filter(Boolean);
}

function configurationReady() {
  const source = element("lc-pobs-source")?.value || "";
  const phase = element("lc-pobs-phase")?.value || "";
  const targetText = element("lc-pobs-target")?.value ?? "";
  const deadbandText = element("lc-pobs-deadband")?.value ?? "";
  const stepText = element("lc-pobs-step")?.value ?? "";
  if (!source || !["A", "B", "C"].includes(phase)) return false;
  if (targetText === "" || deadbandText === "" || stepText === "") return false;
  const target = Number(targetText);
  const deadband = Number(deadbandText);
  const step = Number(stepText);
  return Number.isFinite(target) && Number.isFinite(deadband) && Number.isFinite(step)
    && deadband >= 0 && step > 0;
}

function renderStatus(status) {
  state.status = status;
  const mode = status?.state || "DISABLED";
  const disabled = mode !== "DISABLED";

  setText("lc-pobs-state", mode);
  setText("lc-pobs-reason", status?.reason || "—");
  setText("lc-pobs-cycle", status?.sample_cycle_id == null ? "—" : String(status.sample_cycle_id));
  setText("lc-pobs-p", formatPower(status?.measured_p_w, "W"));
  setText("lc-pobs-q", formatPower(status?.measured_q_var, "var"));
  setText("lc-pobs-quality", status?.sample_quality || "—");
  setText("lc-pobs-age", formatAge(status?.sample_age_s));
  setText("lc-pobs-confirmed-requested", formatDuty(status?.confirmed_requested_duty_percent));
  setText("lc-pobs-confirmed-actual", formatDuty(status?.confirmed_actual_duty_percent));
  setText("lc-pobs-decision", status?.decision || "—");
  setText("lc-pobs-proposed", formatDuty(status?.proposed_duty_percent));

  for (const input of configInputs()) input.disabled = disabled || state.busy;
  const save = element("lc-pobs-configure");
  const enable = element("lc-pobs-enable");
  const disable = element("lc-pobs-disable");
  if (save) save.disabled = disabled || state.busy || !configurationReady();
  if (enable) enable.disabled = disabled || state.busy || !configurationReady();
  if (disable) disable.disabled = !disabled || state.busy;

  const section = document.querySelector(".load-control-p-observer");
  if (section) section.dataset.state = mode;
}

function renderMessage(message) {
  setText("lc-pobs-message", message || "");
}

function renderSources() {
  const select = element("lc-pobs-source");
  if (!select) return;
  const selected = select.value;
  select.innerHTML = '<option value="">Choose Emonio source</option>';
  for (const source of state.sources) {
    if (!source || typeof source.device_id !== "string" || !source.device_id) continue;
    const option = document.createElement("option");
    option.value = source.device_id;
    option.textContent = source.name ? `${source.name} · ${source.device_id}` : source.device_id;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

async function refreshSources() {
  try {
    const payload = await getSafeTestSources();
    state.sources = Array.isArray(payload) ? payload : [];
    renderSources();
  } catch (error) {
    state.sources = [];
    renderSources();
    renderMessage(`Source list unavailable: ${error.message}`);
  }
}

async function refreshStatus() {
  if (!panelVisible()) return;
  try {
    renderStatus(await getPObserverStatus());
  } catch (error) {
    renderMessage(`Observer status unavailable: ${error.message}`);
  }
}

function readSettings() {
  if (!configurationReady()) throw new Error("Enter a valid source, phase, target, deadband, and duty step.");
  return {
    source_id: element("lc-pobs-source").value,
    phase: element("lc-pobs-phase").value,
    p_target_w: Number(element("lc-pobs-target").value),
    p_deadband_w: Number(element("lc-pobs-deadband").value),
    duty_step_percent: Number(element("lc-pobs-step").value),
  };
}

async function runAction(action, successMessage) {
  if (state.busy) return;
  state.busy = true;
  renderStatus(state.status || { state: "DISABLED" });
  renderMessage("");
  try {
    const status = await action();
    renderStatus(status);
    renderMessage(successMessage);
  } catch (error) {
    renderMessage(error.message);
    await refreshStatus();
  } finally {
    state.busy = false;
    renderStatus(state.status || { state: "DISABLED" });
  }
}

function createUi() {
  const slot = element("lc-simulated-operator-slot");
  if (!slot || element("lc-pobs-state")) return;

  const section = document.createElement("section");
  section.className = "load-control-section load-control-primary-section load-control-p-observer";
  section.dataset.state = "DISABLED";
  section.innerHTML = `
    <div class="load-control-section-header"><h3>P Control Observer</h3><span>Stage 4A · observation only</span></div>
    <p class="load-control-section-note load-control-p-observer-boundary">
      P is the only control variable. Q is display-only. No automatic PWM command is sent. Apply a proposal manually with the existing manual PWM control if you want to test it.
    </p>
    <div class="load-control-p-observer-config">
      <label>Emonio source
        <select id="lc-pobs-source"><option value="">Choose Emonio source</option></select>
      </label>
      <label>Phase
        <select id="lc-pobs-phase">
          <option value="">Choose phase</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
      </label>
      <label>P target / W
        <input id="lc-pobs-target" type="number" step="any" placeholder="required">
      </label>
      <label>P deadband / W
        <input id="lc-pobs-deadband" type="number" min="0" step="any" placeholder="required">
      </label>
      <label>Duty step / %
        <input id="lc-pobs-step" type="number" min="0" step="any" placeholder="required">
      </label>
    </div>
    <div class="load-control-actions load-control-p-observer-actions">
      <button id="lc-pobs-configure" type="button" disabled>SAVE OBSERVER CONFIG</button>
      <button id="lc-pobs-enable" type="button" disabled>ENABLE OBSERVER</button>
      <button id="lc-pobs-disable" type="button" disabled>DISABLE OBSERVER</button>
    </div>
    <div class="load-control-p-observer-status" aria-label="P control observer evidence">
      <div><span>State</span><strong id="lc-pobs-state">DISABLED</strong></div>
      <div><span>Reason</span><strong id="lc-pobs-reason">—</strong></div>
      <div><span>Measurement cycle</span><strong id="lc-pobs-cycle">—</strong></div>
      <div><span>Measured P</span><strong id="lc-pobs-p">—</strong></div>
      <div><span>Measured Q · display-only</span><strong id="lc-pobs-q">—</strong></div>
      <div><span>Sample quality</span><strong id="lc-pobs-quality">—</strong></div>
      <div><span>Sample age</span><strong id="lc-pobs-age">—</strong></div>
      <div><span>Confirmed requested duty</span><strong id="lc-pobs-confirmed-requested">—</strong></div>
      <div><span>Confirmed actual duty</span><strong id="lc-pobs-confirmed-actual">—</strong></div>
      <div><span>Decision</span><strong id="lc-pobs-decision">—</strong></div>
      <div class="load-control-p-observer-proposal"><span>Proposed duty</span><strong id="lc-pobs-proposed">—</strong></div>
    </div>
    <div id="lc-pobs-message" class="load-control-status-text" aria-live="polite"></div>
  `;

  const simulated = slot.querySelector(".load-control-simulated-test-section");
  if (simulated) slot.insertBefore(section, simulated);
  else slot.append(section);

  for (const input of configInputs()) input.addEventListener("input", () => renderStatus(state.status || { state: "DISABLED" }));
  element("lc-pobs-configure").addEventListener("click", () => runAction(
    () => configurePObserver(readSettings()),
    "Observer configuration saved. No PWM command was sent.",
  ));
  element("lc-pobs-enable").addEventListener("click", () => runAction(
    enablePObserver,
    "Observer enabled. Waiting for canonical measurement evidence.",
  ));
  element("lc-pobs-disable").addEventListener("click", () => runAction(
    disablePObserver,
    "Observer disabled. Physical PWM output was not changed.",
  ));

  renderStatus({ state: "DISABLED" });
}

function startRefreshLoop() {
  if (state.timer != null) return;
  state.timer = window.setInterval(() => {
    if (panelVisible()) refreshStatus();
  }, REFRESH_MS);
}

async function initialize() {
  createUi();
  await refreshSources();
  if (panelVisible()) await refreshStatus();
  startRefreshLoop();

  const panel = element("load-control-panel");
  if (panel) {
    const observer = new MutationObserver(() => {
      if (panelVisible()) {
        refreshSources();
        refreshStatus();
      }
    });
    observer.observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize, { once: true });
} else {
  initialize();
}
