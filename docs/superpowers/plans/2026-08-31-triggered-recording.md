# Triggered Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic one-shot LEVEL and CROSSING triggered recording for U, I, P, Q, S, PF, and f on Phase A, B, C, or TOTAL, while preserving the existing canonical measurement and manual recording paths.

**Architecture:** Add a small pure trigger module under `src/emonio_viewer/recording/`. `RecordingManager` remains the only owner of recording and trigger runtime state and evaluates triggers inside its existing `RuntimeEventBus` consumer. A fired trigger starts `SessionRecorder` directly from the exact firing `MeasurementSample`; no RuntimeStore re-read is allowed for triggered start.

**Tech Stack:** Python 3, dataclasses, enum, aiohttp API, existing RuntimeEventBus/RuntimeStore/RecordingManager, vanilla JavaScript ES modules, structured CSS, pytest, Node-based browser tests.

**Spec:** `docs/superpowers/specs/2026-08-31-triggered-recording-design.md`

## Global Constraints

- Target branch is `testing` only.
- `main` must not be changed.
- Baseline before this design work is `b539efe7eb3a11d53a3b291254ddd0c50a2cf3df`.
- Target release identity is `v0.4.16 Testing`.
- Modbus/TCP remains read-only.
- Do not change `src/emonio_viewer/modbus/*`.
- Do not change `src/emonio_viewer/measurement/*`.
- Do not change `src/emonio_viewer/acquisition/*`.
- Do not change `src/emonio_viewer/runtime/events.py` or `src/emonio_viewer/runtime/store.py`.
- Do not change `src/emonio_viewer/scope/*`.
- Canonical P/Q signs, quadrants, validation, acquisition timing, and register decoding remain unchanged.
- Trigger evaluation uses exact canonical numeric values. Display rounding is irrelevant to trigger decisions.
- Eligible trigger quality is exactly `VALID` or `DEGRADED`, matching the current recorder.
- Qualification count is fixed at one sample.
- No smoothing, averaging, interpolation, resampling, hysteresis, debounce, or synthetic samples.
- Trigger state is per Emonio and runtime-only.
- One-shot only. No automatic retry and no automatic re-arm.
- LEVEL may fire on the first eligible post-ARM sample.
- CROSSING requires two proven consecutive post-ARM measurement cycles.
- CROSSING continuity is cleared by a same-device `DiagnosticEvent` or any cycle gap.
- Manual START while ARMED disarms the trigger before manual session creation.
- ARM while recording returns conflict and does not affect the active recording.
- Any trigger configuration update results in DISARMED state.
- The exact firing `MeasurementSample` is the first sample of a successful triggered recording.
- Triggered start time is the firing sample `cycle_finished_utc`.
- Pre-trigger recording is out of scope.

---

## File Structure

### Create

- `src/emonio_viewer/recording/trigger.py` — pure trigger configuration, exact field extraction, LEVEL/CROSSING evaluation, and continuity state.
- `tests/unit/test_recording_trigger.py` — pure trigger math and continuity tests.
- `tests/integration/test_recording_trigger_api.py` — HTTP validation, ownership, ARM/DISARM, and status contract.
- `tests/browser/test_triggered_recording_ui.py` — static/Node checks for frontend trigger state and drawer wiring.
- `frontend/js/recording-trigger.js` — frontend trigger-status normalization and selected-device trigger model.
- `frontend/css/recording-trigger.css` — trigger drawer styles only.

### Modify

- `src/emonio_viewer/recording/recorder.py` — per-device trigger ownership, ARM floor, event evaluation, exact-sample start, failure reporting.
- `src/emonio_viewer/recording/session.py` — optional triggered-start metadata only; manual metadata stays structurally unchanged.
- `src/emonio_viewer/server/api.py` — trigger routes, validation, status exposure, and conflict mapping.
- `frontend/js/api.js` — trigger configure/arm/disarm requests.
- `frontend/js/recording-state.js` — include normalized trigger status without changing active/error semantics.
- `frontend/js/app.js` — render and operate trigger controls inside the existing Recording drawer.
- `frontend/css/recording.css` — import `recording-trigger.css` only; keep trigger selectors in the new file.
- `tests/unit/test_recording.py` — RecordingManager ownership, exact first sample, trigger provenance, and start-failure tests.
- `tests/unit/test_recording_dashboard.py` — status contract remains valid for manual recording.
- `tests/integration/test_server.py` only if the existing application fixture is the established API-test entry point; do not duplicate fixture infrastructure.
- `pyproject.toml` — version `0.4.16` after feature tests pass.
- `src/emonio_viewer/__init__.py` — version `0.4.16` only.
- `tests/unit/test_release_identity.py` — expected version `0.4.16`.
- `README.md` — document `v0.4.16 Testing` as a testing-branch feature, not a trusted `main` release.

