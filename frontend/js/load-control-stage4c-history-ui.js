import { getLanDiagnosticLog } from "./load-control-api.js";
import {
  CONTROL_HISTORY_MAX_RECORDS,
  CONTROL_HISTORY_WINDOW_MS,
  Stage4CControlHistory,
  deriveControlHistorySeries,
  nearestControlEvidence,
} from "./load-control-stage4c-history.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const REFRESH_MS = 750;
const SVG_WIDTH = 1000;
const PLOT_LEFT = 70;
const PLOT_RIGHT = 22;
const PLOT_TOP = 18;
const PLOT_BOTTOM = 28;
const P_PLOT_HEIGHT = 190;
const PWM_PLOT_HEIGHT = 190;
const EVENT_PLOT_HEIGHT = 160;

const state = {
  history: new Stage4CControlHistory(),
  selectedEvidence: null,
  timer: null,
  windowStartMs: null,
  windowEndMs: null,
  initialized: false,
};

function element(id) {
  return document.getElementById(id);
}

function panelVisible() {
  const panel = element("load-control-panel");
  return Boolean(panel && !panel.hidden);
}

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, decimals = 4) {
  const number = finite(value);
  return number == null ? "UNAVAILABLE" : number.toFixed(decimals);
}

function formatInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) ? String(number) : "UNAVAILABLE";
}

function formatText(value) {
  return typeof value === "string" && value ? value : "UNAVAILABLE";
}

function formatLocal(utc) {
  if (typeof utc !== "string" || !utc) return "UNAVAILABLE";
  const timestamp = new Date(utc);
  if (!Number.isFinite(timestamp.getTime())) return "UNAVAILABLE";
  return timestamp.toLocaleString([], {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
    hour12: false,
  });
}

function setText(id, value) {
  const target = element(id);
  if (target) target.textContent = value;
}

function svgElement(name, className = null) {
  const node = document.createElementNS(SVG_NS, name);
  if (className) node.setAttribute("class", className);
  return node;
}

function appendSvgLine(svg, x1, y1, x2, y2, className) {
  const line = svgElement("line", className);
  line.setAttribute("x1", String(x1));
  line.setAttribute("y1", String(y1));
  line.setAttribute("x2", String(x2));
  line.setAttribute("y2", String(y2));
  svg.append(line);
  return line;
}

function appendSvgText(svg, x, y, text, className, anchor = "start") {
  const node = svgElement("text", className);
  node.setAttribute("x", String(x));
  node.setAttribute("y", String(y));
  node.setAttribute("text-anchor", anchor);
  node.textContent = text;
  svg.append(node);
  return node;
}

function appendTitle(node, text) {
  const title = svgElement("title");
  title.textContent = text;
  node.append(title);
}

function plotInnerWidth() {
  return SVG_WIDTH - PLOT_LEFT - PLOT_RIGHT;
}

function xForTime(timestampMs, startMs, endMs) {
  if (!Number.isFinite(timestampMs) || endMs <= startMs) return null;
  const ratio = (timestampMs - startMs) / (endMs - startMs);
  if (ratio < 0 || ratio > 1) return null;
  return PLOT_LEFT + ratio * plotInnerWidth();
}

function xForUtc(utc, startMs, endMs) {
  const timestampMs = Date.parse(utc);
  return Number.isFinite(timestampMs) ? xForTime(timestampMs, startMs, endMs) : null;
}

function clearPlot(svg) {
  if (svg) svg.replaceChildren();
}

function drawTimeAxis(svg, height, startMs, endMs) {
  const bottomY = height - PLOT_BOTTOM;
  appendSvgLine(svg, PLOT_LEFT, bottomY, SVG_WIDTH - PLOT_RIGHT, bottomY, "control-history-axis");
  appendSvgText(svg, PLOT_LEFT, height - 8, new Date(startMs).toISOString().slice(11, 23), "control-history-axis-label");
  appendSvgText(svg, SVG_WIDTH - PLOT_RIGHT, height - 8, new Date(endMs).toISOString().slice(11, 23), "control-history-axis-label", "end");
  appendSvgText(svg, SVG_WIDTH - PLOT_RIGHT, 13, "UTC · ROLLING 10 MIN", "control-history-axis-note", "end");
}

