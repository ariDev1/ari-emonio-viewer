# ARI Emonio Viewer — Stage 4A P Control Observer Design

Date: 2026-09-02
Status: APPROVED DESIGN — IMPLEMENTATION NOT STARTED
Repository: `ariDev1/ari-emonio-viewer`
Branch: `testing`
Design input baseline: `858111c6252084ef9940c6677b5f601d3c3b8130`
Viewer version at design input: `v0.4.23 Testing`

## 1. Purpose

Stage 4A adds a read-only active-power control observer.

The observer uses canonical Emonio active-power measurements and the last Viewer-confirmed manual PWM duty to calculate a proposed next PWM duty.

Stage 4A does not send a PWM command.

Stage 4A does not control the actuator.

The operator remains the only authority that can apply a proposed duty by using the existing manual PWM control.

The purpose is to qualify the control decision path before automatic physical output is permitted.

## 2. Scientific boundary

The Emonio remains the canonical electrical measurement authority.

Stage 4A must not change:

- canonical P or Q signs
- quadrant semantics
- PF semantics
- measurement validation
- fixed-deadline acquisition
- Modbus read-only behavior
- register maps
- decoder logic
- canonical measurement ownership
- recording
- CSV precision
- SCOPE measurement semantics

Protected paths remain unchanged:

- `src/emonio_viewer/acquisition/**`
- `src/emonio_viewer/measurement/**`
- `src/emonio_viewer/modbus/**`
- `src/emonio_viewer/recording/**`
- `src/emonio_viewer/scope/**`
- `src/emonio_viewer/runtime/events.py`
- `src/emonio_viewer/runtime/store.py`

The active launcher remains:

`emonio-viewer = "emonio_viewer.main_v0416:main"`

## 3. Existing proven baseline

The existing manual PWM path is the field-confirmed physical-output baseline.

It remains separate from Stage 4A.

The existing manual PWM path provides:

- explicit actuator selection
- WebSocket connection
- HELLO qualification
- `PWM_DUTY_CONTROL` capability qualification
- explicit manual duty command
- explicit OFF command
- ACK identity validation
- requested duty evidence
- actual duty evidence
- compare-tick evidence
- period-tick evidence
- no automatic retry
- no command replay

Stage 4A must not weaken or replace this path.

## 4. Current field evidence used by this design

The present bench evidence is:

- DC bus: approximately 200 VDC
- load: 60 W bulb on the half-bridge output
- PWM frequency: approximately 245 kHz
- tested useful active-duty range: approximately 25 % to 75 %
- Phase A active power changed from approximately -60 W to approximately -15 W while the additional controlled load was active
- the present control objective is active power P only
- reactive power Q is not part of the Stage 4A control law

This evidence supports an incremental P-only observer.

This evidence does not define a linear watts-to-duty transfer function.

Stage 4A must not infer that a specific watt error equals a specific duty value.

## 5. Architecture

Stage 4A uses the existing `RuntimeEventBus` as a read-only measurement observation boundary.

The data path is:

```text
canonical Emonio MeasurementSample
        ↓
explicit selected Emonio source
        ↓
explicit selected phase A, B, or C
        ↓
canonical signed phase P
        ↓
P target and deadband decision
        ↓
read-only snapshot of last qualified manual PWM ACK evidence
        ↓
deterministic next-duty proposal
        ↓
Viewer display
        ↓
NO PWM_COMMAND
```

Stage 4A must not trigger acquisition.

Stage 4A must not read Modbus directly.

Stage 4A must not write to `RuntimeStore`.

Stage 4A must not change a `MeasurementSample`.

### 5.1 Actuator transport ownership

Stage 4A must not become a second owner or consumer of the actuator WebSocket channel.

Stage 4A must not:

- call `QualifiedActuatorChannel.receive()`
- call `QualifiedActuatorChannel.receive_nowait()`
- call `QualifiedActuatorChannel.send()`
- call `QualifiedActuatorChannel.send_pwm()`
- drain actuator frames
- allocate actuator command sequence numbers
- bind or clear the qualified actuator channel

The existing qualification and manual PWM services keep transport ownership.

Stage 4A receives actuator evidence only through a narrow read-only status interface from the existing qualified manual PWM and qualification state.

