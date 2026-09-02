# Stage 4A P Control Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a P-only, observation-only control service that reads canonical Emonio samples and qualified manual PWM ACK status, then displays a deterministic proposed next duty without sending any actuator command.

**Architecture:** Add one isolated `PControlObserverService` under `load_control`. It subscribes read-only to `RuntimeEventBus`, receives qualification and manual-PWM evidence only through status-provider callables, and never receives `QualifiedActuatorChannel`. A dedicated HTTP API and frontend section expose configuration, state, evidence, and proposal. The existing manual PWM service remains the only physical PWM command/ACK owner.

**Tech Stack:** Python 3.10+, `asyncio`, immutable dataclasses, `aiohttp`, existing `RuntimeEventBus`, existing load-control diagnostic log, vanilla JavaScript modules, structured CSS, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-02-stage4a-p-control-observer-design.md`

## Global Constraints

- Work only on branch `testing`.
- Approved design commit: `c4a18e0f4215c89b5a005dcaf5ac4236803a2655`.
- Viewer version remains `0.4.23` during Stage 4A unless a separate version-change approval is given.
- The active launcher remains exactly `emonio-viewer = "emonio_viewer.main_v0416:main"`.
- Do not modify `src/emonio_viewer/acquisition/**`.
- Do not modify `src/emonio_viewer/measurement/**`.
- Do not modify `src/emonio_viewer/modbus/**`.
- Do not modify `src/emonio_viewer/recording/**`.
- Do not modify `src/emonio_viewer/scope/**`.
- Do not modify `src/emonio_viewer/runtime/events.py`.
- Do not modify `src/emonio_viewer/runtime/store.py`.
- Preserve canonical P/Q signs, quadrant semantics, PF semantics, validation, fixed-deadline acquisition, Modbus read-only behavior, recording, CSV precision, and SCOPE semantics.
- Stage 4A uses active power P only. Q is display-only evidence. PF does not enter the calculation.
- SAFE/OFF is exactly `0 %`.
- The current Stage 4A active-duty window is `25 % <= duty <= 75 %`.
- Stage 4A never sends `PWM_COMMAND`.
- Stage 4A never consumes actuator frames.
- Stage 4A never allocates actuator sequence numbers.
- Stage 4A never retries or replays actuator commands.
- Stage 4A configuration can change only while `DISABLED`.
- `BLOCKED` is latched until explicit disable and re-enable.
- A changed qualified manual PWM ACK invalidates the old proposal and requires a later selected-source measurement cycle before the next calculation.
- Existing manual PWM behavior and tests must remain unchanged.
- Automated tests are software evidence only. They are not field evidence.

---

## File Structure

### New files

- `src/emonio_viewer/load_control/automatic_observation.py` — Stage 4A calculation, immutable observer types, read-only event-bus observer service, freshness/block logic, and observer diagnostics.
- `src/emonio_viewer/server/load_control_stage4a_api.py` — Stage 4A HTTP routes only.
- `frontend/js/load-control-stage4a-api.js` — Stage 4A HTTP client only.
- `frontend/js/load-control-stage4a-ui.js` — Stage 4A operator UI only.
- `frontend/css/load-control/p-control-observer.css` — Stage 4A styles only.
- `tests/unit/test_load_control_stage4a_observer.py` — calculation and observer service tests.
- `tests/integration/test_load_control_stage4a_api.py` — HTTP and app-wiring tests.
- `tests/integration/test_load_control_stage4a_spec_contract.py` — static no-output/no-transport contract tests.
- `tests/browser/test_load_control_stage4a_contract.py` — frontend contract tests.

### Existing files with minimal changes

- `src/emonio_viewer/server/keys.py` — add one typed app key.
- `src/emonio_viewer/server/app_v0416.py` — instantiate/start/stop Stage 4A, register routes, and load Stage 4A CSS/JS.

### Existing files that must not change

- `src/emonio_viewer/load_control/manual_pwm.py`
- `src/emonio_viewer/load_control/qualified_channel.py`
- `src/emonio_viewer/load_control/qualification.py`
- `src/emonio_viewer/load_control/stage3a.py`
- `src/emonio_viewer/load_control/stage3b.py`
- `src/emonio_viewer/server/load_control_stage3b_api.py`
- all protected scientific paths listed above

---

### Task 1: Pure P-Only Proposal Calculation

**Files:**
- Create: `src/emonio_viewer/load_control/automatic_observation.py`
- Create: `tests/unit/test_load_control_stage4a_observer.py`

**Interfaces:**
- Consumes: finite scalar `measured_p_w`, `p_target_w`, `p_deadband_w`, `confirmed_duty_percent`, `duty_step_percent`.
- Produces:
  - `PControlDecision`
  - `PControlProposal`
  - `calculate_p_control_proposal(*, measured_p_w, p_target_w, p_deadband_w, confirmed_duty_percent, duty_step_percent) -> PControlProposal`

- [ ] **Step 1: Write failing pure-calculation tests**

Add these exact cases:

```python
from emonio_viewer.load_control.automatic_observation import (
    PControlDecision,
    calculate_p_control_proposal,
)


def test_negative_p_increases_from_safe_off_to_active_minimum() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-60.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 25.0
    assert result.low_w == -2.0
    assert result.high_w == 2.0


def test_negative_p_increases_one_step() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-15.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 30.0


def test_target_band_holds_confirmed_duty() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-1.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=40.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.HOLD
    assert result.proposed_duty_percent == 40.0


def test_decrease_from_active_minimum_proposes_exact_off() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=5.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.DECREASE
    assert result.proposed_duty_percent == 0.0


def test_limits_are_explicit() -> None:
    high = calculate_p_control_proposal(
        measured_p_w=-20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=75.0,
        duty_step_percent=5.0,
    )
    low = calculate_p_control_proposal(
        measured_p_w=20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert high.decision is PControlDecision.LIMIT_HIGH
    assert high.proposed_duty_percent == 75.0
    assert low.decision is PControlDecision.LIMIT_LOW
    assert low.proposed_duty_percent == 0.0
```

Add parameterized validation tests for non-finite target/deadband/step/duty, negative deadband, non-positive step, confirmed active duty in `(0, 25)`, and confirmed duty above `75`.

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: FAIL because the new module does not exist.

- [ ] **Step 3: Implement the exact calculation**

Start the module with:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

ACTIVE_DUTY_MIN_PERCENT = 25.0
ACTIVE_DUTY_MAX_PERCENT = 75.0
SAFE_DUTY_PERCENT = 0.0


class PControlDecision(str, Enum):
    INCREASE = "INCREASE"
    HOLD = "HOLD"
    DECREASE = "DECREASE"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"


@dataclass(frozen=True, slots=True)
class PControlProposal:
    decision: PControlDecision
    proposed_duty_percent: float
    low_w: float
    high_w: float


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validated_confirmed_duty(value: float) -> float:
    duty = _finite("confirmed_duty_percent", value)
    if duty == SAFE_DUTY_PERCENT:
        return duty
    if ACTIVE_DUTY_MIN_PERCENT <= duty <= ACTIVE_DUTY_MAX_PERCENT:
        return duty
    raise ValueError("confirmed_duty_percent is outside the Stage 4A qualified window")


def calculate_p_control_proposal(
    *,
    measured_p_w: float,
    p_target_w: float,
    p_deadband_w: float,
    confirmed_duty_percent: float,
    duty_step_percent: float,
) -> PControlProposal:
    measured_p = _finite("measured_p_w", measured_p_w)
    target = _finite("p_target_w", p_target_w)
    deadband = _finite("p_deadband_w", p_deadband_w)
    step = _finite("duty_step_percent", duty_step_percent)
    duty = _validated_confirmed_duty(confirmed_duty_percent)
    if deadband < 0.0:
        raise ValueError("p_deadband_w must be >= 0")
    if step <= 0.0:
        raise ValueError("duty_step_percent must be > 0")

    low = target - deadband
    high = target + deadband

    if measured_p < low:
        if duty == ACTIVE_DUTY_MAX_PERCENT:
            return PControlProposal(PControlDecision.LIMIT_HIGH, duty, low, high)
        proposed = (
            ACTIVE_DUTY_MIN_PERCENT
            if duty == SAFE_DUTY_PERCENT
            else min(duty + step, ACTIVE_DUTY_MAX_PERCENT)
        )
        decision = (
            PControlDecision.LIMIT_HIGH
            if proposed == ACTIVE_DUTY_MAX_PERCENT and duty + step > ACTIVE_DUTY_MAX_PERCENT
            else PControlDecision.INCREASE
        )
        return PControlProposal(decision, proposed, low, high)

    if measured_p > high:
        if duty == SAFE_DUTY_PERCENT:
            return PControlProposal(PControlDecision.LIMIT_LOW, duty, low, high)
        proposed = SAFE_DUTY_PERCENT if duty == ACTIVE_DUTY_MIN_PERCENT else max(
            duty - step,
            ACTIVE_DUTY_MIN_PERCENT,
        )
        return PControlProposal(PControlDecision.DECREASE, proposed, low, high)

    return PControlProposal(PControlDecision.HOLD, duty, low, high)
```

The function has no Q or PF input. Do not add one.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: PASS for Task 1 tests.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/emonio_viewer/load_control/automatic_observation.py tests/unit/test_load_control_stage4a_observer.py
git commit -m "feat: add Stage 4A P-only proposal calculation"
```

---

### Task 2: Read-Only Observer Service and Fail-Closed State Machine

**Files:**
- Modify: `src/emonio_viewer/load_control/automatic_observation.py`
- Modify: `tests/unit/test_load_control_stage4a_observer.py`

**Interfaces:**
- Consumes:
  - `RuntimeEventBus`
  - `RuntimeConfig`
  - `Callable[[], QualificationStatus]`
  - `Callable[[], ManualPwmStatus | None]`
- Produces:
  - `PControlObserverState`
  - `PControlObserverSettings`
  - `PControlObserverStatus`
  - `PControlObserverError`
  - `PControlObserverService.start()`
  - `PControlObserverService.close()`
  - `PControlObserverService.configure()`
  - `PControlObserverService.enable()`
  - `PControlObserverService.disable()`
  - `PControlObserverService.status()`
  - `PControlObserverService.diagnostics()`
- Does not consume or receive `QualifiedActuatorChannel`.

- [ ] **Step 1: Add failing observer-type and configuration tests**

Define these exact states:

```python
class PControlObserverState(str, Enum):
    DISABLED = "DISABLED"
    WAITING_FOR_SAMPLE = "WAITING_FOR_SAMPLE"
    OBSERVING = "OBSERVING"
    TARGET_BAND = "TARGET_BAND"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"
    BLOCKED = "BLOCKED"
```

Define immutable settings:

```python
@dataclass(frozen=True, slots=True)
class PControlObserverSettings:
    source_id: str | None = None
    phase: str | None = None
    p_target_w: float | None = None
    p_deadband_w: float | None = None
    duty_step_percent: float | None = None
```

Define immutable status fields:

```python
@dataclass(frozen=True, slots=True)
class PControlObserverStatus:
    state: PControlObserverState
    reason: str | None
    source_id: str | None
    phase: str | None
    sample_cycle_id: int | None
    measured_p_w: float | None
    measured_q_var: float | None
    sample_quality: str | None
    sample_age_s: float | None
    p_target_w: float | None
    p_deadband_w: float | None
    duty_step_percent: float | None
    actuator_node_id: str | None
    actuator_boot_id: str | None
    confirmed_command_sequence: int | None
    confirmed_requested_duty_percent: float | None
    confirmed_actual_duty_percent: float | None
    decision: PControlDecision | None
    proposed_duty_percent: float | None
```

Add a test that configuration is rejected while active and the previous configuration remains unchanged.

- [ ] **Step 2: Add failing enable-gate tests**

Use real existing dataclasses `QualificationStatus` and `ManualPwmStatus` in fake provider objects. Prove exact enable rejection behavior for:

- `SOURCE_NOT_AVAILABLE`
- `PHASE_NOT_SELECTED`
- `PARAMETER_INVALID`
- `ACTUATOR_NOT_QUALIFIED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

A rejected enable leaves state `DISABLED` and proposal `None`.

- [ ] **Step 3: Run tests and verify RED**

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: FAIL because the observer service does not exist.

- [ ] **Step 4: Implement provider-only construction and deterministic internal ownership**

Use this exact constructor signature:

```python
class PControlObserverService:
    def __init__(
        self,
        bus: RuntimeEventBus,
        config: RuntimeConfig,
        *,
        qualification_status: Callable[[], QualificationStatus],
        manual_pwm_status: Callable[[], ManualPwmStatus | None],
        diagnostic_log: LoadControlDiagnosticLog | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._qualification_status = qualification_status
        self._manual_pwm_status = manual_pwm_status
        self._diagnostic_log = diagnostic_log or LoadControlDiagnosticLog()
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._settings = PControlObserverSettings()
        self._state = PControlObserverState.DISABLED
        self._reason: str | None = None
        self._subscriber: Queue[RuntimeEvent] | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_sentinel = object()
        self._started = False
        self._latest_cycle_by_source: dict[str, int] = {}
        self._last_source_cycle_id: int | None = None
        self._enable_boundary_cycle = 0
        self._enable_monotonic_ns = 0
        self._freshness_deadline_ns: int | None = None
        self._baseline_fingerprint: tuple[str, str, int, float] | None = None
        self._baseline_requested_duty: float | None = None
        self._baseline_actual_duty: float | None = None
        self._sample_cycle_id: int | None = None
        self._measured_p_w: float | None = None
        self._measured_q_var: float | None = None
        self._sample_quality: str | None = None
        self._sample_finished_monotonic_ns: int | None = None
        self._decision: PControlDecision | None = None
        self._proposed_duty_percent: float | None = None
```

Import only status/data types from qualification/manual PWM modules. Do not import the qualified channel or PWM command frame.

- [ ] **Step 5: Implement atomic configuration while disabled**

`configure()` accepts exactly five keyword arguments:

```python
service.configure(
    source_id="emonio-example",
    phase="A",
    p_target_w=0.0,
    p_deadband_w=2.0,
    duty_step_percent=5.0,
)
```

Validation order is deterministic:

1. observer must be `DISABLED`, otherwise raise `PControlObserverError("OBSERVER_NOT_DISABLED")`;
2. source must resolve to exactly one enabled device, otherwise `SOURCE_NOT_AVAILABLE`;
3. phase must be `A`, `B`, or `C`, otherwise `PHASE_NOT_SELECTED`;
4. target must be finite;
5. deadband must be finite and non-negative;
6. step must be finite and positive.

For numeric validation failure raise `PControlObserverError("PARAMETER_INVALID")`.

Build a complete new `PControlObserverSettings` first. Assign it only after all checks pass. This proves no partial mutation.

- [ ] **Step 6: Implement current qualified PWM evidence extraction**

Use a private helper that reads qualification first, then manual PWM status. The helper must return exact reason codes rather than clamping or guessing.

Required identity checks:

```text
qualification.connected == true
qualification.hello_qualified == true
PWM_DUTY_CONTROL in qualification.capabilities
manual.ack_result == APPLIED
manual.node_id == qualification.node_id
manual.boot_id == qualification.boot_id
manual.command_sequence is not null
manual.requested_duty_percent is not null
requested duty is exactly 0 or inside 25..75 inclusive
```

The accepted fingerprint is:

```python
(
    qualification.node_id,
    qualification.boot_id,
    manual.command_sequence,
    manual.requested_duty_percent,
)
```

Check boot identity before checking manual ACK completeness so a changed qualified boot reports `ACTUATOR_BOOT_CHANGED` during an active session instead of degrading to `CONFIRMED_DUTY_UNKNOWN`.

- [ ] **Step 7: Implement enable/disable semantics**

`enable()` must:

1. require the service to be started;
2. require complete valid settings;
3. obtain current qualified PWM evidence;
4. store current latest selected-source cycle as `_enable_boundary_cycle`;
5. store current monotonic time as `_enable_monotonic_ns`;
6. set `_last_source_cycle_id` to the boundary cycle;
7. store the current ACK fingerprint and requested/actual duty;
8. clear old sample/proposal fields;
9. set state `WAITING_FOR_SAMPLE`;
10. set freshness deadline to `enable time + 2 * selected source poll interval`;
11. append `P_OBSERVER_ENABLED`.

`disable()` must clear the block latch and proposal, return state to `DISABLED`, clear the deadline, and append `P_OBSERVER_DISABLED`. It must not call any actuator API.

- [ ] **Step 8: Add failing canonical-sample behavior tests**

Using `dataclasses.replace()` on the existing `real_sample` fixture, prove:

- negative P is used without sign transformation;
- Q changes do not affect a proposal when P is unchanged;
- PF changes do not affect a proposal when P is unchanged;
- wrong-source samples are ignored;
- an existing pre-enable cycle is not accepted as new evidence;
- one selected-source sample causes at most one calculation;
- two consecutive samples with unchanged confirmed duty repeat the same proposal rather than accumulate it.

Use enum assertions:

```python
assert status.measured_p_w == -60.0
assert status.decision is PControlDecision.INCREASE
assert status.proposed_duty_percent == 30.0
```

- [ ] **Step 9: Implement event-bus observation**

`start()` subscribes with `maxsize=256` and starts one consumer task. Track latest cycle per device even while disabled.

For a selected-source measurement while enabled, process in this order:

1. if already `BLOCKED`, ignore it;
2. require `cycle_id == last_source_cycle_id + 1`, otherwise block `SAMPLE_SEQUENCE_GAP`;
3. update `last_source_cycle_id` to this cycle;
4. while waiting for the first sample after enable, require cycle greater than enable boundary and `cycle_started_monotonic_ns > enable_monotonic_ns`;
5. require `SampleQuality.VALID`, otherwise block `SAMPLE_NOT_VALID`;
6. calculate sample age from the canonical `cycle_finished_monotonic_ns`; negative age or age greater than `2 * poll_interval_s` blocks `SAMPLE_STALE`;
7. read current actuator/manual evidence;
8. if the ACK fingerprint changed, record the new baseline, clear proposal, set state `WAITING_FOR_SAMPLE`, set a new freshness deadline, append `P_OBSERVER_DUTY_BASELINE_CHANGED`, and return without calculating;
9. select P and Q directly from the configured phase block;
10. call `calculate_p_control_proposal()` with P only;
11. store measured P/Q as evidence;
12. map `HOLD` to `TARGET_BAND`, `LIMIT_LOW` to `LIMIT_LOW`, `LIMIT_HIGH` to `LIMIT_HIGH`, and other valid decisions to `OBSERVING`;
13. set the next freshness deadline from the accepted sample finish time plus `2 * poll_interval_s`;
14. append `P_OBSERVER_PROPOSAL_CALCULATED`.

Do not access `sample.total` for the control calculation.

- [ ] **Step 10: Add failing runtime-block tests**

Prove each exact runtime block:

- `SAMPLE_NOT_VALID`
- `SAMPLE_STALE`
- `SAMPLE_SEQUENCE_GAP`
- `ACQUISITION_FAILURE`
- `ACTUATOR_BOOT_CHANGED`
- `ACTUATOR_DISCONNECTED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

For every block:

```python
assert status.state is PControlObserverState.BLOCKED
assert status.proposed_duty_percent is None
```

Then provide later valid evidence and assert the state stays `BLOCKED`. Call `disable()` and assert it returns to `DISABLED`.

- [ ] **Step 11: Implement one block helper and freshness deadline**

Use one helper:

```python
def _block(self, reason: str) -> None:
    if self._state is PControlObserverState.BLOCKED:
        return
    self._state = PControlObserverState.BLOCKED
    self._reason = reason
    self._decision = None
    self._proposed_duty_percent = None
    self._freshness_deadline_ns = None
    self._diagnostic_log.append("P_OBSERVER_BLOCKED", reason=reason)
```

The consumer may use monotonic timeout only to perform a deadline/evidence check. The deadline check must never calculate a new proposal.

Deadline check precedence:

1. disconnected actuator;
2. changed boot ID;
3. missing PWM capability;
4. missing/out-of-window confirmed duty;
5. stale expected sample.

A selected-source `DiagnosticEvent` whose name starts with `ACQUISITION_` blocks with `ACQUISITION_FAILURE`.

- [ ] **Step 12: Add changed-manual-ACK causal-boundary test**

Prove this sequence:

```text
ACK sequence 10 confirms 25 %
enable observer
cycle 101 calculates 30 % proposal
ACK sequence 11 confirms 30 %
cycle 102 detects changed ACK and produces no proposal
cycle 103 calculates from confirmed 30 %
```

Cycle 102 must not calculate from the new baseline.

- [ ] **Step 13: Implement observer diagnostics**

Use `LoadControlDiagnosticLog` with these event names:

- `P_OBSERVER_ENABLED`
- `P_OBSERVER_DISABLED`
- `P_OBSERVER_SAMPLE_IGNORED`
- `P_OBSERVER_DUTY_BASELINE_CHANGED`
- `P_OBSERVER_PROPOSAL_CALCULATED`
- `P_OBSERVER_BLOCKED`

A proposal diagnostic contains:

```text
emonio_device_id
phase
measurement_cycle_id
measured_p_w
p_target_w
p_deadband_w
confirmed_requested_duty_percent
duty_step_percent
decision
proposed_duty_percent
observer_state
```

Never use words that claim the proposal was physically applied.

- [ ] **Step 14: Run observer and manual PWM regressions**

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
pytest tests/unit/test_load_control_manual_pwm.py -q
```

Expected: PASS. `test_load_control_manual_pwm.py` and `manual_pwm.py` remain unchanged.

- [ ] **Step 15: Commit Task 2**

```bash
git add src/emonio_viewer/load_control/automatic_observation.py tests/unit/test_load_control_stage4a_observer.py
git commit -m "feat: add fail-closed Stage 4A observer service"
```

---

### Task 3: Dedicated Stage 4A HTTP API and App Wiring

**Files:**
- Create: `src/emonio_viewer/server/load_control_stage4a_api.py`
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Create: `tests/integration/test_load_control_stage4a_api.py`

**Interfaces:**
- `GET /api/v1/load-control/p-observer/status`
- `POST /api/v1/load-control/p-observer/configure`
- `POST /api/v1/load-control/p-observer/enable`
- `POST /api/v1/load-control/p-observer/disable`
- `GET /api/v1/load-control/p-observer/diagnostics`

- [ ] **Step 1: Write failing API tests**

Configure request is exactly:

```json
{
  "source_id": "emonio-example",
  "phase": "A",
  "p_target_w": 0.0,
  "p_deadband_w": 2.0,
  "duty_step_percent": 5.0
}
```

Test:

- missing or extra fields -> HTTP 400;
- malformed numeric/phase/source values -> HTTP 400;
- configuration attempt while active -> HTTP 409 with `OBSERVER_NOT_DISABLED`;
- failed enable gate -> HTTP 409 with exact backend reason;
- enable/disable body must be exactly `{}`;
- status serializes `None` as JSON `null`;
- decision serializes enum value or `null`;
- diagnostics returns bounded existing observer diagnostic records.

Use a concrete diagnostics response in the test:

```json
{
  "latest_sequence": 7,
  "events": [
    {
      "sequence": 7,
      "utc": "2026-09-02T12:00:00.000Z",
      "event": "P_OBSERVER_PROPOSAL_CALCULATED",
      "line": "2026-09-02T12:00:00.000Z  P_OBSERVER_PROPOSAL_CALCULATED"
    }
  ]
}
```

- [ ] **Step 2: Run API tests and verify RED**

```bash
pytest tests/integration/test_load_control_stage4a_api.py -q
```

Expected: FAIL because routes and app key do not exist.

- [ ] **Step 3: Add one typed app key**

In `server/keys.py`:

```python
from emonio_viewer.load_control.automatic_observation import PControlObserverService

P_CONTROL_OBSERVER_SERVICE_KEY = web.AppKey(
    "p_control_observer_service",
    PControlObserverService,
)
```

Do not change existing keys.

- [ ] **Step 4: Implement strict Stage 4A route module**

The route module resolves only `P_CONTROL_OBSERVER_SERVICE_KEY`.

Mapping rules:

- JSON syntax/type/field errors -> HTTP 400;
- `PControlObserverError` from configuration or enable/disable state conflict -> HTTP 409;
- GET status -> immutable status JSON;
- GET diagnostics accepts `after_sequence` as a non-negative integer query value and returns `latest_sequence` plus event objects.

Do not import Stage 3B route functions or PWM command types.

- [ ] **Step 5: Wire the observer into `app_v0416.py`**

Extend `create_app()` with:

```python
p_control_observer_service: PControlObserverService | None = None,
```

When no observer is injected, create read-only providers:

```python
def qualification_status_provider():
    return qualification_service.status()


def manual_pwm_status_provider():
    getter = getattr(stage3a_service, "manual_pwm_status", None)
    if not callable(getter):
        return None
    return getter()
```

Then construct:

```python
p_control_observer_service = PControlObserverService(
    bus,
    config,
    qualification_status=qualification_status_provider,
    manual_pwm_status=manual_pwm_status_provider,
)
```

Do not pass `qualified_channel`.

Startup/cleanup order:

```text
start load-control service
start Stage 3A/manual PWM service
start Stage 4A observer
cleanup Stage 4A observer
cleanup Stage 3A/manual PWM service
cleanup qualification
cleanup load-control service
```

Register Stage 4A routes after the observer is stored in the app.

- [ ] **Step 6: Run API and existing control API regressions**

```bash
pytest tests/integration/test_load_control_stage4a_api.py -q
pytest tests/integration/test_load_control_stage3a_api.py -q
pytest tests/integration/test_load_control_stage3b_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  src/emonio_viewer/server/load_control_stage4a_api.py \
  src/emonio_viewer/server/keys.py \
  src/emonio_viewer/server/app_v0416.py \
  tests/integration/test_load_control_stage4a_api.py
git commit -m "feat: expose Stage 4A observer API"
```

---

### Task 4: Stage 4A Operator UI With No Output Action

**Files:**
- Create: `frontend/js/load-control-stage4a-api.js`
- Create: `frontend/js/load-control-stage4a-ui.js`
- Create: `frontend/css/load-control/p-control-observer.css`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Create: `tests/browser/test_load_control_stage4a_contract.py`

**Interfaces:**
- Consumes Stage 4A API and existing `getSafeTestSources()` only for enabled Emonio source choices.
- Produces one separate `P CONTROL OBSERVER` section.
- Does not import or call any manual PWM apply/off function.

- [ ] **Step 1: Write failing frontend contract tests**

Require these IDs:

```python
required_ids = {
    "lc-pobs-source",
    "lc-pobs-phase",
    "lc-pobs-target",
    "lc-pobs-deadband",
    "lc-pobs-step",
    "lc-pobs-configure",
    "lc-pobs-enable",
    "lc-pobs-disable",
    "lc-pobs-state",
    "lc-pobs-reason",
    "lc-pobs-cycle",
    "lc-pobs-p",
    "lc-pobs-q",
    "lc-pobs-quality",
    "lc-pobs-age",
    "lc-pobs-confirmed-requested",
    "lc-pobs-confirmed-actual",
    "lc-pobs-decision",
    "lc-pobs-proposed",
}
```

Require visible statements:

- `P is the only control variable`
- `Q is display-only`
- `No automatic PWM command is sent`
- `Apply a proposal manually`

Require these strings to be absent from Stage 4A frontend source:

```python
for forbidden in (
    "applyManualPwmDuty",
    "turnManualPwmOff",
    "/lan-pwm/apply",
    "/lan-pwm/off",
    "APPLY PROPOSED",
):
    assert forbidden not in source
```

- [ ] **Step 2: Run contract test and verify RED**

```bash
pytest tests/browser/test_load_control_stage4a_contract.py -q
```

Expected: FAIL because Stage 4A frontend files do not exist.

- [ ] **Step 3: Implement dedicated Stage 4A API client**

Use one local `requestJson()` matching current load-control API error behavior. Export exactly:

```javascript
export function getPObserverStatus() {
  return requestJson("/api/v1/load-control/p-observer/status");
}

export function configurePObserver(settings) {
  return requestJson("/api/v1/load-control/p-observer/configure", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function enablePObserver() {
  return requestJson("/api/v1/load-control/p-observer/enable", {
    method: "POST",
    body: "{}",
  });
}

export function disablePObserver() {
  return requestJson("/api/v1/load-control/p-observer/disable", {
    method: "POST",
    body: "{}",
  });
}

export function getPObserverDiagnostics(afterSequence = 0) {
  return requestJson(
    `/api/v1/load-control/p-observer/diagnostics?after_sequence=${encodeURIComponent(afterSequence)}`,
  );
}
```

No function in this module may call a PWM route.

- [ ] **Step 4: Implement observer UI section**

Insert Stage 4A under `#lc-simulated-operator-slot`. Because Stage 3B creates manual PWM and simulated-test sections first, insert the observer before `.load-control-simulated-test-section` when present. Otherwise append to the slot.

Configuration starts blank/unselected. Do not silently supply target, deadband, or step.

UI rules:

- `SAVE OBSERVER CONFIG` submits all five values in one request;
- `ENABLE OBSERVER` calls only Stage 4A enable;
- `DISABLE OBSERVER` calls only Stage 4A disable and never OFF;
- configuration controls are disabled whenever state is not `DISABLED`;
- `BLOCKED` proposal renders `—`;
- valid `0.0` proposal renders `0.000000 %`;
- P uses `W`;
- Q uses `var` and is labeled display-only;
- requested and actual duty remain separate;
- no proposed-duty apply button exists;
- refresh once per second only while the load-control panel is visible.

- [ ] **Step 5: Add dedicated structured CSS**

Put Stage 4A-specific rules only in:

`frontend/css/load-control/p-control-observer.css`

Reuse existing load-control classes/variables before adding new selectors. Do not add Stage 4A layout rules to unrelated global CSS.

- [ ] **Step 6: Load Stage 4A CSS/JS through `app_v0416.py`**

Use the existing versioned `static_prefix`. Load Stage 4A CSS in `<head>` and load `load-control-stage4a-ui.js` after `load-control-stage3b-ui.js`.

- [ ] **Step 7: Run frontend/server regressions**

```bash
pytest tests/browser/test_load_control_stage4a_contract.py -q
pytest tests/browser/test_frontend_contract.py -q
pytest tests/integration/test_server.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add \
  frontend/js/load-control-stage4a-api.js \
  frontend/js/load-control-stage4a-ui.js \
  frontend/css/load-control/p-control-observer.css \
  src/emonio_viewer/server/app_v0416.py \
  tests/browser/test_load_control_stage4a_contract.py
git commit -m "feat: add Stage 4A P observer UI"
```

---

### Task 5: Static Safety Contract and Complete Spec Coverage

**Files:**
- Create: `tests/integration/test_load_control_stage4a_spec_contract.py`
- Modify: Stage 4A test files only if coverage review finds a missing approved assertion.

**Interfaces:**
- Proves no actuator transport/output authority exists in Stage 4A.
- Proves launcher remains unchanged.
- Provides explicit test mapping for all 28 design-section-21 requirements.

- [ ] **Step 1: Write transport-boundary AST test**

```python
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "src/emonio_viewer/load_control/automatic_observation.py"


def test_stage4a_has_no_actuator_transport_authority() -> None:
    source = OBSERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "QualifiedActuatorChannel" not in source
    assert "PwmCommandFrame" not in source
    forbidden = {"send", "send_pwm", "receive", "receive_nowait", "bind", "clear"}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called.isdisjoint(forbidden)
```

- [ ] **Step 2: Add launcher/public-boundary assertions**

```python
def test_stage4a_keeps_active_launcher() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'emonio-viewer = "emonio_viewer.main_v0416:main"' in pyproject
```

Define the protected path list in this contract test for reviewer visibility. Do not fake a git diff inside pytest; the final shell gate performs that check.

- [ ] **Step 3: Add API/UI no-output assertions**

Read:

- `src/emonio_viewer/server/load_control_stage4a_api.py`
- `frontend/js/load-control-stage4a-api.js`
- `frontend/js/load-control-stage4a-ui.js`

Assert no file contains:

```text
PWM_COMMAND
/lan-pwm/apply
/lan-pwm/off
applyManualPwmDuty
turnManualPwmOff
```

- [ ] **Step 4: Run all targeted Stage 4A tests**

```bash
pytest \
  tests/unit/test_load_control_stage4a_observer.py \
  tests/integration/test_load_control_stage4a_api.py \
  tests/integration/test_load_control_stage4a_spec_contract.py \
  tests/browser/test_load_control_stage4a_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Map every design test requirement 1-28 to a direct assertion**

Use this checklist during review:

1. canonical P sign unchanged — unit test;
2. Q cannot affect proposal — unit test;
3. PF cannot affect proposal — unit test;
4. wrong source ignored — unit test;
5. only post-enable new cycle accepted — unit test;
6. invalid quality blocks — unit test;
7. stale sample blocks — unit test;
8. acquisition failure blocks — unit test;
9. sequence gap blocks — unit test;
10. unknown confirmed duty rejects/blocks — unit test;
11. old boot rejected — unit test;
12. disconnect blocks — unit test;
13. no active proposal below 25 — calculation test;
14. no active proposal above 75 — calculation test;
15. decrease from 25 proposes 0 — calculation test;
16. increase from 0 proposes 25 — calculation test;
17. unapplied proposals do not accumulate — unit test;
18. target band holds confirmed duty — calculation/unit test;
19. one sample at most one calculation — unit/diagnostic-count test;
20. no PWM command — static contract;
21. no actuator frame consumption — AST contract;
22. no command sequence allocation — AST/source contract;
23. active configuration change rejected without mutation — unit/API test;
24. `BLOCKED` does not auto-recover — unit test;
25. changed manual ACK requires later cycle — unit test;
26. existing manual PWM tests pass unchanged — regression command;
27. protected scientific path gate passes — final shell gate;
28. launcher remains `main_v0416:main` — contract plus final grep.

If one item lacks a direct assertion, add it to the most focused existing Stage 4A test file before proceeding.

- [ ] **Step 6: Commit Task 5**

```bash
git add \
  tests/integration/test_load_control_stage4a_spec_contract.py \
  tests/unit/test_load_control_stage4a_observer.py \
  tests/integration/test_load_control_stage4a_api.py \
  tests/browser/test_load_control_stage4a_contract.py
git commit -m "test: lock Stage 4A observer safety boundary"
```

---

### Task 6: Full Regression and Acceptance Evidence

**Files:**
- No planned production changes.
- If a test exposes a real Stage 4A defect, fix only the smallest responsible Stage 4A file and rerun the failed test before the full suite.

**Interfaces:**
- Produces automated acceptance evidence only.
- Does not produce field evidence.

- [ ] **Step 1: Run existing manual PWM regressions first**

```bash
pytest tests/unit/test_load_control_manual_pwm.py -q
pytest tests/integration/test_load_control_stage3b_api.py -q
```

Expected: PASS with no manual PWM source/test changes.

- [ ] **Step 2: Run all Stage 4A targeted tests**

```bash
pytest \
  tests/unit/test_load_control_stage4a_observer.py \
  tests/integration/test_load_control_stage4a_api.py \
  tests/integration/test_load_control_stage4a_spec_contract.py \
  tests/browser/test_load_control_stage4a_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run full repository acceptance**

```bash
./tools/ari-emonio-acceptance.sh
```

Expected: PASS. Record exact observed counts. Do not invent counts before execution.

- [ ] **Step 4: Run the CI protected scientific path gate exactly**

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df HEAD -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: no diff, exit code 0.

Verify recording separately against the approved design commit:

```bash
git diff --exit-code c4a18e0f4215c89b5a005dcaf5ac4236803a2655 HEAD -- src/emonio_viewer/recording
```

Expected: no diff, exit code 0.

- [ ] **Step 5: Verify version and launcher remain unchanged**

```bash
grep -q 'version = "0.4.23"' pyproject.toml
grep -q 'emonio-viewer = "emonio_viewer.main_v0416:main"' pyproject.toml
```

Expected: both exit 0.

- [ ] **Step 6: Inspect complete implementation diff scope**

```bash
git diff --stat c4a18e0f4215c89b5a005dcaf5ac4236803a2655..HEAD
git diff --name-only c4a18e0f4215c89b5a005dcaf5ac4236803a2655..HEAD
```

Expected production paths are limited to:

```text
src/emonio_viewer/load_control/automatic_observation.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/load_control_stage4a_api.py
src/emonio_viewer/server/app_v0416.py
frontend/js/load-control-stage4a-api.js
frontend/js/load-control-stage4a-ui.js
frontend/css/load-control/p-control-observer.css
```

Additional changed files may only be Stage 4A tests and documentation. Any additional production path requires review before completion.

- [ ] **Step 7: Verify branch state and history**

```bash
git status -sb
git log --oneline --decorate -8
```

Expected: clean working tree on `testing` after task commits.

- [ ] **Step 8: Report automated acceptance precisely**

Report:

- exact final `testing` commit;
- exact observed automated test counts;
- protected-path gate result;
- recording gate result;
- launcher/version result;
- exact changed-file list;
- statement: `Stage 4A automated acceptance is not field evidence`;
- field workflow from design section 22.

Do not promote to `main`.

---

## Execution Order Invariant

Execute Tasks 1 through 6 in order. Task 2 must be green before API work. API must be green before UI work. Full automated acceptance and protected-path gates must pass before field qualification begins.
