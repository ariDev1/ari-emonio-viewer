# Triggered Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic one-shot LEVEL and CROSSING triggered recording for U, I, P, Q, S, PF, and f on Phase A, B, C, or TOTAL, while preserving the canonical measurement path and existing manual recording behavior.

**Architecture:** Add a pure trigger module under `src/emonio_viewer/recording/`. `RecordingManager` remains the only owner of recording and trigger runtime state and evaluates triggers inside its existing RuntimeEventBus consumer. A fired trigger starts `SessionRecorder` from the exact firing `MeasurementSample`; no RuntimeStore re-read selects the triggered first sample.

**Tech Stack:** Python 3, dataclasses, enum, aiohttp, existing RuntimeEventBus/RuntimeStore/RecordingManager, vanilla JavaScript ES modules, structured CSS, pytest, Node-based browser tests.

**Spec:** `docs/superpowers/specs/2026-08-31-triggered-recording-design.md`

## Global Constraints

- Work on branch `testing` only.
- Do not modify `main`.
- Code baseline before v0.4.16 design work: `b539efe7eb3a11d53a3b291254ddd0c50a2cf3df`.
- Target identity: `v0.4.16 Testing`.
- Modbus/TCP remains read-only.
- Do not modify `src/emonio_viewer/modbus/*`.
- Do not modify `src/emonio_viewer/measurement/*`.
- Do not modify `src/emonio_viewer/acquisition/*`.
- Do not modify `src/emonio_viewer/runtime/events.py` or `src/emonio_viewer/runtime/store.py`.
- Do not modify `src/emonio_viewer/scope/*`.
- Canonical P/Q signs, quadrants, measurement validation, acquisition timing, and register decoding remain unchanged.
- Trigger decisions use exact canonical numeric values.
- Eligible trigger quality is exactly `VALID` or `DEGRADED`.
- Qualification count is exactly one sample.
- No smoothing, averaging, interpolation, resampling, hysteresis, debounce, epsilon, or synthetic samples.
- Trigger state is per Emonio and runtime-only.
- One-shot only. No automatic retry and no automatic re-arm.
- LEVEL can fire on the first eligible post-ARM sample.
- CROSSING requires two consecutive post-ARM canonical cycles.
- Same-device diagnostic evidence or a cycle gap clears CROSSING continuity.
- Manual START while ARMED disarms the trigger before manual session creation.
- Manual STOP is a master abort: it disarms an armed trigger; if recording is active it also stops recording.
- ARM while recording is a conflict and leaves the recording unchanged.
- Any accepted trigger configuration update forces DISARMED state.
- The exact firing sample is the first sample of a successful triggered recording.
- Triggered session start time is the firing sample `cycle_finished_utc`.
- Pre-trigger recording is out of scope.

---

## File Structure

### Create

- `src/emonio_viewer/recording/trigger.py` — pure trigger enums, config, exact value extraction, LEVEL/CROSSING evaluation, and continuity state.
- `tests/unit/test_recording_trigger.py` — pure trigger tests.
- `frontend/js/recording-trigger.js` — frontend trigger-status normalization only.
- `frontend/css/recording-trigger.css` — trigger drawer styles only.
- `tests/browser/test_triggered_recording_ui.py` — frontend trigger state, API wiring, drawer, and CSS contract tests.

### Modify

- `src/emonio_viewer/recording/recorder.py` — trigger ownership, ARM floor, manual START/STOP authority, event evaluation, exact-sample start, trigger-start failure reporting.
- `src/emonio_viewer/recording/session.py` — optional trigger provenance only.
- `src/emonio_viewer/server/api.py` — trigger endpoints and status.
- `frontend/js/api.js` — configure/arm/disarm requests.
- `frontend/js/recording-state.js` — normalize trigger status while preserving active/error behavior.
- `frontend/js/app.js` — trigger controls inside the existing Recording drawer.
- `frontend/css/recording.css` — one import of `recording-trigger.css`; no trigger selector definitions here.
- `tests/unit/test_recording.py` — manager ownership, exact first sample, provenance, failure, STOP semantics.
- `tests/unit/test_recording_dashboard.py` — preserve manual status behavior.
- `tests/integration/test_server.py` — extend existing FakeRecordingManager and API tests; do not create a second API-test fixture system.
- `tests/integration/test_multi_device.py` — per-Emonio trigger isolation.
- `tests/integration/test_end_to_end_sign.py` — only add assertions if required to prove trigger use does not alter canonical sign behavior.
- `pyproject.toml` — set version to `0.4.16` after feature tests pass.
- `src/emonio_viewer/__init__.py` — set `__version__` to `0.4.16` only.
- `tests/unit/test_release_identity.py` — expect `0.4.16`.
- `README.md` — describe v0.4.16 as Testing only.

