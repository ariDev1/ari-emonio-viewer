# Negative-Condition Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the partial v0.4.16 one-shot trigger with continuous per-Emonio monitoring that records every selected `P < 0` and/or `PF < 0` interval on Phase A, B, and C, including overlapping events, exact transition evidence, bounded gap evidence, automatic recording stop, and automatic readiness for the next event.

**Architecture:** Keep `RecordingManager` as the single recording and monitor owner. Add a pure negative-condition evaluator under `recording/` and evaluate it inside the existing `RecordingManager` RuntimeEventBus consumer. The first active monitored condition starts one session from the exact canonical sample; all overlapping phase/measurement events use the same session; a monitor-owned session stops when all monitored conditions clear; the monitor then returns to WAITING without changing acquisition, Modbus, measurement, RuntimeStore, RuntimeEventBus, or SCOPE architecture.

**Tech Stack:** Python 3.12, dataclasses, enum, aiohttp, existing RuntimeEventBus/RuntimeStore/RecordingManager/SessionRecorder, vanilla JavaScript ES modules, structured CSS, pytest, Node-based browser tests.

**Spec:** `docs/superpowers/specs/2026-08-31-triggered-recording-design.md`

## Global Constraints

- Work on branch `testing` only.
- Do not modify or merge `main`.
- Target identity is `v0.4.16 Testing` only after all monitor feature tests pass.
- The partial one-shot trigger implementation on `testing` is superseded development material, not the final public model.
- The final candidate must not expose one-shot ARMED/DISARMED trigger controls or public `/api/v1/recording/trigger/*` routes.
- Modbus/TCP stays read-only.
- Do not modify `src/emonio_viewer/modbus/*`.
- Do not modify `src/emonio_viewer/measurement/*`.
- Do not modify `src/emonio_viewer/acquisition/*`.
- Do not modify `src/emonio_viewer/runtime/events.py`.
- Do not modify `src/emonio_viewer/runtime/store.py`.
- Do not modify `src/emonio_viewer/scope/*`.
- Canonical P/Q signs, quadrants, measurement validation, acquisition timing, and register decoding stay unchanged.
- Monitor decisions use exact canonical `MeasurementSample` values only.
- Display rounding never affects monitor decisions.
- Eligible measurement quality is exactly `VALID` or `DEGRADED`.
- No smoothing, averaging, interpolation, resampling, hysteresis, debounce, epsilon, sign correction, or synthetic samples.
- Threshold is fixed at exact numeric `0.0`.
- Supported monitor conditions are exactly `P_NEGATIVE`, `PF_NEGATIVE`, and `P_OR_PF_NEGATIVE`.
- Supported phases are exactly A, B, and C. TOTAL is out of scope.
- Exact negative start is `previous >= 0` and `current < 0`.
- Exact negative end is `previous < 0` and `current >= 0`.
- An exact crossing requires consecutive cycle IDs and no continuity break.
- A gap, invalid/stale sample, non-finite selected value, or same-device acquisition diagnostic prevents an exact crossing claim across that break.
- Viewer restart always starts monitor OFF.
- Monitor configuration and enabled state are runtime-only in v0.4.16.
- One Emonio has at most one active recording session.
- Manual operator RECORD/STOP has higher authority than automatic monitoring.
- Manual STOP never causes immediate automatic restart for the same still-active negative interval.
- No pre-trigger buffer.
- Measurement CSV schema and numeric serialization stay unchanged.
- Structured monitor event evidence uses the existing `events.csv` columns.

---

## File Structure

### Create

- `src/emonio_viewer/recording/negative_monitor.py` — pure monitor configuration, selected condition keys, exact/boundary evaluation, and runtime condition state.
- `tests/unit/test_negative_monitor.py` — pure monitor truth tables, startup, gap, reconnect, duplicate/stale, and multi-condition tests.
- `frontend/js/recording-monitor.js` — DOM-free monitor status normalization.
- `frontend/css/recording-monitor.css` — monitor drawer styles only.
- `tests/browser/test_negative_monitor_ui.py` — monitor API/state/drawer/CSS contract tests.

### Modify

- `src/emonio_viewer/recording/recorder.py` — monitor ownership, enable floor, active recording ownership, event-consumer evaluation, automatic start/stop, manual authority, gap/reconnect hooks, and failure handling.
- `src/emonio_viewer/recording/session.py` — optional negative-monitor session provenance only.
- `src/emonio_viewer/server/api.py` — monitor endpoints/status and successful disconnect continuity notification.
- `frontend/js/api.js` — APPLY/ENABLE/DISABLE monitor requests; remove one-shot trigger requests.
- `frontend/js/recording-state.js` — normalize monitor status while preserving active/error recording behavior.
- `frontend/js/app.js` — replace trigger drawer controls with negative-condition monitor controls and phase status.
- `frontend/css/recording.css` — import `recording-monitor.css`; remove trigger stylesheet import.
- `tests/unit/test_recording.py` — manager ownership, exact automatic start, auto-stop, manual authority, provenance, and failure tests.
- `tests/unit/test_recording_dashboard.py` — manual status compatibility and monitor status behavior.
- `tests/integration/test_server.py` — extend the existing `FakeRecordingManager`; do not create a second API fixture system.
- `tests/integration/test_multi_device.py` — independent monitor state and recording ownership for multiple Emonios.
- `tests/integration/test_end_to_end_sign.py` — change only if an additional monitor-specific sign assertion is required; do not change scientific production code.
- `pyproject.toml` — set version to `0.4.16` only in the release-identity task.
- `src/emonio_viewer/__init__.py` — set `__version__ = "0.4.16"` only in the release-identity task.
- `tests/unit/test_release_identity.py` — expect `0.4.16` only in the release-identity task.
- `README.md` — describe v0.4.16 as Testing and document the monitor controls after automated acceptance.