---

### Task 1: Pure Trigger Engine

**Files:**
- Create: `src/emonio_viewer/recording/trigger.py`
- Create: `tests/unit/test_recording_trigger.py`

**Interfaces:**
- Consumes: `MeasurementSample`, `SampleQuality` from the existing canonical measurement model.
- Produces:
  - `TriggerMode(str, Enum)`: `LEVEL`, `CROSSING`
  - `TriggerBlock(str, Enum)`: `A`, `B`, `C`, `TOTAL`
  - `TriggerMeasurement(str, Enum)`: `U`, `I`, `P`, `Q`, `S`, `PF`, `F`
  - `TriggerOperator(str, Enum)`: `GT`, `GE`, `LT`, `LE`
  - `@dataclass(frozen=True, slots=True) TriggerConfig`
  - `@dataclass(slots=True) TriggerRuntimeState`
  - `@dataclass(frozen=True, slots=True) TriggerFire`
  - `extract_trigger_value(sample, config) -> float`
  - `evaluate_measurement(state, sample) -> TriggerFire | None`
  - `invalidate_crossing_continuity(state) -> None`

Use this exact data contract:

```python
@dataclass(frozen=True, slots=True)
class TriggerConfig:
    device_id: str
    block: TriggerBlock
    measurement: TriggerMeasurement
    operator: TriggerOperator
    threshold: float
    mode: TriggerMode
    recording_interval_s: float


@dataclass(slots=True)
class TriggerRuntimeState:
    config: TriggerConfig
    armed_utc: datetime
    arm_floor_cycle_id: int | None
    previous_cycle_id: int | None = None
    previous_value: float | None = None
    previous_sample_utc: datetime | None = None
    last_fired_cycle_id: int | None = None
    last_fired_utc: datetime | None = None
    last_fired_value: float | None = None


@dataclass(frozen=True, slots=True)
class TriggerFire:
    cycle_id: int
    fired_utc: datetime
    value: float
```

`TriggerRuntimeState` exists only while ARMED. `RecordingManager` stores last-fired evidence separately after it consumes the armed state.

- [ ] **Step 1: Write failing tests for exact field extraction and validation**

Create parameterized tests that replace the selected canonical block measurement and prove all seven fields map exactly:

```python
@pytest.mark.parametrize(
    ("measurement", "field"),
    [
        (TriggerMeasurement.U, "vrms"),
        (TriggerMeasurement.I, "irms"),
        (TriggerMeasurement.P, "p"),
        (TriggerMeasurement.Q, "q"),
        (TriggerMeasurement.S, "s"),
        (TriggerMeasurement.PF, "pf"),
        (TriggerMeasurement.F, "frequency"),
    ],
)
def test_extract_trigger_value_uses_exact_canonical_field(real_sample, measurement, field):
    config = TriggerConfig(
        device_id=real_sample.identity.device_id,
        block=TriggerBlock.B,
        measurement=measurement,
        operator=TriggerOperator.GT,
        threshold=0.0,
        mode=TriggerMode.LEVEL,
        recording_interval_s=1.0,
    )
    assert extract_trigger_value(real_sample, config) == getattr(real_sample.phase_b.measurement, field)
```

Also test A/B/C/TOTAL mapping and reject non-finite `threshold` and `recording_interval_s` in `TriggerConfig.__post_init__`.

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```bash
pytest -q tests/unit/test_recording_trigger.py
```

Expected: FAIL because `emonio_viewer.recording.trigger` does not exist.

- [ ] **Step 3: Implement enums, config validation, and exact field extraction**

Use explicit maps, not reflection on UI strings:

```python
_BLOCK_ATTR = {
    TriggerBlock.A: "phase_a",
    TriggerBlock.B: "phase_b",
    TriggerBlock.C: "phase_c",
    TriggerBlock.TOTAL: "total",
}

_MEASUREMENT_ATTR = {
    TriggerMeasurement.U: "vrms",
    TriggerMeasurement.I: "irms",
    TriggerMeasurement.P: "p",
    TriggerMeasurement.Q: "q",
    TriggerMeasurement.S: "s",
    TriggerMeasurement.PF: "pf",
    TriggerMeasurement.F: "frequency",
}
```

Validate with `math.isfinite()` and reject `recording_interval_s <= 0`. Device acquisition-interval validation remains in `RecordingManager`/API because the pure config does not own `DeviceConfig`.

- [ ] **Step 4: Add failing LEVEL operator tests**

For each operator, test threshold equality and both sides of the threshold. LEVEL must not use previous-state evidence.

Example:

```python
def test_level_ge_fires_on_exact_threshold(real_sample):
    sample = sample_with_value(real_sample, block="A", field="p", value=100.0)
    state = armed_state(operator=TriggerOperator.GE, threshold=100.0, mode=TriggerMode.LEVEL)
    fire = evaluate_measurement(state, sample)
    assert fire is not None
    assert fire.value == 100.0
    assert fire.cycle_id == sample.identity.cycle_id
```

- [ ] **Step 5: Implement LEVEL comparison and eligible-sample rules**

Rules in code:

```python
if sample.identity.device_id != state.config.device_id:
    return None
if sample.quality not in {SampleQuality.VALID, SampleQuality.DEGRADED}:
    return None
if state.arm_floor_cycle_id is not None and sample.identity.cycle_id <= state.arm_floor_cycle_id:
    return None
value = extract_trigger_value(sample, state.config)
if not math.isfinite(value):
    return None
```

Implement operator comparison exactly; use no epsilon.

- [ ] **Step 6: Add failing CROSSING truth-table tests**

Cover exact approved semantics:

```text
GT: previous <= T and current > T
GE: previous <  T and current >= T
LT: previous >= T and current < T
LE: previous >  T and current <= T
```

Tests must prove the first eligible sample establishes baseline only and cannot fire.

- [ ] **Step 7: Add failing continuity tests**

Test all of these cases:

```text
cycle N -> N+1: crossing may fire
cycle N -> N+2: no fire; N+2 becomes new baseline
cycle N -> N: duplicate ignored
cycle N -> N-1: stale sample ignored
same-device continuity invalidation: previous evidence cleared
other-device sample: no state change
pre-ARM queued cycle <= arm floor: no state change
```

- [ ] **Step 8: Implement CROSSING state transitions**

Only update previous evidence with an eligible, newer post-ARM sample. On a gap, set the current sample as the new baseline and return `None`. On a fire, return exact `TriggerFire` evidence from the current sample.

- [ ] **Step 9: Run focused pure tests**

Run:

```bash
pytest -q tests/unit/test_recording_trigger.py
```

Expected: PASS.

- [ ] **Step 10: Commit the pure engine**

```bash
git add src/emonio_viewer/recording/trigger.py tests/unit/test_recording_trigger.py
git commit -m "feat: add deterministic recording trigger engine"
```

---

### Task 2: RecordingManager Trigger Ownership and ARM State

**Files:**
- Modify: `src/emonio_viewer/recording/recorder.py` in `RecordingManager.__init__`, `register_device`, `start`, `stop`, `stop_all`, and new trigger methods.
- Modify: `tests/unit/test_recording.py`

**Interfaces:**
- Consumes: `TriggerConfig`, `TriggerRuntimeState`, `invalidate_crossing_continuity` from Task 1.
- Produces:

```python
RecordingManager.configure_trigger(config: TriggerConfig) -> dict
RecordingManager.arm_trigger(device_id: str) -> dict
RecordingManager.disarm_trigger(device_id: str) -> dict
RecordingManager.trigger_statuses() -> tuple[dict, ...]
```

Internal maps:

```python
self._trigger_configs: dict[str, TriggerConfig] = {}
self._armed_triggers: dict[str, TriggerRuntimeState] = {}
self._trigger_last_fired: dict[str, dict] = {}
```

All three maps are protected by the existing `RLock`.

- [ ] **Step 1: Write failing per-device configuration/status tests**

Prove:

```text
configure A -> A DISARMED with exact config
configure B -> independent B DISARMED
status order is deterministic by device_id
new manager instance -> no ARMED state
```

`configure_trigger()` must validate that the device exists and that `recording_interval_s >= device.poll_interval_s` using the same interval rule as manual recording.

- [ ] **Step 2: Run the ownership tests and confirm RED**

Run only the new test names in `tests/unit/test_recording.py`; expected FAIL because the manager methods do not exist.

- [ ] **Step 3: Implement configure/disarm/status under the existing lock**

`configure_trigger()` must always remove any existing `_armed_triggers[device_id]` before storing the new config. It must not alter another device.

`disarm_trigger()` removes only the armed runtime state. It keeps the stored config and last-fired evidence.

Status JSON shape:

```python
{
    "device_id": device_id,
    "state": "ARMED" if device_id in self._armed_triggers else "DISARMED",
    "config": {
        "block": config.block.value,
        "measurement": config.measurement.value,
        "operator": config.operator.value,
        "threshold": config.threshold,
        "mode": config.mode.value,
        "recording_interval_s": config.recording_interval_s,
    },
    "armed_utc": None or state.armed_utc.isoformat(),
    "last_fired_cycle_id": None or int,
    "last_fired_utc": None or str,
    "last_fired_value": None or float,
}
```

- [ ] **Step 4: Write failing ARM-floor tests**

Test that `arm_trigger()` snapshots `RuntimeStore.get_device(device_id).last_sample.identity.cycle_id` when a sample exists. Test `None` when no sample exists.