---

### Task 1: Pure Trigger Engine

**Files:**
- Create: `src/emonio_viewer/recording/trigger.py`
- Create: `tests/unit/test_recording_trigger.py`

**Interfaces:**

```python
class TriggerMode(str, Enum):
    LEVEL = "LEVEL"
    CROSSING = "CROSSING"

class TriggerBlock(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    TOTAL = "TOTAL"

class TriggerMeasurement(str, Enum):
    U = "U"
    I = "I"
    P = "P"
    Q = "Q"
    S = "S"
    PF = "PF"
    F = "F"

class TriggerOperator(str, Enum):
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"

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

@dataclass(frozen=True, slots=True)
class TriggerFire:
    cycle_id: int
    fired_utc: datetime
    value: float

extract_trigger_value(sample: MeasurementSample, config: TriggerConfig) -> float
evaluate_measurement(state: TriggerRuntimeState, sample: MeasurementSample) -> TriggerFire | None
invalidate_crossing_continuity(state: TriggerRuntimeState) -> None
```

- [ ] **Step 1: Write failing field-extraction tests**

Use `real_sample` and `dataclasses.replace` to set unique values. Cover all seven fields and all four blocks.

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
def test_extract_uses_exact_canonical_field(real_sample, measurement, field):
    config = TriggerConfig(
        real_sample.identity.device_id,
        TriggerBlock.B,
        measurement,
        TriggerOperator.GT,
        0.0,
        TriggerMode.LEVEL,
        1.0,
    )
    assert extract_trigger_value(real_sample, config) == getattr(real_sample.phase_b.measurement, field)
```

Also assert `TriggerConfig` rejects non-finite `threshold`, non-finite interval, and interval `<= 0`.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/unit/test_recording_trigger.py
```

Expected: FAIL because the trigger module does not exist.

- [ ] **Step 3: Implement config validation and explicit maps**

Use explicit maps:

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

Do not import Modbus or acquisition code.

- [ ] **Step 4: Write failing LEVEL truth-table tests**

Cover equality and both sides for GT, GE, LT, LE. The first eligible post-ARM sample may fire.

- [ ] **Step 5: Implement LEVEL rules**

Before comparison:

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

Use exact Python comparisons with no epsilon.

- [ ] **Step 6: Write failing CROSSING truth-table and continuity tests**

Required semantics:

```text
GT: previous <= T and current > T
GE: previous <  T and current >= T
LT: previous >= T and current < T
LE: previous >  T and current <= T
```

Required continuity tests:

```text
first eligible sample -> baseline only
N -> N+1 -> crossing may fire
N -> N+2 -> no fire; N+2 becomes baseline
N -> N -> duplicate ignored
N -> N-1 -> stale ignored
invalidate_crossing_continuity() -> previous evidence cleared
other-device sample -> no state change
pre-ARM queued cycle -> no state change
```

- [ ] **Step 7: Implement CROSSING state transitions**

Only eligible, newer, post-ARM samples can become baseline. A gap sets the current sample as a new baseline and returns no fire. A duplicate or stale sample is ignored and must not replace the baseline.

- [ ] **Step 8: Run GREEN**

```bash
pytest -q tests/unit/test_recording_trigger.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/emonio_viewer/recording/trigger.py tests/unit/test_recording_trigger.py
git commit -m "feat: add deterministic recording trigger engine"
```

---

### Task 2: RecordingManager Ownership, ARM/DISARM, and Manual Authority

**Files:**
- Modify: `src/emonio_viewer/recording/recorder.py` in `RecordingManager.__init__`, `start`, `stop`, `stop_all`, and new trigger methods.
- Modify: `tests/unit/test_recording.py`