### Delete after replacement tests are GREEN

- `src/emonio_viewer/recording/trigger.py`
- `tests/unit/test_recording_trigger.py`
- `frontend/js/recording-trigger.js`
- `frontend/css/recording-trigger.css`
- `tests/browser/test_triggered_recording_ui.py`

Do not delete these files before the replacement monitor tests prove the new behavior. Do not keep both public automation models in the final candidate.

---

### Task 1: Pure Negative-Condition Monitor Engine

**Files:**
- Create: `src/emonio_viewer/recording/negative_monitor.py`
- Create: `tests/unit/test_negative_monitor.py`

**Interfaces:**

```python
class NegativeCondition(str, Enum):
    P_NEGATIVE = "P_NEGATIVE"
    PF_NEGATIVE = "PF_NEGATIVE"
    P_OR_PF_NEGATIVE = "P_OR_PF_NEGATIVE"

class MonitorPhase(str, Enum):
    A = "A"
    B = "B"
    C = "C"

class MonitorMeasurement(str, Enum):
    P = "P"
    PF = "PF"

class MonitorBoundary(str, Enum):
    MONITOR_START = "MONITOR_START"
    GAP = "GAP"
    RECONNECT = "RECONNECT"

@dataclass(frozen=True, slots=True, order=True)
class ConditionKey:
    phase: MonitorPhase
    measurement: MonitorMeasurement

@dataclass(frozen=True, slots=True)
class NegativeMonitorConfig:
    device_id: str
    condition: NegativeCondition
    phases: tuple[MonitorPhase, ...]
    recording_interval_s: float

@dataclass(frozen=True, slots=True)
class NegativeMonitorEvent:
    name: str
    phase: MonitorPhase
    measurement: MonitorMeasurement
    cycle_id: int
    occurred_utc: datetime
    value: float
    continuity: str

@dataclass(slots=True)
class NegativeMonitorRuntime:
    config: NegativeMonitorConfig
    enabled_utc: datetime
    enable_floor_cycle_id: int | None
    previous_cycle_id: int | None = None
    active_keys: set[ConditionKey] = field(default_factory=set)
    initialized_keys: set[ConditionKey] = field(default_factory=set)
    pending_boundary: MonitorBoundary | None = MonitorBoundary.MONITOR_START

@dataclass(frozen=True, slots=True)
class NegativeMonitorEvaluation:
    events: tuple[NegativeMonitorEvent, ...]
    active_keys: tuple[ConditionKey, ...]
    aggregate_active: bool
    first_activation: NegativeMonitorEvent | None
    all_clear_transition: bool
```

Pure functions:

```python
selected_condition_keys(config: NegativeMonitorConfig) -> tuple[ConditionKey, ...]
extract_condition_value(sample: MeasurementSample, key: ConditionKey) -> float
invalidate_monitor_continuity(runtime: NegativeMonitorRuntime, boundary: MonitorBoundary) -> None
evaluate_monitor_sample(runtime: NegativeMonitorRuntime, sample: MeasurementSample) -> NegativeMonitorEvaluation
```

Use deterministic key order:

```text
phase: A, B, C
measurement: P, PF
```

- [ ] **Step 1: Write failing configuration and key-selection tests**

Test exact supported combinations:

```python
def test_p_negative_selects_p_for_each_selected_phase():
    cfg = NegativeMonitorConfig(
        device_id="emonio-a",
        condition=NegativeCondition.P_NEGATIVE,
        phases=(MonitorPhase.A, MonitorPhase.C),
        recording_interval_s=2.0,
    )
    assert selected_condition_keys(cfg) == (
        ConditionKey(MonitorPhase.A, MonitorMeasurement.P),
        ConditionKey(MonitorPhase.C, MonitorMeasurement.P),
    )
```

Also assert:

```text
empty phases -> ValueError("at least one monitor phase is required")
duplicate phases -> ValueError("monitor phases must be unique")
non-finite interval -> ValueError("recording interval must be finite")
interval <= 0 -> ValueError("recording interval must be > 0")
```

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/unit/test_negative_monitor.py
```

Expected: FAIL because `negative_monitor.py` does not exist.

- [ ] **Step 3: Implement enums, dataclasses, validation, explicit field maps, and deterministic key order**

Use explicit phase mapping only:

```python
_PHASE_ATTR = {
    MonitorPhase.A: "phase_a",
    MonitorPhase.B: "phase_b",
    MonitorPhase.C: "phase_c",
}
_MEASUREMENT_ATTR = {
    MonitorMeasurement.P: "p",
    MonitorMeasurement.PF: "pf",
}
```

Do not import Modbus, acquisition, browser history, or SCOPE code.

- [ ] **Step 4: Write failing exact-transition tests**

For one key, prove:

```text
previous +1.0 -> current -1.0 = NEGATIVE_START
previous  0.0 -> current -1.0 = NEGATIVE_START
previous -1.0 -> current  0.0 = NEGATIVE_END
previous -1.0 -> current +1.0 = NEGATIVE_END
negative -> negative = no transition
non-negative -> non-negative = no transition
```

Assert event UTC equals current `cycle_finished_utc`, cycle ID equals current cycle, and value equals the exact current canonical value.

- [ ] **Step 5: Implement exact transition evaluation with no epsilon**

An exact transition is permitted only when the current cycle is exactly previous cycle + 1 and there is no pending boundary.

- [ ] **Step 6: Write failing monitor-start tests**

First eligible post-enable sample:

```text
non-negative key -> initialize NORMAL, no event
negative key -> NEGATIVE_PRESENT_AT_MONITOR_START
several negative keys on same sample -> one event per key in deterministic order
pre-enable queued cycle <= enable_floor_cycle_id -> ignored with no state change
other-device sample -> ignored with no state change
```

The first negative event in deterministic order must be returned as `first_activation`.

- [ ] **Step 7: Implement monitor-start baseline behavior**

`NEGATIVE_PRESENT_AT_MONITOR_START` uses continuity `MONITOR_START`. It is presence evidence, not a crossing claim.

- [ ] **Step 8: Write failing gap and reconnect boundary tests**

Required behavior after `invalidate_monitor_continuity`:

```text
known negative -> current negative = NEGATIVE_PRESENT_AFTER_GAP / RECONNECT
known negative -> current non-negative = NEGATIVE_NOT_PRESENT_AFTER_GAP / RECONNECT
known normal -> current negative = NEGATIVE_PRESENT_AFTER_GAP / RECONNECT
known normal -> current non-negative = no negative event
```

A newer cycle gap detected from cycle IDs must automatically create a GAP boundary before the current sample is evaluated.

A duplicate or stale cycle must be ignored and must not replace previous evidence.

- [ ] **Step 9: Write failing invalid-quality and non-finite tests**

If sample quality is not `VALID` or `DEGRADED`, invalidate continuity as GAP and return no transition event.

If any selected P/PF value is non-finite, invalidate continuity as GAP and return no transition event. Do not partially claim an exact transition from the same sample.

- [ ] **Step 10: Implement boundary, duplicate/stale, quality, and finite-value rules**

Keep the last known active key set across the evidence break. The first later eligible sample replaces that known state using boundary event names and never claims an exact crossing across the break.

- [ ] **Step 11: Write failing aggregate P-or-PF tests**

For `P_OR_PF_NEGATIVE`, prove P and PF transitions are independent and aggregate phase/device activity remains active while either condition is negative.

- [ ] **Step 12: Run GREEN**

```bash
pytest -q tests/unit/test_negative_monitor.py
```

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add src/emonio_viewer/recording/negative_monitor.py tests/unit/test_negative_monitor.py
git commit -m "feat: add deterministic negative-condition monitor engine"
```

---

### Task 2: RecordingManager Monitor Configuration, Enable Floor, and Session Ownership

**Files:**
- Modify: `src/emonio_viewer/recording/recorder.py`
- Modify: `tests/unit/test_recording.py`

**Interfaces:**

```python
class MonitorOperationalState(str, Enum):
    OFF = "OFF"
    WAITING = "WAITING"
    RECORDING = "RECORDING"
    WAITING_FOR_CLEAR = "WAITING_FOR_CLEAR"

class RecordingOwner(str, Enum):
    MANUAL = "MANUAL"
    NEGATIVE_CONDITION_MONITOR = "NEGATIVE_CONDITION_MONITOR"

RecordingManager.configure_monitor(config: NegativeMonitorConfig) -> dict
RecordingManager.enable_monitor(device_id: str) -> dict
RecordingManager.disable_monitor(device_id: str) -> dict
RecordingManager.monitor_statuses() -> tuple[dict, ...]
RecordingManager.note_device_disconnect(device_id: str, occurred_utc: datetime) -> None
```

Internal state under the existing `RLock`:

```python
self._monitor_configs: dict[str, NegativeMonitorConfig] = {}
self._monitor_runtime: dict[str, NegativeMonitorRuntime] = {}
self._monitor_state: dict[str, MonitorOperationalState] = {}
self._monitor_last_event: dict[str, dict] = {}
self._active_owner: dict[str, RecordingOwner] = {}
```

- [ ] **Step 1: Write failing per-device configuration/status tests**

Prove two devices can store independent monitor configurations, monitor status order is sorted by device ID, and a new manager instance starts with no enabled monitor state.

Expected status shape:

```python
{
    "device_id": "emonio-a",
    "state": "OFF",
    "config": {
        "condition": "P_OR_PF_NEGATIVE",
        "phases": ["A", "B", "C"],
        "recording_interval_s": 2.0,
    },
    "active_conditions": [],
    "last_event": None,
}
```

- [ ] **Step 2: Write failing interval and command-disable tests**

`configure_monitor`, `enable_monitor`, and `disable_monitor` must require recording commands enabled. `configure_monitor` must use the existing `_validate_recording_interval` rule against the selected device `poll_interval_s`.

- [ ] **Step 3: Implement configuration and OFF status**

Accepted APPLY behavior:

```text
require commands enabled
require known device
validate recording interval
apply DISABLE semantics to any existing monitor runtime
store new config
state = OFF
```

If a monitor-owned recording exists when configuration is replaced, stop it cleanly. If a manual-owned recording exists, leave that session active and remove only monitor runtime state.

- [ ] **Step 4: Write failing enable-floor tests**

On ENABLE, snapshot only the current RuntimeStore last sample cycle ID as `enable_floor_cycle_id`. Do not use RuntimeStore as the event sample source.

```text
last sample cycle 100 -> queued cycle <=100 cannot initialize or fire monitor
no last sample -> floor None
```