function drawPPlot(series, startMs, endMs) {
  const svg = element("lc-zec-history-p-plot");
  if (!svg) return;
  clearPlot(svg);
  drawTimeAxis(svg, P_PLOT_HEIGHT, startMs, endMs);

  const innerHeight = P_PLOT_HEIGHT - PLOT_TOP - PLOT_BOTTOM;
  const pValues = series.p.map((item) => Math.abs(item.pW)).filter(Number.isFinite);
  const deadbandValues = series.p.map((item) => Math.abs(item.deadbandW)).filter(Number.isFinite);
  const maxAbs = Math.max(1, ...pValues, ...deadbandValues);
  const yForP = (value) => PLOT_TOP + ((maxAbs - value) / (2 * maxAbs)) * innerHeight;
  const zeroY = yForP(0);

  appendSvgLine(svg, PLOT_LEFT, zeroY, SVG_WIDTH - PLOT_RIGHT, zeroY, "control-history-zero-line");
  appendSvgText(svg, PLOT_LEFT - 8, PLOT_TOP + 4, `+${maxAbs.toFixed(2)}`, "control-history-axis-label", "end");
  appendSvgText(svg, PLOT_LEFT - 8, zeroY + 4, "0 W", "control-history-axis-label", "end");
  appendSvgText(svg, PLOT_LEFT - 8, P_PLOT_HEIGHT - PLOT_BOTTOM, `-${maxAbs.toFixed(2)}`, "control-history-axis-label", "end");

  for (const item of series.p) {
    const x = xForUtc(item.utc, startMs, endMs);
    if (x == null) continue;
    const y = yForP(item.pW);
    const marker = svgElement("circle", "control-history-p-point");
    marker.setAttribute("cx", String(x));
    marker.setAttribute("cy", String(y));
    marker.setAttribute("r", "3.3");
    marker.dataset.sequence = String(item.sequence);
    appendTitle(marker, `${item.utc} · P=${item.pW} W · ${item.state || item.action || "DECISION"}`);
    svg.append(marker);

    if (Number.isFinite(item.deadbandW)) {
      const upperY = yForP(item.deadbandW);
      const lowerY = yForP(-item.deadbandW);
      appendSvgLine(svg, x - 3, upperY, x + 3, upperY, "control-history-deadband-tick");
      appendSvgLine(svg, x - 3, lowerY, x + 3, lowerY, "control-history-deadband-tick");
    }
  }

  for (const item of series.settling) {
    const x = xForUtc(item.utc, startMs, endMs);
    if (x == null) continue;
    appendSvgLine(svg, x, PLOT_TOP, x, PLOT_TOP + 10, "control-history-settling-tick");
  }
}

function drawPwmMarker(svg, x, y, className, titleText, sequence) {
  const marker = svgElement("circle", className);
  marker.setAttribute("cx", String(x));
  marker.setAttribute("cy", String(y));
  marker.setAttribute("r", "3.5");
  marker.dataset.sequence = String(sequence);
  appendTitle(marker, titleText);
  svg.append(marker);
}

function drawPwmPlot(series, startMs, endMs) {
  const svg = element("lc-zec-history-pwm-plot");
  if (!svg) return;
  clearPlot(svg);
  drawTimeAxis(svg, PWM_PLOT_HEIGHT, startMs, endMs);

  const innerHeight = PWM_PLOT_HEIGHT - PLOT_TOP - PLOT_BOTTOM;
  const yForDuty = (duty) => PLOT_TOP + ((100 - duty) / 100) * innerHeight;
  const offY = yForDuty(0);
  appendSvgLine(svg, PLOT_LEFT, offY, SVG_WIDTH - PLOT_RIGHT, offY, "control-history-off-line");
  appendSvgText(svg, PLOT_LEFT - 8, PLOT_TOP + 4, "100 %", "control-history-axis-label", "end");
  appendSvgText(svg, PLOT_LEFT - 8, offY + 4, "OFF 0 %", "control-history-axis-label", "end");

  for (const item of series.commands) {
    const duty = finite(item.requestedDutyPercent);
    const x = xForUtc(item.utc, startMs, endMs);
    if (duty == null || x == null) continue;
    const y = yForDuty(duty);
    const marker = svgElement("rect", duty === 0 ? "control-history-command is-off" : "control-history-command");
    marker.setAttribute("x", String(x - 3));
    marker.setAttribute("y", String(y - 3));
    marker.setAttribute("width", "6");
    marker.setAttribute("height", "6");
    marker.dataset.sequence = String(item.sequence);
    appendTitle(marker, `${item.utc} · PWM COMMAND requested=${duty} %`);
    svg.append(marker);
  }

  for (const item of series.acks) {
    const requested = finite(item.requestedDutyPercent);
    const x = xForUtc(item.utc, startMs, endMs);
    if (requested == null || x == null) continue;
    drawPwmMarker(
      svg,
      x,
      yForDuty(requested),
      item.isOff ? "control-history-ack-requested is-off" : "control-history-ack-requested",
      `${item.utc} · PWM ACK requested=${requested} %`,
      item.sequence,
    );
    const actual = finite(item.actualDutyPercent);
    if (actual != null) {
      drawPwmMarker(
        svg,
        x,
        yForDuty(actual),
        item.isOff ? "control-history-ack-actual is-off" : "control-history-ack-actual",
        `${item.utc} · PWM ACK actual=${actual} %`,
        item.sequence,
      );
    }
  }
}

