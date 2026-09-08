export const CONTROL_HISTORY_WINDOW_MS = 10 * 60 * 1000;
export const CONTROL_HISTORY_MAX_RECORDS = 1200;
export const STAGE4C_PWM_OWNER = "STAGE4C_ZERO_EXPORT";

const STAGE4C_PWM_EVENTS = new Set([
  "PWM_COMMAND_SENT",
  "PWM_ACK_QUALIFIED",
]);

export function finiteEvidenceNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textOrNull(value) {
  return typeof value === "string" && value ? value : null;
}

function fieldsOf(item) {
  return item && item.fields && typeof item.fields === "object" && !Array.isArray(item.fields)
    ? item.fields
    : {};
}

function sequenceOf(item) {
  const sequence = Number(item?.sequence);
  return Number.isInteger(sequence) && sequence >= 0 ? sequence : null;
}

function timestampMsOf(utc) {
  if (typeof utc !== "string" || !utc) return null;
  const timestampMs = Date.parse(utc);
  return Number.isFinite(timestampMs) ? timestampMs : null;
}

export function isStage4CControlEvidence(item) {
  const event = textOrNull(item?.event);
  if (event == null) return false;
  if (event.startsWith("ZERO_EXPORT_")) return true;
  return STAGE4C_PWM_EVENTS.has(event) && fieldsOf(item).owner === STAGE4C_PWM_OWNER;
}

function normalizeEvidence(item) {
  const sequence = sequenceOf(item);
  const utc = textOrNull(item?.utc);
  const event = textOrNull(item?.event);
  const timestampMs = timestampMsOf(utc);
  if (sequence == null || utc == null || event == null || timestampMs == null) return null;
  return {
    sequence,
    utc,
    timestampMs,
    event,
    line: typeof item.line === "string" ? item.line : "",
    fields: { ...fieldsOf(item) },
  };
}

function displayUtcOf(item) {
  const event = textOrNull(item?.event);
  const fields = fieldsOf(item);
  if (event === "ZERO_EXPORT_DECISION" || event === "ZERO_EXPORT_SETTLING_SAMPLE") {
    const measurementUtc = textOrNull(fields.cycle_finished_utc);
    if (measurementUtc != null && timestampMsOf(measurementUtc) != null) return measurementUtc;
  }
  const diagnosticUtc = textOrNull(item?.utc);
  return diagnosticUtc != null && timestampMsOf(diagnosticUtc) != null ? diagnosticUtc : null;
}

export function controlEvidenceForSequence(events, targetSequence) {
  const target = Number(targetSequence);
  if (!Number.isInteger(target) || target < 0) return null;

  for (const item of Array.isArray(events) ? events : []) {
    if (!isStage4CControlEvidence(item) || sequenceOf(item) !== target) continue;
    const event = textOrNull(item?.event);
    const diagnosticUtc = textOrNull(item?.utc);
    const utc = displayUtcOf(item);
    const timestampMs = timestampMsOf(utc);
    if (event == null || diagnosticUtc == null || utc == null || timestampMs == null) return null;
    return {
      sequence: target,
      event,
      utc,
      diagnosticUtc,
      timestampMs,
      fields: { ...fieldsOf(item) },
    };
  }
  return null;
}

export function nearestControlEvidence(events, targetTimestampMs) {
  const targetMs = Number(targetTimestampMs);
  if (!Number.isFinite(targetMs)) return null;

  let selected = null;
  let selectedDistance = Infinity;
  for (const item of Array.isArray(events) ? events : []) {
    if (!isStage4CControlEvidence(item)) continue;
    const sequence = sequenceOf(item);
    const event = textOrNull(item?.event);
    const diagnosticUtc = textOrNull(item?.utc);
    const utc = displayUtcOf(item);
    const timestampMs = timestampMsOf(utc);
    if (sequence == null || event == null || diagnosticUtc == null || utc == null || timestampMs == null) continue;

    const distance = Math.abs(timestampMs - targetMs);
    if (distance < selectedDistance || (distance === selectedDistance && sequence < selected.sequence)) {
      selectedDistance = distance;
      selected = {
        sequence,
        event,
        utc,
        diagnosticUtc,
        timestampMs,
        fields: { ...fieldsOf(item) },
      };
    }
  }
  return selected;
}

export class Stage4CControlHistory {
  constructor() {
    this._events = [];
    this._sequenceGaps = [];
    this._lastSeenSequence = null;
  }

  get lastSeenSequence() {
    return this._lastSeenSequence ?? 0;
  }

  ingest(payload, nowMs = Date.now()) {
    const events = Array.isArray(payload?.events) ? payload.events : [];
    for (const item of events) {
      const sequence = sequenceOf(item);
      if (sequence == null) continue;
      if (this._lastSeenSequence != null && sequence <= this._lastSeenSequence) continue;

      if (this._lastSeenSequence != null && sequence > this._lastSeenSequence + 1) {
        this._sequenceGaps.push({
          afterSequence: this._lastSeenSequence,
          beforeSequence: sequence,
          missingCount: sequence - this._lastSeenSequence - 1,
        });
        if (this._sequenceGaps.length > CONTROL_HISTORY_MAX_RECORDS) {
          this._sequenceGaps = this._sequenceGaps.slice(-CONTROL_HISTORY_MAX_RECORDS);
        }
      }
      this._lastSeenSequence = sequence;

      if (!isStage4CControlEvidence(item)) continue;
      const normalized = normalizeEvidence(item);
      if (normalized != null) this._events.push(normalized);
    }
    this.prune(nowMs);
    return this.events();
  }