- [ ] **Step 5: Write failing ownership-conflict tests**

Test:

```text
ARM while active recording -> RuntimeError("recording already active") or dedicated deterministic conflict error
manual START while ARMED -> trigger becomes DISARMED and manual recording starts
manual START failure after disarm -> trigger stays DISARMED
```

Keep API-specific HTTP translation for Task 4.

- [ ] **Step 6: Implement ARM and manual START precedence**

`arm_trigger()` must:

```python
self._require_commands_enabled()
if device_id in self._active:
    raise RuntimeError("recording already active")
config = self._trigger_configs.get(device_id)
if config is None:
    raise RuntimeError("trigger not configured")
snapshot = self._store.get_device(device_id)
floor = None if snapshot.last_sample is None else snapshot.last_sample.identity.cycle_id
self._armed_triggers[device_id] = TriggerRuntimeState(
    config=config,
    armed_utc=datetime.now(timezone.utc),
    arm_floor_cycle_id=floor,
)
```

In manual `start()`, after normal command/device/interval validation and before `SessionRecorder.create()`, remove the selected device from `_armed_triggers`. Do not restore it if manual session creation fails.

- [ ] **Step 7: Run RecordingManager ownership tests**

Run:

```bash
pytest -q tests/unit/test_recording.py tests/unit/test_recording_trigger.py
```

Expected: PASS.

- [ ] **Step 8: Commit ownership state**

```bash
git add src/emonio_viewer/recording/recorder.py tests/unit/test_recording.py
git commit -m "feat: add per-emonio recording trigger ownership"
```

---

### Task 3: Exact Trigger Firing, Session Provenance, and Failure Evidence

**Files:**
- Modify: `src/emonio_viewer/recording/recorder.py` in `SessionRecorder.create`, `RecordingManager._consume`, and new exact-sample start/failure helpers.
- Modify: `src/emonio_viewer/recording/session.py` in `initial_session_metadata`.
- Modify: `tests/unit/test_recording.py`
- Modify: `tests/unit/test_recording_dashboard.py` only to prove manual metadata/status remains unchanged.

**Interfaces:**
- Consumes: `evaluate_measurement()` and `TriggerFire` from Task 1; armed state from Task 2.
- Produces an internal exact-sample start path with this semantic contract:

```python
RecordingManager._start_triggered_from_sample(
    device_id: str,
    sample: MeasurementSample,
    fire: TriggerFire,
    config: TriggerConfig,
) -> SessionRecorder
```

Add optional provenance to session creation without altering the manual call contract:

```python
SessionRecorder.create(
    ...,
    started_utc: datetime | None = None,
    trigger_evidence: dict | None = None,
) -> SessionRecorder
```

`initial_session_metadata(..., trigger_evidence: dict | None = None)` adds trigger metadata only when `trigger_evidence is not None`.

- [ ] **Step 1: Write failing exact-first-sample test**

Arm a LEVEL trigger. Publish a firing sample with a distinct cycle ID and distinct P value. Before consumption, make RuntimeStore contain a newer sample. Assert the first measurement CSV row still contains the firing sample cycle/value, proving no RuntimeStore re-read selected the first sample.

- [ ] **Step 2: Write failing CROSSING event-consumer tests**

Test the manager consumer with:

```text
first post-ARM sample -> no recording
consecutive crossing sample -> recording starts
DiagnosticEvent between baseline and crossing candidate -> no recording
cycle gap between baseline and candidate -> no recording
next consecutive pair after reset -> may fire
```

Use the existing `RuntimeEventBus` and manager background consumer. Do not call trigger math directly in these integration-with-manager tests.

- [ ] **Step 3: Write failing one-shot test**

After the trigger fires, publish more satisfying samples. Assert there is still exactly one active session and trigger status is DISARMED.

- [ ] **Step 4: Write failing provenance test**

Read `session.json` and assert:

```python
assert metadata["recording"]["start_source"] == "TRIGGER"
assert metadata["recording"]["trigger"] == {
    "mode": "LEVEL",
    "block": "A",
    "measurement": "P",
    "operator": "GT",
    "threshold": 1000.0,
    "fired_cycle_id": firing_sample.identity.cycle_id,
    "fired_utc": firing_sample.timing.cycle_finished_utc.isoformat(),
    "fired_value": exact_value,
}
```

Assert `events.csv` contains `TRIGGER_FIRED` with the same cycle ID and exact-value text. Assert measurement CSV remains normal canonical recording output.

- [ ] **Step 5: Write failing manual-metadata compatibility test**

Create a manual `SessionRecorder` with no trigger evidence. Assert its `recording` object is still exactly:

```python
{"interval_s": recording_interval_s}
```