function eventLabel(item) {
  if (item.event === "ZERO_EXPORT_DECISION") return item.state || item.action || "DECISION";
  if (item.event === "ZERO_EXPORT_SETTLING_SAMPLE") return "SETTLING";
  if (item.event.startsWith("ZERO_EXPORT_")) return item.event.slice("ZERO_EXPORT_".length);
  return item.event;
}

function drawEventMarker(svg, x, y, className, label, titleText, sequence, showLabel) {
  const marker = svgElement("circle", className);
  marker.setAttribute("cx", String(x));
  marker.setAttribute("cy", String(y));
  marker.setAttribute("r", "3.4");
  marker.dataset.sequence = String(sequence);
  appendTitle(marker, titleText);
  svg.append(marker);
  if (showLabel) {
    appendSvgText(svg, x + 5, y - 5, label, "control-history-event-label");
  }
}

function drawEventPlot(series, startMs, endMs) {
  const svg = element("lc-zec-history-event-plot");
  if (!svg) return;
  clearPlot(svg);
  drawTimeAxis(svg, EVENT_PLOT_HEIGHT, startMs, endMs);

  appendSvgText(svg, PLOT_LEFT - 8, 48, "CTRL", "control-history-axis-label", "end");
  appendSvgText(svg, PLOT_LEFT - 8, 92, "PWM", "control-history-axis-label", "end");
  appendSvgLine(svg, PLOT_LEFT, 48, SVG_WIDTH - PLOT_RIGHT, 48, "control-history-row-line");
  appendSvgLine(svg, PLOT_LEFT, 92, SVG_WIDTH - PLOT_RIGHT, 92, "control-history-row-line");

  for (const item of series.timeline) {
    const x = xForUtc(item.utc, startMs, endMs);
    if (x == null) continue;
    const label = eventLabel(item);
    const significant = item.event !== "ZERO_EXPORT_DECISION" && item.event !== "ZERO_EXPORT_CAUSAL_BOUNDARY_ARMED";
    drawEventMarker(
      svg,
      x,
      48,
      "control-history-controller-event",
      label,
      `${item.utc} · ${item.event} · state=${item.state || "UNAVAILABLE"} · reason=${item.reason || "UNAVAILABLE"}`,
      item.sequence,
      significant,
    );
  }

  for (const item of series.commands) {
    const x = xForUtc(item.utc, startMs, endMs);
    if (x == null) continue;
    drawEventMarker(svg, x, 86, "control-history-pwm-command-event", "PWM CMD", `${item.utc} · PWM_COMMAND_SENT`, item.sequence, false);
  }
  for (const item of series.acks) {
    const x = xForUtc(item.utc, startMs, endMs);
    if (x == null) continue;
    drawEventMarker(svg, x, 98, "control-history-pwm-ack-event", "PWM ACK", `${item.utc} · PWM_ACK_QUALIFIED`, item.sequence, false);
  }
}

function removeCursors() {
  for (const id of ("lc-zec-history-p-plot", "lc-zec-history-pwm-plot", "lc-zec-history-event-plot")) {
    const svg = element(id);
    if (!svg) continue;
    for (const cursor of svg.querySelectorAll(".control-history-cursor")) cursor.remove();
  }
}

