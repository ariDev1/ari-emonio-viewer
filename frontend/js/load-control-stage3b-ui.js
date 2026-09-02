import { getLanQualificationStatus } from "./load-control-api.js";
import {
  applyManualPwmDuty,
  getManualPwmStatus,
  getSimulatedTestStatus,
  runSimulatedCommandTest,
  turnManualPwmOff,
} from "./load-control-stage3b-api.js";


const PWM_DUTY_CONTROL_CAPABILITY = "PWM_DUTY_CONTROL";
const ACTIVE_STATES = new Set([
  "WAITING_FOR_SAMPLE",
  "COMMAND_SENT",
  "WAITING_FOR_ACK",
]);

let pwmStatus = null;
let simulatedStatus = null;
let qualificationStatus = null;
let created = false;
let pwmRequestActive = false;


function element(id) {
  return document.getElementById(id);
}


function setStatusTone(id, tone) {
  const target = element(id);
  const card = target?.parentElement;
  if (!card) return;
  card.dataset.tone = tone;
}


function createUi() {
  if (created) return true;
  const slot = element("lc-simulated-operator-slot");
  if (!slot) return false;

  const pwmSection = document.createElement("section");
  pwmSection.className = "load-control-section load-control-primary-section load-control-pwm-section";
  pwmSection.innerHTML = `
    <div class="load-control-section-header"><h3>Manual PWM duty</h3><span>QUALIFIED ACTUATOR</span></div>
    <p class="load-control-section-note">
      Manual engineering control only. This control does not use Emonio measurements and does not convert watts to duty.
    </p>
    <div class="load-control-pwm-control">
      <label>
        <span>Duty [%]</span>
        <input id="lc-pwm-duty" class="load-control-pwm-input" type="number" min="0" max="99.999999" step="0.1" value="50.0" disabled>
      </label>
      <div class="load-control-actions">
        <button id="lc-pwm-apply" type="button" disabled>APPLY DUTY</button>
        <button id="lc-pwm-off" type="button" disabled>OFF</button>
      </div>
    </div>
    <div class="load-control-primary-status load-control-operator-status" aria-label="Manual PWM duty state">
      <div><span>State</span><strong id="lc-pwm-state">DISCONNECTED</strong></div>
      <div><span>Requested duty</span><strong id="lc-pwm-requested">—</strong></div>
      <div><span>Actual duty</span><strong id="lc-pwm-actual">—</strong></div>
    </div>
    <div id="lc-pwm-message" class="load-control-status-text" aria-live="polite">
      Connect and qualify a PWM-capable actuator first.
    </div>
    <details class="load-control-engineering-inline">
      <summary>PWM ACK DETAILS</summary>
      <div class="load-control-safe-status" aria-label="Manual PWM command evidence">
        <div><span>COMMAND sequence</span><strong id="lc-pwm-sequence">—</strong></div>
        <div><span>ACK result</span><strong id="lc-pwm-ack">—</strong></div>
        <div><span>Compare ticks</span><strong id="lc-pwm-compare">—</strong></div>
        <div><span>Period ticks</span><strong id="lc-pwm-period">—</strong></div>
        <div><span>Rejection</span><strong id="lc-pwm-rejection">—</strong></div>
      </div>
    </details>
  `;

  const simulatedSection = document.createElement("section");
  simulatedSection.className = "load-control-section load-control-primary-section load-control-simulated-test-section";
  simulatedSection.innerHTML = `
    <div class="load-control-section-header"><h3>Simulated test</h3><span>1 W</span></div>
    <p class="load-control-section-note load-control-safe-warning">
      NO PHYSICAL OUTPUT. This action requests a fixed simulated load of A=1 W, B=0 W, C=0 W. After the test, SAFE 0 W is required.
    </p>
    <div class="load-control-primary-status load-control-operator-status" aria-label="Simulated test state">
      <div><span>State</span><strong id="lc-simulated-state">IDLE</strong></div>
      <div><span>Request</span><strong id="lc-simulated-request">A 1.0 W · B 0.0 W · C 0.0 W</strong></div>
      <div><span>Reset</span><strong id="lc-simulated-reset">NOT REQUIRED</strong></div>
    </div>
    <div class="load-control-actions">
      <button id="lc-simulated-run" type="button" disabled>TEST 1 W — PHASE A</button>
    </div>
    <div id="lc-simulated-message" class="load-control-status-text" aria-live="polite">
      Connect the actuator and select the Emonio source first.
    </div>
    <details class="load-control-engineering-inline">
      <summary>ENGINEERING DETAILS</summary>
      <p class="load-control-section-note">
        Fixed protocol request: control_enabled=true · P request A=1 W, B=0 W, C=0 W · Q request A/B/C=0 var · No retry · Measured Emonio P/Q is provenance only · NONZERO REAL CONTROL DISABLED.
      </p>
      <div class="load-control-safe-status" aria-label="Stage 3B simulated command evidence">
        <div><span>COMMAND sequence</span><strong id="lc-simulated-sequence">—</strong></div>
        <div><span>ACK result</span><strong id="lc-simulated-ack">—</strong></div>
        <div><span>Rejection</span><strong id="lc-simulated-rejection">—</strong></div>
      </div>
    </details>
  `;

  slot.append(pwmSection, simulatedSection);
  element("lc-pwm-apply").addEventListener("click", applyPwmDuty);
  element("lc-pwm-off").addEventListener("click", turnPwmOff);
  element("lc-simulated-run").addEventListener("click", runSimulatedTest);
  created = true;
  return true;
}