  prune(nowMs = Date.now()) {
    const referenceMs = Number(nowMs);
    if (Number.isFinite(referenceMs)) {
      const cutoffMs = referenceMs - CONTROL_HISTORY_WINDOW_MS;
      this._events = this._events.filter((item) => item.timestampMs >= cutoffMs);
    }
    if (this._events.length > CONTROL_HISTORY_MAX_RECORDS) {
      this._events = this._events.slice(-CONTROL_HISTORY_MAX_RECORDS);
    }
  }

  events() {
    return this._events.map((item) => ({
      ...item,
      fields: { ...item.fields },
    }));
  }

  sequenceGaps() {
    return this._sequenceGaps.map((item) => ({ ...item }));
  }
}

function timelineState(item) {
  const fields = fieldsOf(item);
  if (textOrNull(fields.controller_state) != null) return fields.controller_state;
  if (textOrNull(fields.state) != null) return fields.state;
  if (item.event === "ZERO_EXPORT_LIMIT_LOW") return "LIMIT_LOW";
  if (item.event === "ZERO_EXPORT_RESOLUTION_LIMIT" || item.event === "ZERO_EXPORT_RESOLUTION_LIMIT_ACTIVE") {
    return "RESOLUTION_LIMIT";
  }
  if (item.event === "ZERO_EXPORT_DISABLED") return "DISABLED";
  return null;
}

export function deriveControlHistorySeries(events) {
  const series = {
    p: [],
    commands: [],
    acks: [],
    settling: [],
    timeline: [],
  };

  for (const item of Array.isArray(events) ? events : []) {
    if (!item || typeof item !== "object") continue;
    const sequence = sequenceOf(item);
    const utc = textOrNull(item.utc);
    const event = textOrNull(item.event);
    if (sequence == null || utc == null || event == null) continue;
    const fields = fieldsOf(item);

    if (event === "ZERO_EXPORT_DECISION") {
      const measurementUtc = textOrNull(fields.cycle_finished_utc);
      const pW = finiteEvidenceNumber(fields.measured_p_w);
      if (measurementUtc != null && timestampMsOf(measurementUtc) != null && pW != null) {
        series.p.push({
          sequence,
          utc: measurementUtc,
          diagnosticUtc: utc,
          cycleId: Number.isInteger(Number(fields.cycle_id)) ? Number(fields.cycle_id) : null,
          cycleFinishedMonotonicNs: finiteEvidenceNumber(fields.cycle_finished_monotonic_ns),
          sourceId: textOrNull(fields.source_id),
          phase: textOrNull(fields.phase),
          pW,
          deadbandW: finiteEvidenceNumber(fields.p_deadband_w),
          action: textOrNull(fields.action),
          state: textOrNull(fields.controller_state),
          reason: textOrNull(fields.reason),
          confirmedRequestedDutyPercent: finiteEvidenceNumber(fields.confirmed_requested_duty_percent),
          nextRequestedDutyPercent: finiteEvidenceNumber(fields.next_requested_duty_percent),
          lowerBracketDutyPercent: finiteEvidenceNumber(fields.lower_bracket_duty_percent),
          upperBracketDutyPercent: finiteEvidenceNumber(fields.upper_bracket_duty_percent),
        });
      }
    }

    if (event === "ZERO_EXPORT_SETTLING_SAMPLE") {
      const measurementUtc = textOrNull(fields.cycle_finished_utc);
      if (measurementUtc != null && timestampMsOf(measurementUtc) != null) {
        series.settling.push({
          sequence,
          utc: measurementUtc,
          diagnosticUtc: utc,
          cycleId: Number.isInteger(Number(fields.cycle_id)) ? Number(fields.cycle_id) : null,
          cycleFinishedMonotonicNs: finiteEvidenceNumber(fields.cycle_finished_monotonic_ns),
          state: textOrNull(fields.controller_state),
        });
      }
    }

    if (event === "PWM_COMMAND_SENT" && fields.owner === STAGE4C_PWM_OWNER) {
      series.commands.push({
        sequence,
        utc,
        requestedDutyPercent: finiteEvidenceNumber(fields.requested_duty_percent),
      });
    }

    if (event === "PWM_ACK_QUALIFIED" && fields.owner === STAGE4C_PWM_OWNER) {
      const requestedDutyPercent = finiteEvidenceNumber(fields.requested_duty_percent);
      series.acks.push({
        sequence,
        utc,
        requestedDutyPercent,
        actualDutyPercent: finiteEvidenceNumber(fields.actual_duty_percent),
        compareTicks: finiteEvidenceNumber(fields.compare_ticks),
        periodTicks: finiteEvidenceNumber(fields.period_ticks),
        isOff: requestedDutyPercent === 0,
      });
    }

    if (event.startsWith("ZERO_EXPORT_")) {
      series.timeline.push({
        sequence,
        utc,
        event,
        state: timelineState(item),
        reason: textOrNull(fields.reason),
        action: textOrNull(fields.action),
      });
    }
  }

  return series;
}