No `start_source` or `trigger` key may appear in a manual session in v0.4.16.

- [ ] **Step 6: Implement optional session provenance**

In `initial_session_metadata`, construct the current metadata first. Only when trigger evidence exists:

```python
metadata["recording"] = {
    "interval_s": recording_interval_s,
    "start_source": "TRIGGER",
    "trigger": dict(trigger_evidence),
}
```

Manual path leaves the existing object unchanged.

- [ ] **Step 7: Implement trigger evaluation in `_consume()`**

For `MeasurementSample` under the existing lock:

```text
1. Existing active recorder path remains first and unchanged for active sessions.
2. If no recorder is active and this device is ARMED, evaluate the exact event.
3. If no fire, retain updated trigger runtime evidence only.
4. If fire, copy last-fired evidence, remove ARMED state, then call exact-sample triggered start with this same event object.
```

For `DiagnosticEvent`, preserve existing active-recorder invalid-cycle behavior. Additionally, if the same device is ARMED in CROSSING mode, call `invalidate_crossing_continuity(state)`.

Do not add another RuntimeEventBus subscriber.

- [ ] **Step 8: Write failing triggered-start initialization failure test**

Monkeypatch `SessionRecorder.create` to raise `OSError("simulated trigger start failure")`. Publish a firing sample. Assert:

```text
trigger state = DISARMED
active recording absent
recording_failures contains device-specific entry
failure start_source = TRIGGER
failed_cycle_id = firing sample cycle
DiagnosticEvent event = TRIGGERED_RECORDING_START_ERROR
no automatic second attempt
```

- [ ] **Step 9: Implement deterministic trigger-start failure reporting**

Use the existing `_failed` collection. The failure object must contain these keys when no usable recorder exists:

```python
{
    "device_id": device_id,
    "device_name": self._devices[device_id].name,
    "state": "ERROR",
    "start_source": "TRIGGER",
    "session_id": "",
    "session_dir": "",
    "failed_utc": failed_utc.isoformat(),
    "failed_cycle_id": sample.identity.cycle_id,
    "error_type": type(error).__name__,
    "error_detail": str(error) or type(error).__name__,
}
```

Publish one same-device `DiagnosticEvent` named `TRIGGERED_RECORDING_START_ERROR`. Do not re-arm.

- [ ] **Step 10: Run recording tests**

Run:

```bash
pytest -q tests/unit/test_recording_trigger.py tests/unit/test_recording.py tests/unit/test_recording_dashboard.py
```

Expected: PASS.

- [ ] **Step 11: Commit exact triggered recording**

```bash
git add src/emonio_viewer/recording/recorder.py src/emonio_viewer/recording/session.py tests/unit/test_recording.py tests/unit/test_recording_dashboard.py
git commit -m "feat: start triggered recordings from exact firing sample"
```

---

### Task 4: Trigger HTTP API and Status Contract

**Files:**
- Modify: `src/emonio_viewer/server/api.py` in route registration, recording status, and new trigger handlers/validators.
- Create: `tests/integration/test_recording_trigger_api.py`
- Modify: `tests/integration/test_server.py` only if existing app/test-client fixtures must expose the new endpoints.

**Interfaces:**
- Consumes RecordingManager methods from Task 2.
- Produces endpoints:

```text
POST /api/v1/recording/trigger/configure
POST /api/v1/recording/trigger/arm
POST /api/v1/recording/trigger/disarm
GET  /api/v1/recording/status   # now includes triggers
```

Configure request body:

```json
{
  "device_id": "emonio-id",
  "block": "A",
  "measurement": "P",
  "operator": "GT",
  "threshold": 1000.0,
  "mode": "LEVEL",
  "recording_interval_s": 1.0
}
```

ARM/DISARM request body:

```json
{"device_id": "emonio-id"}
```

- [ ] **Step 1: Write failing configure validation tests**

Assert 400 for:

```text
missing/invalid block
missing/invalid measurement
missing/invalid operator
missing/invalid mode
non-numeric threshold
NaN/Infinity threshold
non-positive interval
non-finite interval
interval below device acquisition interval
```

Assert 404 for unknown `device_id`.

- [ ] **Step 2: Write failing state-transition HTTP tests**

Assert:

```text
valid configure -> 200 DISARMED
ARM without config -> 409
valid ARM -> 200 ARMED
DISARM -> 200 DISARMED
ARM while recording -> 409 and recording remains active
manual START while ARMED -> 200 RECORDING and trigger becomes DISARMED
commands disabled -> 503 for configure/arm/disarm
```

- [ ] **Step 3: Write failing status response test**

Existing keys remain:

```json
{"active": [], "errors": []}
```

and add:

```json
"triggers": [ ... ]
```

Verify exact numeric threshold is returned as a number and status does not expose Python enum representations.

