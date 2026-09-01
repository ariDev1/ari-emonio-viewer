import {
  connectLanQualification,
  disableLoadControl,
  disconnectLanQualification,
  enableLoadControl,
  getDiscoveredActuators,
  getLanDiagnosticLog,
  getLanQualificationStatus,
  getLoadControlStatus,
  getRecentLoadControlEvidence,
  getSafeTestSources,
  getSafeTestStatus,
  runSafeCommandTest,
  scanLanActuators,
  selectSafeTestSource,
  setLoadControlBinding,
  setLoadControlLimits,
  setLoadControlTiming,
} from "./load-control-api.js";

const state = {
  status: null,
  qualification: null,
  safeStatus: null,
  safeSources: [],
  visible: false,
  lanResults: [],
  selectedNodeId: "",
  diagnosticAfterSequence: 0,
  diagnosticLines: [],
};

const SAFE_ACTIVE_STATES = new Set([
  "WAITING_FOR_SAMPLE",
  "COMMAND_SENT",
  "WAITING_FOR_ACK",
]);

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
    <strong id="load-control-summary-mode">REAL DISABLED</strong>
    <span id="load-control-summary-session">IDLE</span>
    <span id="load-control-summary-safe">HELLO NOT QUALIFIED</span>
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
        <span class="eyebrow">STAGE 3A · SAFE COMMAND QUALIFICATION</span>
        <h2>External Load Control</h2>
      </div>
      <div class="load-control-header-actions">
        <strong class="load-control-real-disabled">REAL CONTROL DISABLED</strong>
        <button id="load-control-close" type="button">CLOSE</button>
      </div>
    </div>
    <p class="load-control-stage-note">
      Stage 2 qualifies the real actuator connection. Stage 3A can then send one explicit SAFE zero-output protocol COMMAND and qualify its ACK. Real load control remains disabled.
    </p>

    <section class="load-control-section load-control-primary-section">
      <div class="load-control-section-header"><h3>Actuator connection</h3><span>real LAN</span></div>
      <p class="load-control-section-note">
        SCAN LAN is read-only. A scan never selects, connects, binds, or enables an actuator.
      </p>
      <div class="load-control-connection-controls">
        <label>Discovery window / s
          <input id="lc-lan-discovery-window" type="number" min="0" step="any" value="5">
        </label>
        <label>Resolve timeout / s
          <input id="lc-lan-resolve-timeout" type="number" min="0" step="any" value="5">
        </label>
      </div>
      <div class="load-control-actions">
        <button id="lc-scan-lan" type="button">SCAN LAN</button>
      </div>
      <div id="lc-lan-scan-status" class="load-control-status-text" aria-live="polite">No LAN scan run.</div>
      <label class="load-control-real-actuator-label">Discovered actuator
        <select id="lc-real-actuator">
          <option value="">Choose discovered actuator</option>
        </select>
      </label>
      <div id="lc-selected-actuator" class="load-control-real-actuator-summary">No actuator selected.</div>
      <div class="load-control-actions">
        <button id="lc-select-qualify" type="button" disabled>CONNECT / QUALIFY</button>
      </div>
    </section>

    <section class="load-control-section load-control-primary-section load-control-qualification-section">
      <div class="load-control-section-header"><h3>Qualification</h3><span>HELLO only</span></div>
      <div class="load-control-primary-status" aria-label="Real actuator qualification state">
        <div><span>WebSocket</span><strong id="lc-ws-state">DISCONNECTED</strong></div>
        <div><span>HELLO</span><strong id="lc-hello-state">NOT QUALIFIED</strong></div>
      </div>
      <div class="load-control-qualification-evidence">
        <div><span>Actuator instance</span><strong id="lc-qualification-identity">—</strong></div>
        <div><span>Protocol / class / capability</span><strong id="lc-qualification-protocol">—</strong></div>
        <div><span>Advertised test limit</span><strong id="lc-qualification-limits">—</strong></div>
        <div><span>WebSocket locator</span><strong id="lc-qualification-location">—</strong></div>
      </div>
      <div id="lc-qualification-error" class="load-control-status-text" aria-live="polite"></div>
      <div class="load-control-actions">
        <button id="lc-qualification-disconnect" type="button" disabled>DISCONNECT</button>
      </div>
    </section>

    <section class="load-control-section load-control-primary-section load-control-safe-test-section">
      <div class="load-control-section-header"><h3>SAFE command qualification</h3><span>one real COMMAND</span></div>
      <p class="load-control-section-note load-control-safe-warning">
        This test sends exactly one real protocol COMMAND only after explicit operator action: control_enabled=false · P request A/B/C = 0 W · Q request A/B/C = 0 var · No retry · No nonzero control.
      </p>
      <label class="load-control-safe-source-label">Emonio measurement source
        <select id="lc-safe-source">
          <option value="">Choose Emonio source</option>
        </select>
      </label>
      <div class="load-control-actions">
        <button id="lc-safe-select-source" type="button" disabled>SELECT SOURCE</button>
      </div>
      <div class="load-control-safe-status" aria-label="SAFE command qualification state">
        <div><span>SAFE test</span><strong id="lc-safe-state">IDLE</strong></div>
        <div><span>Selected source</span><strong id="lc-safe-source-state">—</strong></div>
        <div><span>Sample cycle</span><strong id="lc-safe-cycle">—</strong></div>
        <div><span>COMMAND sequence</span><strong id="lc-safe-sequence">—</strong></div>
        <div><span>ACK result</span><strong id="lc-safe-ack">—</strong></div>
        <div><span>Rejection</span><strong id="lc-safe-rejection">—</strong></div>
      </div>
      <div class="load-control-actions">
        <button id="lc-safe-run" type="button" disabled>RUN SAFE 0 W TEST</button>
      </div>
      <div id="lc-safe-message" class="load-control-status-text" aria-live="polite">
        Select an Emonio source explicitly. The SAFE test remains disabled until the actuator HELLO is qualified.
      </div>
    </section>

    <section class="load-control-section load-control-primary-section load-control-diagnostic-section">
      <div class="load-control-section-header"><h3>Diagnostic log</h3><span>real actuator only</span></div>
      <p class="load-control-section-note">
        This backend-owned log contains real LAN discovery, WebSocket/HELLO, and SAFE command qualification events. CLEAR VIEW does not delete the backend log.
      </p>
      <pre id="lc-diagnostic-log" class="load-control-diagnostic-log">No real actuator diagnostic events yet.</pre>
      <div class="load-control-actions">
        <button id="lc-copy-diagnostic-log" type="button">COPY LOG</button>
        <button id="lc-clear-diagnostic-view" type="button">CLEAR VIEW</button>
      </div>
      <div id="lc-diagnostic-status" class="load-control-status-text" aria-live="polite"></div>
    </section>

    <details id="lc-development-tools" class="load-control-development-tools">
      <summary>DEVELOPMENT / MOCK CONTROL</summary>
      <p class="load-control-section-note">
        These controls belong to the deterministic Stage-1 mock path. They do not control the real LAN actuator.
      </p>

      <section class="load-control-state-grid" aria-label="Mock load control state">
        <div><span>Mock control</span><strong id="lc-mode">DISABLED</strong></div>
        <div><span>Mock session</span><strong id="lc-session">UNBOUND</strong></div>
        <div><span>Safe state</span><strong id="lc-safe">SAFE_UNCONFIRMED</strong></div>
        <div><span>Trip</span><strong id="lc-trip">—</strong></div>
        <div><span>Source cycle</span><strong id="lc-cycle">—</strong></div>
        <div><span>Evidence</span><strong id="lc-evidence-health">—</strong></div>
      </section>

      <section class="load-control-section">
        <div class="load-control-section-header"><h3>Mock binding</h3><span>DISABLED only</span></div>
        <div class="load-control-form-grid">
          <label>Emonio control source
            <input id="lc-source" type="text" autocomplete="off" spellcheck="false" placeholder="emonio device id">
          </label>
          <label>Mock actuator
            <select id="lc-actuator"></select>
          </label>
        </div>
        <div class="load-control-actions"><button id="lc-save-binding" type="button">SAVE MOCK BINDING</button></div>
      </section>

      <section class="load-control-section">
        <div class="load-control-section-header"><h3>Mock active-power target and limits</h3><span>W</span></div>
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
        <div class="load-control-actions"><button id="lc-save-limits" type="button">SAVE MOCK TARGET / LIMITS</button></div>
      </section>

      <section class="load-control-section">
        <div class="load-control-section-header"><h3>Mock volatile timing qualification</h3><span>not persisted</span></div>
        <div class="load-control-form-grid">
          <label>Maximum sample age / s
            <input id="lc-sample-age-limit" type="number" min="0" step="any" placeholder="required each start">
          </label>
          <label>ACK timeout / s
            <input id="lc-ack-timeout" type="number" min="0" step="any" placeholder="required each start">
          </label>
        </div>
        <div class="load-control-actions"><button id="lc-save-timing" type="button">SET MOCK SESSION TIMING</button></div>
      </section>

      <section class="load-control-section">
        <div class="load-control-section-header"><h3>Mock supervisor evidence</h3><span id="lc-session-id">—</span></div>
        <div class="load-control-value-grid">
          <div><span>Acknowledged load</span><strong id="lc-ack-p">—</strong></div>
          <div><span>Outstanding command</span><strong id="lc-outstanding">—</strong></div>
          <div><span>Actuator boot</span><strong id="lc-boot">—</strong></div>
          <div><span>Sample age</span><strong id="lc-sample-age">—</strong></div>
        </div>
        <div class="load-control-actions">
          <button id="lc-enable" type="button">ENABLE MOCK CONTROL</button>
          <button id="lc-disable" type="button">DISABLE MOCK CONTROL</button>
          <button id="lc-refresh-evidence" type="button">REFRESH MOCK EVIDENCE</button>
        </div>
        <div id="lc-message" class="load-control-status-text" aria-live="polite"></div>
        <pre id="lc-evidence" class="load-control-evidence">No mock control evidence loaded.</pre>
      </section>
    </details>
  `;
  document.body.append(panel);

  toggle.addEventListener("click", () => setVisible(!state.visible));
  element("load-control-close").addEventListener("click", () => setVisible(false));
  element("lc-scan-lan").addEventListener("click", runLanScan);
  element("lc-real-actuator").addEventListener("change", onRealActuatorSelection);
  element("lc-select-qualify").addEventListener("click", runSelectedLanQualification);
  element("lc-qualification-disconnect").addEventListener("click", runLanQualificationDisconnect);
  element("lc-safe-select-source").addEventListener("click", selectSafeSource);
  element("lc-safe-run").addEventListener("click", runSafeTest);
  element("lc-copy-diagnostic-log").addEventListener("click", copyDiagnosticLog);
  element("lc-clear-diagnostic-view").addEventListener("click", clearDiagnosticView);
  element("lc-development-tools").addEventListener("toggle", onDevelopmentToolsToggle);
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
  if (visible) refreshPrimary().catch(() => {});
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

function setSafeMessage(message, isError = false) {
  const target = element("lc-safe-message");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
}

function setDiagnosticMessage(message, isError = false) {
  const target = element("lc-diagnostic-status");
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

function selectedDescriptor() {
  return state.lanResults.find((item) => item.node_id === state.selectedNodeId) || null;
}

function renderSelectedActuator() {
  const target = element("lc-selected-actuator");
  const item = selectedDescriptor();
  if (!target) return;
  if (!item) {
    target.textContent = "No actuator selected.";
    return;
  }
  const capabilities = Array.isArray(item.capabilities) ? item.capabilities.join(", ") : "—";
  target.textContent = [
    `Node: ${item.node_id}`,
    `WebSocket: ${item.location}`,
    `${item.device_class} · ${capabilities}`,
    `Advertised test limit: ${powerTriplet(item.p_max)}`,
  ].join("\n");
}

function updateQualifyButton() {
  const button = element("lc-select-qualify");
  if (!button) return;
  button.disabled = !state.selectedNodeId || Boolean(state.qualification?.connected);
}

function renderLanResults(values) {
  state.lanResults = Array.isArray(values) ? values : [];
  const select = element("lc-real-actuator");
  if (!select) return;

  const previousSelection = state.selectedNodeId;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose discovered actuator";
  select.append(placeholder);

  for (const item of state.lanResults) {
    const option = document.createElement("option");
    option.value = item.node_id;
    option.textContent = `${item.node_id} · ${item.device_class}`;
    select.append(option);
  }

  if (previousSelection && state.lanResults.some((item) => item.node_id === previousSelection)) {
    state.selectedNodeId = previousSelection;
    select.value = previousSelection;
  } else {
    state.selectedNodeId = "";
    select.value = "";
  }
  renderSelectedActuator();
  updateQualifyButton();
}

function onRealActuatorSelection() {
  state.selectedNodeId = element("lc-real-actuator")?.value || "";
  renderSelectedActuator();
  updateQualifyButton();
}

function renderLanQualification(status) {
  state.qualification = status || null;
  const connected = Boolean(status?.connected);
  const qualified = Boolean(status?.hello_qualified);

  element("lc-ws-state").textContent = connected ? "CONNECTED" : "DISCONNECTED";
  element("lc-hello-state").textContent = qualified
    ? "QUALIFIED"
    : status?.state === "REJECTED"
      ? "REJECTED"
      : "NOT QUALIFIED";

  const nodeId = status?.node_id || status?.selected_node_id || "";
  const bootId = status?.boot_id || "";
  element("lc-qualification-identity").textContent = nodeId
    ? bootId
      ? `${nodeId} · ${bootId}`
      : nodeId
    : "—";

  const capabilities = Array.isArray(status?.capabilities) ? status.capabilities.join(", ") : "";
  element("lc-qualification-protocol").textContent = status?.protocol_version != null
    ? `${status.protocol_version} · ${status.device_class || "—"} · ${capabilities || "—"}`
    : "—";
  element("lc-qualification-limits").textContent = powerTriplet(status?.p_max);
  element("lc-qualification-location").textContent = status?.location || "—";

  const error = element("lc-qualification-error");
  error.textContent = status?.last_error || "";
  error.dataset.error = status?.last_error ? "true" : "false";

  element("lc-qualification-disconnect").disabled = !connected;
  element("load-control-summary-session").textContent = status?.state || "IDLE";
  element("load-control-summary-safe").textContent = qualified ? "HELLO QUALIFIED" : "HELLO NOT QUALIFIED";
  updateQualifyButton();
  updateSafeButtons();
}

function renderSafeSources(values) {
  state.safeSources = Array.isArray(values) ? values : [];
  const select = element("lc-safe-source");
  if (!select) return;

  const previous = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose Emonio source";
  select.append(placeholder);

  for (const item of state.safeSources) {
    const option = document.createElement("option");
    option.value = item.device_id;
    const interval = Number.isFinite(Number(item.poll_interval_s))
      ? ` · ${Number(item.poll_interval_s).toFixed(3)} s`
      : "";
    option.textContent = `${item.name || item.device_id} · ${item.device_id}${interval}`;
    select.append(option);
  }

  if (previous && state.safeSources.some((item) => item.device_id === previous)) {
    select.value = previous;
  } else {
    select.value = "";
  }
  updateSafeButtons();
}

function renderSafeStatus(status) {
  state.safeStatus = status || null;
  const safeState = status?.state || "IDLE";
  element("lc-safe-state").textContent = safeState;
  element("lc-safe-source-state").textContent = status?.selected_source_id || "—";
  element("lc-safe-cycle").textContent = status?.sample_cycle_id ?? "—";
  element("lc-safe-sequence").textContent = status?.command_sequence ?? "—";
  element("lc-safe-ack").textContent = status?.ack_result || "—";
  element("lc-safe-rejection").textContent = status?.rejection_reason || "—";
  updateSafeButtons();
}

function updateSafeButtons() {
  const select = element("lc-safe-source");
  const selectButton = element("lc-safe-select-source");
  const runButton = element("lc-safe-run");
  if (!selectButton || !runButton) return;

  const active = SAFE_ACTIVE_STATES.has(state.safeStatus?.state);
  selectButton.disabled = !select?.value || active;
  runButton.disabled = !Boolean(state.safeStatus?.admissible)
    || !Boolean(state.qualification?.hello_qualified)
    || active;
}

async function refreshSafeSources() {
  renderSafeSources(await getSafeTestSources());
}

async function refreshSafeTestStatus() {
  const status = await getSafeTestStatus();
  renderSafeStatus(status);
  return status;
}

async function selectSafeSource() {
  const deviceId = element("lc-safe-source")?.value || "";
  if (!deviceId) {
    setSafeMessage("Choose one Emonio source first.", true);
    return;
  }

  const button = element("lc-safe-select-source");
  try {
    if (button) button.disabled = true;
    setSafeMessage("Selecting volatile Emonio source. No COMMAND is sent.");
    renderSafeStatus(await selectSafeTestSource(deviceId));
    setSafeMessage("Emonio source selected for this Viewer session. No COMMAND was sent.");
  } catch (error) {
    setSafeMessage(error.message, true);
    await refreshSafeTestStatus().catch(() => {});
  } finally {
    updateSafeButtons();
    await refreshDiagnosticLog().catch(() => {});
  }
}

async function runSafeTest() {
  const button = element("lc-safe-run");
  try {
    if (button) button.disabled = true;
    setSafeMessage("Waiting for the first valid post-request Emonio sample, then sending one SAFE 0 W COMMAND...");
    const status = await runSafeCommandTest();
    renderSafeStatus(status);
    if (status?.state === "PASSED") {
      setSafeMessage(`SAFE test PASSED. ACK ${status.ack_result || "—"}; sequence ${status.command_sequence ?? "—"}.`);
    } else {
      setSafeMessage(`SAFE test ${status?.state || "REJECTED"}: ${status?.rejection_reason || "unknown reason"}.`, true);
    }
  } catch (error) {
    setSafeMessage(error.message, true);
    await refreshSafeTestStatus().catch(() => {});
  } finally {
    updateSafeButtons();
    await refreshDiagnosticLog().catch(() => {});
  }
}

function renderDiagnosticLog() {
  const target = element("lc-diagnostic-log");
  if (!target) return;
  target.textContent = state.diagnosticLines.length
    ? state.diagnosticLines.join("\n")
    : "No real actuator diagnostic events in this view.";
  target.scrollTop = target.scrollHeight;
}

async function refreshDiagnosticLog() {
  const payload = await getLanDiagnosticLog(state.diagnosticAfterSequence, 200);
  const events = Array.isArray(payload?.events) ? payload.events : [];
  for (const item of events) {
    if (typeof item?.line === "string") state.diagnosticLines.push(item.line);
  }
  if (state.diagnosticLines.length > 200) {
    state.diagnosticLines = state.diagnosticLines.slice(-200);
  }
  if (Number.isInteger(payload?.latest_sequence) && payload.latest_sequence >= state.diagnosticAfterSequence) {
    state.diagnosticAfterSequence = payload.latest_sequence;
  }
  renderDiagnosticLog();
  return payload;
}

async function copyDiagnosticLog() {
  if (!state.diagnosticLines.length) {
    setDiagnosticMessage("No diagnostic events to copy.");
    return;
  }
  try {
    await navigator.clipboard.writeText(state.diagnosticLines.join("\n"));
    setDiagnosticMessage(`Copied ${state.diagnosticLines.length} diagnostic line(s).`);
  } catch (error) {
    setDiagnosticMessage(`Copy failed: ${error.message}`, true);
  }
}

async function clearDiagnosticView() {
  try {
    const payload = await getLanDiagnosticLog(0, 200);
    if (Number.isInteger(payload?.latest_sequence)) {
      state.diagnosticAfterSequence = payload.latest_sequence;
    }
    state.diagnosticLines = [];
    renderDiagnosticLog();
    setDiagnosticMessage("View cleared. Backend log retained.");
  } catch (error) {
    setDiagnosticMessage(error.message, true);
  }
}

function renderStatus(status) {
  state.status = status;
  const mode = status.control_mode || "DISABLED";
  const session = status.session_state || "UNBOUND";
  const safe = status.safe_state || "SAFE_UNCONFIRMED";
  const toggle = element("load-control-toggle");
  if (toggle) toggle.dataset.controlMode = mode;

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
  element("lc-sample-age").textContent = Number.isFinite(status.last_sample_age_s)
    ? `${Number(status.last_sample_age_s).toFixed(3)} s`
    : "—";

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
  for (const id of [
    "lc-source",
    "lc-actuator",
    "lc-reserve",
    "lc-limit-a",
    "lc-limit-b",
    "lc-limit-c",
    "lc-sample-age-limit",
    "lc-ack-timeout",
    "lc-save-binding",
    "lc-save-limits",
    "lc-save-timing",
  ]) {
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
      : "No mock control evidence recorded.";
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function refreshPrimary() {
  await refreshLanQualification();
  await refreshSafeSources();
  await refreshSafeTestStatus();
  await refreshDiagnosticLog();
}

async function refreshAll() {
  try {
    await refreshStatus();
    await refreshActuators();
    await refreshPrimary();
    if (element("lc-development-tools")?.open) await refreshEvidence();
  } catch (error) {
    setDiagnosticMessage(error.message, true);
  }
}

async function onDevelopmentToolsToggle() {
  if (!element("lc-development-tools")?.open) return;
  await refreshStatus().catch((error) => setMessage(error.message, true));
  await refreshActuators().catch((error) => setMessage(error.message, true));
  await refreshEvidence();
}

async function runLanScan() {
  const button = element("lc-scan-lan");
  try {
    const discoveryWindow = positiveInputValue("lc-lan-discovery-window", "Discovery window");
    const resolveTimeout = positiveInputValue("lc-lan-resolve-timeout", "Resolve timeout");
    if (button) button.disabled = true;
    setLanMessage("Scanning for compatible actuator advertisements...");
    const values = await scanLanActuators({
      discovery_window_s: discoveryWindow,
      resolve_timeout_s: resolveTimeout,
    });
    renderLanResults(values);
    setLanMessage(`LAN scan complete. ${values.length} compatible actuator advertisement(s) found.`);
    await refreshDiagnosticLog();
  } catch (error) {
    setLanMessage(error.message, true);
    await refreshDiagnosticLog().catch(() => {});
  } finally {
    if (button) button.disabled = false;
  }
}

async function runSelectedLanQualification() {
  const nodeId = element("lc-real-actuator")?.value || "";
  if (!nodeId) {
    const target = element("lc-qualification-error");
    target.textContent = "Select one discovered actuator first.";
    target.dataset.error = "true";
    return;
  }
  state.selectedNodeId = nodeId;
  renderSelectedActuator();
  await runLanQualification(nodeId);
}

async function runLanQualification(nodeId) {
  const button = element("lc-select-qualify");
  const errorTarget = element("lc-qualification-error");
  try {
    if (button) button.disabled = true;
    errorTarget.textContent = "Opening WebSocket and waiting for HELLO...";
    errorTarget.dataset.error = "false";
    renderLanQualification(await connectLanQualification(nodeId));
    await refreshSafeTestStatus().catch(() => {});
  } catch (error) {
    try {
      await refreshLanQualification();
      await refreshSafeTestStatus();
    } catch (_refreshError) {
      // Keep the connection error as operator evidence.
    }
    errorTarget.textContent = error.message;
    errorTarget.dataset.error = "true";
  } finally {
    await refreshDiagnosticLog().catch(() => {});
    updateQualifyButton();
    updateSafeButtons();
  }
}

async function runLanQualificationDisconnect() {
  const button = element("lc-qualification-disconnect");
  try {
    if (button) button.disabled = true;
    renderLanQualification(await disconnectLanQualification());
    await refreshSafeTestStatus().catch(() => {});
  } catch (error) {
    const target = element("lc-qualification-error");
    target.textContent = error.message;
    target.dataset.error = "true";
  } finally {
    await refreshDiagnosticLog().catch(() => {});
    updateSafeButtons();
  }
}

async function saveBinding() {
  try {
    const sourceInput = element("lc-source");
    const activeSelector = element("device-selector");
    const source = sourceInput.value || activeSelector?.value || "";
    const actuator = element("lc-actuator").value;
    await setLoadControlBinding(source, actuator);
    setMessage("Mock binding saved. Mock control remains DISABLED.");
    await refreshStatus();
    await refreshActuators();
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
    setMessage("Mock target and operator limits saved. Mock control remains DISABLED.");
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
    setMessage("Volatile timing qualification set for this mock Viewer session.");
    await refreshStatus();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function runEnable() {
  try {
    await enableLoadControl();
    setMessage("Mock control ENABLED for the deterministic mock actuator.");
    await refreshStatus();
  } catch (error) {
    setMessage(`Mock enable rejected: ${error.message}`, true);
    await refreshStatus();
  }
}

async function runDisable() {
  try {
    await disableLoadControl();
    setMessage("Mock control authority revoked. Safe 0/0/0 W requested for the mock actuator.");
    await refreshStatus();
  } catch (error) {
    setMessage(error.message, true);
  }
}

createUi();
refreshAll();
setInterval(() => {
  refreshStatus().catch(() => {});
  if (state.visible) {
    refreshLanQualification().catch(() => {});
    refreshSafeTestStatus().catch(() => {});
    refreshDiagnosticLog().catch(() => {});
  }
}, 1000);
