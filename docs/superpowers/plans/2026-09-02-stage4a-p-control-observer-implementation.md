# Stage 4A P Control Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a P-only, observation-only control service that reads canonical Emonio samples and qualified manual PWM ACK status, then displays a deterministic proposed next duty without sending any actuator command.

**Architecture:** Add one isolated `PControlObserverService` under `load_control`. It subscribes read-only to `RuntimeEventBus`, receives qualification and manual-PWM evidence only through status-provider callables, and never receives `QualifiedActuatorChannel`. A dedicated HTTP API and frontend section expose configuration, state, evidence, and proposal. The existing manual PWM service remains the only physical PWM command/ACK owner.

**Tech Stack:** Python 3.10+, `asyncio`, immutable dataclasses, `aiohttp`, existing `RuntimeEventBus`, existing load-control diagnostic log, vanilla JavaScript modules, structured CSS, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-02-stage4a-p-control-observer-design.md`

## Global Constraints

- Work only on branch `testing`.
- The approved design input baseline is `858111c6252084ef9940c6677b5f601d3c3b8130`; the approved design commit is `c4a18e0f4215c89b5a005dcaf5ac4236803a2655`.
- Viewer version remains `0.4.23` during this Stage 4A implementation unless a separate version-change approval is given.
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
- SAFE/OFF is exactly `0 %`. The current Stage 4A active-duty window is `25 % <= duty <= 75 %`.
- Stage 4A never sends `PWM_COMMAND`, never consumes actuator frames, never allocates actuator sequence numbers, never retries, and never replays.
- Stage 4A configuration can change only while `DISABLED`.
- `BLOCKED` is latched until explicit disable and re-enable.
- A changed qualified manual PWM ACK invalidates the old proposal and requires a later selected-source measurement cycle before the next calculation.
- Existing manual PWM behavior and tests must remain unchanged.
- Automated tests are software evidence only. They are not field evidence.

---

## File Structure

### New files

- `src/emonio_viewer/load_control/automatic_observation.py` — Stage 4A calculation, immutable status/configuration types, event-bus observer service, freshness/block logic, and observer diagnostic evidence.
- `src/emonio_viewer/server/load_control_stage4a_api.py` — Stage 4A HTTP routes only.
- `frontend/js/load-control-stage4a-api.js` — Stage 4A HTTP client functions only.
- `frontend/js/load-control-stage4a-ui.js` — Stage 4A operator UI and rendering only.
- `frontend/css/load-control/p-control-observer.css` — Stage 4A styles only.
- `tests/unit/test_load_control_stage4a_observer.py` — pure calculation and observer state-machine/service tests.
- `tests/integration/test_load_control_stage4a_api.py` — HTTP and app-wiring tests.
- `tests/integration/test_load_control_stage4a_spec_contract.py` — static transport-boundary and launcher/protected-contract checks.
- `tests/browser/test_load_control_stage4a_contract.py` — Stage 4A frontend contract tests.

### Existing files with minimal changes

- `src/emonio_viewer/server/keys.py` — add one typed app key for the observer service.
- `src/emonio_viewer/server/app_v0416.py` — instantiate/start/stop Stage 4A, register routes, and load its dedicated CSS/JS.

### Existing files that must not change

- `src/emonio_viewer/load_control/manual_pwm.py`
- `src/emonio_viewer/load_control/qualified_channel.py`
- `src/emonio_viewer/load_control/qualification.py`
- `src/emonio_viewer/load_control/stage3a.py`
- `src/emonio_viewer/load_control/stage3b.py`
- `src/emonio_viewer/server/load_control_stage3b_api.py`
- all protected scientific paths listed in Global Constraints

---

### Task 1: Pure P-Only Proposal Calculation

**Files:**
- Create: `src/emonio_viewer/load_control/automatic_observation.py`
- Create: `tests/unit/test_load_control_stage4a_observer.py`

**Interfaces:**
- Consumes: finite scalar `measured_p_w`, `p_target_w`, `p_deadband_w`, `confirmed_duty_percent`, and `duty_step_percent`.
- Produces:
  - `PControlDecision(str, Enum)` with `INCREASE`, `HOLD`, `DECREASE`, `LIMIT_LOW`, `LIMIT_HIGH`.
  - `PControlProposal` immutable dataclass with `decision`, `proposed_duty_percent`, `low_w`, `high_w`.
  - `calculate_p_control_proposal(...) -> PControlProposal`.

- [ ] **Step 1: Write the failing pure-calculation tests**

Add tests that use the exact approved equations and qualified duty window:

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


def test_negative_p_increases_one_step_without_watts_to_duty_mapping() -> None:
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

Also add parameterized validation tests that reject non-finite target/deadband/step/duty, negative deadband, non-positive step, and confirmed active duty in `(0, 25)` or above `75`.

- [ ] **Step 2: Run the pure-calculation tests and verify RED**

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: FAIL because `automatic_observation.py` and its public interfaces do not exist yet.

- [ ] **Step 3: Implement the minimal pure calculation**

Start `automatic_observation.py` with these exact public constants and types:

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
```

