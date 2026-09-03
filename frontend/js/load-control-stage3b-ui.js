import { getLanQualificationStatus } from "./load-control-api.js";
import {
  applyManualPwmDuty,
  getManualPwmStatus,
  turnManualPwmOff,
} from "./load-control-stage3b-api.js";

const PWM_DUTY_CONTROL_CAPABILITY = "PWM_DUTY_CONTROL";
const ACTIVE_STATES = new Set([
  "WAITING_FOR_SAMPLE",
  "COMMAND_SENT",
  "WAITING_FOR_ACK",
]);

let pwmStatus = null;
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

function dutyText(value) {
  if (value === null || value === undefined) return "—";
  const duty = Number(value);
  return Number.isFinite(duty) ? `${duty.toFixed(6)} %` : "—";
}

function createUi() {
  if (created) return true;
  const slot = element("lc-manual-pwm-slot");
  if (!slot) return false;

  const pwmSection = document.createElement("section");
  pwmSection.className = "load-control-section load-control-primary-section load-control-pwm-section";
  pwmSection.innerHTML = `
    <div class="load-control-section-header"><h3>Manual PWM duty</h3><span>ENGINEERING · QUALIFIED ACTUATOR</span></div>
    <p class="load-control-section-note">
      Manual engineering control only. This control does not use Emonio measurements and does not convert watts to duty. Do not use it while automatic zero-export control owns PWM authority.
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

  slot.append(pwmSection);
  element("lc-pwm-apply").addEventListener("click", applyPwmDuty);
  element("lc-pwm-off").addEventListener("click", turnPwmOff);
  created = true;
  return true;
}

function setPwmMessage(message, isError = false) {
  const target = element("lc-pwm-message");
  if (!target) return;
  target.textContent = message || "";
  target.dataset.error = isError ? "true" : "false";
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

function renderPwm(status) {
  pwmStatus = status || null;
  if (!createUi()) return;

  const currentState = status?.state || "DISCONNECTED";
  const rejected = currentState === "REJECTED";
  const applied = currentState === "APPLIED";
  const off = currentState === "OFF";
  const active = ACTIVE_STATES.has(currentState);

  element("lc-pwm-state").textContent = currentState;
  element("lc-pwm-requested").textContent = dutyText(status?.requested_duty_percent);
  element("lc-pwm-actual").textContent = dutyText(status?.actual_duty_percent);
  element("lc-pwm-sequence").textContent = status?.command_sequence ?? "—";
  element("lc-pwm-ack").textContent = status?.ack_result || "—";
  element("lc-pwm-compare").textContent = status?.compare_ticks ?? "—";
  element("lc-pwm-period").textContent = status?.period_ticks ?? "—";
  element("lc-pwm-rejection").textContent = status?.rejection_reason || "—";

  setStatusTone(
    "lc-pwm-state",
    rejected ? "error" : active ? "warn" : applied || off ? "ok" : "idle",
  );
  setStatusTone("lc-pwm-actual", applied || off ? "ok" : "idle");

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

async function refresh() {
  if (!createUi()) return;
  const [qualification, pwm] = await Promise.all([
    getLanQualificationStatus(),
    getManualPwmStatus(),
  ]);
  qualificationStatus = qualification;
  renderPwm(pwm);
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
    renderPwm(await applyManualPwmDuty(duty));
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
    renderPwm(await turnManualPwmOff());
  } catch (error) {
    setPwmMessage(error.message, true);
  } finally {
    pwmRequestActive = false;
    await refresh().catch(() => {});
    updatePwmControls();
  }
}

function start() {
  if (!createUi()) {
    window.setTimeout(start, 50);
    return;
  }
  refresh().catch((error) => setPwmMessage(error.message, true));
  window.setInterval(() => {
    const panel = element("load-control-panel");
    if (panel && !panel.hidden) refresh().catch(() => {});
  }, 1000);
}

start();