This prevents two services from competing for one actuator frame stream.

## 6. Control scope

Stage 4A controls one selected phase conceptually.

Valid phase selections are:

- A
- B
- C

`TOTAL` is not supported in Stage 4A.

The first field qualification is expected to use Phase A.

Only active power P from the selected phase enters the control calculation.

Reactive power Q may be displayed as canonical evidence, but Q must not affect:

- the control error
- the decision direction
- the proposed duty
- the control state

PF must not be used as a substitute for the sign of P.

## 7. Operator parameters

Stage 4A requires explicit session parameters:

- Emonio source
- phase: A, B, or C
- `P_target_w`
- `P_deadband_w`
- `duty_step_percent`

Parameter validation is:

- source must resolve to exactly one enabled Emonio device
- phase must be A, B, or C
- `P_target_w` must be finite
- `P_deadband_w` must be finite and `>= 0`
- `duty_step_percent` must be finite and `> 0`

Stage 4A must not silently replace invalid values with defaults.

Stage 4A parameters are session control parameters. They must not modify Emonio configuration.

All Stage 4A configuration changes are allowed only while the observer is `DISABLED`.

An attempt to change source, phase, target, deadband, or duty step while observation is active must be rejected without changing the existing configuration.

A new enable action establishes a new measurement-cycle observation boundary.

## 8. Duty evidence and operating window

The control baseline is the last requested PWM duty that received a qualified `PWM_ACK` for the currently qualified actuator instance.

The current actuator instance is identified by:

- node ID
- boot ID

A requested duty from an older boot ID is not admissible control evidence.

The Stage 4A operating window is:

- SAFE/OFF duty: exactly 0 %
- active-duty minimum: 25 %
- active-duty maximum: 75 %

The 25 % and 75 % values are current field-qualified Stage 4A limits.

They are not declared as permanent hardware limits.

Stage 4A must not propose an active duty below 25 % or above 75 %.

The requested duty from the qualified manual PWM ACK is the control setpoint evidence.

The actual duty from the PWM ACK remains engineering evidence and must be displayed separately when available.

Stage 4A must not treat an unacknowledged manual request as confirmed duty.

## 9. Calculation

For every admissible new sample:

```text
LOW  = P_target_w - P_deadband_w
HIGH = P_target_w + P_deadband_w
```

Let:

- `P` = canonical signed active power of the selected phase
- `D` = last Viewer-confirmed requested PWM duty for the current actuator boot
- `S` = `duty_step_percent`

### 9.1 Increase condition

If:

```text
P < LOW
```

then more active load is requested conceptually.

The proposed duty is:

```text
if D == 0:
    proposed = 25
else:
    proposed = min(D + S, 75)
```

An active `D` is admissible only when `25 <= D <= 75`.

### 9.2 Hold condition

If:

```text
LOW <= P <= HIGH
```

then:

```text
proposed = D
```

The observer state is `TARGET_BAND`.

### 9.3 Decrease condition

If:

```text
P > HIGH
```

then less active load is requested conceptually.

The proposed duty is:

```text
if D > 25:
    proposed = max(D - S, 25)
else:
    proposed = 0
```

Thus, the transition below the qualified active-duty minimum is an explicit proposal for SAFE/OFF at 0 %.

Stage 4A never proposes a duty between 0 % and 25 %.

### 9.4 Saturation states

If `P < LOW` and `D == 75`, the proposal remains 75 % and the state is `LIMIT_HIGH`.

If `P > HIGH` and `D == 0`, the proposal remains 0 % and the state is `LIMIT_LOW`.

If `P > HIGH` and `D == 25`, the proposal is 0 %. This is a valid decrease decision, not a blocked condition.

## 10. No synthetic duty accumulation

Stage 4A must not advance its internal proposal as if the proposal had been physically applied.

Example:

- confirmed requested duty is 25 %
- observer proposes 30 %
- operator does not apply 30 %
- next valid sample still uses 25 % as `D`
- observer may again propose 30 %

The observer must not calculate 35 % from an unapplied 30 % proposal.

Only a new qualified PWM ACK may change the confirmed duty baseline.

### 10.1 New manual ACK during observation

