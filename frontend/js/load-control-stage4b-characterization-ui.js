import { getSafeTestSources } from "./load-control-api.js";
import {
  captureCurrentDuty,
  getCharacterizationStatus,
  runExplicitSweep,
} from "./load-control-stage4b-characterization-api.js";

const REFRESH_MS = 1000;
const DUTY_MIN_PERCENT = 25;
const DUTY_MAX_PERCENT = 75;
const MAX_SWEEP_POINTS = 51;

const ACTIVE_STATES = new Set([
  "CAPTURING",
  "SWEEPING",
  "SETTLING",
  "MEASURING",
]);

const state = {
  status: null,
  sources: [],
  timer: null,
  busy: false,
};

function element(id) {
  return document.getElementById(id);
}

function panelVisible() {
  const panel = element("load-control-panel");
  return Boolean(panel && !panel.hidden);
}

function setText(id, value) {
  const node = element(id);
  if (node) node.textContent = value;
}

function formatDuty(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(6)} %`;
}

function formatPower(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(6)} W`;
}

function formatSequence(value) {
  return Number.isInteger(Number(value)) ? String(Number(value)) : "—";
}

function parseExplicitDuties(text) {
  const tokens = String(text || "")
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (tokens.length < 2) throw new Error("Enter at least two explicit duty points.");
  if (tokens.length > MAX_SWEEP_POINTS) throw new Error("Enter no more than 51 duty points.");

  const duties = tokens.map((token) => Number(token));
  if (duties.some((value) => !Number.isFinite(value))) {
    throw new Error("Each duty point must be a finite number.");
  }
  if (duties.some((value) => value < DUTY_MIN_PERCENT || value > DUTY_MAX_PERCENT)) {
    throw new Error("Each duty point must be inside the qualified 25–75 % range.");
  }
  if (new Set(duties).size !== duties.length) {
    throw new Error("Each duty point must be unique.");
  }
  return duties;
}

function selectionReady() {
  const source = element("lc-pchar-source")?.value || "";
  const phase = element("lc-pchar-phase")?.value || "";
  return Boolean(source && ["A", "B", "C"].includes(phase));
}

function sweepReady() {
  if (!selectionReady()) return false;
  try {
    parseExplicitDuties(element("lc-pchar-duties")?.value || "");
    return true;
  } catch (_error) {
    return false;
  }
}

function readSelection() {
  if (!selectionReady()) throw new Error("Select one Emonio source and one phase.");
  return {
    source_id: element("lc-pchar-source").value,
    phase: element("lc-pchar-phase").value,
  };
}