function setPwmMessage(message, isError = false) {
  const target = element("lc-pwm-message");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
}


function setSimulatedMessage(message, isError = false) {
  const target = element("lc-simulated-message");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
}


function powerTriplet(value) {
  if (!value) return "A 1.0 W · B 0.0 W · C 0.0 W";
  return `A ${Number(value.a).toFixed(1)} W · B ${Number(value.b).toFixed(1)} W · C ${Number(value.c).toFixed(1)} W`;
}


function dutyText(value) {
  if (value === null || value === undefined) return "—";
  const duty = Number(value);
  return Number.isFinite(duty) ? `${duty.toFixed(6)} %` : "—";
}


function pwmQualified() {
  return Boolean(qualificationStatus?.connected)
    && Boolean(qualificationStatus?.hello_qualified)
    && Boolean(qualificationStatus?.capabilities?.includes(PWM_DUTY_CONTROL_CAPABILITY));
}


function updatePwmControls() {
  const input = element("lc-pwm-duty");
  const applyButton = element("lc-pwm-apply");
  const offButton = element("lc-pwm-off");
  const active = ACTIVE_STATES.has(pwmStatus?.state) || pwmRequestActive;
  const enabled = pwmQualified() && Boolean(pwmStatus?.admissible) && !active;

  if (input) input.disabled = !enabled;
  if (applyButton) applyButton.disabled = !enabled;
  if (offButton) offButton.disabled = !enabled;
}


function updateSimulatedButton() {
  const button = element("lc-simulated-run");
  if (!button) return;
  const active = ACTIVE_STATES.has(simulatedStatus?.state);
  button.disabled = !Boolean(simulatedStatus?.admissible)
    || !Boolean(qualificationStatus?.hello_qualified)
    || active
    || Boolean(simulatedStatus?.safe_reset_required);
}


function renderPwm(status) {
  pwmStatus = status || null;
  if (!createUi()) return;

  const state = status?.state || "DISCONNECTED";
  const rejected = state === "REJECTED";
  const applied = state === "APPLIED";
  const off = state === "OFF";
  const active = ACTIVE_STATES.has(state);

  element("lc-pwm-state").textContent = state;
  element("lc-pwm-requested").textContent = dutyText(status?.requested_duty_percent);
  element("lc-pwm-actual").textContent = dutyText(status?.actual_duty_percent);
  element("lc-pwm-sequence").textContent = status?.command_sequence ?? "—";
  element("lc-pwm-ack").textContent = status?.ack_result || "—";
  element("lc-pwm-compare").textContent = status?.compare_ticks ?? "—";
  element("lc-pwm-period").textContent = status?.period_ticks ?? "—";
  element("lc-pwm-rejection").textContent = status?.rejection_reason || "—";

  setStatusTone(
    "lc-pwm-state",
    rejected
      ? "error"
      : active
        ? "warn"
        : applied || off
          ? "ok"
          : "idle",
  );
  setStatusTone("lc-pwm-actual", applied ? "ok" : off ? "ok" : "idle");

  if (!qualificationStatus?.connected || !qualificationStatus?.hello_qualified) {
    setPwmMessage("Connect and qualify an actuator first.");
  } else if (!qualificationStatus?.capabilities?.includes(PWM_DUTY_CONTROL_CAPABILITY)) {
    setPwmMessage("The qualified actuator does not advertise PWM_DUTY_CONTROL.", true);
  } else if (rejected) {
    setPwmMessage(`PWM command rejected: ${status?.rejection_reason || "unknown reason"}.`, true);
  } else if (applied) {
    setPwmMessage(
      `Duty applied. Requested ${dutyText(status?.requested_duty_percent)} · actual ${dutyText(status?.actual_duty_percent)}.`,
    );
  } else if (off) {
    setPwmMessage("PWM output is OFF. HIN and LIN are in the actuator safe state.");
  } else if (!active) {
    setPwmMessage("Manual duty control is ready. No Emonio measurement is used for this command.");
  }

  updatePwmControls();
}