When the operator applies a new manual duty and a new qualified PWM ACK changes the confirmed duty baseline:

- the previous Stage 4A proposal becomes invalid
- Stage 4A must not calculate from a measurement that could belong to the previous duty state
- on the first selected-source sample where Stage 4A detects the changed confirmed-duty baseline, Stage 4A records the new baseline and does not calculate a proposal from that sample
- Stage 4A then enters `WAITING_FOR_SAMPLE`
- the next continuous valid selected-source measurement cycle may be used for the next calculation

This rule gives a deterministic causal boundary without making Stage 4A consume actuator frames or modify the manual PWM service transport behavior.

## 11. Measurement admissibility

A sample is admissible only when all required conditions pass.

Required conditions are:

- observation mode is enabled
- explicit Emonio source is selected
- explicit phase is selected
- sample belongs to the selected Emonio source
- sample is a new measurement cycle
- sample quality is `VALID`
- sample age is within the Stage 4A freshness limit
- no selected-source acquisition failure invalidates the expected cycle
- measurement cycle sequence is continuous for the observer session
- current actuator instance is still HELLO-qualified
- `PWM_DUTY_CONTROL` remains present
- a qualified requested-duty baseline exists for the current node ID and boot ID
- confirmed requested duty is either exactly 0 % or within 25 % to 75 %

Samples from another Emonio device are ignored.

They must not change the Stage 4A state or proposal.

## 12. Freshness and timing

Stage 4A has no independent control calculation clock.

One canonical Emonio sample can produce at most one Stage 4A calculation.

No sample means no new calculation.

Stage 4A must not interpolate between samples.

Stage 4A must not average samples unless a later approved design adds that behavior.

The observation start establishes a measurement-cycle boundary.

The first accepted sample must be a new cycle produced after the observation start boundary.

An already existing sample must not be presented as new control evidence.

The initial Stage 4A freshness limit is:

```text
2 × selected Emonio poll interval
```

A deadline check may use monotonic time only to detect that the expected new measurement did not arrive. The deadline check must not calculate a new duty proposal.

If no admissible new sample arrives inside this interval, the observer enters `BLOCKED` with reason `SAMPLE_STALE`.

This timing rule does not change acquisition timing.

## 13. State model

Primary Stage 4A states are:

- `DISABLED`
- `WAITING_FOR_SAMPLE`
- `OBSERVING`
- `TARGET_BAND`
- `LIMIT_LOW`
- `LIMIT_HIGH`
- `BLOCKED`

### 13.1 DISABLED

Observation is not active.

No proposed duty is valid.

### 13.2 WAITING_FOR_SAMPLE

The operator enabled observation and all enable gates passed, or a new qualified manual PWM ACK changed the confirmed-duty baseline during observation.

The observer waits for an admissible new canonical measurement cycle.

### 13.3 OBSERVING

A valid sample produced a valid increase or decrease proposal that is not at a limit state.

### 13.4 TARGET_BAND

The measured P is inside the inclusive target deadband.

The proposal is HOLD at the current confirmed requested duty.

### 13.5 LIMIT_LOW

The valid calculation requires no further decrease below SAFE/OFF.

The proposed duty is 0 %.

### 13.6 LIMIT_HIGH

The valid calculation requires no further increase above 75 %.

The proposed duty is 75 %.

### 13.7 BLOCKED

Required runtime control evidence became missing, stale, invalid, discontinuous, or no longer bound to the current actuator instance after observation was enabled.

In `BLOCKED`:

```text
proposed_duty_percent = null
```

The UI must display `—`, not `0 %`.

`0 %` means a valid OFF proposal.

`—` means no valid control proposal exists.

`BLOCKED` is latched for the current observer session.

New measurements, actuator reconnection, or later valid evidence must not automatically resume calculations.

The operator must explicitly disable Stage 4A and enable it again after the cause is corrected.

This prevents hidden observer restart after a fault boundary.

## 14. Reason codes

Stage 4A uses explicit deterministic reason codes.

### 14.1 Enable rejection reasons

If an enable gate fails, the observer remains `DISABLED`, no proposal is valid, and one exact rejection reason is reported.

Required enable rejection reasons include:

- `SOURCE_NOT_AVAILABLE`
- `PHASE_NOT_SELECTED`
- `PARAMETER_INVALID`
- `ACTUATOR_NOT_QUALIFIED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

### 14.2 Runtime block reasons

After a successful enable, required runtime block reasons include:

- `SAMPLE_NOT_VALID`
- `SAMPLE_STALE`
- `SAMPLE_SEQUENCE_GAP`
- `ACQUISITION_FAILURE`
- `ACTUATOR_BOOT_CHANGED`
- `ACTUATOR_DISCONNECTED`
- `PWM_DUTY_CONTROL_NOT_SUPPORTED`
- `CONFIRMED_DUTY_UNKNOWN`
- `CONFIRMED_DUTY_OUTSIDE_QUALIFIED_WINDOW`

The implementation may add a more specific reason only when it preserves the same fail-closed meaning and is covered by tests.

## 15. Actuator disconnect and reboot

Stage 4A does not send a command when the actuator disconnects.

On actuator disconnect after observation is enabled:

- the current proposal becomes invalid
- state becomes latched `BLOCKED`
- reason becomes `ACTUATOR_DISCONNECTED`
- previous confirmed duty must not be reused after reconnection without new current-instance evidence

On boot ID change after observation is enabled:

- previous PWM ACK evidence becomes obsolete
- the current proposal becomes invalid
- state becomes latched `BLOCKED`
- reason becomes `ACTUATOR_BOOT_CHANGED`
- a new qualified manual PWM ACK is required before a later Stage 4A enable can produce another proposal

There is no automatic reconnect.

There is no automatic observer restart.

There is no automatic command replay.

## 16. Observation disable behavior

When the operator disables Stage 4A observation:

- state becomes `DISABLED`
- proposed duty becomes null
- runtime block latch is cleared
- Stage 4A sends no actuator command
- Stage 4A does not modify the physical PWM output
- the existing manual PWM mode remains available

Disabling observation does not imply an automatic OFF command because Stage 4A has no output authority.

The operator can use the existing manual OFF action when physical OFF is required.

## 17. Manual PWM separation

Manual PWM remains a separate engineering mode and remains the only real PWM command source in Stage 4A.

Stage 4A must not add:

- automatic PWM transmission
- `APPLY PROPOSED` action
- automatic duty confirmation
- automatic retry
- automatic replay
- automatic actuator selection
- automatic source selection

The operator may read the proposal and manually apply the proposed duty through the existing manual PWM control.

The observer reads the resulting qualified manual PWM status. It does not intercept the ACK.

## 18. User interface

Stage 4A adds a separate `P CONTROL OBSERVER` section in the external load-control panel.

The section must show at least:

- observer state
- rejection or block reason when present
- selected Emonio source
- selected phase
- measurement cycle ID
- measured P
- measured Q as display-only evidence
- sample quality
- sample age
- P target
- P deadband
- duty step
- confirmed requested duty
- confirmed actual duty when available
- decision: `INCREASE`, `HOLD`, `DECREASE`, `LIMIT_LOW`, or `LIMIT_HIGH`
- proposed duty

The UI must state that:

- P is the only control variable in Stage 4A
- Q is display-only
- no automatic PWM command is sent
- the proposal must be applied manually if the operator wants to test it

The existing manual PWM UI remains unchanged in behavior.

## 19. Proposed implementation boundary

The preferred new backend module is:

`src/emonio_viewer/load_control/automatic_observation.py`

The preferred API module is a new dedicated load-control API file.

The preferred frontend files are dedicated Stage 4A JavaScript and structured load-control CSS changes.

`app_v0416.py` may receive minimal wiring for the new service and routes.

The observer may receive read-only callables or narrow status providers for:

- current qualification status
- current manual PWM status

The observer must not receive actuator transport ownership.

No protected scientific path requires modification.

The exact file list is an implementation-plan decision and must be minimized during test-first planning.

## 20. Diagnostics and evidence

Stage 4A diagnostics must distinguish observation evidence from physical-output evidence.

Useful diagnostic events include:

- observer enabled
- observer disabled
- source selected
- phase selected
- parameter set changed
- valid sample observed
- sample ignored because source does not match
- observer blocked with exact reason
- proposal calculated
- confirmed-duty baseline changed because of a qualified manual PWM ACK
- actuator boot invalidated the confirmed-duty baseline

A proposal diagnostic must contain enough information to reproduce the calculation:

- Emonio device ID
- phase
- measurement cycle ID
- measurement UTC or monotonic evidence already carried by the canonical sample
- measured P
- target P
- deadband
- confirmed requested duty
- duty step
- decision
- proposed duty
- observer state

A Stage 4A diagnostic must never claim that proposed duty was physically applied.

## 21. Testing requirements

Implementation must use test-driven development.

At minimum, tests must prove:

1. canonical P sign is consumed without transformation
2. Q cannot affect the proposal
3. PF cannot affect the proposal
4. wrong-source samples are ignored
5. only a new post-enable cycle is accepted initially
6. invalid quality blocks the observer
7. stale measurement blocks the observer
8. acquisition failure blocks the observer
9. cycle sequence gap blocks the observer
10. unknown confirmed duty rejects enable or blocks an active session as applicable
11. old-boot duty evidence is rejected
12. disconnect blocks the observer
13. active duty below 25 % is never proposed
14. active duty above 75 % is never proposed
15. decrease from 25 % proposes exactly 0 %
16. increase from 0 % proposes exactly 25 %
17. unapplied proposals do not accumulate
18. target-band calculation holds the confirmed duty
19. one sample causes at most one calculation
20. Stage 4A sends no `PWM_COMMAND`
21. Stage 4A never consumes actuator channel frames
22. Stage 4A never allocates actuator command sequence numbers
23. configuration changes while active are rejected without mutation
24. `BLOCKED` does not automatically recover
25. a changed qualified manual duty invalidates the old proposal and requires a later measurement cycle
26. existing manual PWM tests remain unchanged and pass
27. protected scientific path gate remains pass
28. launcher remains `emonio_viewer.main_v0416:main`

Automated test success is not field evidence.

## 22. Stage 4A field acceptance

Stage 4A field acceptance is observation-only.

A representative workflow is:

```text
operator applies manual 25 %
        ↓
