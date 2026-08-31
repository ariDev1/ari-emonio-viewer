# ARI Emonio Viewer v0.4.16 Testing — Triggered Recording Design

Date: 2026-08-31  
Status: DESIGN SPECIFICATION FOR REVIEW  
Target branch: `testing`  
Baseline commit before this document: `b539efe7eb3a11d53a3b291254ddd0c50a2cf3df`  
Target version: `v0.4.16 Testing`

## 1. Purpose

Add deterministic triggered recording to the ARI Emonio Viewer without changing the canonical measurement path.

The trigger must use the exact canonical `MeasurementSample` objects that already reach the existing recording subsystem. The trigger must never change a measured value. It must never create a synthetic sample. It must never infer a crossing across missing evidence.

The existing manual recording path remains valid and remains available.

Pre-trigger recording is not part of this version.

## 2. Scientific requirements

The implementation must preserve these rules:

- Modbus/TCP stays read-only.
- Acquisition timing stays unchanged.
- Register maps and decoders stay unchanged.
- Canonical measurement validation stays unchanged.
- Canonical P and Q signs stay unchanged.
- Trigger comparison uses the exact canonical numeric value.
- Display rounding must not affect trigger evaluation.
- No smoothing is permitted.
- No averaging is permitted.
- No interpolation is permitted.
- No resampling is permitted.
- No hysteresis is permitted in v0.4.16.
- No configurable debounce is permitted in v0.4.16.
- Qualification count is fixed at one qualifying canonical sample.
- One trigger firing can create only one recording session.
- The exact firing sample must be the first sample of the triggered recording.

## 3. Existing architecture evidence

The existing `RecordingManager` already owns one `RuntimeEventBus` subscriber and consumes canonical `MeasurementSample` and `DiagnosticEvent` objects.

The existing `SessionRecorder.create()` already accepts a specific `first_sample` and immediately passes that sample through the normal recording logic.

The existing Runtime Event Bus uses bounded subscriber queues. If a queue is full, an older event can be dropped. Therefore CROSSING logic must not assume continuity only because two measurements arrive consecutively at the trigger engine. Cycle identity and diagnostic evidence must also prove continuity.

The existing session metadata records device, application, Modbus transport, acquisition interval, and recording interval. Triggered sessions need additional start provenance, but manual-session metadata must remain compatible.

## 4. Approaches considered

### 4.1 Selected: TriggerEngine inside RecordingManager

The trigger evaluator runs inside the existing `RecordingManager` consumer path.

Data flow:

```text
canonical MeasurementSample
        |
        v
RuntimeEventBus
        |
        v
RecordingManager._consume()
        |
        +--> active SessionRecorder
        |
        +--> armed TriggerEngine
                 |
                 +--> no fire: retain only required runtime evidence
                 |
                 +--> fire: SessionRecorder.create(exact firing sample)
```

Advantages:

- One recording owner per device.
- One ordered consumer path for trigger and recording.
- The firing sample is available directly.
- Manual and triggered recording conflicts can be resolved under the existing RecordingManager lock.
- No new acquisition dependency is required.
- No browser measurement becomes authoritative.

This is the selected architecture.

### 4.2 Rejected: separate backend trigger subscriber

A separate Runtime Event Bus subscriber would create a second asynchronous owner of the same evidence.

It would require coordination between two bounded queues and two consumers. A sample could reach one subscriber before the other. Event loss could also differ between subscribers.

This adds race conditions without scientific benefit.

### 4.3 Rejected: frontend/browser trigger

The browser must not decide when scientific recording starts.

Browser history is display state. It is not the authoritative recording evidence path. Browser suspension, reconnects, page refreshes, or WebSocket loss would weaken trigger integrity.

## 5. Scope

### 5.1 Supported measurements

The first version supports these numeric canonical measurements:

| UI name | Canonical field |
| --- | --- |
| U | `vrms` |
| I | `irms` |
| P | `p` |
| Q | `q` |
| S | `s` |
| PF | `pf` |
| f | `frequency` |

### 5.2 Supported measurement blocks

- Phase A
- Phase B
- Phase C
- TOTAL

### 5.3 Supported operators

- `>`
- `>=`
- `<`
- `<=`

### 5.4 Supported trigger modes

