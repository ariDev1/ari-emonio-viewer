import {
  connectLanQualification,
  disconnectLanQualification,
  getLanDiagnosticLog,
  getLanQualificationStatus,
  scanLanActuators,
} from "./load-control-api.js";

const state = {
  qualification: null,
  visible: false,
  lanResults: [],
  selectedNodeId: "",
  diagnosticAfterSequence: 0,
  diagnosticLines: [],
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

function positiveInputValue(id, label) {
  const value = Number(element(id)?.value);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label} must be finite and greater than 0 s.`);
  }
  return value;
}

function setStatusTone(id, tone) {
  const target = element(id);
  const card = target?.parentElement;
  if (!card) return;
  card.dataset.tone = tone;
}

function setLanMessage(message, isError = false) {
  const target = element("lc-lan-scan-status");
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
    <strong id="load-control-summary-mode">ZERO EXPORT</strong>
    <span id="load-control-summary-session">IDLE</span>
    <span id="load-control-summary-safe">DEVICE NOT READY</span>
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
        <span class="eyebrow">OPERATOR VIEW</span>
        <h2>External Load Control</h2>
      </div>
      <div class="load-control-header-actions">
        <strong class="load-control-real-disabled">QUALIFIED PWM CONTROL</strong>
        <button id="load-control-close" type="button">CLOSE</button>
      </div>
    </div>
    <p class="load-control-stage-note">
      Connect and qualify one actuator. Then use the Zero-Export Controller for automatic physical PWM control. Engineering controls and protocol evidence are available below when needed.
    </p>

    <section class="load-control-section load-control-primary-section">
      <div class="load-control-section-header"><h3>Actuator</h3><span>LAN</span></div>
      <p class="load-control-section-note">Find one compatible actuator, select it, and connect.</p>
      <div class="load-control-actions">
        <button id="lc-scan-lan" type="button">SCAN LAN</button>
      </div>
      <div id="lc-lan-scan-status" class="load-control-status-text" aria-live="polite">No LAN scan run.</div>
      <label class="load-control-real-actuator-label">Actuator
        <select id="lc-real-actuator">
          <option value="">Choose discovered actuator</option>
        </select>
      </label>
      <div id="lc-selected-actuator" class="load-control-real-actuator-summary">No actuator selected.</div>
      <div class="load-control-primary-status" aria-label="Actuator connection state">
        <div><span>Connection</span><strong id="lc-ws-state">DISCONNECTED</strong></div>
        <div><span>Device</span><strong id="lc-hello-state">NOT READY</strong></div>
      </div>
      <div class="load-control-actions">
        <button id="lc-select-qualify" type="button" disabled>CONNECT / QUALIFY</button>
        <button id="lc-qualification-disconnect" type="button" disabled>DISCONNECT</button>
      </div>
      <div id="lc-qualification-error" class="load-control-status-text" aria-live="polite"></div>
    </section>

    <div id="lc-zero-export-slot"></div>

    <details id="lc-engineering-diagnostics" class="load-control-engineering-tools">
      <summary>ENGINEERING DIAGNOSTICS</summary>
      <p class="load-control-section-note">
        Manual PWM control, characterization, qualification evidence, and protocol diagnostics are available here. They are not required for normal zero-export operation.
      </p>

      <section class="load-control-section">
        <div class="load-control-section-header"><h3>LAN discovery timing</h3><span>s</span></div>
        <div class="load-control-connection-controls">
          <label>Discovery window / s
            <input id="lc-lan-discovery-window" type="number" min="0" step="any" value="5">
          </label>
          <label>Resolve timeout / s
            <input id="lc-lan-resolve-timeout" type="number" min="0" step="any" value="5">
          </label>
        </div>
      </section>

      <section class="load-control-section load-control-qualification-section">
        <div class="load-control-section-header"><h3>Qualification evidence</h3><span>HELLO</span></div>
        <div class="load-control-qualification-evidence">
          <div><span>Actuator instance</span><strong id="lc-qualification-identity">—</strong></div>
          <div><span>Protocol / class / capability</span><strong id="lc-qualification-protocol">—</strong></div>
          <div><span>Advertised test limit</span><strong id="lc-qualification-limits">—</strong></div>
          <div><span>WebSocket locator</span><strong id="lc-qualification-location">—</strong></div>
        </div>
      </section>

      <div id="lc-manual-pwm-slot"></div>
      <div id="lc-characterization-slot"></div>

      <section class="load-control-section load-control-diagnostic-section">
        <div class="load-control-section-header"><h3>Diagnostic log</h3><span>actuator protocol</span></div>
        <p class="load-control-section-note">
          This backend-owned log contains LAN discovery, WebSocket/HELLO, PWM command, ACK, and rejection evidence. CLEAR VIEW does not delete the backend log.
        </p>
        <pre id="lc-diagnostic-log" class="load-control-diagnostic-log">No real actuator diagnostic events yet.</pre>
        <div class="load-control-actions">
          <button id="lc-copy-diagnostic-log" type="button">COPY LOG</button>
          <button id="lc-clear-diagnostic-view" type="button">CLEAR VIEW</button>
        </div>
        <div id="lc-diagnostic-status" class="load-control-status-text" aria-live="polite"></div>
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
  element("lc-copy-diagnostic-log").addEventListener("click", copyDiagnosticLog);
  element("lc-clear-diagnostic-view").addEventListener("click", clearDiagnosticView);
}

function setVisible(visible) {
  state.visible = visible;
  const panel = element("load-control-panel");
  const toggle = element("load-control-toggle");
  if (panel) panel.hidden = !visible;
  if (toggle) toggle.setAttribute("aria-expanded", String(visible));
  if (visible) refreshPrimary().catch(() => {});
}

function selectedDescriptor() {
  return state.lanResults.find((item) => item.node_id === state.selectedNodeId) || null;
}

function renderSelectedActuator() {
  const target = element("lc-selected-actuator");
  const item = selectedDescriptor();
  if (!target) return;
  target.textContent = item ? `${item.node_id} · ${item.device_class}` : "No actuator selected.";
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
  const rejected = status?.state === "REJECTED";
  const hasSelectedActuator = Boolean(
    state.selectedNodeId || status?.selected_node_id || status?.node_id,
  );

  element("lc-ws-state").textContent = connected ? "CONNECTED" : "DISCONNECTED";
  element("lc-hello-state").textContent = qualified
    ? "READY"
    : rejected
      ? "REJECTED"
      : "NOT READY";

  setStatusTone(
    "lc-ws-state",
    connected ? "ok" : rejected ? "error" : hasSelectedActuator ? "warn" : "idle",
  );
  setStatusTone(
    "lc-hello-state",
    qualified ? "ok" : rejected ? "error" : connected || hasSelectedActuator ? "warn" : "idle",
  );

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
  element("load-control-summary-safe").textContent = qualified ? "DEVICE READY" : "DEVICE NOT READY";
  updateQualifyButton();
}

async function refreshLanQualification() {
  const status = await getLanQualificationStatus();
  renderLanQualification(status);
  return status;
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
    errorTarget.textContent = "Connecting and checking actuator...";
    errorTarget.dataset.error = "false";
    renderLanQualification(await connectLanQualification(nodeId));
  } catch (error) {
    try {
      await refreshLanQualification();
    } catch (_refreshError) {
      // Keep the connection error as operator evidence.
    }
    errorTarget.textContent = error.message;
    errorTarget.dataset.error = "true";
  } finally {
    await refreshDiagnosticLog().catch(() => {});
    updateQualifyButton();
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
    await refreshDiagnosticLog().catch(() => {});
  }
}

async function refreshPrimary() {
  await refreshLanQualification();
  await refreshDiagnosticLog();
}

createUi();
refreshPrimary().catch(() => {});
window.setInterval(() => {
  if (!state.visible) return;
  refreshLanQualification().catch(() => {});
  refreshDiagnosticLog().catch(() => {});
}, 1000);
