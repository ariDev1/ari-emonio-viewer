# Stage 4A P Control Observer Implementation Plan

> **Execution requirement:** Use test-driven development. Implement tasks in order. Do not start a production step until its new test fails for the expected reason.

**Goal:** Add a P-only, observation-only service that reads canonical Emonio samples and current qualified manual PWM ACK evidence, then displays a deterministic proposed next duty. Stage 4A has no actuator output authority.

**Approved design:** `docs/superpowers/specs/2026-09-02-stage4a-p-control-observer-design.md`

**Approved design commit:** `c4a18e0f4215c89b5a005dcaf5ac4236803a2655`

## Fixed boundaries

- Work only on `testing`.
- Keep Viewer version `0.4.23` unless separately approved.
- Keep launcher `emonio-viewer = "emonio_viewer.main_v0416:main"`.
- Do not modify acquisition, measurement, Modbus, recording, SCOPE, `runtime/events.py`, or `runtime/store.py`.
- Do not modify canonical P/Q signs, quadrant semantics, PF semantics, validation, acquisition timing, Modbus read-only behavior, recording, CSV precision, or SCOPE semantics.
- Stage 4A uses P only. Q is display-only. PF is not a control input.
- SAFE/OFF is exactly `0 %`.
- Qualified Stage 4A active-duty window is `25 %` through `75 %`, inclusive.
- Stage 4A never sends `PWM_COMMAND`.
- Stage 4A never consumes actuator frames.
- Stage 4A never receives `QualifiedActuatorChannel`.
- Stage 4A never allocates actuator sequence numbers.
- Stage 4A never retries or replays commands.
- Existing manual PWM remains the only physical PWM command owner.
- `BLOCKED` is latched until explicit observer disable and enable.
- Configuration changes are accepted only in `DISABLED`.
- A changed qualified manual PWM ACK invalidates the old proposal and requires a later Emonio cycle before the next proposal.
- Automated tests are not field evidence.

## Planned production files

New:

- `src/emonio_viewer/load_control/automatic_observation.py`
- `src/emonio_viewer/server/load_control_stage4a_api.py`
- `frontend/js/load-control-stage4a-api.js`
- `frontend/js/load-control-stage4a-ui.js`
- `frontend/css/load-control/p-control-observer.css`

Minimal existing-file changes:

- `src/emonio_viewer/server/keys.py`
- `src/emonio_viewer/server/app_v0416.py`

The following existing control files remain unchanged:

- `src/emonio_viewer/load_control/manual_pwm.py`
- `src/emonio_viewer/load_control/qualified_channel.py`
- `src/emonio_viewer/load_control/qualification.py`
- `src/emonio_viewer/load_control/stage3a.py`
- `src/emonio_viewer/load_control/stage3b.py`
- `src/emonio_viewer/server/load_control_stage3b_api.py`

## Planned test files

- `tests/unit/test_load_control_stage4a_observer.py`
- `tests/integration/test_load_control_stage4a_api.py`
- `tests/integration/test_load_control_stage4a_spec_contract.py`
- `tests/browser/test_load_control_stage4a_contract.py`

---

## Task 1 — Pure P-only proposal calculation

### 1.1 Write RED unit tests

Create `tests/unit/test_load_control_stage4a_observer.py` and test these exact cases:

```python
from emonio_viewer.load_control.automatic_observation import (
    PControlDecision,
    calculate_p_control_proposal,
)


def test_increase_from_off_starts_at_25_percent() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-60.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.INCREASE
    assert result.proposed_duty_percent == 25.0


def test_increase_uses_one_step() -> None:
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


def test_decrease_from_25_percent_proposes_off() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=5.0,
        p_target_w=0.0,
        p_deadband_w=2.0,
        confirmed_duty_percent=25.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.DECREASE
    assert result.proposed_duty_percent == 0.0


def test_confirmed_75_percent_is_high_limit() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=-20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=75.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.LIMIT_HIGH
    assert result.proposed_duty_percent == 75.0


def test_confirmed_off_is_low_limit_when_less_load_is_required() -> None:
    result = calculate_p_control_proposal(
        measured_p_w=20.0,
        p_target_w=0.0,
        p_deadband_w=1.0,
        confirmed_duty_percent=0.0,
        duty_step_percent=5.0,
    )
    assert result.decision is PControlDecision.LIMIT_LOW
    assert result.proposed_duty_percent == 0.0
```