- `LEVEL`
- `CROSSING`

### 5.5 Explicitly deferred

- Pre-trigger recording.
- Automatic re-arm.
- Repeating triggers.
- Hysteresis.
- Configurable debounce or N-sample qualification.
- Dedicated P sign-change trigger type.
- Dedicated Q sign-change trigger type.
- Dedicated quadrant-transition trigger type.
- Compound Boolean trigger expressions.
- Time-based trigger conditions.

## 6. Trigger configuration

A trigger configuration is immutable while it is armed.

Recommended backend model:

```text
TriggerConfig
  device_id
  block          A | B | C | TOTAL
  measurement    U | I | P | Q | S | PF | F
  operator       GT | GE | LT | LE
  threshold      finite float
  mode           LEVEL | CROSSING
  recording_interval_s
  session_note   optional bounded text
```

`recording_interval_s` is part of the armed configuration because it changes the resulting evidence stream. If it changes while armed, the trigger must disarm.

The server must reject a non-finite threshold.

The server must reject an unknown measurement, block, operator, or mode.

The recording interval must use the existing recording interval validation. It must be finite, greater than zero, and not less than the device acquisition interval.

## 7. Runtime trigger state

Trigger state is owned per Emonio.

Recommended runtime record:

```text
TriggerRuntimeState
  config
  state                  DISARMED | ARMED
  armed_utc
  arm_floor_cycle_id
  previous_cycle_id      optional
  previous_value         optional
  previous_sample_utc    optional
  last_fired_cycle_id    optional
  last_fired_utc         optional
  last_fired_value       optional
```

ARMED state is runtime-only.

Viewer restart result:

```text
DISARMED
```

There is no trigger auto-resume and no automatic re-arm.

Configuration values can be retained by the frontend for operator convenience, but retained UI values do not mean the backend trigger is armed.

## 8. ARM semantics

ARM is explicit.

When ARM is accepted, the RecordingManager takes a snapshot of the current device store state and records the latest known canonical cycle ID as `arm_floor_cycle_id` when available.

This floor prevents an event that was published before ARM but is still waiting in the recorder queue from firing the new trigger.

A measurement event with:

```text
cycle_id <= arm_floor_cycle_id
```

must not be evaluated as a post-ARM sample.

If no canonical sample exists at ARM time, no floor cycle is required. The first later eligible canonical sample is the first post-ARM sample.

ARM must be rejected with a conflict if recording is already active for that Emonio.

Each Emonio has independent trigger state.

## 9. Manual recording ownership

Manual operator action has higher authority than an armed trigger.

### 9.1 Manual START while ARMED

When manual START can proceed, it disarms the trigger before the manual session becomes active.

Result:

```text
ARMED + MANUAL START -> DISARMED + MANUAL RECORDING
```

The existing manual recording start behavior otherwise remains unchanged.

If manual session creation fails after ownership has moved to manual START, the trigger stays DISARMED. There is no hidden automatic return to ARMED state.

### 9.2 ARM while recording

Result:

```text
RECORDING + ARM -> 409 CONFLICT
```

The active recording continues unchanged.

### 9.3 Manual STOP

Manual STOP never arms or re-arms a trigger.

A triggered one-shot is already consumed when recording starts. STOP leaves the trigger DISARMED.

## 10. Configuration changes while ARMED

Any configuration change disarms the trigger immediately.

This includes:

- block / phase;
- measurement;
- operator;
- threshold;
- trigger mode;
- recording interval;
- session note if the note is part of the armed session configuration.

Result:

```text
ARMED + CONFIG CHANGE -> DISARMED
```

The new values may be stored as configuration, but a new explicit ARM command is required.

The backend is authoritative for this state transition. Frontend behavior alone is not sufficient.

## 11. Eligible trigger samples

The trigger can evaluate only a canonical `MeasurementSample` for the same device as the trigger owner.

Eligible sample quality is the same quality class accepted by the existing recorder:

- `VALID`
- `DEGRADED`

Any other quality must not fire a trigger.

The selected numeric value must be finite. A non-finite selected value must not fire a trigger.

A sample from another Emonio must never affect the trigger state.

## 12. LEVEL semantics

LEVEL uses only the current eligible post-ARM sample.