- [ ] **Step 4: Implement parsers with explicit enum conversion**

Use narrow helpers in `api.py`:

```python
def _trigger_config(request, body: dict) -> TriggerConfig:
    device_id = _require_device_id(request, body)
    ...
```

Convert strings with the enum constructors and catch `ValueError` to `HTTPBadRequest`. Use `math.isfinite()` for threshold. Reuse `_positive_interval()` and `_validate_recording_interval_for_device()`.

- [ ] **Step 5: Implement routes and conflict translation**

Register exactly the three new POST routes. Convert `RuntimeError("trigger not configured")` and `RuntimeError("recording already active")` to HTTP 409. Convert `recording commands disabled` to 503.

- [ ] **Step 6: Run API tests**

Run:

```bash
pytest -q tests/integration/test_recording_trigger_api.py tests/integration/test_server.py
```

Expected: PASS.

- [ ] **Step 7: Commit API contract**

```bash
git add src/emonio_viewer/server/api.py tests/integration/test_recording_trigger_api.py tests/integration/test_server.py
git commit -m "feat: expose triggered recording API"
```

If `tests/integration/test_server.py` required no change, do not stage it.

---

### Task 5: Frontend Trigger State and API Client

**Files:**
- Create: `frontend/js/recording-trigger.js`
- Modify: `frontend/js/api.js`
- Modify: `frontend/js/recording-state.js`
- Create: `tests/browser/test_triggered_recording_ui.py`

**Interfaces:**
- Produces API functions:

```javascript
configureRecordingTrigger(deviceId, config)
armRecordingTrigger(deviceId)
disarmRecordingTrigger(deviceId)
```

- Produces frontend trigger model:

```javascript
export class RecordingTriggerState {
  replace(records)
  forDevice(deviceId)
}
```

Normalized trigger shape:

```javascript
Object.freeze({
  device_id,
  state,              // "ARMED" | "DISARMED"
  config: configOrNull,
  armed_utc,
  last_fired_cycle_id,
  last_fired_utc,
  last_fired_value,
})
```

`RecordingState` owns one `RecordingTriggerState` instance and exposes:

```javascript
triggerForDevice(deviceId)
```

- [ ] **Step 1: Write failing Node/static tests for normalization**

Use the repository's existing Node/data-URL test style. Test valid records, malformed records fail closed, and exact threshold/last-fired numeric values are retained without formatting conversion.

- [ ] **Step 2: Run browser test and confirm RED**

Run:

```bash
pytest -q tests/browser/test_triggered_recording_ui.py
```

Expected: FAIL because `recording-trigger.js` and API functions do not exist.

- [ ] **Step 3: Implement small independent trigger-state module**

Keep it independent of DOM and `app.js`. Do not import acquisition/history modules.

- [ ] **Step 4: Add API request functions**

Use existing `requestJson()`:

```javascript
export function configureRecordingTrigger(deviceId, config) {
  return requestJson("/api/v1/recording/trigger/configure", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, ...config }),
  });
}
```

ARM and DISARM send only `device_id`.

- [ ] **Step 5: Extend RecordingState without changing active/error behavior**

`replaceStatus(activeRecords, errorRecords, triggerRecords = [])` must preserve existing two-argument callers. It updates trigger state separately and does not classify ARMED as active recording.

- [ ] **Step 6: Run focused frontend state tests**

Run:

```bash
pytest -q tests/browser/test_triggered_recording_ui.py tests/unit/test_recording_dashboard.py
```

Expected: PASS.

- [ ] **Step 7: Commit frontend data model**

```bash
git add frontend/js/recording-trigger.js frontend/js/api.js frontend/js/recording-state.js tests/browser/test_triggered_recording_ui.py
git commit -m "feat: add triggered recording frontend state"
```

---

### Task 6: Recording Drawer Trigger Controls and Structured CSS

**Files:**
- Modify: `frontend/js/app.js` in recording imports, `ensureRecordingDashboardStructure`, recording-state refresh, selected-device rendering, and recording-control initialization.
- Create: `frontend/css/recording-trigger.css`
- Modify: `frontend/css/recording.css` only to import the new stylesheet.
- Modify: `tests/browser/test_triggered_recording_ui.py`

**Interfaces:**
- Consumes API/state from Task 5.
- Adds Recording drawer controls with stable IDs:

```text
recording-trigger-state
recording-trigger-mode
recording-trigger-block
recording-trigger-measurement
recording-trigger-operator
recording-trigger-threshold
recording-trigger-interval
recording-trigger-configure
recording-trigger-arm
recording-trigger-disarm
recording-trigger-last-fired
```

- [ ] **Step 1: Write failing structural browser tests**

Assert source contains the stable IDs, imports `recording-trigger.css`, and wires configure/arm/disarm API functions. Assert the compact main recording strip is not replaced by trigger controls.

