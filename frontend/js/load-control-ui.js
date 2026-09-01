import {
  disableLoadControl,
  enableLoadControl,
  getDiscoveredActuators,
  getLoadControlStatus,
  getRecentLoadControlEvidence,
  setLoadControlBinding,
  setLoadControlLimits,
  setLoadControlTiming,
} from "./load-control-api.js";

const state = {
  status: null,
  visible: false,
};

function element(id) {
  return document.getElementById(id);
}

function formatPower(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(1)} W`;
}

function powerTriplet(value) {
  if (!value) return "—";
  return `A ${formatPower(value.a)} · B ${formatPower(value.b)} · C ${formatPower(value.c)}`;
}

function createUi() {
  const controls = document.querySelector(".utility-status-controls");
  if (!controls || element("load-control-toggle")) return;

  const toggle = document.createElement("button");
  toggle.id = "load-control-toggle";
  toggle.className = "utility-status-button load-control-toggle";
  toggle.type = "button";
  toggle.setAttribute("aria-controls", "load-control-panel");
  toggle.setAttribute("aria-expanded", "false");
  toggle.innerHTML = `
    <span class="utility-status-label">LOAD CTRL</span>
    <strong id="load-control-summary-mode">DISABLED</strong>
    <span id="load-control-summary-session">UNBOUND</span>
    <span id="load-control-summary-safe">SAFE UNCONFIRMED</span>
  `;
  controls.append(toggle);

  const panel = document.createElement("aside");
  panel.id = "load-control-panel";
  panel.className = "load-control-panel";
  panel.hidden = true;
  panel.setAttribute("aria-label", "External load control");
  panel.innerHTML = `
    <div class="load-control-panel-header">
      <div>
        <span class="eyebrow">STAGE 1 · MOCK ACTUATOR ONLY</span>
        <h2>External Load Control</h2>
      </div>
      <button id="load-control-close" type="button">CLOSE</button>
    </div>
    <p class="load-control-stage-note">
      Viewer supervisory test mode. No mDNS, real WebSocket actuator, ESP32, PWM, or physical power-stage output is active.
    </p>

    <section class="load-control-state-grid" aria-label="Load control state">
      <div><span>Control</span><strong id="lc-mode">DISABLED</strong></div>
      <div><span>Session</span><strong id="lc-session">UNBOUND</strong></div>
      <div><span>Safe state</span><strong id="lc-safe">SAFE_UNCONFIRMED</strong></div>
      <div><span>Trip</span><strong id="lc-trip">—</strong></div>
      <div><span>Source cycle</span><strong id="lc-cycle">—</strong></div>
      <div><span>Evidence</span><strong id="lc-evidence-health">—</strong></div>
    </section>

    <section class="load-control-section">
      <div class="load-control-section-header"><h3>Binding</h3><span>DISABLED only</span></div>
      <div class="load-control-form-grid">
        <label>Emonio control source
          <input id="lc-source" type="text" autocomplete="off" spellcheck="false" placeholder="emonio device id">
        </label>
        <label>Mock actuator
          <select id="lc-actuator"></select>
        </label>
      </div>
      <div class="load-control-actions"><button id="lc-save-binding" type="button">SAVE BINDING</button></div>
    </section>

    <section class="load-control-section">
      <div class="load-control-section-header"><h3>Active-power target and limits</h3><span>W</span></div>
      <div class="load-control-form-grid">
        <label>Import reserve per phase
          <input id="lc-reserve" type="number" min="0" step="any" placeholder="required">
        </label>
        <label>Phase A operator max
          <input id="lc-limit-a" type="number" min="0" step="any" placeholder="required">
        </label>
        <label>Phase B operator max
          <input id="lc-limit-b" type="number" min="0" step="any" placeholder="required">
        </label>
        <label>Phase C operator max
          <input id="lc-limit-c" type="number" min="0" step="any" placeholder="required">
        </label>
      </div>
      <div class="load-control-actions"><button id="lc-save-limits" type="button">SAVE TARGET / LIMITS</button></div>
    </section>

    <section class="load-control-section">
      <div class="load-control-section-header"><h3>Volatile timing qualification</h3><span>not persisted</span></div>
      <div class="load-control-form-grid">
        <label>Maximum sample age / s
          <input id="lc-sample-age-limit" type="number" min="0" step="any" placeholder="required each start">
        </label>
        <label>ACK timeout / s
          <input id="lc-ack-timeout" type="number" min="0" step="any" placeholder="required each start">
        </label>
      </div>
      <div class="load-control-actions"><button id="lc-save-timing" type="button">SET SESSION TIMING</button></div>
    </section>

    <section class="load-control-section">
      <div class="load-control-section-header"><h3>Supervisor evidence</h3><span id="lc-session-id">—</span></div>
      <div class="load-control-value-grid">
        <div><span>Acknowledged load</span><strong id="lc-ack-p">—</strong></div>
        <div><span>Outstanding command</span><strong id="lc-outstanding">—</strong></div>
        <div><span>Actuator boot</span><strong id="lc-boot">—</strong></div>
        <div><span>Sample age</span><strong id="lc-sample-age">—</strong></div>
      </div>
      <div class="load-control-actions">
        <button id="lc-enable" type="button">ENABLE EXTERNAL CONTROL</button>
        <button id="lc-disable" type="button">DISABLE</button>
        <button id="lc-refresh-evidence" type="button">REFRESH EVIDENCE</button>
      </div>
      <div id="lc-message" class="load-control-status-text" aria-live="polite"></div>
      <pre id="lc-evidence" class="load-control-evidence">No control evidence loaded.</pre>
    </section>
  `;
  document.body.append(panel);

  toggle.addEventListener("click", () => setVisible(!state.visible));
  element("load-control-close").addEventListener("click", () => setVisible(false));
  element("lc-save-binding").addEventListener("click", saveBinding);
  element("lc-save-limits").addEventListener("click", saveLimits);
  element("lc-save-timing").addEventListener("click", saveTiming);
  element("lc-enable").addEventListener("click", runEnable);
  element("lc-disable").addEventListener("click", runDisable);
  element("lc-refresh-evidence").addEventListener("click", refreshEvidence);
}

function setVisible(visible) {
  state.visible = visible;
  const panel = element("load-control-panel");
  const toggle = element("load-control-toggle");
  if (panel) panel.hidden = !visible;
  if (toggle) toggle.setAttribute("aria-expanded", String(visible));
  if (visible) {
    refreshAll();
  }
}

function setMessage(message, isError = false) {
  const target = element("lc-message");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
}

function setInputIfIdle(id, value) {
  const input = element(id);
  if (!input || document.activeElement === input || value == null) return;
  input.value = String(value);
}

function renderStatus(status) {
  state.status = status;
  const mode = status.control_mode || "DISABLED";
  const session = status.session_state || "UNBOUND";
  const safe = status.safe_state || "SAFE_UNCONFIRMED";
  const toggle = element("load-control-toggle");
  if (toggle) toggle.dataset.controlMode = mode;
  element("load-control-summary-mode").textContent = mode;
  element("load-control-summary-session").textContent = session;
  element("load-control-summary-safe").textContent = safe.replaceAll("_", " ");
  element("lc-mode").textContent = mode;
  element("lc-session").textContent = session;
  element("lc-safe").textContent = safe;
  element("lc-trip").textContent = status.trip_reason || "—";
  element("lc-cycle").textContent = status.last_source_cycle_id ?? "—";
  element("lc-evidence-health").textContent = status.evidence_healthy ? "HEALTHY" : `FAULT: ${status.evidence_error || "UNKNOWN"}`;
  element("lc-session-id").textContent = status.viewer_session_id || "—";
  element("lc-ack-p").textContent = powerTriplet(status.acknowledged_p);
  element("lc-outstanding").textContent = status.outstanding_sequence ?? "—";
  element("lc-boot").textContent = status.actuator_boot_id || "—";
  element("lc-sample-age").textContent = Number.isFinite(status.last_sample_age_s) ? `${Number(status.last_sample_age_s).toFixed(3)} s` : "—";

  const config = status.config || {};
  setInputIfIdle("lc-source", config.bound_emonio_device_id);
  setInputIfIdle("lc-reserve", config.p_reserve);
  setInputIfIdle("lc-limit-a", config.operator_limit_a);
  setInputIfIdle("lc-limit-b", config.operator_limit_b);
  setInputIfIdle("lc-limit-c", config.operator_limit_c);
  if (status.timing) {
    setInputIfIdle("lc-sample-age-limit", status.timing.control_sample_max_age_s);
    setInputIfIdle("lc-ack-timeout", status.timing.ack_timeout_s);
  }

  const locked = mode !== "DISABLED";
  for (const id of ["lc-source", "lc-actuator", "lc-reserve", "lc-limit-a", "lc-limit-b", "lc-limit-c", "lc-sample-age-limit", "lc-ack-timeout", "lc-save-binding", "lc-save-limits", "lc-save-timing"]) {
    const node = element(id);
    if (node) node.disabled = locked;
  }
  element("lc-enable").disabled = mode === "ENABLED";
  element("lc-disable").disabled = mode === "DISABLED";
}

async function refreshStatus() {
  const status = await getLoadControlStatus();
  renderStatus(status);
  return status;
}

async function refreshActuators() {
  const values = await getDiscoveredActuators();
  const select = element("lc-actuator");
  if (!select) return;
  const selected = state.status?.config?.bound_actuator_node_id || select.value;
  select.replaceChildren();
  for (const item of values) {
    const option = document.createElement("option");
    option.value = item.node_id;
    option.textContent = `${item.node_id} · ${item.device_class}`;
    select.append(option);
  }
  if (selected && values.some((item) => item.node_id === selected)) select.value = selected;
}

async function refreshEvidence() {
  try {
    const rows = await getRecentLoadControlEvidence(20);
    element("lc-evidence").textContent = rows.length
      ? rows.map((row) => JSON.stringify(row)).join("\n")
      : "No control evidence recorded.";
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function refreshAll() {
  try {
    await refreshStatus();
    await refreshActuators();
    if (state.visible) await refreshEvidence();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function saveBinding() {
  try {
    const sourceInput = element("lc-source");
    const activeSelector = element("device-selector");
    const source = sourceInput.value || activeSelector?.value || "";
    const actuator = element("lc-actuator").value;
    await setLoadControlBinding(source, actuator);
    setMessage("Binding saved. Control remains DISABLED.");
    await refreshAll();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function saveLimits() {
  try {
    await setLoadControlLimits({
      p_reserve: Number(element("lc-reserve").value),
      operator_limit_a: Number(element("lc-limit-a").value),
      operator_limit_b: Number(element("lc-limit-b").value),
      operator_limit_c: Number(element("lc-limit-c").value),
    });
    setMessage("Target and operator limits saved. Control remains DISABLED.");
    await refreshStatus();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function saveTiming() {
  try {
    await setLoadControlTiming({
      control_sample_max_age_s: Number(element("lc-sample-age-limit").value),
      ack_timeout_s: Number(element("lc-ack-timeout").value),
    });
    setMessage("Volatile timing qualification set for this Viewer session.");
    await refreshStatus();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function runEnable() {
  try {
    await enableLoadControl();
    setMessage("External control ENABLED for the deterministic mock actuator.");
    await refreshStatus();
  } catch (error) {
    setMessage(`Enable rejected: ${error.message}`, true);
    await refreshStatus();
  }
}

async function runDisable() {
  try {
    await disableLoadControl();
    setMessage("External control authority revoked. Safe 0/0/0 W requested.");
    await refreshStatus();
  } catch (error) {
    setMessage(error.message, true);
  }
}

createUi();
refreshAll();
setInterval(() => refreshStatus().catch(() => {}), 1000);