**Interfaces:**

```python
RecordingManager.configure_trigger(config: TriggerConfig) -> dict
RecordingManager.arm_trigger(device_id: str) -> dict
RecordingManager.disarm_trigger(device_id: str) -> dict
RecordingManager.trigger_statuses() -> tuple[dict, ...]
```

Internal maps under the existing `RLock`:

```python
self._trigger_configs: dict[str, TriggerConfig] = {}
self._armed_triggers: dict[str, TriggerRuntimeState] = {}
self._trigger_last_fired: dict[str, dict] = {}
```

Exact manager errors:

```text
unknown device -> KeyError(device_id)
trigger not configured -> RuntimeError("trigger not configured")
ARM while recording -> RuntimeError("recording already active")
commands disabled -> RuntimeError("recording commands disabled")
```

- [ ] **Step 1: Write failing per-device configuration/status tests**

Prove A and B configurations are independent, status order is sorted by `device_id`, and a new manager instance has no armed trigger state.

- [ ] **Step 2: Write failing command-disable and interval tests**

`configure_trigger`, `arm_trigger`, and `disarm_trigger` must call `_require_commands_enabled()`. `configure_trigger` must reject `recording_interval_s < device.poll_interval_s` using the existing recording interval rule.

- [ ] **Step 3: Implement configure/disarm/status**

`configure_trigger()`:

```text
require commands enabled
require known device
validate interval against acquisition interval
remove existing armed state for that device
store config
return DISARMED status
```

`disarm_trigger()`:

```text
require commands enabled
require known device
remove armed runtime state if present
keep config and last-fired evidence
return DISARMED status
```

- [ ] **Step 4: Write failing ARM-floor tests**

Assert ARM snapshots the current store sample cycle as `arm_floor_cycle_id`, or `None` when no sample exists.

- [ ] **Step 5: Write failing ARM conflict and manual START tests**

Prove:

```text
recording active + ARM -> RuntimeError("recording already active")
ARMED + manual START -> trigger DISARMED and manual recording active
manual START creation failure after ownership transfer -> trigger stays DISARMED
```

- [ ] **Step 6: Implement ARM and manual START precedence**

`arm_trigger()`:

```python
self._require_commands_enabled()
if device_id not in self._devices:
    raise KeyError(device_id)
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

Manual `start()` removes `_armed_triggers[device_id]` before `SessionRecorder.create()` and does not restore it on failure.

- [ ] **Step 7: Write failing manual STOP master-abort tests**

Cover three exact cases:

```text
active recording + STOP -> recorder stopped; trigger absent
ARMED only + STOP -> trigger DISARMED; no KeyError
neither active nor ARMED + STOP -> KeyError as existing inactive-stop behavior
```

- [ ] **Step 8: Implement STOP semantics**

Under the existing lock:

```python
was_armed = self._armed_triggers.pop(device_id, None) is not None
recorder = self._active.pop(device_id, None)
if recorder is not None:
    recorder.stop()
    return
if was_armed:
    return