- [ ] **Step 2: Write failing behavior tests for control-state rules**

Using the existing browser-test approach, prove rendering logic expresses:

```text
no selected device -> controls disabled
active recording -> ARM disabled
DISARMED configured trigger -> ARM enabled
ARMED trigger -> DISARM enabled
configuration input change -> backend configure call; returned state becomes DISARMED
manual RECORD while ARMED -> normal manual start call; refreshed backend status determines DISARMED state
```

Do not simulate final backend state only in the browser.

- [ ] **Step 3: Add trigger section to existing Recording drawer**

Create the section from JavaScript in the same style as `ensureRecordingDashboardStructure()` so current HTML layout remains stable. Use select options:

```text
MODE: LEVEL, CROSSING
PHASE: A, B, C, TOTAL
MEASUREMENT: U, I, P, Q, S, PF, f
OPERATOR: >, >=, <, <=
INTERVAL: reuse the same valid recording intervals used by manual recording controls
```

Threshold input must be `type="number"` and use a free numeric value; do not round a backend status value before assigning it to the input.

- [ ] **Step 4: Wire backend-authoritative state refresh**

`refreshRecordingState()` must pass `payload.triggers` into `recordingState.replaceStatus(...)`. After configure/arm/disarm/manual start/stop, refresh status before rendering final trigger state.

- [ ] **Step 5: Add scoped trigger CSS**

`frontend/css/recording-trigger.css` owns only `.recording-trigger-*` selectors. Keep layout compact and instrument-like. Use existing CSS variables and no inline style attributes.

At the top of `frontend/css/recording.css`, add:

```css
@import url("./recording-trigger.css");
```

Do not move existing recording styles into the new file.

- [ ] **Step 6: Run frontend tests**

Run:

```bash
pytest -q tests/browser/test_triggered_recording_ui.py
```

Then run the existing browser suite:

```bash
pytest -q tests/browser
```

Expected: PASS.

- [ ] **Step 7: Commit UI**

```bash
git add frontend/js/app.js frontend/css/recording.css frontend/css/recording-trigger.css tests/browser/test_triggered_recording_ui.py
git commit -m "feat: add triggered recording controls"
```

---

### Task 7: Multi-Device and Scientific Regression Tests

**Files:**
- Modify: `tests/unit/test_recording.py`
- Modify: `tests/integration/test_multi_device.py`
- Modify: `tests/integration/test_end_to_end_sign.py` only if necessary to assert unchanged sign behavior; do not change production science code.

**Interfaces:**
- Consumes complete backend feature.
- Produces regression evidence only.

- [ ] **Step 1: Add failing multi-device trigger-isolation test**

Configure and ARM A and B with different thresholds. Publish an A firing sample. Assert:

```text
A starts one recording and A trigger becomes DISARMED
B remains ARMED
A sample never changes B previous-value/cycle evidence
B later fires from B evidence only
```

- [ ] **Step 2: Add event-loss continuity regression**

Create a CROSSING state with baseline cycle N, then deliver cycle N+2 with a value beyond the threshold. Assert no trigger. Deliver N+3 from the opposite side as appropriate and assert only a real N+2 -> N+3 crossing can fire.

- [ ] **Step 3: Add canonical sign regression around trigger usage**

Use negative P/Q fixture evidence. Configure numeric thresholds that cross zero and prove trigger evaluation does not alter the measurement sample or canonical sign. Assert the same sample object values remain negative/positive exactly as supplied.

- [ ] **Step 4: Run backend regression groups**

Run:

```bash
pytest -q tests/unit/test_recording_trigger.py tests/unit/test_recording.py tests/integration/test_recording_trigger_api.py tests/integration/test_multi_device.py tests/integration/test_end_to_end_sign.py
```

Expected: PASS.

- [ ] **Step 5: Commit regression evidence**

```bash
git add tests/unit/test_recording.py tests/integration/test_multi_device.py tests/integration/test_end_to_end_sign.py
git commit -m "test: verify triggered recording isolation and sign integrity"
```

If `test_end_to_end_sign.py` required no modification, do not stage it.

---

### Task 8: Release Identity and Testing-Branch Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/emonio_viewer/__init__.py`
- Modify: `tests/unit/test_release_identity.py`
- Modify: `README.md`

**Interfaces:**
- Produces release identity `0.4.16` and documents feature status as Testing only.

- [ ] **Step 1: Write the failing release identity expectation**

Change the expected release identity test to `0.4.16` before changing production version files.

- [ ] **Step 2: Run release identity test and confirm RED**

Run:

```bash
pytest -q tests/unit/test_release_identity.py
```

Expected: FAIL because runtime/package identity is still `0.4.15`.