Also test:

- an increase from `70 %` with a `10 %` step proposes `75 %` with decision `INCREASE`;
- `LIMIT_HIGH` occurs only when confirmed baseline is already `75 %` and P still requires more load;
- non-finite values are rejected;
- negative deadband is rejected;
- zero or negative duty step is rejected;
- confirmed active duty in `(0, 25)` is rejected;
- confirmed duty above `75` is rejected.

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
```

Expected: RED because the new module does not exist.

### 1.2 Implement the pure calculator

Create `automatic_observation.py` with:

```python
ACTIVE_DUTY_MIN_PERCENT = 25.0
ACTIVE_DUTY_MAX_PERCENT = 75.0
SAFE_DUTY_PERCENT = 0.0
```

Define:

```python
class PControlDecision(str, Enum):
    INCREASE = "INCREASE"
    HOLD = "HOLD"
    DECREASE = "DECREASE"
    LIMIT_LOW = "LIMIT_LOW"
    LIMIT_HIGH = "LIMIT_HIGH"
```

Define immutable `PControlProposal` with:

```text
decision
proposed_duty_percent
low_w
high_w
```

Implement this exact decision order:

```text
LOW  = target - deadband
HIGH = target + deadband

if P < LOW:
    if D == 75:
        LIMIT_HIGH, proposal 75
    elif D == 0:
        INCREASE, proposal 25
    else:
        INCREASE, proposal min(D + step, 75)

elif P > HIGH:
    if D == 0:
        LIMIT_LOW, proposal 0
    elif D == 25:
        DECREASE, proposal 0
    else:
        DECREASE, proposal max(D - step, 25)

else:
    HOLD, proposal D
```

The function signature contains no Q or PF argument.

Run the Task 1 unit tests. Expected: GREEN.

Commit:

```bash
git add src/emonio_viewer/load_control/automatic_observation.py tests/unit/test_load_control_stage4a_observer.py
git commit -m "feat: add Stage 4A P-only proposal calculation"
```

---

## Task 2 — Read-only observer service and fail-closed state

### 2.1 Write RED state and configuration tests

Extend `test_load_control_stage4a_observer.py`.

Define expected states:

```text
DISABLED
WAITING_FOR_SAMPLE
OBSERVING
TARGET_BAND
LIMIT_LOW
LIMIT_HIGH
BLOCKED
```

Define immutable settings with:

```text
source_id
phase
p_target_w
p_deadband_w
duty_step_percent
```

Define immutable status with at least:

```text
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

Test that configuration is atomic and rejected with `OBSERVER_NOT_DISABLED` whenever state is not `DISABLED`.

Test enable rejection reasons independently:

- `SOURCE_NOT_AVAILABLE`
- `PHASE_NOT_SELECTED`
- `PARAMETER_INVALID`
- `ACTUATOR_NOT_QUALIFIED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

A rejected enable must remain `DISABLED` with proposal `None`.

Run the unit file. Expected: RED.

### 2.2 Implement provider-only construction

`PControlObserverService` constructor must accept only:

```text
RuntimeEventBus
RuntimeConfig
qualification_status callable
manual_pwm_status callable
optional LoadControlDiagnosticLog
optional monotonic_ns callable
```

It must not accept:

```text
QualifiedActuatorChannel
WebSocketActuatorSession
PwmCommandFrame
```

`configure()` accepts all five settings in one call. Validate the complete replacement before assigning it.

### 2.3 Implement qualified duty evidence validation

Read qualification status first, then manual PWM status.

Require:

```text
qualification.connected is true
qualification.hello_qualified is true
PWM_DUTY_CONTROL is advertised
manual ACK result is APPLIED
manual node ID matches qualification node ID
manual boot ID matches qualification boot ID
manual command sequence exists
manual requested duty exists
manual requested duty is 0 or inside 25..75 inclusive
```

Use this baseline fingerprint:

```text
(node_id, boot_id, command_sequence, requested_duty_percent)
```

During an active observer session, check boot identity before generic ACK completeness so a qualified new boot reports `ACTUATOR_BOOT_CHANGED`.

### 2.4 Implement enable and disable

`enable()` must:

1. require service started;
2. require complete settings;
3. require current qualified PWM evidence;
4. record the latest selected-source cycle as the enable boundary;
5. record current monotonic time;
6. store the ACK fingerprint and requested/actual duty;
7. clear old measurement/proposal evidence;
8. enter `WAITING_FOR_SAMPLE`;
9. set freshness deadline to `enable time + 2 * selected source poll interval`;
10. log `P_OBSERVER_ENABLED`.

`disable()` must:

1. enter `DISABLED`;
2. clear block latch and proposal;
3. clear freshness deadline;
4. log `P_OBSERVER_DISABLED`;
5. send no actuator command.

### 2.5 Write RED canonical-sample tests

Using `dataclasses.replace()` on the existing `real_sample` fixture, prove:

- canonical negative P remains negative;
- Q changes cannot affect the proposal when P and all control inputs are unchanged;
- PF changes cannot affect the proposal;
- wrong-source samples are ignored;
- an existing pre-enable cycle is not accepted as new evidence;
- one sample causes at most one calculation;
- unchanged confirmed duty causes the same proposal on later cycles and does not accumulate an unapplied proposal.

### 2.6 Implement event-bus observation

`start()` subscribes to `RuntimeEventBus(maxsize=256)` and starts one consumer task.

Track latest cycle per device while disabled so enable can establish a true cycle boundary.

For a selected-source `MeasurementSample` while active:

1. if already `BLOCKED`, ignore it;
2. require continuous cycle sequence;
3. require a new post-enable cycle;
4. require `SampleQuality.VALID`;
5. calculate sample age from canonical `cycle_finished_monotonic_ns`;
6. block if age is negative or greater than `2 * poll_interval`;
7. read current qualification/manual PWM evidence;
8. detect changed manual ACK fingerprint before calculation;
9. if fingerprint changed, store the new baseline, clear proposal, enter `WAITING_FOR_SAMPLE`, reset freshness deadline, log `P_OBSERVER_DUTY_BASELINE_CHANGED`, and consume this cycle without calculation;
10. otherwise read P and Q directly from the selected phase block;
11. call the pure calculator with P only;
12. map decision to observer state;
13. set the next freshness deadline from the accepted sample;
14. log `P_OBSERVER_PROPOSAL_CALCULATED`.

Do not use `sample.total` for control.

### 2.7 Write RED runtime-block tests

Prove these exact block reasons:

- `SAMPLE_NOT_VALID`
- `SAMPLE_STALE`
- `SAMPLE_SEQUENCE_GAP`
- `ACQUISITION_FAILURE`
- `ACTUATOR_BOOT_CHANGED`
- `ACTUATOR_DISCONNECTED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

For every runtime block:

```text
state = BLOCKED
proposed_duty_percent = null
```

Provide later valid evidence and prove the block remains latched. Only explicit disable clears it.

### 2.8 Implement deterministic block and deadline handling

Use one internal block helper. It sets `BLOCKED`, stores the first reason, clears decision/proposal/deadline, and logs `P_OBSERVER_BLOCKED`.

Deadline/evidence check precedence:

1. actuator disconnected;
2. boot changed;
3. PWM capability missing;
4. confirmed duty missing or outside window;
5. sample stale.

A selected-source diagnostic whose event starts with `ACQUISITION_` blocks with `ACQUISITION_FAILURE`.

The deadline check may detect faults. It must never calculate a proposal.

### 2.9 Write changed-ACK causal-boundary test

Prove:

```text
ACK sequence 10 confirms 25 %
enable observer
cycle 101 -> proposal 30 %
ACK sequence 11 confirms 30 %
cycle 102 -> no proposal, WAITING_FOR_SAMPLE
cycle 103 -> calculate from confirmed 30 %
```

### 2.10 Implement diagnostics

Required event names:

- `P_OBSERVER_ENABLED`
- `P_OBSERVER_DISABLED`
- `P_OBSERVER_SAMPLE_IGNORED`
- `P_OBSERVER_DUTY_BASELINE_CHANGED`
- `P_OBSERVER_PROPOSAL_CALCULATED`
- `P_OBSERVER_BLOCKED`

A proposal record must contain enough evidence to reproduce the calculation:

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

Do not use wording that claims a proposal was applied.

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py -q
pytest tests/unit/test_load_control_manual_pwm.py -q
```

Expected: GREEN. Existing manual PWM files and tests remain unchanged.

Commit:

```bash
git add src/emonio_viewer/load_control/automatic_observation.py tests/unit/test_load_control_stage4a_observer.py
git commit -m "feat: add fail-closed Stage 4A observer service"
```

---

## Task 3 — Dedicated Stage 4A HTTP API and app wiring

### 3.1 Write RED API tests

Create `tests/integration/test_load_control_stage4a_api.py`.

Routes:

- `GET /api/v1/load-control/p-observer/status`
- `POST /api/v1/load-control/p-observer/configure`
- `POST /api/v1/load-control/p-observer/enable`
- `POST /api/v1/load-control/p-observer/disable`
- `GET /api/v1/load-control/p-observer/diagnostics`

Configure body is exactly:

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

- missing/extra configure fields -> HTTP 400;
- malformed numeric/phase/source values -> HTTP 400;
- active configuration conflict -> HTTP 409;
- failed enable gate -> HTTP 409 with exact backend reason;
- enable/disable body must be exactly `{}`;
- status serializes Python `None` as JSON `null`;
- enum decision serializes its value or `null`;
- diagnostics returns bounded observer records.

Run API tests. Expected: RED.

### 3.2 Implement API key and routes

Add `P_CONTROL_OBSERVER_SERVICE_KEY` to `server/keys.py`.

Create `load_control_stage4a_api.py` with strict JSON validation. It resolves only the Stage 4A service. It must not import Stage 3B PWM routes or PWM command types.

Map malformed request data to HTTP 400 and `PControlObserverError` conflicts/gates to HTTP 409.

### 3.3 Wire service into `app_v0416.py`

Add optional injection:

```text
p_control_observer_service: PControlObserverService | None
```

Default construction uses two read-only provider functions:

```text
qualification_service.status()
stage3a_service.manual_pwm_status() when that method exists
```

If an injected Stage 3A service has no `manual_pwm_status`, the provider returns `None`; Stage 4A then fails closed at its confirmed-duty gate.

Never pass `qualified_channel` to Stage 4A.

Startup/cleanup order:

```text
start load-control
start Stage 3A/manual PWM
start Stage 4A
cleanup Stage 4A
cleanup Stage 3A/manual PWM
cleanup qualification
cleanup load-control
```

Run:

```bash
pytest tests/integration/test_load_control_stage4a_api.py -q
pytest tests/integration/test_load_control_stage3a_api.py -q
pytest tests/integration/test_load_control_stage3b_api.py -q
```

Expected: GREEN.

Commit:

```bash
git add src/emonio_viewer/server/load_control_stage4a_api.py src/emonio_viewer/server/keys.py src/emonio_viewer/server/app_v0416.py tests/integration/test_load_control_stage4a_api.py
git commit -m "feat: expose Stage 4A observer API"
```

---

## Task 4 — Stage 4A operator UI with no output action

### 4.1 Write RED frontend contract tests

Create `tests/browser/test_load_control_stage4a_contract.py`.

Require IDs for:

```text
source
phase
target
deadband
duty step
save configuration
enable
disable
state
reason
cycle
P
Q
quality
sample age
confirmed requested duty
confirmed actual duty
decision
proposed duty
```

Require visible statements:

- `P is the only control variable`
- `Q is display-only`
- `No automatic PWM command is sent`
- `Apply a proposal manually`

Require Stage 4A frontend source to contain none of:

```text
applyManualPwmDuty
turnManualPwmOff
/lan-pwm/apply
/lan-pwm/off
APPLY PROPOSED
```

Run browser contract test. Expected: RED.

### 4.2 Implement dedicated Stage 4A API client

Create `frontend/js/load-control-stage4a-api.js` with only:

```text
getPObserverStatus
configurePObserver
enablePObserver
disablePObserver
getPObserverDiagnostics
```

Use only Stage 4A routes.

### 4.3 Implement observer UI

Create `frontend/js/load-control-stage4a-ui.js`.

Insert `P CONTROL OBSERVER` in the existing load-control panel before the simulated-test section when that section exists.

UI rules:

- configuration inputs start blank/unselected;
- no target/deadband/step defaults are silently inserted;
- save submits all five settings atomically;
- enable calls only Stage 4A enable;
- disable calls only Stage 4A disable and does not send OFF;
- configuration controls are disabled while state is not `DISABLED`;
- `BLOCKED` proposal renders `—`;
- valid `0.0` proposal renders `0.000000 %`;
- P uses W;
- Q uses var and is visibly display-only;
- requested and actual duty remain separate;
- there is no proposed-duty apply button;
- status refresh follows the existing once-per-second visible-panel pattern.

### 4.4 Add structured CSS

Create `frontend/css/load-control/p-control-observer.css` for Stage 4A-specific rules. Reuse current load-control CSS classes/variables where possible. Do not add Stage 4A rules to unrelated global CSS.

Load the new CSS and JS through the existing versioned `static_prefix` in `app_v0416.py`. Load Stage 4A JS after Stage 3B UI.

Run:

```bash
pytest tests/browser/test_load_control_stage4a_contract.py -q
pytest tests/browser/test_frontend_contract.py -q
pytest tests/integration/test_server.py -q
```

Expected: GREEN.

Commit:

```bash
git add frontend/js/load-control-stage4a-api.js frontend/js/load-control-stage4a-ui.js frontend/css/load-control/p-control-observer.css src/emonio_viewer/server/app_v0416.py tests/browser/test_load_control_stage4a_contract.py
git commit -m "feat: add Stage 4A P observer UI"
```

---

## Task 5 — Static safety contract and complete design coverage

### 5.1 Write RED no-transport contract

Create `tests/integration/test_load_control_stage4a_spec_contract.py`.

Use AST/source checks to prove `automatic_observation.py`:

- does not import or name `QualifiedActuatorChannel`;
- does not import or construct `PwmCommandFrame`;
- does not call `send`, `send_pwm`, `receive`, `receive_nowait`, `bind`, or `clear` on an actuator transport;
- contains no actuator sequence allocator.

Also prove:

```text
pyproject launcher remains emonio_viewer.main_v0416:main
Stage 4A API has no PWM apply/off route
Stage 4A frontend has no PWM apply/off route
Stage 4A frontend has no APPLY PROPOSED action
```

### 5.2 Map all approved design tests

Before final acceptance, confirm a direct assertion exists for every approved requirement:

1. canonical P sign unchanged;
2. Q cannot affect proposal;
3. PF cannot affect proposal;
4. wrong source ignored;
5. only new post-enable cycle accepted;
6. invalid quality blocks;
7. stale sample blocks;
8. acquisition failure blocks;
9. cycle sequence gap blocks;
10. unknown confirmed duty rejects/blocks;
11. old boot evidence rejected;
12. disconnect blocks;
13. no active proposal below 25;
14. no active proposal above 75;
15. decrease from 25 proposes 0;
16. increase from 0 proposes 25;
17. unapplied proposals do not accumulate;
18. target band holds confirmed duty;
19. one sample causes at most one calculation;
20. Stage 4A sends no PWM command;
21. Stage 4A consumes no actuator frame;
22. Stage 4A allocates no actuator sequence;
23. active configuration change is rejected without mutation;
24. BLOCKED does not auto-recover;
25. changed manual ACK requires a later measurement cycle;
26. existing manual PWM tests pass unchanged;
27. protected scientific path gate passes;
28. launcher remains `main_v0416:main`.

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py tests/integration/test_load_control_stage4a_api.py tests/integration/test_load_control_stage4a_spec_contract.py tests/browser/test_load_control_stage4a_contract.py -q
```

