import { getSafeTestSources } from "./load-control-api.js";
import {
  configureZeroExport,
  disableZeroExport,
  enableZeroExport,
  getZeroExportStatus,
} from "./load-control-stage4c-api.js";

const REFRESH_MS = 750;

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

function setText(id, value) {
  const node = element(id);
  if (node) node.textContent = value;
}

function formatPower(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(6)} W`;
}

function formatDuty(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(6)} %`;
}

function formatSequence(value) {
  return Number.isInteger(Number(value)) ? String(Number(value)) : "—";
}

function configurationReady() {
  const source = element("lc-zec-source")?.value || "";
  const phase = element("lc-zec-phase")?.value || "";
  const deadbandText = element("lc-zec-deadband")?.value ?? "";
  if (!source || !["A", "B", "C"].includes(phase) || deadbandText === "") return false;
  const deadband = Number(deadbandText);
  return Number.isFinite(deadband) && deadband >= 0;
}

function readConfiguration() {
  if (!configurationReady()) {
    throw new Error("Select one Emonio source, one phase, and a non-negative P deadband.");
  }
  return {
    source_id: element("lc-zec-source").value,
    phase: element("lc-zec-phase").value,
    p_deadband_w: Number(element("lc-zec-deadband").value),
  };
}

function configurationMatchesStatus() {
  if (!configurationReady() || !state.status) return false;
  const settings = readConfiguration();
  return state.status.source_id === settings.source_id
    && state.status.phase === settings.phase
    && Number(state.status.p_deadband_w) === settings.p_deadband_w;
}