- [ ] **Step 3: Change only release identity values**

Set:

```text
pyproject.toml version = "0.4.16"
src/emonio_viewer/__init__.py __version__ = "0.4.16"
```

Do not alter other package metadata as part of the version bump.

- [ ] **Step 4: Update README status**

Document that `v0.4.16 Testing` adds one-shot LEVEL/CROSSING triggered recording and is on `testing`. Keep the trusted `main` baseline statement unchanged. Do not claim field confirmation or full acceptance before those gates occur.

- [ ] **Step 5: Run release identity and publication-sensitive unit tests**

Run:

```bash
pytest -q tests/unit/test_release_identity.py tests/unit/test_publication_contract.py tests/unit/test_publication_gate.py tests/unit/test_release_builder.py
```

Expected: PASS.

- [ ] **Step 6: Commit release identity**

```bash
git add pyproject.toml src/emonio_viewer/__init__.py tests/unit/test_release_identity.py README.md
git commit -m "chore: set v0.4.16 testing identity"
```

---

### Task 9: Full Verification and Protected-Path Audit

**Files:**
- No production changes unless a test proves a defect.
- If any failure appears, stop this task and use `superpowers:systematic-debugging` before changing code.

**Interfaces:**
- Produces acceptance evidence for the testing candidate. It does not promote or merge `main`.

- [ ] **Step 1: Verify working tree and branch**

Run:

```bash
git status -sb
git branch --show-current
```

Expected branch: `testing`.

- [ ] **Step 2: Verify protected scientific/runtime paths are unchanged from the v0.4.15 field-confirmed code baseline**

Run:

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime \
  src/emonio_viewer/scope
```

Expected: no output and exit status 0.

`src/emonio_viewer/recording/*` is intentionally changed and is not part of this byte-identical check.

- [ ] **Step 3: Run whitespace/diff validation**

```bash
git diff --check b539efe7eb3a11d53a3b291254ddd0c50a2cf3df..HEAD
```

Expected: no errors.

- [ ] **Step 4: Run focused triggered-recording tests**

```bash
pytest -q \
  tests/unit/test_recording_trigger.py \
  tests/unit/test_recording.py \
  tests/unit/test_recording_dashboard.py \
  tests/integration/test_recording_trigger_api.py \
  tests/integration/test_multi_device.py \
  tests/browser/test_triggered_recording_ui.py
```

Expected: PASS.

- [ ] **Step 5: Run complete project acceptance**

Run the canonical project acceptance script:

```bash
./tools/ari-emonio-acceptance.sh
```

Required evidence before calling the candidate automated-acceptance complete:

```text
unit PASS
integration PASS
frontend/browser PASS
read-only gate PASS
Python compilation PASS
scientific sign path PASS
publication/package gates PASS
```

Do not infer any PASS result that the script does not print or otherwise prove.

- [ ] **Step 6: Verify `main` remains untouched**

Run:

```bash
git fetch origin
git rev-parse origin/main
```

Expected exact SHA:

```text
a0c19118f5a83fb61c559c1470b6aeb0950f058e
```

If `origin/main` differs, do not modify it. Report the difference as external repository state.

- [ ] **Step 7: Record candidate evidence without promotion**

At this point the result can be called `v0.4.16 Testing automated-acceptance candidate` only if every required gate passed. It must not be called field-confirmed until real Emonio testing succeeds. It must not be merged to `main`.

---

## Field Test Checklist After Automated Acceptance

Use one real Emonio first, then a second device if available. These are operator checks, not substitutes for automated tests.

1. Configure `LEVEL`, Phase A, P, `>`, threshold safely above/below current P as needed, and ARM it.
2. Confirm ARMED does not fire from the pre-ARM displayed/stored sample.
3. Cause the next real canonical sample to satisfy the LEVEL condition and verify recording starts on that sample.
4. Inspect `measurements.csv` and `session.json`; verify firing cycle ID/time/value match the trigger evidence.
5. Configure `CROSSING` and prove the first post-ARM sample only establishes baseline.
6. Produce a real threshold crossing and verify one session starts once.
7. Verify trigger state is DISARMED after firing and remains DISARMED after STOP.
8. ARM a trigger, press manual RECORD, and verify manual recording starts and trigger becomes DISARMED.
9. While recording, attempt ARM and verify conflict without disturbing the active recording.
10. Change trigger configuration while ARMED and verify it becomes DISARMED.
11. Restart Viewer after ARM and verify it starts DISARMED.
12. With two Emonios, verify a trigger on one device cannot be fired by the other device.
13. Verify existing manual recording, Density, History Inspector, Vector, Modbus evidence, and SCOPE behavior remain normal.

Field evidence is required before v0.4.16 can be called field-confirmed. `main` remains frozen unless the user explicitly changes that policy.