raise KeyError(device_id)
```

`stop_all()` clears all armed runtime states during shutdown. Stored config persistence is not required because manager lifetime ends.

- [ ] **Step 9: Run GREEN**

```bash
pytest -q tests/unit/test_recording_trigger.py tests/unit/test_recording.py
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/emonio_viewer/recording/recorder.py tests/unit/test_recording.py
git commit -m "feat: add per-emonio trigger ownership"
```

---

### Task 3: Exact Firing Sample, Provenance, and Trigger-Start Failure

**Files:**
- Modify: `src/emonio_viewer/recording/recorder.py` in `SessionRecorder.create`, `RecordingManager._consume`, and new triggered-start helpers.
- Modify: `src/emonio_viewer/recording/session.py` in `initial_session_metadata`.
- Modify: `tests/unit/test_recording.py`
- Modify: `tests/unit/test_recording_dashboard.py`

**Interfaces:**

```python
RecordingManager._start_triggered_from_sample(
    device_id: str,
    sample: MeasurementSample,
    fire: TriggerFire,
    config: TriggerConfig,
) -> SessionRecorder
```

Add optional provenance without changing existing callers:

```python
SessionRecorder.create(
    root,
    first_sample,
    device,
    recording_interval_s,
    application_version,
    started_utc=None,
    trigger_evidence=None,
)
```

`initial_session_metadata(..., trigger_evidence: dict | None = None)` adds trigger data only when supplied.

- [ ] **Step 1: Write failing exact-first-sample test**

Arm LEVEL. Deliver a firing sample with unique cycle/value. Put a newer sample into RuntimeStore before the manager processes the firing event. Assert the first CSV row still contains the firing cycle/value.

- [ ] **Step 2: Write failing manager-level CROSSING tests**

Through RuntimeEventBus and the background manager consumer, prove:

```text
first post-ARM sample -> no recording
consecutive crossing sample -> recording starts
same-device DiagnosticEvent between pair -> no recording
cycle gap -> no recording
next real consecutive pair after reset -> may fire
```

- [ ] **Step 3: Write failing one-shot test**

After firing, publish more satisfying samples. Assert one active session only and trigger state DISARMED.

- [ ] **Step 4: Write failing provenance tests**

Triggered `session.json` must contain:

```python
{
    "interval_s": interval,
    "start_source": "TRIGGER",
    "trigger": {
        "mode": config.mode.value,
        "block": config.block.value,
        "measurement": config.measurement.value,
        "operator": config.operator.value,
        "threshold": config.threshold,
        "fired_cycle_id": sample.identity.cycle_id,
        "fired_utc": sample.timing.cycle_finished_utc.isoformat(),
        "fired_value": fire.value,
    },
}
```

`events.csv` contains one `TRIGGER_FIRED` event with the same exact evidence.

- [ ] **Step 5: Write failing manual-metadata compatibility test**

Manual `session.json["recording"]` remains exactly:

```python
{"interval_s": recording_interval_s}
```

- [ ] **Step 6: Implement optional provenance**

Only triggered sessions add `start_source` and `trigger` keys. Do not add them to manual sessions.

- [ ] **Step 7: Implement trigger evaluation inside existing `_consume()`**

For each `MeasurementSample` under the existing lock:

```text
1. Preserve current active-recorder handling.
2. If no recorder is active and this device is ARMED, evaluate the exact event.
3. If no fire, keep updated runtime state only.
4. If fire, save last-fired evidence, remove ARMED state, and start from the same event object.
```

For `DiagnosticEvent`, preserve existing recorder invalid-cycle evidence. If the same device is ARMED in CROSSING mode, clear crossing continuity.

Do not add another event subscriber.

- [ ] **Step 8: Write failing trigger-start creation failure test**

Monkeypatch `SessionRecorder.create` to raise `OSError("simulated trigger start failure")`. Assert:

```text
trigger DISARMED
no active recorder
recording_failures has device entry
start_source == TRIGGER
failed_cycle_id == firing cycle
one DiagnosticEvent event == TRIGGERED_RECORDING_START_ERROR
no automatic second start
```

- [ ] **Step 9: Implement failure evidence**

Store this minimum failure shape:

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

Publish one `TRIGGERED_RECORDING_START_ERROR` DiagnosticEvent for the same device.

- [ ] **Step 10: Run GREEN**

```bash
pytest -q tests/unit/test_recording_trigger.py tests/unit/test_recording.py tests/unit/test_recording_dashboard.py
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/emonio_viewer/recording/recorder.py src/emonio_viewer/recording/session.py tests/unit/test_recording.py tests/unit/test_recording_dashboard.py
git commit -m "feat: start trigger sessions from exact firing sample"
```

---

### Task 4: HTTP API and Existing Server Test Harness

**Files:**
- Modify: `src/emonio_viewer/server/api.py` in route registration, recording status, STOP response handling, and new trigger handlers.
- Modify: `tests/integration/test_server.py` in `FakeRecordingManager` and recording API tests.

**Interfaces:**

```text
POST /api/v1/recording/trigger/configure
POST /api/v1/recording/trigger/arm
POST /api/v1/recording/trigger/disarm
GET  /api/v1/recording/status
POST /api/v1/recording/stop   # existing endpoint; armed-only STOP now returns DISARMED
```

Configure body:

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

- [ ] **Step 1: Extend FakeRecordingManager first and write failing API tests**

Add fake methods with call recording:

```python
configure_trigger(config)
arm_trigger(device_id)
disarm_trigger(device_id)
trigger_statuses()
```

Add fake STOP state so tests can distinguish active-stop and armed-only disarm.

- [ ] **Step 2: Write failing validation tests**

Require 400 for invalid/missing block, measurement, operator, mode, threshold, non-finite threshold, invalid interval, or interval below acquisition interval. Require 404 for unknown device.

- [ ] **Step 3: Write failing state/HTTP tests**

Require:

```text
configure -> 200 DISARMED
ARM without config -> 409
ARM -> 200 ARMED
DISARM -> 200 DISARMED
ARM while recording -> 409
manual START while ARMED -> 200 RECORDING and later status DISARMED
STOP while only ARMED -> 200 DISARMED
STOP when neither recording nor ARMED -> 404
commands disabled -> 503 for configure/arm/disarm
```

- [ ] **Step 4: Write failing status test**

Existing keys remain `active` and `errors`; add `triggers`. Exact threshold and last-fired values remain JSON numbers, not formatted strings or enum representations.

- [ ] **Step 5: Implement explicit API parsing**

Use a helper that converts request strings to the exact trigger enums. Catch `ValueError` as `HTTPBadRequest`. Use `math.isfinite()` for threshold. Reuse `_positive_interval()` and `_validate_recording_interval_for_device()`.

- [ ] **Step 6: Implement routes and error translation**

Map:

```text
trigger not configured -> 409
recording already active -> 409
recording commands disabled -> 503
unknown device -> 404
```

For existing STOP, distinguish manager result so armed-only STOP returns `{"state":"DISARMED"}` while active recording STOP remains `{"state":"STOPPED"}`. Preserve 404 when neither state existed.

- [ ] **Step 7: Run GREEN**

```bash
pytest -q tests/integration/test_server.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/emonio_viewer/server/api.py tests/integration/test_server.py
git commit -m "feat: expose triggered recording API"
```

---

### Task 5: Frontend Trigger State and API Client

**Files:**
- Create: `frontend/js/recording-trigger.js`
- Modify: `frontend/js/api.js`
- Modify: `frontend/js/recording-state.js`
- Create: `tests/browser/test_triggered_recording_ui.py`

**Interfaces:**

```javascript
configureRecordingTrigger(deviceId, config)
armRecordingTrigger(deviceId)
disarmRecordingTrigger(deviceId)
```

```javascript
export class RecordingTriggerState {
  replace(records)
  forDevice(deviceId)
}
```

`RecordingState` adds:

```javascript
triggerForDevice(deviceId)
```

and changes:

```javascript
replaceStatus(activeRecords, errorRecords, triggerRecords = [])
```

The default third argument preserves existing two-argument callers.

- [ ] **Step 1: Write failing Node/static normalization tests**

Test valid ARMED/DISARMED records, malformed records fail closed, and exact numeric threshold/last-fired values are retained without display formatting.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/browser/test_triggered_recording_ui.py
```