function renderSimulated(status) {
  simulatedStatus = status || null;
  if (!createUi()) return;

  const simulatedState = status?.state || "IDLE";
  const active = ACTIVE_STATES.has(simulatedState);
  const rejected = simulatedState === "REJECTED";
  const resetRequired = Boolean(status?.safe_reset_required);

  element("lc-simulated-state").textContent = simulatedState;
  element("lc-simulated-request").textContent = powerTriplet(status?.fixed_request);
  element("lc-simulated-reset").textContent = resetRequired
    ? "ZERO RESET REQUIRED"
    : "NOT REQUIRED";
  element("lc-simulated-sequence").textContent = status?.command_sequence ?? "—";
  element("lc-simulated-ack").textContent = status?.ack_result || "—";
  element("lc-simulated-rejection").textContent = status?.rejection_reason || "—";

  setStatusTone(
    "lc-simulated-state",
    rejected
      ? "error"
      : resetRequired || active
        ? "warn"
        : simulatedState === "PASSED"
          ? "ok"
          : "idle",
  );
  setStatusTone(
    "lc-simulated-reset",
    resetRequired
      ? "warn"
      : simulatedState === "PASSED"
        ? "ok"
        : "idle",
  );
  updateSimulatedButton();
}


async function refresh() {
  if (!createUi()) return;
  const [qualification, pwm, simulated] = await Promise.all([
    getLanQualificationStatus(),
    getManualPwmStatus(),
    getSimulatedTestStatus(),
  ]);
  qualificationStatus = qualification;
  renderPwm(pwm);
  renderSimulated(simulated);
}


function readPwmDuty() {
  const input = element("lc-pwm-duty");
  const raw = input?.value?.trim() || "";
  const duty = Number(raw);
  if (!raw || !Number.isFinite(duty) || duty < 0.0 || duty >= 100.0) {
    throw new Error("Duty must be a finite value from 0.0 up to, but not including, 100.0 %.");
  }
  return duty;
}


async function applyPwmDuty() {
  try {
    const duty = readPwmDuty();
    pwmRequestActive = true;
    updatePwmControls();
    setPwmMessage(`Applying manual PWM duty ${duty.toFixed(6)} %...`);
    const status = await applyManualPwmDuty(duty);
    renderPwm(status);
  } catch (error) {
    setPwmMessage(error.message, true);
  } finally {
    pwmRequestActive = false;
    await refresh().catch(() => {});
    updatePwmControls();
  }
}


async function turnPwmOff() {
  try {
    pwmRequestActive = true;
    updatePwmControls();
    setPwmMessage("Sending explicit PWM OFF...");
    const status = await turnManualPwmOff();
    renderPwm(status);
  } catch (error) {
    setPwmMessage(error.message, true);
  } finally {
    pwmRequestActive = false;
    await refresh().catch(() => {});
    updatePwmControls();
  }
}


async function runSimulatedTest() {
  const button = element("lc-simulated-run");
  try {
    if (button) button.disabled = true;
    setSimulatedMessage("Waiting for a fresh Emonio sample, then applying the fixed simulated 1 W Phase A test...");
    const status = await runSimulatedCommandTest();
    renderSimulated(status);
    if (status?.safe_reset_required) {
      setSimulatedMessage("1 W simulated test finished. SAFE 0 W is required before another 1 W test.");
    } else if (status?.state === "REJECTED") {
      setSimulatedMessage(`Simulated test rejected: ${status?.rejection_reason || "unknown reason"}.`, true);
    }
  } catch (error) {
    setSimulatedMessage(error.message, true);
  } finally {
    await refresh().catch(() => {});
    updateSimulatedButton();
  }
}


function start() {
  if (!createUi()) {
    window.setTimeout(start, 50);
    return;
  }
  refresh().catch((error) => {
    setPwmMessage(error.message, true);
    setSimulatedMessage(error.message, true);
  });
  window.setInterval(() => {
    const panel = element("load-control-panel");
    if (panel && !panel.hidden) refresh().catch(() => {});
  }, 1000);
}


start();
