import {
  connectLanQualification,
  disableLoadControl,
  disconnectLanQualification,
  enableLoadControl,
  getDiscoveredActuators,
  getLanQualificationStatus,
  getLoadControlStatus,
  getRecentLoadControlEvidence,
  scanLanActuators,
  setLoadControlBinding,
  setLoadControlLimits,
  setLoadControlTiming,
} from "./load-control-api.js";

const state = {
  status: null,
  qualification: null,
  visible: false,
  lanResults: [],
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
        <span class="eyebrow">STAGE 2 · REAL WEBSOCKET HELLO QUALIFICATION · CONTROL DISABLED</span>
        <h2>External Load Control</h2>
      </div>
      <button id="load-control-close" type="button">CLOSE</button>
    </div>
    <p class="load-control-stage-note">
      LAN discovery and WebSocket HELLO qualification are real. Real actuator COMMAND transport is not available in Stage 2, and real actuator control remains disabled. Existing mock-control development functions remain separate.
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
      <div class="load-control-section-header"><h3>Binding</h3><span>MOCK · DISABLED only</span></div>
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
      <div class="load-control-section-header"><h3>LAN actuator discovery</h3><span>read-only mDNS</span></div>
      <p class="load-control-section-note">
        This scan only locates compatible actuator advertisements. It does not change the mock control binding, enable external control, or open a WebSocket until you select an actuator explicitly.
      </p>
      <div class="load-control-form-grid">
        <label>Discovery window / s
          <input id="lc-lan-discovery-window" type="number" min="0" step="any" placeholder="required">
        </label>
        <label>Resolve timeout / s
          <input id="lc-lan-resolve-timeout" type="number" min="0" step="any" placeholder="required">
        </label>
      </div>
      <div class="load-control-actions"><button id="lc-scan-lan" type="button">SCAN LAN</button></div>
      <div id="lc-lan-scan-status" class="load-control-status-text" aria-live="polite"></div>
      <div id="lc-lan-results" class="load-control-lan-results">No LAN scan run.</div>
    </section>

    <section class="load-control-section load-control-qualification-section">
      <div class="load-control-section-header"><h3>Real WebSocket qualification</h3><span>HELLO only</span></div>
      <p class="load-control-section-note">
        Qualification uses the WebSocket locator from the latest LAN discovery result. The qualified actuator instance is node ID plus boot ID. IP address is only a locator.
      </p>
      <div class="load-control-value-grid load-control-qualification-grid">
        <div><span>Qualification</span><strong id="lc-qualification-state">IDLE</strong></div>
        <div><span>Node</span><strong id="lc-qualification-node">—</strong></div>
        <div><span>Boot</span><strong id="lc-qualification-boot">—</strong></div>
        <div><span>Protocol</span><strong id="lc-qualification-protocol">—</strong></div>
        <div><span>Device class</span><strong id="lc-qualification-class">—</strong></div>
        <div><span>Capability</span><strong id="lc-qualification-capability">—</strong></div>
        <div><span>Advertised test limit</span><strong id="lc-qualification-limits">—</strong></div>
        <div><span>WebSocket locator</span><strong id="lc-qualification-location">—</strong></div>
      </div>
      <div id="lc-qualification-error" class="load-control-status-text" aria-live="polite"></div>
      <div class="load-control-actions">
        <button id="lc-qualification-disconnect" type="button">DISCONNECT</button>
      </div>
    </section>

    <section class="load-control-section">
      <div class="load-control-section-header"><h3>Active-power target and limits</h3><span>MOCK · W</span></div>
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
      <div class="load-control-section-header"><h3>Volatile timing qualification</h3><span>MOCK · not persisted</span></div>
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
      <div class="load-control-section-header"><h3>Supervisor evidence</h3><span id="lc-session-id">MOCK · —</span></div>
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
  element("lc-scan-lan").addEventListener("click", runLanScan);
  element("lc-qualification-disconnect").addEventListener("click", runLanQualificationDisconnect);
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

function setLanMessage(message, isError = false) {
  const target = element("lc-lan-scan-status");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
}

function setInputIfIdle(id, value) {
  const input = element(id);
  if (!input || document.activeElement === input || value == null) return;
  input.value = String(value);
}

function positiveInputValue(id, label) {
  const value = Number(element(id)?.value);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label} must be finite and greater than 0 s.`);
  }
  return value;
}

function renderLanResults(values) {
  state.lanResults = Array.isArray(values) ? values : [];
  const target = element("lc-lan-results");
  if (!target) return;
  target.replaceChildren();

  if (!state.lanResults.length) {
    target.textContent = "No compatible LAN actuator advertisement was found in this scan.";
    return;
  }

  for (const item of state.lanResults) {
    const card = document.createElement("div");
    card.className = "load-control-lan-result";

    const identity = document.createElement("strong");
    identity.textContent = item.node_id || "UNKNOWN NODE";

    const location = document.createElement("span");
    location.textContent = item.location || "NO LOCATION";

    const details = document.createElement("span");
    const capabilities = Array.isArray(item.capabilities) ? item.capabilities.join(", ") : "—";
    details.textContent = `${item.device_class || "UNKNOWN CLASS"} · ${capabilities}`;

    const limits = document.createElement("span");
    limits.textContent = `Advertised test limit: ${powerTriplet(item.p_max)}`;

    const qualify = document.createElement("button");
    qualify.type = "button";
    qualify.className = "load-control-lan-qualify";
    qualify.textContent = "SELECT / QUALIFY";
    qualify.addEventListener("click", () => runLanQualification(item.node_id));

    card.append(identity, location, details, limits, qualify);
    target.append(card);
  }
}

function renderLanQualification(status) {
  state.qualification = status || null;

  const labels = [status?.state || "IDLE"];
  if (status?.connected) labels.push("CONNECTED");
  if (status?.hello_qualified) labels.push("HELLO QUALIFIED");
  element("lc-qualification-state").textContent = labels.join(" · ");
  element("lc-qualification-node").textContent = status?.node_id || status?.selected_node_id || "—";
  element("lc-qualification-boot").textContent = status?.boot_id || "—";
  element("lc-qualification-protocol").textContent = status?.protocol_version ?? "—";
  element("lc-qualification-class").textContent = status?.device_class || "—";
  element("lc-qualification-capability").textContent = Array.isArray(status?.capabilities)
    ? status.capabilities.join(", ") || "—"
    : "—";
  element("lc-qualification-limits").textContent = powerTriplet(status?.p_max);
  element("lc-qualification-location").textContent = status?.location || "—";

  const error = element("lc-qualification-error");
  error.textContent = status?.last_error || "";
  error.dataset.error = status?.last_error ? "true" : "false";

  const disconnect = element("lc-qualification-disconnect");
  disconnect.disabled = !status || status.state === "IDLE";
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

async function refreshLanQualification() {
  const status = await getLanQualificationStatus();
  renderLanQualification(status);
  return status;
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
    await refreshLanQualification();
    if (state.visible) await refreshEvidence();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function runLanScan() {
  const button = element("lc-scan-lan");
  try {
    const discoveryWindow = positiveInputValue("lc-lan-discovery-window", "Discovery window");
    const resolveTimeout = positiveInputValue("lc-lan-resolve-timeout", "Resolve timeout");
    if (button) button.disabled = true;
    setLanMessage("Scanning for _ari-emonio-load._tcp.local. advertisements...");
    const values = await scanLanActuators({
      discovery_window_s: discoveryWindow,
      resolve_timeout_s: resolveTimeout,
    });
    renderLanResults(values);
    setLanMessage(`LAN scan complete. ${values.length} compatible actuator advertisement(s) found.`);
  } catch (error) {
    setLanMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function runLanQualification(nodeId) {
  const errorTarget = element("lc-qualification-error");
  try {
    errorTarget.textContent = "Opening WebSocket and waiting for HELLO...";
    errorTarget.dataset.error = "false";
    renderLanQualification(await connectLanQualification(nodeId));
  } catch (error) {
    try {
      await refreshLanQualification();
    } catch (_refreshError) {
      // Keep the connection error as the operator evidence.
    }
    errorTarget.textContent = error.message;
    errorTarget.dataset.error = "true";
  }
}

async function runLanQualificationDisconnect() {
  const button = element("lc-qualification-disconnect");
  try {
    if (button) button.disabled = true;
    renderLanQualification(await disconnectLanQualification());
  } catch (error) {
    const target = element("lc-qualification-error");
    target.textContent = error.message;
    target.dataset.error = "true";
  } finally {
    if (button && state.qualification?.state !== "IDLE") button.disabled = false;
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
    setMessage("External control authority revoked. Safe 0/0/0 W requested for the mock actuator.");
    await refreshStatus();
  } catch (error) {
    setMessage(error.message, true);
  }
}

createUi();
refreshAll();
setInterval(() => {
  refreshStatus().catch(() => {});
  if (state.visible) refreshLanQualification().catch(() => {});
}, 1000);