Expected: FAIL because trigger frontend module/functions do not exist.

- [ ] **Step 3: Implement independent trigger state module**

No DOM dependency. No history, acquisition, Modbus, or SCOPE imports.

- [ ] **Step 4: Add API functions through existing `requestJson()`**

```javascript
export function configureRecordingTrigger(deviceId, config) {
  return requestJson("/api/v1/recording/trigger/configure", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, ...config }),
  });
}
```

ARM/DISARM send only `device_id`.

- [ ] **Step 5: Extend RecordingState**

Trigger state is independent of active/error state. ARMED must never make `isActive(deviceId)` true.

- [ ] **Step 6: Run GREEN**

```bash
pytest -q tests/browser/test_triggered_recording_ui.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/js/recording-trigger.js frontend/js/api.js frontend/js/recording-state.js tests/browser/test_triggered_recording_ui.py
git commit -m "feat: add triggered recording frontend state"
```

---

### Task 6: Recording Drawer Controls and Structured CSS

**Files:**
- Modify: `frontend/js/app.js` in recording imports, `ensureRecordingDashboardStructure`, `refreshRecordingState`, selected-device rendering, and recording control initialization.
- Create: `frontend/css/recording-trigger.css`
- Modify: `frontend/css/recording.css` only for the import.
- Modify: `tests/browser/test_triggered_recording_ui.py`