function renderSources() {
  const select = element("lc-pchar-source");
  if (!select) return;
  const selected = select.value;
  select.innerHTML = '<option value="">Choose Emonio source</option>';
  for (const source of state.sources) {
    if (!source || typeof source.device_id !== "string" || !source.device_id) continue;
    const option = document.createElement("option");
    option.value = source.device_id;
    option.textContent = source.name ? `${source.name} · ${source.device_id}` : source.device_id;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function renderResults(points) {
  const target = element("lc-pchar-results");
  if (!target) return;
  const rows = Array.isArray(points) ? points : [];
  if (!rows.length) {
    target.innerHTML = '<div class="load-control-p-characterization-empty">No characterization point is recorded.</div>';
    return;
  }

  const body = rows.map((point) => `
    <tr>
      <td>${point.requested_duty_percent == null ? "—" : Number(point.requested_duty_percent).toFixed(6)}</td>
      <td>${point.actual_duty_percent == null ? "—" : Number(point.actual_duty_percent).toFixed(6)}</td>
      <td>${formatSequence(point.command_sequence)}</td>
      <td>${Array.isArray(point.cycle_ids) ? point.cycle_ids.join(", ") : "—"}</td>
      <td>${Array.isArray(point.p_samples_w) ? point.p_samples_w.map((value) => Number(value).toFixed(6)).join(", ") : "—"}</td>
      <td>${formatPower(point.mean_p_w)}</td>
      <td>${formatPower(point.min_p_w)}</td>
      <td>${formatPower(point.max_p_w)}</td>
      <td>${formatPower(point.sample_stdev_p_w)}</td>
      <td>${point.utc || "—"}</td>
    </tr>
  `).join("");

  target.innerHTML = `
    <div class="load-control-p-characterization-table-wrap">
      <table class="load-control-p-characterization-table">
        <thead>
          <tr>
            <th>Requested duty / %</th>
            <th>Actual duty / %</th>
            <th>Command sequence</th>
            <th>Measurement cycles</th>
            <th>Signed canonical P samples / W</th>
            <th>Mean P</th>
            <th>Min P</th>
            <th>Max P</th>
            <th>Sample stdev P</th>
            <th>UTC</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function renderStatus(status) {
  state.status = status || { state: "IDLE" };
  const mode = state.status.state || "IDLE";
  const active = ACTIVE_STATES.has(mode);
  const inputLocked = active || state.busy;

  setText("lc-pchar-state", mode);
  setText("lc-pchar-mode", state.status.mode || "—");
  const pointIndex = state.status.point_index == null ? "—" : state.status.point_index;
  const pointCount = state.status.point_count == null ? "—" : state.status.point_count;
  setText("lc-pchar-progress", `${pointIndex} / ${pointCount}`);
  setText("lc-pchar-current-duty", formatDuty(state.status.current_requested_duty_percent));
  setText("lc-pchar-settling", String(state.status.settling_cycles_observed ?? 0));
  setText("lc-pchar-measured", String(state.status.measured_cycles_observed ?? 0));
  setText(
    "lc-pchar-safe",
    state.status.safe_confirmed == null ? "—" : (state.status.safe_confirmed ? "CONFIRMED OFF" : "UNCONFIRMED"),
  );
  setText("lc-pchar-error", state.status.last_error || "—");
  renderResults(state.status.points);

  const source = element("lc-pchar-source");
  const phase = element("lc-pchar-phase");
  const duties = element("lc-pchar-duties");
  const manual = element("lc-pchar-manual-capture");
  const sweep = element("lc-pchar-auto-sweep");
  if (source) source.disabled = inputLocked;
  if (phase) phase.disabled = inputLocked;
  if (duties) duties.disabled = inputLocked;
  if (manual) manual.disabled = inputLocked || !selectionReady();
  if (sweep) sweep.disabled = inputLocked || !sweepReady();

  const section = document.querySelector(".load-control-p-characterization");
  if (section) section.dataset.state = mode;
}

function renderMessage(message) {
  setText("lc-pchar-message", message || "");
}

async function refreshSources() {
  try {
    const payload = await getSafeTestSources();
    state.sources = Array.isArray(payload) ? payload : [];
    renderSources();
  } catch (error) {
    state.sources = [];
    renderSources();
    renderMessage(`Source list unavailable: ${error.message}`);
  }
}

async function refreshStatus() {
  if (!panelVisible()) return;
  try {
    renderStatus(await getCharacterizationStatus());
  } catch (error) {
    renderMessage(`Characterization status unavailable: ${error.message}`);
  }
}

async function runAction(action, successMessage) {
  if (state.busy) return;
  state.busy = true;
  renderStatus(state.status);
  renderMessage("");
  try {
    const status = await action();
    renderStatus(status);
    renderMessage(successMessage);
  } catch (error) {
    renderMessage(error.message);
    await refreshStatus();
  } finally {
    state.busy = false;
    renderStatus(state.status);
  }
}

function createUi() {
  const slot = element("lc-characterization-slot");
  if (!slot || element("lc-pchar-state")) return;

  const section = document.createElement("section");
  section.className = "load-control-section load-control-primary-section load-control-p-characterization";
  section.dataset.state = "IDLE";
  section.innerHTML = `
    <div class="load-control-section-header">
      <h3>P Characterization</h3>
      <span>Stage 4B · controlled physical experiment</span>
    </div>
    <p class="load-control-section-note load-control-p-characterization-boundary">
      Physical PWM commands are sent. P is the only characterized measurement. The Viewer records signed canonical P without sign repair. Each point uses 2 settling cycles and 3 measured cycles. The qualified characterization range is 25–75 %. Final OFF = 0 % must be acknowledged. No PID or regulator is active.
    </p>
    <div class="load-control-p-characterization-config">
      <label>Emonio source
        <select id="lc-pchar-source"><option value="">Choose Emonio source</option></select>
      </label>
      <label>Phase
        <select id="lc-pchar-phase">
          <option value="">Choose phase</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
      </label>
      <label>Explicit duty points / %
        <input id="lc-pchar-duties" type="text" inputmode="decimal" placeholder="25, 35, 45, 55, 65, 75">
      </label>
    </div>
    <div class="load-control-actions load-control-p-characterization-actions">
      <button id="lc-pchar-manual-capture" type="button" disabled>CAPTURE CURRENT DUTY</button>
      <button id="lc-pchar-auto-sweep" type="button" disabled>RUN EXPLICIT SWEEP</button>
    </div>
    <div class="load-control-p-characterization-status" aria-label="P characterization status">
      <div><span>State</span><strong id="lc-pchar-state">IDLE</strong></div>
      <div><span>Mode</span><strong id="lc-pchar-mode">—</strong></div>
      <div><span>Point</span><strong id="lc-pchar-progress">— / —</strong></div>
      <div><span>Current requested duty</span><strong id="lc-pchar-current-duty">—</strong></div>
      <div><span>Settling cycles observed</span><strong id="lc-pchar-settling">0</strong></div>
      <div><span>Measured cycles observed</span><strong id="lc-pchar-measured">0</strong></div>
      <div><span>Final safe state</span><strong id="lc-pchar-safe">—</strong></div>
      <div><span>Last error</span><strong id="lc-pchar-error">—</strong></div>
    </div>
    <div id="lc-pchar-results" class="load-control-p-characterization-results" aria-label="P characterization evidence"></div>
    <div id="lc-pchar-message" class="load-control-status-text" aria-live="polite"></div>
  `;

  slot.append(section);

  const updateControls = () => renderStatus(state.status || { state: "IDLE", points: [] });
  element("lc-pchar-source").addEventListener("change", updateControls);
  element("lc-pchar-phase").addEventListener("change", updateControls);
  element("lc-pchar-duties").addEventListener("input", updateControls);

  element("lc-pchar-manual-capture").addEventListener("click", () => runAction(
    () => captureCurrentDuty(readSelection()),
    "Current qualified duty was characterized and final OFF was requested.",
  ));
  element("lc-pchar-auto-sweep").addEventListener("click", () => {
    const selection = readSelection();
    return runAction(
      () => runExplicitSweep({
        ...selection,
        duties: parseExplicitDuties(element("lc-pchar-duties").value),
      }),
      "Explicit characterization sweep finished and final OFF was requested.",
    );
  });

  renderStatus({ state: "IDLE", points: [] });
}

function startRefreshLoop() {
  if (state.timer != null) return;
  state.timer = window.setInterval(() => {
    if (panelVisible()) refreshStatus();
  }, REFRESH_MS);
}

async function initialize() {
  createUi();
  await refreshSources();
  if (panelVisible()) await refreshStatus();
  startRefreshLoop();

  const panel = element("load-control-panel");
  if (panel) {
    const observer = new MutationObserver(() => {
      if (panelVisible()) {
        refreshSources();
        refreshStatus();
      }
    });
    observer.observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize, { once: true });
} else {
  initialize();
}