Implement `calculate_p_control_proposal()` exactly from design section 9. The function signature must not accept Q or PF:

```python
def calculate_p_control_proposal(
    *,
    measured_p_w: float,
    p_target_w: float,
    p_deadband_w: float,
    confirmed_duty_percent: float,
    duty_step_percent: float,
) -> PControlProposal:
    ...
```

Use finite numeric validation. Accept confirmed duty only when it is exactly `0.0` or in the inclusive range `25.0..75.0`. Never clamp an invalid confirmed baseline into the qualified window.

- [ ] **Step 4: Run the pure-calculation tests and verify GREEN**

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: PASS for the calculation tests.

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
  - `RuntimeEventBus` for canonical `MeasurementSample | DiagnosticEvent` observation.
  - `RuntimeConfig` for enabled Emonio source identity and `poll_interval_s` only.
  - `Callable[[], QualificationStatus]` for current HELLO-qualified actuator status.
  - `Callable[[], ManualPwmStatus | None]` for current qualified manual PWM ACK status.
- Produces:
  - `PControlObserverState` enum.
  - `PControlObserverSettings` immutable dataclass.
  - `PControlObserverStatus` immutable dataclass.
  - `PControlObserverError`.
  - `PControlObserverService.start()`, `.close()`, `.configure()`, `.enable()`, `.disable()`, `.status()`, `.diagnostics()`.
- Does not consume or receive `QualifiedActuatorChannel`.

- [ ] **Step 1: Add failing state/configuration tests**

Define tests around these exact state and status fields:

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

`PControlObserverStatus` must expose at least:

```python
state
reason
source_id
phase
sample_cycle_id
measured_p_w
measured_q_var
sample_quality
sample_age_s
p_target_w
p_deadband_w
duty_step_percent
actuator_node_id
actuator_boot_id
confirmed_command_sequence
confirmed_requested_duty_percent
confirmed_actual_duty_percent
decision
proposed_duty_percent
```

Add a test that proves configuration is atomic and rejected while active:

```python
service.configure(
    source_id="emonio-a",
    phase="A",
    p_target_w=0.0,
    p_deadband_w=2.0,
    duty_step_percent=5.0,
)
await service.enable()
with pytest.raises(PControlObserverError, match="OBSERVER_NOT_DISABLED"):
    service.configure(
        source_id="emonio-a",
        phase="B",
        p_target_w=0.0,
        p_deadband_w=2.0,
        duty_step_percent=5.0,
    )
assert service.status().phase == "A"
```

- [ ] **Step 2: Add failing enable-gate tests**

Build simple provider objects that return real existing dataclasses `QualificationStatus` and `ManualPwmStatus`. Test each exact enable rejection independently:

- `SOURCE_NOT_AVAILABLE`
- `PHASE_NOT_SELECTED`
- `PARAMETER_INVALID`
- `ACTUATOR_NOT_QUALIFIED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

A rejected enable must leave state `DISABLED` and `proposed_duty_percent is None`.

- [ ] **Step 3: Run state/configuration tests and verify RED**

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: FAIL because the service/state interfaces are not implemented.

- [ ] **Step 4: Implement immutable settings/status and provider-only service construction**

Add these constructor semantics:

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
        ...
```

Do not add any constructor argument for a WebSocket session or `QualifiedActuatorChannel`.

`configure()` must accept all five session settings in one call and must mutate nothing if any value is invalid.

`enable()` must:

1. verify a configured enabled source and phase,
2. read one qualification snapshot,
3. require `connected` and `hello_qualified`,
4. require `PWM_DUTY_CONTROL` in capabilities,
5. read one manual PWM status snapshot,
6. require `ack_result == "APPLIED"`,
7. require current node/boot identity to match qualification,
8. require confirmed requested duty to be exactly `0.0` or within `25.0..75.0`,
9. record the current source cycle boundary and current monotonic start time,
10. record the manual ACK fingerprint `(node_id, boot_id, command_sequence, requested_duty_percent)`,
11. enter `WAITING_FOR_SAMPLE`,
12. set the freshness deadline to `enable_monotonic_ns + 2 * poll_interval_s`.

- [ ] **Step 5: Add failing canonical-sample calculation tests**

Use `dataclasses.replace()` on the existing `real_sample` fixture to create selected-source cycles with controlled P, Q, PF, quality, identity, and timing.

Prove:

- canonical negative P is consumed without sign inversion or `abs()`;
- two samples with equal P and different Q produce the same proposal;
- two samples with equal P and different PF produce the same proposal;
- wrong-source samples are ignored without changing state/proposal;
- the first accepted cycle is strictly after the enable boundary;
- one selected-source sample produces at most one calculation;
- two consecutive samples with unchanged confirmed duty repeat the same proposal rather than accumulating it.

Representative assertion:

```python
assert status.measured_p_w == -60.0
assert status.decision == "INCREASE"
assert status.proposed_duty_percent == 30.0
```

- [ ] **Step 6: Implement event-bus observation and phase selection**

`start()` subscribes to `RuntimeEventBus(maxsize=256)` and starts one consumer task.

The service tracks latest cycle per source even while disabled so enable can establish a real boundary.

For a selected-source `MeasurementSample` while enabled:

1. reject a sequence gap before proposal calculation,
2. reject non-`VALID` quality,
3. compute age from `cycle_finished_monotonic_ns` using the injected monotonic clock,
4. reject negative age or age greater than `2 * poll_interval_s` as `SAMPLE_STALE`,
5. read qualification/manual PWM snapshots,
6. validate actuator identity/capability/current confirmed duty,
7. detect any changed manual ACK fingerprint before proposal calculation,
8. if the fingerprint changed, invalidate the old proposal, record the new baseline, consume this cycle only as the causal boundary, enter `WAITING_FOR_SAMPLE`, and do not calculate,
9. otherwise select P and Q directly from `sample.phase_a|b|c.measurement`,
10. call `calculate_p_control_proposal()` with P only,
11. update immutable status fields and set `OBSERVING`, `TARGET_BAND`, `LIMIT_LOW`, or `LIMIT_HIGH`.

Do not access `sample.total` for Stage 4A control.

- [ ] **Step 7: Add failing runtime-block tests**

Test each exact runtime block:

- `SAMPLE_NOT_VALID`
- `SAMPLE_STALE`
- `SAMPLE_SEQUENCE_GAP`
- `ACQUISITION_FAILURE`
- `ACTUATOR_BOOT_CHANGED`
- `ACTUATOR_DISCONNECTED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

For every block assert:

```python
assert status.state is PControlObserverState.BLOCKED
assert status.proposed_duty_percent is None
```

Then provide later valid evidence and assert the state remains `BLOCKED`. Finally call `disable()` and assert the latch clears to `DISABLED`.

- [ ] **Step 8: Implement deterministic runtime blocking and freshness deadline**

Add one internal helper that all fault paths use:

```python
def _block(self, reason: str) -> None:
    if self._state is PControlObserverState.BLOCKED:
        return
    self._state = PControlObserverState.BLOCKED
    self._reason = reason
    self._proposed_duty_percent = None
    self._decision = None
    self._diagnostic_log.append("P_OBSERVER_BLOCKED", reason=reason)