**Stable control IDs:**

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

- [ ] **Step 1: Write failing structure/wiring tests**

Assert stable IDs, trigger API imports, and `recording-trigger.css` import. Assert the compact main recording strip remains present.

- [ ] **Step 2: Write failing control-state tests**

Backend-authoritative rules:

```text
no selected device -> trigger controls disabled
active recording -> ARM disabled
DISARMED configured trigger -> ARM enabled
ARMED -> DISARM enabled
ARMED -> main STOP enabled
configuration change -> configure request; returned state DISARMED
manual RECORD while ARMED -> normal manual start; refreshed backend status controls final state
manual STOP while only ARMED -> existing stop request; returned state DISARMED
```

- [ ] **Step 3: Add trigger section inside existing Recording drawer**

Controls:

```text
MODE: LEVEL, CROSSING
PHASE: A, B, C, TOTAL
MEASUREMENT: U, I, P, Q, S, PF, f
OPERATOR: >, >=, <, <=
THRESHOLD: free numeric input
INTERVAL: existing valid recording intervals
STATE
CONFIGURE / ARM / DISARM
LAST FIRED
```

Do not add trigger controls to the main measurement layout.

- [ ] **Step 4: Refresh from backend after every state-changing command**

`refreshRecordingState()` passes `payload.triggers` to `recordingState.replaceStatus(...)`. Configure, ARM, DISARM, manual START, and manual STOP all refresh before final render.

- [ ] **Step 5: Add scoped CSS**

`frontend/css/recording-trigger.css` owns only `.recording-trigger-*` selectors. Use existing CSS variables. No inline styles.

Add only this to `frontend/css/recording.css`:

```css
@import url("./recording-trigger.css");
```

Do not move existing recording CSS.

- [ ] **Step 6: Run browser regression**

```bash
pytest -q tests/browser/test_triggered_recording_ui.py
pytest -q tests/browser
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/js/app.js frontend/css/recording.css frontend/css/recording-trigger.css tests/browser/test_triggered_recording_ui.py
git commit -m "feat: add triggered recording controls"
```

---

### Task 7: Multi-Device and Scientific Regression Evidence

**Files:**
- Modify: `tests/integration/test_multi_device.py`
- Modify: `tests/integration/test_end_to_end_sign.py` only when the existing fixture can directly prove unchanged sign behavior.
- Modify: `tests/unit/test_recording.py` for any manager-level isolation case not already covered.

- [ ] **Step 1: Add failing two-Emonio isolation test**

Configure and ARM A and B independently. Fire A. Assert A becomes recording/DISARMED while B remains ARMED and its previous-value evidence is unchanged by A samples. Then fire B from B evidence only.

- [ ] **Step 2: Add event-gap regression**

CROSSING baseline N followed by N+2 beyond threshold must not fire. N+2 becomes baseline. Only a real consecutive N+2 -> N+3 crossing can fire.

- [ ] **Step 3: Add canonical sign regression**

Use negative P/Q evidence and prove trigger evaluation does not modify the sample or canonical sign. If `test_end_to_end_sign.py` already proves the same sample path and needs no trigger-specific edit, keep it byte-identical and rely on the full sign-path acceptance gate.

- [ ] **Step 4: Run backend regression group**

```bash
pytest -q \
  tests/unit/test_recording_trigger.py \
  tests/unit/test_recording.py \
  tests/integration/test_server.py \
  tests/integration/test_multi_device.py \
  tests/integration/test_end_to_end_sign.py
```

Expected: PASS.

- [ ] **Step 5: Commit only changed test files**

```bash
git add tests/unit/test_recording.py tests/integration/test_multi_device.py tests/integration/test_end_to_end_sign.py
git diff --cached --quiet || git commit -m "test: verify trigger isolation and sign integrity"
```

Do not modify production science code to make this regression task pass.