function renderCursor() {
  removeCursors();
  const selected = state.selectedEvidence;
  if (!selected || state.windowStartMs == null || state.windowEndMs == null) return;
  const x = xForUtc(selected.utc, state.windowStartMs, state.windowEndMs);
  if (x == null) return;
  for (const [id, height] of (
    [["lc-zec-history-p-plot", P_PLOT_HEIGHT], ["lc-zec-history-pwm-plot", PWM_PLOT_HEIGHT], ["lc-zec-history-event-plot", EVENT_PLOT_HEIGHT]]
  )) {
    const svg = element(id);
    if (!svg) continue;
    appendSvgLine(svg, x, PLOT_TOP, x, height - PLOT_BOTTOM, "control-history-cursor");
  }
}

function selectedRequestedDuty(fields) {
  const direct = finite(fields.requested_duty_percent);
  if (direct != null) return direct;
  return finite(fields.next_requested_duty_percent);
}

function renderInspector() {
  const selected = state.selectedEvidence;
  const fields = selected?.fields || {};
  const available = Boolean(selected);

  setText("lc-zec-history-inspector-state", available ? `SEQUENCE ${selected.sequence} · ${selected.event}` : "SELECT A PLOT POINT OR MOVE THE CURSOR");
  setText("lc-zec-history-utc", available ? selected.utc : "UNAVAILABLE");
  setText("lc-zec-history-local", available ? formatLocal(selected.utc) : "UNAVAILABLE");
  setText("lc-zec-history-diagnostic-utc", available ? selected.diagnosticUtc : "UNAVAILABLE");
  setText("lc-zec-history-event", available ? selected.event : "UNAVAILABLE");
  setText("lc-zec-history-source", available ? formatText(fields.source_id) : "UNAVAILABLE");
  setText("lc-zec-history-phase", available ? formatText(fields.phase) : "UNAVAILABLE");
  setText("lc-zec-history-cycle", available ? formatInteger(fields.cycle_id) : "UNAVAILABLE");
  setText("lc-zec-history-p", available ? formatNumber(fields.measured_p_w) : "UNAVAILABLE");
  setText("lc-zec-history-requested-duty", available ? formatNumber(selectedRequestedDuty(fields)) : "UNAVAILABLE");
  setText("lc-zec-history-confirmed-requested-duty", available ? formatNumber(fields.confirmed_requested_duty_percent) : "UNAVAILABLE");
  setText("lc-zec-history-actual-duty", available ? formatNumber(fields.actual_duty_percent) : "UNAVAILABLE");
  setText("lc-zec-history-compare-ticks", available ? formatInteger(fields.compare_ticks) : "UNAVAILABLE");
  setText("lc-zec-history-period-ticks", available ? formatInteger(fields.period_ticks) : "UNAVAILABLE");
  setText("lc-zec-history-controller-state", available ? formatText(fields.controller_state ?? fields.state) : "UNAVAILABLE");
  setText("lc-zec-history-action", available ? formatText(fields.action) : "UNAVAILABLE");
  setText("lc-zec-history-reason", available ? formatText(fields.reason) : "UNAVAILABLE");
  setText("lc-zec-history-monotonic", available ? formatInteger(fields.cycle_finished_monotonic_ns) : "UNAVAILABLE");
}

function renderMeta(events) {
  setText("lc-zec-history-record-count", `${events.length} / ${CONTROL_HISTORY_MAX_RECORDS}`);
  setText("lc-zec-history-sequence", String(state.history.lastSeenSequence));
  const gaps = state.history.sequenceGaps();
  const missing = gaps.reduce((sum, item) => sum + item.missingCount, 0);
  setText(
    "lc-zec-history-sequence-gaps",
    gaps.length ? `${missing} MISSING · ${gaps.length} GAP(S)` : "NONE OBSERVED",
  );
  const last = events.at(-1);
  setText("lc-zec-history-last-event", last?.utc || "UNAVAILABLE");
}

function renderHistory(nowMs = Date.now()) {
  const events = state.history.events();
  const series = deriveControlHistorySeries(events);
  const endMs = Number(nowMs);
  const startMs = endMs - CONTROL_HISTORY_WINDOW_MS;
  state.windowStartMs = startMs;
  state.windowEndMs = endMs;

  drawPPlot(series, startMs, endMs);
  drawPwmPlot(series, startMs, endMs);
  drawEventPlot(series, startMs, endMs);
  renderMeta(events);

  if (state.selectedEvidence == null && events.length) {
    state.selectedEvidence = nearestControlEvidence(events, endMs);
  } else if (state.selectedEvidence != null && !events.some((item) => item.sequence === state.selectedEvidence.sequence)) {
    state.selectedEvidence = events.length ? nearestControlEvidence(events, endMs) : null;
  }
  renderInspector();
  renderCursor();
}