function renderSources() {
  const select = element("lc-zec-source");
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

function renderSafeState(status) {
  if (status?.state === "SAFE_UNCONFIRMED") return "SAFE_UNCONFIRMED";
  if (status?.safe_confirmed === true) return "CONFIRMED OFF";
  if (status?.confirmed_requested_duty_percent != null
      && Number(status.confirmed_requested_duty_percent) > 0) {
    return "ACTIVE DUTY";
  }
  return status?.safe_confirmed === false ? "OFF NOT CONFIRMED" : "—";
}

function renderStatus(status) {
  state.status = status || { state: "DISABLED" };
  const mode = state.status.state || "DISABLED";
  const disabled = mode === "DISABLED";

  setText("lc-zec-state", mode);
  setText("lc-zec-reason", state.status.reason || "—");
  setText("lc-zec-cycle", state.status.sample_cycle_id == null ? "—" : String(state.status.sample_cycle_id));
  setText("lc-zec-p", formatPower(state.status.measured_p_w));
  setText("lc-zec-quality", state.status.sample_quality || "—");
  setText("lc-zec-action", state.status.action || "—");
  setText("lc-zec-confirmed-requested", formatDuty(state.status.confirmed_requested_duty_percent));
  setText("lc-zec-confirmed-actual", formatDuty(state.status.confirmed_actual_duty_percent));
  setText("lc-zec-lower", formatDuty(state.status.lower_bracket_duty_percent));
  setText("lc-zec-upper", formatDuty(state.status.upper_bracket_duty_percent));
  setText("lc-zec-node", state.status.actuator_node_id || "—");
  setText("lc-zec-boot", state.status.actuator_boot_id || "—");
  setText("lc-zec-sequence", formatSequence(state.status.command_sequence));
  setText("lc-zec-safe", renderSafeState(state.status));

  const inputLocked = !disabled || state.busy;
  for (const id of ("lc-zec-source", "lc-zec-phase", "lc-zec-deadband")) {
    const input = element(id);
    if (input) input.disabled = inputLocked;
  }

  const configure = element("lc-zec-configure");
  const enable = element("lc-zec-enable");
  const disable = element("lc-zec-disable");
  if (configure) configure.disabled = !disabled || state.busy || !configurationReady();
  if (enable) enable.disabled = !disabled || state.busy || !configurationMatchesStatus();
  if (disable) disable.disabled = disabled || state.busy;

  const section = document.querySelector(".load-control-zero-export");
  if (section) section.dataset.state = mode;
}

function renderMessage(message) {
  setText("lc-zec-message", message || "");
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
    renderStatus(await getZeroExportStatus());
  } catch (error) {
    renderMessage(`Zero-export status unavailable: ${error.message}`);
  }
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
  if (!slot || element("lc-zec-state")) return;

  const section = document.createElement("section");
  section.className = "load-control-section load-control-primary-section load-control-zero-export";
  section.dataset.state = "DISABLED";
  section.innerHTML = `
    <div class="load-control-section-header">
      <h3>Zero-Export Controller</h3>
      <span>Stage 4C · automatic physical control</span>
    </div>
    <p class="load-control-section-note load-control-zero-export-boundary">
      Automatic physical PWM control is active when enabled. Canonical signed P is the only feedback input. Target is fixed at 0 W. No watts-to-duty calibration, Duty step, Q or PF control, PID, or automatic reconnect is used. The qualified PWM range is OFF 0 % and active 25–75 %. A control fault requests one explicit OFF. If OFF cannot be confirmed, the state is SAFE_UNCONFIRMED.
    </p>
    <div class="load-control-zero-export-config">
      <label>Emonio source
        <select id="lc-zec-source"><option value="">Choose Emonio source</option></select>
      </label>
      <label>Phase
        <select id="lc-zec-phase">
          <option value="">Choose phase</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
      </label>
      <label>P deadband / W
        <input id="lc-zec-deadband" type="number" min="0" step="any" value="2">
      </label>
    </div>
    <div class="load-control-actions load-control-zero-export-actions">
      <button id="lc-zec-configure" type="button" disabled>SAVE ZERO-EXPORT CONFIG</button>
      <button id="lc-zec-enable" type="button" disabled>ENABLE AUTOMATIC CONTROL</button>
      <button id="lc-zec-disable" type="button" disabled>DISABLE + OFF</button>
    </div>
    <div class="load-control-zero-export-status" aria-label="Zero-export control evidence">
      <div><span>State</span><strong id="lc-zec-state">DISABLED</strong></div>
      <div><span>Reason</span><strong id="lc-zec-reason">—</strong></div>
      <div><span>Measurement cycle</span><strong id="lc-zec-cycle">—</strong></div>
      <div><span>Canonical P</span><strong id="lc-zec-p">—</strong></div>
      <div><span>Sample quality</span><strong id="lc-zec-quality">—</strong></div>
      <div><span>Control action</span><strong id="lc-zec-action">—</strong></div>
      <div><span>Confirmed requested duty</span><strong id="lc-zec-confirmed-requested">—</strong></div>
      <div><span>Confirmed actual duty</span><strong id="lc-zec-confirmed-actual">—</strong></div>
      <div><span>Negative-P bracket</span><strong id="lc-zec-lower">—</strong></div>
      <div><span>Positive-P bracket</span><strong id="lc-zec-upper">—</strong></div>
      <div><span>Actuator node</span><strong id="lc-zec-node">—</strong></div>
      <div><span>Actuator boot</span><strong id="lc-zec-boot">—</strong></div>
      <div><span>Command sequence</span><strong id="lc-zec-sequence">—</strong></div>
      <div class="load-control-zero-export-safe"><span>OFF evidence</span><strong id="lc-zec-safe">—</strong></div>
    </div>
    <div id="lc-zec-message" class="load-control-status-text" aria-live="polite"></div>
  `;

  const observer = slot.querySelector(".load-control-p-observer");
  if (observer) slot.insertBefore(section, observer);
  else slot.prepend(section);

  const updateControls = () => renderStatus(state.status || { state: "DISABLED" });
  element("lc-zec-source").addEventListener("change", updateControls);
  element("lc-zec-phase").addEventListener("change", updateControls);
  element("lc-zec-deadband").addEventListener("input", updateControls);

  element("lc-zec-configure").addEventListener("click", () => runAction(
    () => configureZeroExport(readConfiguration()),
    "Zero-export configuration saved. No active load command was sent.",
  ));
  element("lc-zec-enable").addEventListener("click", () => runAction(
    enableZeroExport,
    "Automatic control enabled. The controller first requires acknowledged OFF, then fresh canonical P evidence.",
  ));
  element("lc-zec-disable").addEventListener("click", () => runAction(
    disableZeroExport,
    "Automatic control disabled. Check OFF evidence before disconnecting the actuator.",
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