---

### Task 8: Release Identity, Full Acceptance, and Protected-Path Audit

**Files:**
- Modify: `tests/unit/test_release_identity.py`
- Modify: `pyproject.toml`
- Modify: `src/emonio_viewer/__init__.py`
- Modify: `README.md`
- No other production changes unless a failing test proves a defect and systematic debugging identifies the cause.

- [ ] **Step 1: Write failing release identity expectation**

Change the expected identity to `0.4.16` first.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/unit/test_release_identity.py
```

Expected: FAIL while package/runtime still report `0.4.15`.

- [ ] **Step 3: Set version only**

```text
pyproject.toml version = "0.4.16"
src/emonio_viewer/__init__.py __version__ = "0.4.16"
```

- [ ] **Step 4: Update README without promotion claims**

Document v0.4.16 Testing and Triggered Recording. Keep trusted `main` baseline wording unchanged. Do not call v0.4.16 field-confirmed yet.

- [ ] **Step 5: Run release/publication-sensitive tests**

```bash
pytest -q tests/unit/test_release_identity.py tests/unit/test_publication_contract.py tests/unit/test_publication_gate.py tests/unit/test_release_builder.py
```

Expected: PASS.

- [ ] **Step 6: Commit version/docs**

```bash
git add pyproject.toml src/emonio_viewer/__init__.py tests/unit/test_release_identity.py README.md
git commit -m "chore: set v0.4.16 testing identity"
```

- [ ] **Step 7: Verify branch and clean diff syntax**

```bash
git status -sb
git branch --show-current
git diff --check b539efe7eb3a11d53a3b291254ddd0c50a2cf3df..HEAD
```

Expected branch: `testing`. Expected diff-check output: none.

- [ ] **Step 8: Prove protected paths remain unchanged from v0.4.15 code baseline**

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime \
  src/emonio_viewer/scope
```

Expected: no output, exit 0.

- [ ] **Step 9: Run focused trigger regression**

```bash
pytest -q \
  tests/unit/test_recording_trigger.py \
  tests/unit/test_recording.py \
  tests/unit/test_recording_dashboard.py \
  tests/integration/test_server.py \
  tests/integration/test_multi_device.py \
  tests/browser/test_triggered_recording_ui.py
```

Expected: PASS.

- [ ] **Step 10: Run complete project acceptance**

```bash
./tools/ari-emonio-acceptance.sh
```

Require explicit evidence for:

```text
unit PASS
integration PASS
frontend/browser PASS
read-only gate PASS
Python compilation PASS
scientific sign path PASS
publication/package gates PASS
```

Do not infer a gate that was not proved.

If any failure occurs, stop and invoke `superpowers:systematic-debugging` before modifying code.

- [ ] **Step 11: Verify `main` remains unchanged**

```bash
git fetch origin
git rev-parse origin/main
```

Expected:

```text
a0c19118f5a83fb61c559c1470b6aeb0950f058e
```

If it differs, do not modify `main`; report the external repository state.

---

## Field Test Checklist

After complete automated acceptance:

1. ARM LEVEL and verify the pre-ARM stored/displayed sample cannot fire it.
2. Make the next real canonical sample satisfy LEVEL and verify recording starts from that exact cycle.
3. Verify first `measurements.csv` row and trigger evidence use the same firing cycle/time/value.
4. ARM CROSSING and verify the first post-ARM sample establishes baseline only.
5. Produce a real consecutive threshold crossing and verify one recording starts.
6. Verify trigger is DISARMED after firing and does not re-arm after STOP.
7. ARM, then use manual RECORD; verify trigger disarms and manual recording starts normally.
8. ARM without recording, then press main STOP; verify trigger becomes DISARMED.
9. While recording, attempt ARM; verify conflict and uninterrupted recording.
10. Change trigger configuration while ARMED; verify DISARMED.
11. Restart Viewer after ARM; verify DISARMED.
12. With two Emonios, verify one device cannot fire or alter the other device trigger.
13. Verify existing manual recording, Density, History Inspector, Vector, Modbus evidence, and SCOPE remain normal.

Only after real-device success can v0.4.16 be called field-confirmed. Do not merge to `main`.