function selectionFromPointer(event, svg) {
  if (state.windowStartMs == null || state.windowEndMs == null) return;
  const rect = svg.getBoundingClientRect();
  if (!(rect.width > 0)) return;
  const plotLeftPx = (PLOT_LEFT / SVG_WIDTH) * rect.width;
  const plotRightPx = (PLOT_RIGHT / SVG_WIDTH) * rect.width;
  const usableWidth = rect.width - plotLeftPx - plotRightPx;
  if (!(usableWidth > 0)) return;
  const localX = event.clientX - rect.left;
  const ratio = Math.max(0, Math.min(1, (localX - plotLeftPx) / usableWidth));
  const targetMs = state.windowStartMs + ratio * (state.windowEndMs - state.windowStartMs);
  const selected = nearestControlEvidence(state.history.events(), targetMs);
  if (!selected) return;
  state.selectedEvidence = selected;
  renderInspector();
  renderCursor();
}

function bindPlotInspection() {
  for (const id of ("lc-zec-history-p-plot", "lc-zec-history-pwm-plot", "lc-zec-history-event-plot")) {
    const svg = element(id);
    if (!svg) continue;
    svg.addEventListener("pointermove", (event) => selectionFromPointer(event, svg));
    svg.addEventListener("click", (event) => selectionFromPointer(event, svg));
  }
}