- [ ] **Step 5: Implement ENABLE and DISABLE**

ENABLE:

```text
require commands enabled
require known device
require stored config
snapshot enable floor
create NegativeMonitorRuntime with MONITOR_START pending boundary
state = WAITING
```

DISABLE:

```text
manual-owned recording -> leave recording active
monitor-owned recording -> stop recording cleanly
clear monitor runtime and active condition state
state = OFF
keep stored config and last-event evidence
```

- [ ] **Step 6: Write failing active recording ownership tests**

Prove manual `start()` sets owner MANUAL. Prove stop/removal clears owner. Prove owner state is per Emonio.

- [ ] **Step 7: Implement recording owner tracking without changing `SessionRecorder` measurement behavior**

Do not replace `_active` with a second recorder collection. Keep `_active[device_id]` authoritative and add only the owner map required for monitor/manual control rules.

- [ ] **Step 8: Write failing explicit-disconnect continuity test**

A successful disconnect notification while monitor enabled must set pending boundary `RECONNECT`, even if the next canonical reconnect sample has cycle ID exactly previous + 1.

If a recorder is active, write a deterministic `DEVICE_DISCONNECTED` event using the provided disconnect UTC; do not invent a measurement cycle ID.

- [ ] **Step 9: Implement `note_device_disconnect`**

Set the monitor boundary to RECONNECT. This server-to-recording notification is required because acquisition reconnect deliberately continues cycle numbering and therefore cycle identity alone cannot prove that a disconnect occurred.

Do not modify acquisition code.

- [ ] **Step 10: Run GREEN**

```bash
pytest -q tests/unit/test_negative_monitor.py tests/unit/test_recording.py
```

Expected: PASS for configuration, enable floor, ownership, and disconnect boundary tests.

- [ ] **Step 11: Commit**

```bash
git add src/emonio_viewer/recording/recorder.py tests/unit/test_recording.py
git commit -m "feat: add negative monitor ownership and control state"
```

---

### Task 3: Automatic Recording START/STOP, Event Evidence, Manual Authority, and Fail-Closed Errors

**Files:**
- Modify: `src/emonio_viewer/recording/recorder.py`
- Modify: `src/emonio_viewer/recording/session.py`
- Modify: `tests/unit/test_recording.py`
- Modify: `tests/unit/test_recording_dashboard.py`

**Interfaces:**

Extend `SessionRecorder.create` without changing existing callers:

```python
SessionRecorder.create(
    root,
    first_sample,
    device,
    recording_interval_s,
    application_version,
    started_utc=None,
    monitor_evidence=None,
)
```

Extend metadata creation similarly:

```python
initial_session_metadata(..., monitor_evidence: dict | None = None) -> dict
```

Add manager helpers:

```python
RecordingManager._process_monitor_sample(sample: MeasurementSample) -> list[DiagnosticEvent]
RecordingManager._start_monitor_recording(
    device_id: str,
    sample: MeasurementSample,
    evaluation: NegativeMonitorEvaluation,
) -> SessionRecorder
RecordingManager._write_monitor_events(
    recorder: SessionRecorder,
    events: tuple[NegativeMonitorEvent, ...],
) -> None
```

- [ ] **Step 1: Write failing exact first-sample automatic-start test**

Arrange RuntimeStore with a newer sample than the event-consumer sample. ENABLE monitor and evaluate the exact event sample that proves `P >= 0 -> P < 0`.

Assert:

```text
recording starts from event-consumer sample, not RuntimeStore sample
session started_utc = firing sample cycle_finished_utc
first measurements.csv row cycle_id = firing cycle_id
owner = NEGATIVE_CONDITION_MONITOR
monitor state = RECORDING
```

- [ ] **Step 2: Implement automatic start from exact evaluation sample**

Never re-read RuntimeStore between monitor evaluation and `SessionRecorder.create()`.

If several conditions activate on the same sample, select session start provenance using deterministic A/B/C then P/PF event order.

- [ ] **Step 3: Write failing monitor event evidence tests**

Assert existing `events.csv` columns remain unchanged and detail is deterministic:

```text
phase=B;measurement=P;value=-36.807934;threshold=0.0;continuity=EXACT
```

Required event names:

```text
NEGATIVE_PRESENT_AT_MONITOR_START
NEGATIVE_START
NEGATIVE_END
NEGATIVE_PRESENT_AFTER_GAP
NEGATIVE_NOT_PRESENT_AFTER_GAP
NEGATIVE_PRESENT_AFTER_RECONNECT
NEGATIVE_NOT_PRESENT_AFTER_RECONNECT
```

Use Python `repr()` semantics for exact finite numeric values, consistent with existing scientific CSV precision policy.

- [ ] **Step 4: Implement event writing after monitor evaluation**

When a recorder exists, write every monitor event to that same recorder. Do not add monitor columns to `measurements.csv`.

If no recorder exists and an activating event starts a monitor-owned session, create the session first from the exact sample and then write all monitor events from that sample.

- [ ] **Step 5: Write failing automatic-stop and re-arm tests**

Prove overlapping behavior:

```text
A P starts negative -> one monitor-owned session starts
B P starts negative -> same session
A P clears -> same session continues
B P clears -> monitor-owned session stops
monitor state -> WAITING
later C P starts negative -> a new session starts automatically
```

- [ ] **Step 6: Implement automatic stop only for monitor-owned sessions**

When aggregate active state becomes false:

```text
monitor-owned session -> stop session, clear owner, state WAITING
manual-owned session -> keep session active, state WAITING
```

- [ ] **Step 7: Write failing manual RECORD tests**

Prove:

```text
monitor WAITING + manual RECORD -> owner MANUAL, monitor remains enabled
negative event during manual session -> event is written into same session, no second session
all conditions clear -> monitor WAITING, manual session continues
ENABLE while manual recording active -> allowed; first post-enable negative sample writes NEGATIVE_PRESENT_AT_MONITOR_START into manual session
```

- [ ] **Step 8: Implement manual recording coexistence**

Do not let monitor automation replace or stop a manual-owned session.

- [ ] **Step 9: Write failing manual STOP suppression tests**

Cover:

```text
manual STOP while no active negative condition -> recording stops, monitor WAITING
manual STOP while negative condition active -> recording stops, monitor WAITING_FOR_CLEAR
while WAITING_FOR_CLEAR and condition remains negative -> no automatic restart
last active condition clears -> monitor WAITING
next new negative transition -> automatic recording may start
```

- [ ] **Step 10: Implement `WAITING_FOR_CLEAR`**

Continue condition evaluation so the monitor can detect when all conditions clear. Do not create a hidden event journal when no recording session exists. Keep last-event/status evidence in runtime only.

- [ ] **Step 11: Write failing startup/gap/reconnect automatic-start tests**

Prove a negative condition already present on the first post-enable sample starts recording with `NEGATIVE_PRESENT_AT_MONITOR_START`.

Prove a previously normal condition that is negative on the first post-gap or post-reconnect sample may start recording with `NEGATIVE_PRESENT_AFTER_GAP` or `NEGATIVE_PRESENT_AFTER_RECONNECT`, but never `NEGATIVE_START`.

- [ ] **Step 12: Write failing monitor-start creation-failure test**

Monkeypatch `SessionRecorder.create` to raise. Assert:

```text
no active recorder
monitor remains enabled
monitor state WAITING_FOR_CLEAR when condition remains active
no automatic retry on the next still-negative sample
failure status identifies start_source NEGATIVE_CONDITION_MONITOR
failure includes device_id, failed_cycle_id, failed_utc, error_type, error_detail
one DiagnosticEvent named NEGATIVE_MONITOR_RECORDING_START_ERROR is published
```

- [ ] **Step 13: Implement fail-closed start failure**

Use the exact event sample cycle/time for failure evidence. Do not report RECORDING and do not retry the same continuous condition.

- [ ] **Step 14: Write failing active recording write-failure test**

After existing recorder failure handling runs, assert monitor state becomes WAITING_FOR_CLEAR if a negative condition is still active, otherwise WAITING. No replacement session is created for the same condition.

- [ ] **Step 15: Implement recording-failure monitor transition**

Reuse existing recording ERROR finalization. Add only monitor state transition and owner cleanup.

- [ ] **Step 16: Write manual metadata compatibility test**

Assert a manual recording still has exactly the existing manual `recording` metadata structure and does not gain monitor provenance.

Monitor-owned metadata must add:

```json
{
  "recording": {
    "interval_s": 2.0,
    "start_source": "NEGATIVE_CONDITION_MONITOR",
    "monitor": {
      "condition": "P_OR_PF_NEGATIVE",
      "phases": ["A", "B", "C"],
      "start_phase": "B",
      "start_measurement": "P",
      "start_event": "NEGATIVE_START",
      "start_cycle_id": 1254,
      "start_utc": "canonical cycle_finished_utc",
      "start_value": -36.807934
    }
  }
}
```

- [ ] **Step 17: Run GREEN**

```bash
pytest -q tests/unit/test_negative_monitor.py tests/unit/test_recording.py tests/unit/test_recording_dashboard.py
```

Expected: PASS.

- [ ] **Step 18: Commit**

```bash
git add src/emonio_viewer/recording/recorder.py src/emonio_viewer/recording/session.py tests/unit/test_recording.py tests/unit/test_recording_dashboard.py
git commit -m "feat: record continuous negative-condition events"
```

---

### Task 4: Replace One-Shot Trigger HTTP API with Monitor API

**Files:**
- Modify: `src/emonio_viewer/server/api.py`
- Modify: `tests/integration/test_server.py`

**Public routes:**

```text
POST /api/v1/recording/monitor/configure
POST /api/v1/recording/monitor/enable
POST /api/v1/recording/monitor/disable
GET  /api/v1/recording/status
```

Remove before Task 4 is GREEN:

```text
POST /api/v1/recording/trigger/configure
POST /api/v1/recording/trigger/arm
POST /api/v1/recording/trigger/disarm
```

Monitor configure body:

```json
{
  "device_id": "emonio-a",
  "condition": "P_OR_PF_NEGATIVE",
  "phases": ["A", "B", "C"],
  "recording_interval_s": 2.0
}
```

Status adds `monitors`:

```json
{
  "active": [],
  "errors": [],
  "monitors": []
}
```

- [ ] **Step 1: Extend the existing `FakeRecordingManager` with monitor methods and write failing API tests**

Do not create another app fixture. Add fake methods:

```python
configure_monitor(config)
enable_monitor(device_id)
disable_monitor(device_id)
monitor_statuses()
note_device_disconnect(device_id, occurred_utc)
```

- [ ] **Step 2: Write failing configure validation tests**

Required HTTP behavior:

```text
unknown device -> 404
unknown condition -> 400
phases not list -> 400
empty phases -> 400
unknown phase or TOTAL -> 400
duplicate phase -> 400
non-numeric interval -> 400
non-finite interval -> 400
interval <= 0 -> 400
interval below acquisition interval -> 400
commands disabled -> 503
valid configure -> 200 with state OFF
```

- [ ] **Step 3: Implement explicit monitor parser**

Construct `NegativeMonitorConfig` from validated enum values. Do not reuse the old free threshold/operator trigger parser because the monitor has fixed negative semantics.

- [ ] **Step 4: Write failing ENABLE/DISABLE/status tests**

Required behavior:

```text
ENABLE without config -> 409
valid ENABLE -> 200 WAITING
valid DISABLE -> 200 OFF
commands disabled -> 503
GET status -> active + errors + monitors
```

- [ ] **Step 5: Implement routes and status response**

Delete the one-shot trigger route registration and handlers from `server/api.py` in the same GREEN change so there is one public automation model only.

- [ ] **Step 6: Write failing disconnect continuity notification test**

For a successful `/devices/{device_id}/disconnect`, assert the existing lifecycle operation succeeds first and then `recording.note_device_disconnect(device_id, occurred_utc)` is called once.

For a failed disconnect command, assert no disconnect notification is sent to `RecordingManager`.

- [ ] **Step 7: Implement successful-disconnect notification without modifying acquisition**

Use server-side UTC for the lifecycle event. This notification exists only to mark the evidence boundary and optional recording event; it does not claim a measurement timestamp.

- [ ] **Step 8: Run GREEN**

```bash
pytest -q tests/integration/test_server.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/emonio_viewer/server/api.py tests/integration/test_server.py
git commit -m "feat: expose negative-condition monitor API"
```

---

### Task 5: Frontend Monitor State and API Client

**Files:**
- Create: `frontend/js/recording-monitor.js`
- Create: `tests/browser/test_negative_monitor_ui.py`
- Modify: `frontend/js/api.js`
- Modify: `frontend/js/recording-state.js`

**Interfaces:**

```javascript
export class RecordingMonitorState {
  replace(records)
  forDevice(deviceId)
}

export function configureRecordingMonitor(deviceId, config)
export function enableRecordingMonitor(deviceId)
export function disableRecordingMonitor(deviceId)
```

- [ ] **Step 1: Write failing DOM-free monitor normalization test**

Normalize exact backend values without rounding:

```javascript
{
  device_id: "emonio-a",
  state: "RECORDING",
  config: {
    condition: "P_OR_PF_NEGATIVE",
    phases: ["A", "B", "C"],
    recording_interval_s: 2
  },
  active_conditions: [
    {phase: "B", measurement: "P", value: -36.807934}
  ],
  last_event: {
    event: "NEGATIVE_START",
    phase: "B",
    measurement: "P",
    cycle_id: 1254,
    utc: "...",
    value: -36.807934
  }
}
```