The first eligible sample after ARM can fire immediately.

For threshold `T` and current exact canonical value `x`:

```text
>   fires when x >  T
>=  fires when x >= T
<   fires when x <  T
<=  fires when x <= T
```

No previous value is required.

An acquisition gap before a later LEVEL sample does not require inference. Therefore a later valid/degraded sample can still fire LEVEL if its current value satisfies the condition.

## 13. CROSSING semantics

The first eligible post-ARM sample establishes the previous value only. It cannot fire.

For previous exact value `p`, current exact value `x`, and threshold `T`:

```text
>   fires when p <= T and x >  T
>=  fires when p <  T and x >= T
<   fires when p >= T and x <  T
<=  fires when p >  T and x <= T
```

These rules define threshold contact exactly. No epsilon is permitted.

### 13.1 Continuity requirement

A crossing is valid only when continuity is proven.

For two MeasurementSample events to form a crossing pair:

```text
current.cycle_id == previous.cycle_id + 1
```

and no `DiagnosticEvent` for that Emonio may have invalidated continuity between them.

If a `DiagnosticEvent` is received for the armed Emonio, CROSSING previous-state evidence is cleared.

If the next MeasurementSample cycle ID is not exactly one greater than the previous cycle ID, CROSSING previous-state evidence is cleared. The current eligible sample becomes a new baseline and cannot fire.

This rule detects an unseen cycle even if a bounded Runtime Event Bus queue dropped an event.

A duplicate or stale cycle must never fire. It must not be used as a new crossing pair.

The implementation must never infer a crossing across a gap.

## 14. Trigger firing

When a trigger fires:

1. Capture the exact `MeasurementSample` object that satisfied LEVEL or completed CROSSING.
2. Consume the one-shot trigger immediately.
3. Change trigger state to DISARMED.
4. Create the recording session from that exact sample.
5. Set recording start time to `sample.timing.cycle_finished_utc`.
6. Record that exact sample through the existing `SessionRecorder` path as the first measurement record.
7. Record trigger provenance in session evidence.

No RuntimeStore re-read is permitted between trigger evaluation and triggered session creation.

A later sample must never replace the firing sample as the first recording sample.

## 15. Triggered session provenance

Triggered recordings must be distinguishable from manual recordings.

The existing manual session metadata should remain compatible.

Recommended triggered-session evidence inside `session.json`:

```json
{
  "recording": {
    "interval_s": 1.0,
    "start_source": "TRIGGER",
    "trigger": {
      "mode": "CROSSING",
      "block": "A",
      "measurement": "P",
      "operator": ">",
      "threshold": 1000.0,
      "fired_cycle_id": 12345,
      "fired_utc": "canonical cycle_finished_utc",
      "fired_value": 1000.25
    }
  }
}
```

Manual sessions may explicitly report `start_source: "MANUAL"` only if this can be added without breaking existing metadata consumers. Otherwise absence of trigger evidence continues to mean manual start.

A triggered session should also write an event entry:

```text
TRIGGER_FIRED
```

with:

- firing UTC;
- firing cycle ID;
- trigger mode;
- block;
- measurement;
- operator;
- threshold;
- exact firing value.

This event is evidence only. It must not modify measurement CSV content.

## 16. Recording failure semantics

If triggered session creation or later recording I/O fails:

```text
TRIGGER CONSUMED -> DISARMED
RECORDING -> ERROR when a session exists and fails
```

There is no automatic retry.

There is no automatic second session.

There is no automatic re-arm.

Existing recording write-error evidence must remain intact.

If failure occurs before a usable session exists, the API/runtime must expose a deterministic error state or diagnostic result. It must not pretend that recording succeeded.

## 17. Backend component boundaries

### 17.1 New `recording/trigger.py`

This module should contain trigger-specific pure logic:

- enums or validated constants;
- immutable `TriggerConfig`;
- runtime trigger state;
- canonical field extraction;
- LEVEL comparison;
- CROSSING comparison;
- continuity handling;
- deterministic evaluation result.

The module must not import Modbus code or acquisition worker code.

The evaluation function should be independently unit-testable.

### 17.2 Existing `recording/recorder.py`

`RecordingManager` remains the owner of:

- per-device active recorders;
- per-device trigger state;
- manual/trigger ownership conflicts;
- event-consumer ordering;
- triggered session start from the exact firing sample.

Add a narrow internal method such as:

```text
_start_from_sample(device_id, sample, interval_s, ...)
```

or an equivalent deterministic interface.

Manual `start()` may continue to use RuntimeStore. Triggered start must not.

### 17.3 Existing `recording/session.py`

Only make the smallest change required to store optional trigger start provenance.

Manual session behavior must not be weakened.

### 17.4 No change required

The design does not require changes to:

- `modbus/*`
- `measurement/*`
- `acquisition/*`
- `runtime/events.py`
- `runtime/store.py`
- `scope/*`

If implementation evidence later shows that one of these paths must change, implementation must stop and the design must be reviewed again before that change is made.

## 18. API design

Keep the existing recording endpoints.

Add narrow trigger endpoints:

```text
GET  /api/v1/recording/status
POST /api/v1/recording/trigger/configure
POST /api/v1/recording/trigger/arm
POST /api/v1/recording/trigger/disarm
```

The existing status response gains a trigger collection:

```json
{
  "active": [],
  "errors": [],
  "triggers": []
}
```

A trigger status record should include:

- device ID;
- state;
- complete current configuration;
- armed UTC when ARMED;
- last fired cycle ID when available;
- last fired UTC when available;
- last fired value when available.

Do not expose internal Python object representations.

### 18.1 HTTP status rules

- Invalid trigger configuration: `400 Bad Request`.
- Unknown device: `404 Not Found`.
- ARM while recording: `409 Conflict`.
- Recording commands disabled: `503 Service Unavailable`.
- Valid ARM: `200` with `ARMED` state.
- Valid DISARM: `200` with `DISARMED` state.

Manual START keeps its existing endpoint. If it succeeds while a trigger is ARMED, the trigger is disarmed as part of the same RecordingManager ownership operation.

## 19. Frontend design

Keep the compact Session Recording strip.

Add trigger configuration to the existing Recording drawer so the main workstation remains compact.

Recommended selected-device controls:

```text
TRIGGERED RECORDING

MODE         [ LEVEL | CROSSING ]
PHASE        [ A | B | C | TOTAL ]
MEASUREMENT  [ U | I | P | Q | S | PF | f ]
OPERATOR     [ > | >= | < | <= ]
THRESHOLD    [ numeric input ]
INTERVAL     [ existing valid recording intervals ]

[ ARM ] [ DISARM ]

STATUS: DISARMED
```

When armed, status should show the complete armed condition. Example:

```text
ARMED · PHASE A · P > 1000 W · CROSSING
```

The displayed threshold can use normal UI formatting, but the backend configuration value is authoritative.

Changing any armed configuration control must cause a backend DISARM before the changed configuration can later be armed again.

The UI must not simulate ARMED state before the backend confirms ARM.

The UI must not simulate trigger firing from WebSocket measurement data.

When a triggered recording is active, the normal recording session status remains the source of truth.

## 20. State model

Per device:

```text
                 configure
                    |
                    v
               +----------+
               | DISARMED |
               +----------+
                  |     ^
               ARM|     |DISARM / config change / restart
                  v     |
               +----------+
               |  ARMED   |
               +----------+
                  |     |
     qualifying   |     |manual START
       sample     |     |
                  v     v
             +----------------+
             |   RECORDING    |
             +----------------+
                 |        |
              STOP|        |write/storage failure
                 v        v
             +---------+  +-------+
             | STOPPED |  | ERROR |
             +---------+  +-------+

Trigger state after firing, STOP, or ERROR: DISARMED.
```

`STOPPED` is a recording result, not a persistent trigger state.

## 21. Determinism and concurrency

All trigger ownership changes and recording ownership changes must use the existing RecordingManager lock or an equivalent single synchronization boundary.

The following operations must be atomic from the RecordingManager point of view:

- ARM conflict check and state creation;
- configuration update and forced disarm;
- manual START and trigger disarm;
- trigger fire and one-shot consumption;
- triggered recorder creation from the firing sample;
- recording failure removal and error-state publication.

The trigger evaluator must not launch a second worker thread.

The trigger evaluator must not use wall-clock polling.

The trigger fires only while processing canonical runtime events.

