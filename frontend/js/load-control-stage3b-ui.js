import { getLanQualificationStatus } from "./load-control-api.js";
import {
  getSimulatedTestStatus,
  runSimulatedCommandTest,
} from "./load-control-stage3b-api.js";


const ACTIVE_STATES = new Set([
  "WAITING_FOR_SAMPLE",
  "COMMAND_SENT",
  "WAITING_FOR_ACK",
]);

let simulatedStatus = null;
let qualificationStatus = null;
let created = false;


function element(id) {
  return document.getElementById(id);
}


function createUi() {
  if (created) return true;
  const safeSection = document.querySelector(".load-control-safe-test-section");
  if (!safeSection) return false;

  const section = document.createElement("section");
  section.className = "load-control-section load-control-primary-section load-control-simulated-test-section";
  section.innerHTML = `
    <div class="load-control-section-header"><h3>SIMULATED nonzero qualification</h3><span>one explicit COMMAND</span></div>
    <p class="load-control-section-note load-control-safe-warning">
      NO PHYSICAL OUTPUT. This test sends one fixed simulated protocol COMMAND after explicit operator action: control_enabled=true · P request A=1 W, B=0 W, C=0 W · Q request A/B/C=0 var · No retry. Measured Emonio P/Q is provenance only. NONZERO REAL CONTROL DISABLED.
    </p>
    <div class="load-control-safe-status" aria-label="Stage 3B simulated command qualification state">
      <div><span>Stage 3B</span><strong id="lc-simulated-state">IDLE</strong></div>
      <div><span>Fixed request</span><strong id="lc-simulated-request">A 1.0 W · B 0.0 W · C 0.0 W</strong></div>
      <div><span>Reset</span><strong id="lc-simulated-reset">NOT REQUIRED</strong></div>
      <div><span>COMMAND sequence</span><strong id="lc-simulated-sequence">—</strong></div>
      <div><span>ACK result</span><strong id="lc-simulated-ack">—</strong></div>
      <div><span>Rejection</span><strong id="lc-simulated-rejection">—</strong></div>
    </div>
    <div class="load-control-actions">
      <button id="lc-simulated-run" type="button" disabled>SEND 1 W SIMULATED TEST — PHASE A</button>
    </div>
    <div id="lc-simulated-message" class="load-control-status-text" aria-live="polite">
      Select an Emonio source and qualify the actuator first. The request value is fixed and cannot be edited.
    </div>
  `;
  safeSection.insertAdjacentElement("afterend", section);
  element("lc-simulated-run").addEventListener("click", runSimulatedTest);
  created = true;
  return true;
}


function setMessage(message, isError = false) {
  const target = element("lc-simulated-message");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
}


function powerTriplet(value) {
  if (!value) return "A 1.0 W · B 0.0 W · C 0.0 W";
  return `A ${Number(value.a).toFixed(1)} W · B ${Number(value.b).toFixed(1)} W · C ${Number(value.c).toFixed(1)} W`;
}


function updateButton() {
  const button = element("lc-simulated-run");
  if (!button) return;
  const active = ACTIVE_STATES.has(simulatedStatus?.state);
  button.disabled = !Boolean(simulatedStatus?.admissible)
    || !Boolean(qualificationStatus?.hello_qualified)
    || active
    || Boolean(simulatedStatus?.safe_reset_required);
}


function render(status) {
  simulatedStatus = status || null;
  if (!createUi()) return;
  element("lc-simulated-state").textContent = status?.state || "IDLE";
  element("lc-simulated-request").textContent = powerTriplet(status?.fixed_request);
  element("lc-simulated-reset").textContent = status?.safe_reset_required
    ? "ZERO RESET REQUIRED"
    : "NOT REQUIRED";
  element("lc-simulated-sequence").textContent = status?.command_sequence ?? "—";
  element("lc-simulated-ack").textContent = status?.ack_result || "—";
  element("lc-simulated-rejection").textContent = status?.rejection_reason || "—";
  updateButton();
}


async function refresh() {
  if (!createUi()) return;
  const [qualification, status] = await Promise.all([
    getLanQualificationStatus(),
    getSimulatedTestStatus(),
  ]);
  qualificationStatus = qualification;
  render(status);
}


async function runSimulatedTest() {
  const button = element("lc-simulated-run");
  try {
    if (button) button.disabled = true;
    setMessage("Waiting for the first valid post-request Emonio sample, then sending one fixed simulated 1 W Phase A COMMAND...");
    const status = await runSimulatedCommandTest();
    render(status);
    if (status?.safe_reset_required) {
      setMessage("Simulated 1 W command completed or was attempted. ZERO RESET REQUIRED. Use SEND SAFE TEST COMMAND to confirm 0 W before another nonzero test.");
    } else if (status?.state === "REJECTED") {
      setMessage(`Stage 3B REJECTED: ${status?.rejection_reason || "unknown reason"}.`, true);
    }
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    await refresh().catch(() => {});
    updateButton();
  }
}


function start() {
  if (!createUi()) {
    window.setTimeout(start, 50);
    return;
  }
  refresh().catch((error) => setMessage(error.message, true));
  window.setInterval(() => {
    const panel = element("load-control-panel");
    if (panel && !panel.hidden) refresh().catch(() => {});
  }, 1000);
}


start();