Reject malformed state, condition, phase, measurement, non-finite interval, and non-finite event/active values.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/browser/test_negative_monitor_ui.py
```

Expected: FAIL because `recording-monitor.js` does not exist.

- [ ] **Step 3: Implement DOM-free monitor normalizer**

Do not import history, acquisition, Modbus, SCOPE, or DOM code.

- [ ] **Step 4: Write failing API-client contract tests**

Assert `api.js` exports the three monitor functions and uses only `/api/v1/recording/monitor/*` for automation.

- [ ] **Step 5: Implement monitor API client and remove trigger API exports**

`configureRecordingMonitor` sends:

```javascript
{
  device_id: deviceId,
  condition: config.condition,
  phases: config.phases,
  recording_interval_s: config.recording_interval_s,
}
```

- [ ] **Step 6: Write failing `RecordingState` integration test**

Change signature to:

```javascript
replaceStatus(activeRecords, errorRecords, monitorRecords = [])
monitorForDevice(deviceId)
```

Monitor state must not make `isActive(deviceId)` true. Active recording remains determined only by `activeRecords`.

- [ ] **Step 7: Implement monitor state integration**

Replace the old `RecordingTriggerState` dependency with `RecordingMonitorState`.

- [ ] **Step 8: Run GREEN**

```bash
pytest -q tests/browser/test_negative_monitor_ui.py
node --check frontend/js/recording-monitor.js
node --check frontend/js/recording-state.js
node --check frontend/js/api.js
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/js/recording-monitor.js frontend/js/api.js frontend/js/recording-state.js tests/browser/test_negative_monitor_ui.py
git commit -m "feat: add negative monitor frontend state"
```

---

### Task 6: Replace Trigger Drawer with Continuous Monitor Controls

**Files:**
- Modify: `frontend/js/app.js`
- Create: `frontend/css/recording-monitor.css`
- Modify: `frontend/css/recording.css`
- Modify: `tests/browser/test_negative_monitor_ui.py`

**Stable control IDs:**

```text
recording-monitor-state
recording-monitor-condition
recording-monitor-phase-a
recording-monitor-phase-b
recording-monitor-phase-c
recording-monitor-interval
recording-monitor-apply
recording-monitor-enable
recording-monitor-disable
recording-monitor-phase-state-a
recording-monitor-phase-state-b
recording-monitor-phase-state-c
recording-monitor-last-event
```

- [ ] **Step 1: Write failing drawer structure test**

Assert the existing compact main recording strip remains present and the drawer contains the monitor controls above. Assert old `recording-trigger-*` control IDs are absent from the final `app.js` source.

- [ ] **Step 2: Write failing explicit APPLY semantics test**

Changing condition/phase/interval controls must not call backend configuration automatically.

Only `recording-monitor-apply` calls `configureRecordingMonitor`.

This fixes the observed one-shot UI problem where field changes could silently configure the backend.

- [ ] **Step 3: Write failing backend-authoritative refresh test**

After APPLY, ENABLE, DISABLE, manual RECORD, or manual STOP, the handler must call `refreshRecordingState()` before final render.

The 1-second status refresh must not overwrite a field while the operator is editing an un-applied monitor configuration. Use an explicit dirty-form flag or focused-control guard. Backend values may overwrite the form only when the form is clean or after a successful APPLY.

- [ ] **Step 4: Write failing phase status rendering tests**

Expected examples:

```text
A NORMAL
B NEGATIVE P
C NEGATIVE PF
```

For P and PF both active on one phase:

```text
B NEGATIVE P + PF
```

Render monitor states exactly:

```text
OFF
WAITING
RECORDING
WAITING FOR CLEAR
```

- [ ] **Step 5: Implement monitor drawer and handlers**

Configuration controls:

```text
CONDITION: P < 0 | PF < 0 | P < 0 OR PF < 0
PHASES: independent A/B/C checkboxes, at least one required
INTERVAL: existing valid recording intervals
APPLY
ENABLE MONITOR
DISABLE MONITOR
```

Do not expose a user threshold, operator, LEVEL/CROSSING mode, ARM, or TOTAL phase.

- [ ] **Step 6: Preserve manual control authority**

Manual RECORD and STOP stay visible and functional.

Manual STOP remains enabled only for an active recording session. The monitor itself is controlled by DISABLE MONITOR; unlike the obsolete one-shot trigger, an enabled WAITING monitor does not make the main STOP button active.

- [ ] **Step 7: Write failing structured-CSS test**

`frontend/css/recording.css` must begin with or contain one import:

```css
@import url("./recording-monitor.css");
```

All new monitor selectors must be `.recording-monitor-*` and live only in `recording-monitor.css`. No inline `style=` additions.

- [ ] **Step 8: Implement structured CSS**

Keep the instrument-like Recording drawer. Do not move existing unrelated recording styles.

- [ ] **Step 9: Run GREEN**

```bash
pytest -q tests/browser/test_negative_monitor_ui.py
node --check frontend/js/app.js
node --check frontend/js/recording-monitor.js
node --check frontend/js/recording-state.js
node --check frontend/js/api.js
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/js/app.js frontend/css/recording.css frontend/css/recording-monitor.css tests/browser/test_negative_monitor_ui.py
git commit -m "feat: add continuous negative monitor controls"
```

---

### Task 7: Multi-Device, Continuity, Scientific Regression, and One-Shot Removal

**Files:**
- Modify: `tests/integration/test_multi_device.py`
- Modify: `tests/integration/test_end_to_end_sign.py` only if needed
- Delete: `src/emonio_viewer/recording/trigger.py`
- Delete: `tests/unit/test_recording_trigger.py`
- Delete: `frontend/js/recording-trigger.js`
- Delete: `frontend/css/recording-trigger.css`
- Delete: `tests/browser/test_triggered_recording_ui.py`
- Modify any import references found by repository search only when they belong to the superseded trigger model.

- [ ] **Step 1: Write failing two-Emonio isolation test**

Prove:

```text
A-device monitor event never changes B-device monitor state
A-device automatic session never becomes B-device session
A-device manual STOP does not alter B-device monitor or recording
both devices can independently own one recording at the same time
```

- [ ] **Step 2: Write failing overlap and gap integration test through RuntimeEventBus**

Use the real RecordingManager event subscriber. Publish canonical samples and diagnostics. Prove exact crossing only for consecutive cycles and boundary presence events after a gap.

- [ ] **Step 3: Write failing explicit disconnect/reconnect integration test**

Notify successful disconnect, then publish a reconnect sample with a numerically consecutive cycle ID that changed sign. Assert the event is `NEGATIVE_PRESENT_AFTER_RECONNECT`, never `NEGATIVE_START`.

This proves the server-to-recording continuity hook protects against the acquisition coordinator's intentional continuous cycle numbering across reconnect.

- [ ] **Step 4: Run these tests RED, then implement only the minimum integration corrections required**

```bash
pytest -q tests/integration/test_multi_device.py
```

Do not change protected acquisition/science paths to make these tests pass.

- [ ] **Step 5: Prove canonical sign behavior is unchanged**

Run the existing sign-path integration test first:

```bash
pytest -q tests/integration/test_end_to_end_sign.py
```

Only add a monitor-specific assertion if the existing test does not prove that negative canonical P/PF reaches the monitor unchanged. Do not alter sign calculations.

- [ ] **Step 6: Search for obsolete trigger public model references**

Run:

```bash
grep -RInE 'recording/trigger|recording-trigger|TriggerConfig|TriggerMode|TriggerOperator|ARMED|DISARMED' src frontend tests --exclude-dir='__pycache__'
```

Classify every match. Delete or replace only matches that belong to the v0.4.16 one-shot automation model. Do not remove unrelated English words from historical docs or legitimate lifecycle state names.

- [ ] **Step 7: Delete superseded trigger modules/tests/styles after monitor replacements are GREEN**

The final runtime and frontend must have one automation model only.

- [ ] **Step 8: Run focused complete monitor regression**

```bash
pytest -q \
  tests/unit/test_negative_monitor.py \
  tests/unit/test_recording.py \
  tests/unit/test_recording_dashboard.py \
  tests/integration/test_server.py \
  tests/integration/test_multi_device.py \
  tests/integration/test_end_to_end_sign.py \
  tests/browser/test_negative_monitor_ui.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add -A src/emonio_viewer/recording frontend tests
git commit -m "refactor: replace one-shot trigger with negative monitor"
```

---

### Task 8: Release Identity, Documentation, Full Acceptance, and Protected-Path Gate

**Files:**
- Modify: `tests/unit/test_release_identity.py`
- Modify: `pyproject.toml`
- Modify: `src/emonio_viewer/__init__.py`
- Modify: `README.md`

- [ ] **Step 1: Write release-identity RED test**

Change only the test expectation to `0.4.16`, then run:

```bash
pytest -q tests/unit/test_release_identity.py
```

Expected: FAIL because production identity is still `0.4.15`.

- [ ] **Step 2: Update only the two release identity values**

```toml
# pyproject.toml
version = "0.4.16"
```

```python
# src/emonio_viewer/__init__.py
__version__ = "0.4.16"
```

- [ ] **Step 3: Run release-identity GREEN**

```bash
pytest -q tests/unit/test_release_identity.py
```

Expected: PASS.

- [ ] **Step 4: Update README with Testing-only monitor behavior**

Document:

```text
condition choices: P < 0, PF < 0, P < 0 OR PF < 0
phase selection: A/B/C
APPLY commits configuration
ENABLE MONITOR starts continuous monitoring
automatic recording starts on negative presence/event
one session covers overlapping phase events
automatic recording stops when all monitored conditions clear
automatic monitoring stays enabled for the next event
manual STOP has higher authority and can enter WAITING FOR CLEAR
Viewer restart returns monitor OFF
no pre-trigger recording
```

Do not claim field confirmation.

- [ ] **Step 5: Run syntax and diff hygiene**

```bash
git diff --check
python -m compileall -q src tests
node --check frontend/js/app.js
node --check frontend/js/api.js
node --check frontend/js/recording-state.js
node --check frontend/js/recording-monitor.js
```

Expected: all PASS/no output except normal compile status.

- [ ] **Step 6: Prove protected scientific/acquisition paths did not change from the pre-feature code baseline**

Use the established v0.4.15 code baseline:

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: empty diff and exit code 0.

If this gate fails, stop. Do not justify a protected-path change after the fact.

- [ ] **Step 7: Run full project acceptance**

```bash
./tools/ari-emonio-acceptance.sh
```

Record only gates explicitly printed by the script. Required evidence before candidate status:

```text
unit PASS
integration PASS
frontend/browser PASS
read-only gate PASS
Python compilation PASS
scientific sign path PASS
publication/package gate PASS when the script exposes it
```

Do not infer a missing gate.

- [ ] **Step 8: Verify `main` is unchanged**

Fetch/compare the remote branch. Expected trusted `main` remains:

```text
a0c19118f5a83fb61c559c1470b6aeb0950f058e
```

If remote evidence has legitimately changed since planning, report the observed SHA instead of forcing this expected value. Do not write to `main`.

- [ ] **Step 9: Commit release identity/docs only after acceptance evidence is clean**

```bash
git add pyproject.toml src/emonio_viewer/__init__.py tests/unit/test_release_identity.py README.md
git commit -m "release: prepare v0.4.16 negative monitor testing candidate"
```

- [ ] **Step 10: Field-test handoff**

Automated PASS is not field confirmation. Provide this exact field checklist:

```text
1. Enable P < 0 on A/B/C while all phases are positive -> WAITING, no recording.
2. Drive Phase B P negative -> one recording starts on the exact observed negative event sample.
3. Keep B negative and drive Phase C negative -> same session continues and logs C event.
4. Return B positive while C remains negative -> session continues.
5. Return C positive -> session stops and monitor returns WAITING.
6. Drive a later Phase A negative event -> a new session starts automatically without ENABLE again.
7. Test PF < 0 independently.
8. Test P < 0 OR PF < 0 with P and PF clearing at different times.
9. Manual STOP during an active negative interval -> no immediate restart; WAITING FOR CLEAR until all conditions clear.
10. Manual RECORD while monitor WAITING -> monitor events use the same manual session; no second session.
11. Disconnect/reconnect across a sign change -> boundary event, never a fabricated exact crossing.
12. Restart Viewer -> monitor OFF.
13. Verify events.csv phase/measurement/cycle/time/value evidence and first measurements.csv row of monitor-owned session.
14. Verify History, Density, Inspector, Vector, manual Recording, Modbus evidence, and SCOPE remain normal.
```

---

## Plan Self-Review Checklist

Before execution begins, verify:

- Every approved spec requirement maps to a task above.
- No `TODO`, `TBD`, or unspecified implementation step remains.
- Public automation routes use `monitor`, not `trigger`.
- Frontend controls use APPLY/ENABLE/DISABLE and never silently configure on field edits.
- Exact crossing, monitor-start presence, gap presence, and reconnect presence are distinct evidence classes.
- Explicit disconnect breaks continuity even when reconnect cycle numbering is consecutive.
- Manual-owned and monitor-owned recording semantics are distinct.
- Manual STOP suppression is represented by `WAITING_FOR_CLEAR`.
- One-shot trigger modules are deleted only after replacement monitor tests are GREEN.
- Protected acquisition/scientific paths remain outside the implementation scope.
- `main` is never modified by this plan.
