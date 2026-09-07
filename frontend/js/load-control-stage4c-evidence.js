function finiteNumber(value) {
  if (value == null || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function deriveStage4CEvidence(status) {
  const deadband = finiteNumber(status?.p_deadband_w);
  const measuredP = finiteNumber(status?.measured_p_w);
  const lower = finiteNumber(status?.lower_bracket_duty_percent);
  const upper = finiteNumber(status?.upper_bracket_duty_percent);
  const periodTicks = finiteNumber(status?.confirmed_period_ticks);

  let pCondition = "—";
  if (deadband != null && deadband >= 0 && measuredP != null) {
    if (measuredP < -deadband) {
      pCondition = "EXPORT · INCREASE LOAD";
    } else if (measuredP > deadband) {
      pCondition = "IMPORT · DECREASE LOAD";
    } else {
      pCondition = "TARGET BAND · HOLD";
    }
  }

  const bracketWidthPercent = (
    lower != null && upper != null && upper >= lower
      ? upper - lower
      : null
  );

  const timerStepPercent = (
    periodTicks != null && Number.isInteger(periodTicks) && periodTicks > 0
      ? 100.0 / periodTicks
      : null
  );

  const mode = typeof status?.state === "string" ? status.state : "";
  const commandSuppressed = mode
    ? (mode === "RESOLUTION_LIMIT" ? "YES" : "NO")
    : "—";

  return {
    deadbandW: deadband != null && deadband >= 0 ? deadband : null,
    pCondition,
    bracketWidthPercent,
    timerStepPercent,
    commandSuppressed,
  };
}

const STATE_EXPLANATIONS = Object.freeze({
  DISABLED: "Automatic control is disabled. No Stage4C PWM command is active.",
  ENABLING: "Automatic control is enabling and requires acknowledged OFF before control starts.",
  WAITING_FOR_SAMPLE: "Automatic control is waiting for a fresh causal canonical P sample.",
  SETTLING: "The first causal post-ACK sample is reserved for settling. No control decision is made from this sample.",
  CONTROLLING: "A bounded sign-based control decision is active. See Control action and PWM evidence.",
  TARGET_BAND: "Canonical P is inside the configured deadband. HOLD is active and no PWM command is required.",
  LIMIT_LOW: "The low-authority boundary is active. Confirmed OFF is held and repeated OFF↔5 % commands are suppressed.",
  LIMIT_HIGH: "The active maximum is reached. No higher active duty is qualified.",
  RESOLUTION_LIMIT: "The requested adjustment produced no new physical PWM timer state. Further commands in the same direction are suppressed.",
  SAFE_OFF: "Explicit OFF is confirmed after a safe-state transition.",
  BLOCKED_SAFE: "Control is blocked in a safe state. Check the reason and OFF evidence.",
  SAFE_UNCONFIRMED: "OFF could not be confirmed. Automatic control is disabled and the actuator state requires operator attention.",
});

export function explainStage4CState(status) {
  const mode = typeof status?.state === "string" ? status.state : "";
  return STATE_EXPLANATIONS[mode] || "No Stage4C state explanation is available.";
}