Expected: GREEN.

Commit:

```bash
git add tests/unit/test_load_control_stage4a_observer.py tests/integration/test_load_control_stage4a_api.py tests/integration/test_load_control_stage4a_spec_contract.py tests/browser/test_load_control_stage4a_contract.py
git commit -m "test: lock Stage 4A observer safety boundary"
```

---

## Task 6 — Full regression and acceptance evidence

### 6.1 Manual PWM regression

Run first:

```bash
pytest tests/unit/test_load_control_manual_pwm.py -q
pytest tests/integration/test_load_control_stage3b_api.py -q
```

Expected: PASS with existing manual PWM implementation/tests unchanged.

### 6.2 Stage 4A targeted acceptance

Run:

```bash
pytest tests/unit/test_load_control_stage4a_observer.py tests/integration/test_load_control_stage4a_api.py tests/integration/test_load_control_stage4a_spec_contract.py tests/browser/test_load_control_stage4a_contract.py -q
```

Record exact observed counts.

### 6.3 Full repository acceptance

Run:

```bash
./tools/ari-emonio-acceptance.sh
```

Record exact output and counts. Do not predict them.

### 6.4 Protected scientific path gate

Run exactly as current CI:

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df HEAD -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: no diff, exit 0.

Verify recording separately against the approved design commit:

```bash
git diff --exit-code c4a18e0f4215c89b5a005dcaf5ac4236803a2655 HEAD -- src/emonio_viewer/recording
```

Expected: no diff, exit 0.

### 6.5 Version and launcher gate

```bash
grep -q 'version = "0.4.23"' pyproject.toml
grep -q 'emonio-viewer = "emonio_viewer.main_v0416:main"' pyproject.toml
```

Expected: both exit 0.

### 6.6 Diff scope review

```bash
git diff --name-only c4a18e0f4215c89b5a005dcaf5ac4236803a2655..HEAD
```

Production changes must be limited to the seven planned production paths. Additional changed files may only be Stage 4A tests/documentation unless new evidence justifies another path.

### 6.7 Final branch evidence

```bash
git status -sb
git log --oneline --decorate -8
```

Expected: clean `testing` worktree after all task commits.

Final report must state:

- exact final `testing` commit;
- exact automated counts actually observed;
- protected-path gate result;
- recording gate result;
- launcher/version result;
- changed-file list;
- `Stage 4A automated acceptance is not field evidence`;
- next field workflow from design section 22.

Do not promote to `main`.

## Execution order invariant

Execute Tasks 1 through 6 in order. Task 2 must be green before API work. API must be green before UI work. Full automated acceptance and protected-path gates must pass before Stage 4A field qualification begins.