```

The event consumer may use a monotonic timeout only to call an internal deadline check. The deadline check must never calculate a proposal.

Deadline precedence must be deterministic:

1. actuator disconnected,
2. actuator boot changed,
3. capability missing,
4. confirmed duty missing/outside window,
5. expected sample stale.

A selected-source `DiagnosticEvent` whose `event` starts with `ACQUISITION_` blocks with `ACQUISITION_FAILURE`.

- [ ] **Step 9: Add failing changed-manual-ACK causal-boundary test**

Test this exact sequence:

```text
ACK sequence 10 confirms 25 %
enable observer
cycle 101 -> proposal 30 %
provider changes to ACK sequence 11 confirming 30 %
cycle 102 -> detect new ACK, proposal becomes null, state WAITING_FOR_SAMPLE
cycle 103 -> calculate from confirmed 30 %
```

Assert cycle 102 is never used to calculate from the new 30 % baseline.

- [ ] **Step 10: Implement manual-ACK fingerprint boundary and diagnostics**

Use the fingerprint:

```python
(node_id, boot_id, command_sequence, requested_duty_percent)
```

Do not use unacknowledged manual request state as a baseline.

Add reproducible diagnostics with event names such as:

- `P_OBSERVER_ENABLED`
- `P_OBSERVER_DISABLED`
- `P_OBSERVER_SAMPLE_IGNORED`
- `P_OBSERVER_DUTY_BASELINE_CHANGED`
- `P_OBSERVER_PROPOSAL_CALCULATED`
- `P_OBSERVER_BLOCKED`

`P_OBSERVER_PROPOSAL_CALCULATED` must include source, phase, cycle, measured P, target, deadband, confirmed requested duty, duty step, decision, proposed duty, and state. It must not contain text that claims the proposal was applied.

- [ ] **Step 11: Run all Stage 4A unit tests**

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
pytest tests/unit/test_load_control_manual_pwm.py -q
```

Expected: PASS. The existing manual PWM test file must be unchanged.

- [ ] **Step 12: Commit Task 2**

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
- Consumes: `PControlObserverService` only.
- Produces routes:
  - `GET /api/v1/load-control/p-observer/status`
  - `POST /api/v1/load-control/p-observer/configure`
  - `POST /api/v1/load-control/p-observer/enable`
  - `POST /api/v1/load-control/p-observer/disable`
  - `GET /api/v1/load-control/p-observer/diagnostics`

- [ ] **Step 1: Write failing API serialization and validation tests**

The configure request must contain exactly:

```json
{
  "source_id": "emonio-example",
  "phase": "A",
  "p_target_w": 0.0,
  "p_deadband_w": 2.0,
  "duty_step_percent": 5.0
}
```

Reject extra/missing fields with HTTP 400. Reject invalid numeric/phase/source payloads with HTTP 400. Reject active-state configuration and failed enable gates with HTTP 409 and the exact backend reason text.

Status JSON must expose the fields defined in Task 2 and must encode `None` as JSON `null`.

Diagnostics JSON format:

```json
{
  "latest_sequence": 7,
  "events": [
    {"sequence": 7, "utc": "...", "event": "P_OBSERVER_PROPOSAL_CALCULATED", "line": "..."}
  ]
}
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
pytest tests/integration/test_load_control_stage4a_api.py -q
```

Expected: FAIL because the routes and app key do not exist.

- [ ] **Step 3: Implement one typed app key**

In `server/keys.py`, import `PControlObserverService` and add:

```python
P_CONTROL_OBSERVER_SERVICE_KEY = web.AppKey(
    "p_control_observer_service",
    PControlObserverService,
)
```

Do not change existing keys.

- [ ] **Step 4: Implement the dedicated route module**

`load_control_stage4a_api.py` must have its own strict JSON parser/validators and must not call Stage 3B PWM endpoints.

Use the app key to resolve the observer service. Implement status, configure, enable, disable, and diagnostics only.

`enable` and `disable` accept exactly an empty JSON object `{}`.

- [ ] **Step 5: Wire Stage 4A into `app_v0416.py` without transport ownership**

Extend `create_app()` with optional injection:

```python
p_control_observer_service: PControlObserverService | None = None,
```

After the existing default manual PWM-capable `stage3a_service` is resolved, create the default observer with read-only providers:

```python
def qualification_status_provider():
    return qualification_service.status()


def manual_pwm_status_provider():
    getter = getattr(stage3a_service, "manual_pwm_status", None)
    return getter() if callable(getter) else None


p_control_observer_service = PControlObserverService(
    bus,
    config,
    qualification_status=qualification_status_provider,
    manual_pwm_status=manual_pwm_status_provider,
)
```

This wrapper preserves existing tests that may inject a plain Stage 3A service with no manual PWM interface. In that case Stage 4A exists but cannot pass the confirmed-duty enable gate.

Register observer startup after Stage 3A startup and observer cleanup before Stage 3A cleanup so its read-only providers remain valid while it shuts down.

Register the dedicated Stage 4A routes.

Do not pass `qualified_channel` into the observer.

- [ ] **Step 6: Run API/app tests and existing Stage 3A/3B API regressions**