## 22. Tests required before implementation can be accepted

### 22.1 Unit tests — trigger math and state

Test at least:

- all four LEVEL operators;
- all four CROSSING operators;
- exact equality behavior at threshold;
- first CROSSING sample cannot fire;
- fixed qualification count equals one;
- no hysteresis;
- non-finite threshold rejected;
- non-finite measurement value cannot fire;
- wrong device cannot affect trigger;
- wrong phase/measurement extraction cannot occur;
- DiagnosticEvent resets CROSSING continuity;
- cycle gap resets CROSSING continuity;
- stale pre-ARM queued cycle cannot fire;
- duplicate cycle cannot fire;
- configuration change disarms.

### 22.2 RecordingManager integration tests

Test at least:

- LEVEL firing creates one session;
- CROSSING firing creates one session;
- exact firing sample is first measurement row;
- recording `started_utc` equals firing `cycle_finished_utc`;
- trigger provenance contains exact firing cycle and value;
- no RuntimeStore re-read can substitute a newer sample;
- trigger is DISARMED after fire;
- no automatic second firing;
- manual START disarms ARMED trigger;
- ARM while recording returns conflict behavior;
- manual STOP leaves trigger DISARMED;
- write error leaves trigger DISARMED;
- independent Emonio triggers do not interfere;
- event gap cannot create a false CROSSING.

### 22.3 API tests

Test:

- configuration validation;
- finite threshold validation;
- interval validation;
- ARM response;
- DISARM response;
- 409 ARM conflict while recording;
- status serialization;
- manual START ownership rule;
- command-disable behavior.

### 22.4 Browser tests

Test:

- trigger controls use backend API only;
- correct A/B/C/TOTAL options;
- correct U/I/P/Q/S/PF/f options;
- correct operators and modes;
- ARMED status comes from backend status;
- configuration change while ARMED causes DISARM;
- device switching preserves independent backend trigger status;
- triggered session appears in normal recording status UI.

### 22.5 Regression tests

All existing recording, measurement, history, Density, vector, device lifecycle, SCOPE, and read-only tests must continue to pass.

## 23. Acceptance gates

v0.4.16 must remain `Testing` until all required evidence exists.

Required evidence:

1. New trigger unit tests pass.
2. New trigger integration tests pass.
3. New API tests pass.
4. New browser tests pass.
5. Existing unit tests pass.
6. Existing integration tests pass.
7. Existing frontend/browser tests pass.
8. Read-only gate passes.
9. Python compilation passes.
10. Scientific sign path passes.
11. Publication/package gates pass when a package is built.
12. Real Emonio field testing confirms LEVEL behavior.
13. Real Emonio field testing confirms CROSSING behavior.
14. Real Emonio field testing confirms exact first-sample evidence.

`main` is not part of this work. Development and testing stay on `testing`.

## 24. Implementation sequence

Implementation must use test-driven development.

Recommended sequence:

1. Add failing pure TriggerEngine tests.
2. Implement `recording/trigger.py` until the pure tests pass.
3. Add failing RecordingManager ownership and exact-first-sample tests.
4. Add the minimal RecordingManager integration.
5. Add failing session provenance tests.
6. Add minimal trigger metadata/event evidence.
7. Add failing API tests.
8. Add trigger API endpoints.
9. Add failing frontend state/API tests.
10. Add trigger controls in the existing Recording drawer with structured CSS.
11. Run focused trigger regression tests.
12. Run complete project acceptance.
13. Perform real-device field testing on `testing`.

No implementation step may modify `main`.

## 25. Success criteria

v0.4.16 Triggered Recording is successful only when all of these statements are true:

- A numeric LEVEL condition can start recording from the first qualifying new canonical sample.
- A numeric CROSSING condition can start recording only from two proven consecutive post-ARM canonical samples.
- A gap cannot create a false crossing.
- The exact firing sample is the first recorded sample.
- The trigger fires once only.
- Manual recording and triggered recording cannot compete for one Emonio.
- Multiple Emonios remain independent.
- Restart never automatically re-arms a trigger.
- Recording failure never automatically retries or re-arms.
- Trigger provenance is recoverable from recording evidence.
- Existing manual recording behavior remains functional.
- Canonical measurement and acquisition architecture remain unchanged.