qualified PWM ACK confirms 25 %
        ↓
operator enables Stage 4A
        ↓
new canonical Emonio sample arrives
        ↓
Stage 4A calculates proposed next duty
        ↓
operator reviews proposal
        ↓
operator may manually apply the proposal
        ↓
new qualified PWM ACK establishes the next confirmed duty baseline
        ↓
first selected-source sample detects the changed duty baseline and is not used for a proposal
        ↓
following continuous valid Emonio sample evaluates the electrical response
```

Field acceptance must confirm that:

- measured P shown by Stage 4A matches the canonical Viewer P for the selected phase
- proposed duty follows the exact approved calculation
- the proposal does not advance without a new qualified manual PWM ACK
- a new qualified manual PWM ACK invalidates the old proposal and establishes a new causal measurement boundary
- Q changes do not change the proposal when P and all control inputs are unchanged
- no Stage 4A path sends an automatic `PWM_COMMAND`

## 23. Explicitly out of scope

Stage 4A does not implement:

- automatic PWM output
- closed-loop physical control
- PID control
- proportional watts-to-duty gain
- linear transfer-function assumption
- adaptive control
- derivative control
- integral control
- reactive-power control
- Q compensation
- PF control
- automatic negative-P reaction with physical output
- automatic actuator reconnect
- automatic observer restart after a block
- automatic command retry
- automatic command replay
- persistent automatic-control enable

These functions require later approved stages and new evidence.

## 24. Later stages

The expected sequence after Stage 4A is:

- Stage 4A: P-only control observer, no automatic output
- Stage 4B: explicit automatic bench-output authority with fail-closed state control
- Stage 4C: measured electrical characterization of duty versus active-power response
- Stage 4D: regulator design based on Stage 4C evidence

Each later stage requires a separate design approval.

## 25. Design acceptance statement

This specification freezes the approved Stage 4A architecture.

The required invariant is:

**Stage 4A may calculate and display a proposed duty, but it has no authority to send that duty to the actuator.**

Implementation must remain deterministic, minimal, measurable, reversible, and evidence-based.