Run:

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
- Consumes: Stage 4A HTTP API from Task 3 and existing `getSafeTestSources()` only for the list of enabled Emonio sources.
- Produces: one separate `P CONTROL OBSERVER` section in the existing load-control panel.
- Must not import or call `applyManualPwmDuty()` or `turnManualPwmOff()`.

- [ ] **Step 1: Write failing frontend contract tests**

Read the Stage 4A frontend source as text and assert all required operator fields exist:

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

Assert the visible copy contains all four scientific boundary statements:

- `P is the only control variable`
- `Q is display-only`
- `No automatic PWM command is sent`
- `Apply a proposal manually`

Assert forbidden output hooks are absent from `load-control-stage4a-ui.js` and `load-control-stage4a-api.js`:

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

- [ ] **Step 2: Run browser contract tests and verify RED**

Run:

```bash
pytest tests/browser/test_load_control_stage4a_contract.py -q
```

Expected: FAIL because Stage 4A frontend files do not exist.

- [ ] **Step 3: Implement the dedicated Stage 4A API client**

Export only:

```javascript
export function getPObserverStatus() { ... }
export function configurePObserver(settings) { ... }
export function enablePObserver() { ... }
export function disablePObserver() { ... }
export function getPObserverDiagnostics(afterSequence = 0) { ... }
```

Use the exact Task 3 routes. Do not import Stage 3B PWM API functions.

- [ ] **Step 4: Implement the observer UI section**

Create the section under `#lc-simulated-operator-slot`. Because `load-control-stage3b-ui.js` already creates the manual PWM and simulated-test sections, insert the observer section before `.load-control-simulated-test-section` when that element exists; otherwise append it to the slot.

Configuration inputs start unselected/blank. Do not silently populate a control target, deadband, or duty step.

The UI behavior is:

- `SAVE OBSERVER CONFIG` sends all five settings atomically.
- `ENABLE OBSERVER` is available only after settings are valid enough to submit; backend enable gates remain authoritative.
- `DISABLE OBSERVER` disables observation only. It does not send OFF.
- configuration controls are disabled while state is not `DISABLED`.
- `BLOCKED` renders proposed duty as `—`.
- a valid `0.0` proposal renders `0.000000 %`, not `—`.
- measured P and Q are shown separately with units `W` and `var`.
- requested and actual PWM duty are shown separately.
- refresh status once per second only while the load-control panel is visible, following the current load-control UI pattern.

Do not add an `APPLY PROPOSED` button.

- [ ] **Step 5: Add dedicated structured CSS**

Use `frontend/css/load-control/p-control-observer.css` for Stage 4A-specific layout only. Reuse existing load-control variables/classes where possible. Do not add Stage 4A rules to unrelated global CSS files.

- [ ] **Step 6: Load the new CSS/JS through `app_v0416.py`**

Add one versioned stylesheet and one versioned module script using the existing `static_prefix` mechanism. Load `load-control-stage4a-ui.js` after `load-control-stage3b-ui.js` so the insertion point/order is deterministic.

- [ ] **Step 7: Run frontend and server regressions**

Run:

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

### Task 5: Static Safety Contract and Complete Stage 4A Coverage

**Files:**
- Create: `tests/integration/test_load_control_stage4a_spec_contract.py`
- Modify: `tests/unit/test_load_control_stage4a_observer.py` only if a missing approved behavioral case is found during coverage review.

**Interfaces:**
- Consumes: frozen Stage 4A source files.
- Produces: deterministic regression proof that the Stage 4A module has no actuator transport/output interface and that protected/public launcher boundaries remain intact.

- [ ] **Step 1: Write the transport-boundary contract test**

Use AST plus exact file paths. The test must fail if `automatic_observation.py` imports `QualifiedActuatorChannel` or calls any forbidden actuator channel method:

```python
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "src/emonio_viewer/load_control/automatic_observation.py"


def test_stage4a_has_no_actuator_transport_authority() -> None:
    source = OBSERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "QualifiedActuatorChannel" not in source
    forbidden = {"send", "send_pwm", "receive", "receive_nowait", "bind", "clear"}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called.isdisjoint(forbidden)
```

Also assert no `PwmCommandFrame` import or construction exists in Stage 4A.

- [ ] **Step 2: Add launcher and protected-path contract assertions**

The test must read `pyproject.toml` and assert:

```python
assert 'emonio-viewer = "emonio_viewer.main_v0416:main"' in pyproject
```

It must also define the exact protected path list used by the project gate so reviewers can compare it to the final git diff.