function createUi() {
  const slot = element("lc-zero-export-slot");
  if (!slot || element("lc-zec-control-history")) return Boolean(element("lc-zec-control-history"));

  const section = document.createElement("section");
  section.id = "lc-zec-control-history";
  section.className = "load-control-section load-control-control-history";
  section.setAttribute("aria-label", "Stage4C Control History");
  section.innerHTML = `
    <div class="load-control-section-header">
      <h3>Stage4C Control History</h3>
      <span>OBSERVATIONAL CONTROL EVIDENCE</span>
    </div>
    <p class="control-history-boundary">
      OBSERVATIONAL CONTROL EVIDENCE · DOES NOT CONTROL THE ACTUATOR · CANONICAL P REMAINS THE CONTROL INPUT
    </p>
    <p class="control-history-causal-note">
      MEASUREMENT → DECISION → PWM COMMAND → PWM ACK → SETTLING → MEASUREMENT. Each marker keeps its own recorded timestamp. Different timestamps are not presented as simultaneous evidence.
    </p>

    <div class="control-history-meta" aria-label="Control history retention and sequence evidence">
      <div><span>Window</span><strong>10 MIN</strong></div>
      <div><span>Records</span><strong id="lc-zec-history-record-count">0 / ${CONTROL_HISTORY_MAX_RECORDS}</strong></div>
      <div><span>Diagnostic sequence</span><strong id="lc-zec-history-sequence">0</strong></div>
      <div><span>Sequence gaps</span><strong id="lc-zec-history-sequence-gaps">NONE OBSERVED</strong></div>
      <div><span>Last diagnostic UTC</span><strong id="lc-zec-history-last-event">UNAVAILABLE</strong></div>
    </div>

    <div class="control-history-plots">
      <section class="control-history-plot-card">
        <div class="control-history-plot-heading"><strong>Canonical P(t)</strong><span>SIGNED W · DECISION INPUT SAMPLES</span></div>
        <svg id="lc-zec-history-p-plot" class="control-history-plot" viewBox="0 0 ${SVG_WIDTH} ${P_PLOT_HEIGHT}" preserveAspectRatio="none" aria-label="Canonical active power control history"></svg>
      </section>
      <section class="control-history-plot-card">
        <div class="control-history-plot-heading"><strong>PWM duty(t)</strong><span>REQUEST → ACK · ACTUAL WHEN REPORTED</span></div>
        <svg id="lc-zec-history-pwm-plot" class="control-history-plot" viewBox="0 0 ${SVG_WIDTH} ${PWM_PLOT_HEIGHT}" preserveAspectRatio="none" aria-label="PWM control history"></svg>
      </section>
      <section class="control-history-plot-card">
        <div class="control-history-plot-heading"><strong>Controller / event timeline</strong><span>EXACT STAGE4C AND OWNED PWM EVIDENCE</span></div>
        <svg id="lc-zec-history-event-plot" class="control-history-plot control-history-event-plot" viewBox="0 0 ${SVG_WIDTH} ${EVENT_PLOT_HEIGHT}" preserveAspectRatio="none" aria-label="Controller state and event history"></svg>
      </section>
    </div>

    <section id="lc-zec-history-inspector" class="control-history-inspector" aria-label="Selected control evidence">
      <div class="control-history-inspector-heading">
        <strong>Exact evidence inspector</strong>
        <span id="lc-zec-history-inspector-state">SELECT A PLOT POINT OR MOVE THE CURSOR</span>
      </div>
      <dl class="control-history-inspector-grid">
        <div><dt>UTC</dt><dd id="lc-zec-history-utc">UNAVAILABLE</dd></div>
        <div><dt>Local time</dt><dd id="lc-zec-history-local">UNAVAILABLE</dd></div>
        <div><dt>Diagnostic UTC</dt><dd id="lc-zec-history-diagnostic-utc">UNAVAILABLE</dd></div>
        <div><dt>Event</dt><dd id="lc-zec-history-event">UNAVAILABLE</dd></div>
        <div><dt>Source</dt><dd id="lc-zec-history-source">UNAVAILABLE</dd></div>
        <div><dt>Phase</dt><dd id="lc-zec-history-phase">UNAVAILABLE</dd></div>
        <div><dt>Cycle</dt><dd id="lc-zec-history-cycle">UNAVAILABLE</dd></div>
        <div><dt>Canonical P / W</dt><dd id="lc-zec-history-p">UNAVAILABLE</dd></div>
        <div><dt>Requested duty / %</dt><dd id="lc-zec-history-requested-duty">UNAVAILABLE</dd></div>
        <div><dt>Confirmed requested / %</dt><dd id="lc-zec-history-confirmed-requested-duty">UNAVAILABLE</dd></div>
        <div><dt>Actual duty / %</dt><dd id="lc-zec-history-actual-duty">UNAVAILABLE</dd></div>
        <div><dt>Compare ticks</dt><dd id="lc-zec-history-compare-ticks">UNAVAILABLE</dd></div>
        <div><dt>Period ticks</dt><dd id="lc-zec-history-period-ticks">UNAVAILABLE</dd></div>
        <div><dt>Controller state</dt><dd id="lc-zec-history-controller-state">UNAVAILABLE</dd></div>
        <div><dt>Action</dt><dd id="lc-zec-history-action">UNAVAILABLE</dd></div>
        <div><dt>Reason</dt><dd id="lc-zec-history-reason">UNAVAILABLE</dd></div>
        <div><dt>Monotonic finish / ns</dt><dd id="lc-zec-history-monotonic">UNAVAILABLE</dd></div>
      </dl>
    </section>
    <div id="lc-zec-history-status" class="load-control-status-text" aria-live="polite"></div>
  `;
  slot.append(section);
  bindPlotInspection();
  renderHistory(Date.now());
  return true;
}

async function refreshHistory() {
  if (!panelVisible()) return;
  const nowMs = Date.now();
  try {
    const payload = await getLanDiagnosticLog(state.history.lastSeenSequence, 200);
    state.history.ingest(payload, nowMs);
    setText("lc-zec-history-status", "");
  } catch (error) {
    state.history.prune(nowMs);
    setText("lc-zec-history-status", `History read failed: ${error.message}`);
  }
  renderHistory(nowMs);
}

function startRefreshLoop() {
  if (state.timer != null) return;
  state.timer = window.setInterval(() => {
    if (panelVisible()) refreshHistory();
  }, REFRESH_MS);
}

async function initialize() {
  if (state.initialized) return;
  if (!createUi()) {
    window.setTimeout(initialize, 50);
    return;
  }
  state.initialized = true;
  if (panelVisible()) await refreshHistory();
  startRefreshLoop();

  const panel = element("load-control-panel");
  if (panel) {
    const observer = new MutationObserver(() => {
      if (panelVisible()) refreshHistory();
    });
    observer.observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize, { once: true });
} else {
  initialize();
}