Do not attempt to prove a git diff inside a normal pytest test; the final shell gate does that deterministically.

- [ ] **Step 3: Add API/UI no-output contract assertions**

Read these files:

- `src/emonio_viewer/server/load_control_stage4a_api.py`
- `frontend/js/load-control-stage4a-api.js`
- `frontend/js/load-control-stage4a-ui.js`

Assert they contain no manual PWM apply/off route and no `PWM_COMMAND` construction/transmission path.

- [ ] **Step 4: Run the Stage 4A contract and all targeted Stage 4A tests**

Run:

```bash
pytest \
  tests/unit/test_load_control_stage4a_observer.py \
  tests/integration/test_load_control_stage4a_api.py \
  tests/integration/test_load_control_stage4a_spec_contract.py \
  tests/browser/test_load_control_stage4a_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Review the 28 approved spec tests against implementation**

Check each numbered requirement in design section 21 against an explicit test. The final test set must contain a direct assertion for every item 1 through 28. Add a missing assertion only to the most focused existing Stage 4A test file. Do not create duplicate tests for behavior already directly asserted.

- [ ] **Step 6: Commit Task 5**

```bash
git add \
  tests/integration/test_load_control_stage4a_spec_contract.py \
  tests/unit/test_load_control_stage4a_observer.py
git commit -m "test: lock Stage 4A observer safety boundary"
```

---

### Task 6: Full Regression, Protected-Path Gate, and Publication Evidence

**Files:**
- No production files should be added in this task.
- Modify tests only if a real regression exposes a Stage 4A defect; fix the smallest responsible Stage 4A file and rerun the failed gate first.

**Interfaces:**
- Consumes: complete Stage 4A implementation from Tasks 1-5.
- Produces: automated acceptance evidence only; no field-evidence claim.

- [ ] **Step 1: Run existing manual PWM regression first**

```bash
pytest tests/unit/test_load_control_manual_pwm.py -q
pytest tests/integration/test_load_control_stage3b_api.py -q
```

Expected: PASS with no modifications to the existing manual PWM implementation or tests.

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

- [ ] **Step 3: Run the full repository acceptance**

```bash
./tools/ari-emonio-acceptance.sh
```

Expected: PASS. Record the exact counts from the script output. Do not invent counts in advance.

- [ ] **Step 4: Run the protected scientific path gate exactly as CI does**

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df HEAD -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: no diff and exit code 0.

Also verify recording separately because it is protected by the Stage 4A design even though the current CI protected-path command does not list it:

```bash
git diff --exit-code c4a18e0f4215c89b5a005dcaf5ac4236803a2655 HEAD -- src/emonio_viewer/recording
```

Expected: no diff and exit code 0.

- [ ] **Step 5: Verify launcher and version remain unchanged**

```bash
grep -q 'version = "0.4.23"' pyproject.toml
grep -q 'emonio-viewer = "emonio_viewer.main_v0416:main"' pyproject.toml
```

Expected: both commands exit 0.

- [ ] **Step 6: Inspect the complete implementation diff for scope**

```bash
git diff --stat c4a18e0f4215c89b5a005dcaf5ac4236803a2655..HEAD
git diff --name-only c4a18e0f4215c89b5a005dcaf5ac4236803a2655..HEAD
```

Expected changed production paths are limited to:

```text
src/emonio_viewer/load_control/automatic_observation.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/load_control_stage4a_api.py
src/emonio_viewer/server/app_v0416.py
frontend/js/load-control-stage4a-api.js
frontend/js/load-control-stage4a-ui.js
frontend/css/load-control/p-control-observer.css
```

plus the Stage 4A test files and this implementation plan. Any additional production file requires explicit evidence and review before completion.

- [ ] **Step 7: Verify working tree and commit history**

```bash
git status -sb
git log --oneline --decorate -8
```

Expected: clean working tree on `testing` after all task commits.

- [ ] **Step 8: Report acceptance without claiming field evidence**

Report:

- exact final testing commit,
- exact automated test counts actually observed,
- protected-path gate result,
- launcher/version result,
- exact changed-file list,
- statement: `Stage 4A automated acceptance is not field evidence`,
- next field workflow from design section 22.

Do not promote to `main`.

---

## Execution Order Invariant

Execute Tasks 1 through 6 in order. Do not start Task 3 before Task 2 is green. Do not create UI behavior before the backend API contract is green. Do not run field qualification until the complete automated acceptance and protected-path gates pass.
