# ARI Emonio Viewer v0.4.16 Testing — Triggered Recording Design

Date: 2026-08-31  
Status: DESIGN SPECIFICATION FOR REVIEW  
Target branch: `testing`  
Baseline commit before this design: `b539efe7eb3a11d53a3b291254ddd0c50a2cf3df`  
Target version: `v0.4.16 Testing`

## 1. Purpose

Add deterministic triggered recording to the ARI Emonio Viewer without changing the canonical measurement path.

The trigger uses the exact canonical `MeasurementSample` objects that already reach the recording subsystem. The trigger does not change a measured value. It does not create a synthetic sample. It does not infer a crossing across missing evidence.

The existing manual recording path remains available and keeps its existing scientific behavior.

Pre-trigger recording is not part of this version.

## 2. Scientific requirements

The implementation must preserve these rules:

- Modbus/TCP stays read-only.
- Acquisition timing stays unchanged.
- Register maps and decoders stay unchanged.
- Canonical measurement validation stays unchanged.
- Canonical P and Q signs stay unchanged.
- Trigger comparison uses the exact canonical numeric value.
- Display rounding does not affect trigger evaluation.
- No smoothing is permitted.
- No averaging is permitted.
- No interpolation is permitted.
- No resampling is permitted.
- No hysteresis is permitted in v0.4.16.
- No configurable debounce is permitted in v0.4.16.
- Qualification count is fixed at one qualifying canonical sample.
- One trigger firing creates at most one recording session.
- The exact firing sample is the first sample of a successful triggered recording.

## 3. Existing architecture evidence

The existing `RecordingManager` owns one `RuntimeEventBus` subscriber and consumes canonical `MeasurementSample` and `DiagnosticEvent` objects.

The existing `SessionRecorder.create()` accepts a specific `first_sample` and sends that sample through the normal recording logic.

The existing Runtime Event Bus uses bounded subscriber queues. If a subscriber queue is full, an older event can be dropped. CROSSING logic therefore must prove continuity from cycle identity and diagnostic evidence. Event arrival alone is not sufficient proof.

The existing session metadata records device, application, Modbus transport, acquisition interval, and recording interval. Triggered sessions require additional start provenance. Manual-session metadata must keep its current structure and meaning.

## 4. Architecture selection

### 4.1 Selected architecture: TriggerEngine inside RecordingManager

The trigger evaluator runs inside the existing `RecordingManager` consumer path.

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

This architecture provides:

- one recording owner per device;
- one ordered consumer path for trigger and recording;
- direct access to the exact firing sample;
- one synchronization boundary for manual and triggered recording ownership;
- no new dependency on acquisition internals;
- no browser authority over recording start.

### 4.2 Rejected architecture: separate backend trigger subscriber

A separate Runtime Event Bus subscriber creates a second asynchronous owner of the same evidence.

It requires coordination between two bounded queues and two consumers. Event delivery and event loss can differ between subscribers. This adds race conditions without scientific benefit.

### 4.3 Rejected architecture: frontend/browser trigger

The browser does not decide when scientific recording starts.

Browser history is display state. It is not authoritative recording evidence. Browser suspension, reconnects, page refreshes, or WebSocket loss would weaken trigger integrity.

## 5. Scope

### 5.1 Supported measurements

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

### 5.4 Supported modes

- `LEVEL`
- `CROSSING`

### 5.5 Deferred features

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

The backend trigger configuration is:

```text
TriggerConfig
  device_id
  block                  A | B | C | TOTAL
  measurement            U | I | P | Q | S | PF | F
  operator               GT | GE | LT | LE
  threshold              finite float
  mode                   LEVEL | CROSSING
  recording_interval_s   finite positive float
```

The server rejects:

- a non-finite threshold;
- an unknown block;
- an unknown measurement;
- an unknown operator;
- an unknown mode;
- a non-finite recording interval;
- a recording interval less than or equal to zero;
- a recording interval lower than the device acquisition interval.

The recording interval uses the same validation rule as existing manual recording.

The complete configuration is immutable while ARMED. A configuration update replaces the stored configuration and forces DISARMED state before the new configuration becomes available for a later ARM command.

## 7. Per-device runtime trigger state

Each Emonio owns an independent trigger runtime record:

```text
TriggerRuntimeState
  config
  state                  DISARMED | ARMED
  armed_utc              optional
  arm_floor_cycle_id     optional
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

The backend does not persist ARMED state and does not auto-resume it.

The frontend can retain entered configuration values in normal browser state, but those values do not represent backend ARMED state.

## 8. ARM semantics

ARM is explicit.

When ARM is accepted, `RecordingManager` reads the current device snapshot from `RuntimeStore` only to establish the post-ARM cycle floor. If a last canonical sample exists, its cycle ID becomes `arm_floor_cycle_id`.

A queued measurement event with:

```text
cycle_id <= arm_floor_cycle_id
```

is treated as pre-ARM evidence and is not evaluated.

This prevents a measurement that was published before ARM, but is still waiting in the recorder subscriber queue, from firing the new trigger.

If no canonical sample exists at ARM time, `arm_floor_cycle_id` is empty. The first later eligible canonical sample is the first post-ARM sample.

ARM while recording is rejected:

```text
RECORDING + ARM -> 409 CONFLICT
```

The active recording continues unchanged.

## 9. Manual recording ownership

Manual operator action has higher authority than an armed trigger.

### 9.1 Manual START while ARMED

If the manual START request passes normal input and ownership validation, `RecordingManager` disarms the trigger before it creates the manual session.

```text
ARMED + MANUAL START -> DISARMED + MANUAL RECORDING
```

The existing manual recording start path otherwise remains unchanged.

If session creation then fails because of filesystem or recording initialization failure, the trigger stays DISARMED. There is no hidden automatic return to ARMED state.

### 9.2 Manual STOP

Manual STOP never arms or re-arms a trigger.

A one-shot triggered recording has already consumed its trigger when recording starts. STOP leaves trigger state DISARMED.

## 10. Configuration changes while ARMED

Any trigger configuration change causes:

```text
ARMED + CONFIG UPDATE -> DISARMED
```

This applies to:

- block / phase;
- measurement;
- operator;
- threshold;
- mode;
- recording interval.

The backend is authoritative for this transition. The frontend does not simulate it locally as final state.

A new explicit ARM command is required after any configuration update.

## 11. Eligible samples

The trigger evaluates only a canonical `MeasurementSample` for the same device as the trigger owner.

Eligible quality values are the same quality values accepted by the current recorder:

- `VALID`
- `DEGRADED`

Any other quality does not fire the trigger.

The selected numeric measurement value must be finite. A non-finite selected value does not fire the trigger.

A sample from another Emonio does not change this trigger's state or continuity evidence.

## 12. LEVEL semantics

LEVEL uses only the current eligible post-ARM sample.

The first eligible sample after ARM can fire immediately.

For threshold `T` and exact canonical value `x`:

```text
>   fires when x >  T
>=  fires when x >= T
<   fires when x <  T
<=  fires when x <= T
```

No previous value is required.

An acquisition gap before a later LEVEL sample does not require interpolation or inference. A later eligible sample can fire LEVEL from its own exact current value.

## 13. CROSSING semantics

The first eligible post-ARM sample establishes previous-state evidence only. It cannot fire.

For previous exact value `p`, current exact value `x`, and threshold `T`:

```text
>   fires when p <= T and x >  T
>=  fires when p <  T and x >= T
<   fires when p >= T and x <  T
<=  fires when p >  T and x <= T
```

No epsilon is used.

### 13.1 Continuity requirement

A crossing pair is valid only when:

```text
current.cycle_id == previous.cycle_id + 1
```

and no `DiagnosticEvent` for that Emonio invalidated continuity between the two measurement samples.

When a `DiagnosticEvent` for the armed Emonio is consumed, CROSSING previous-state evidence is cleared.

When a later MeasurementSample cycle ID is not exactly one greater than the previous cycle ID, CROSSING previous-state evidence is cleared. If that later sample is otherwise eligible and newer, it becomes the new baseline and cannot fire on that evaluation.

A duplicate cycle ID is ignored and cannot fire.

A stale or decreasing cycle ID is ignored and cannot fire.

This cycle rule also detects an unseen event after bounded Runtime Event Bus queue loss.

The implementation never infers a crossing across a gap.

## 14. Trigger firing transaction

When a trigger fires, `RecordingManager` performs these actions under its recording ownership synchronization boundary:

1. Keep the exact firing `MeasurementSample` object.
2. Record last-fired trigger evidence from that sample.
3. Consume the one-shot trigger.
4. Set trigger state to DISARMED.
5. Create the recording session from that exact sample.
6. Set session `started_utc` to `sample.timing.cycle_finished_utc`.
7. Pass the exact sample to the existing `SessionRecorder` first-sample path.
8. Write trigger provenance to session evidence.

There is no RuntimeStore re-read between evaluation and triggered session creation.

A newer sample cannot replace the firing sample as the first recorded sample.

## 15. Triggered session provenance

Triggered recordings are distinguishable from manual recordings.

Manual sessions keep the current session metadata structure. The implementation does not add `start_source` to existing manual sessions in v0.4.16.

Triggered sessions add these fields inside the existing `recording` metadata object:

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

The triggered session also writes one `TRIGGER_FIRED` event entry with:

- firing UTC;
- firing cycle ID;
- trigger mode;
- block;
- measurement;
- operator;
- threshold;
- exact firing value.

This event is evidence only. It does not change measurement CSV data.

## 16. Failure semantics

### 16.1 Failure after SessionRecorder exists

Existing recording failure behavior remains in force.

```text
TRIGGER CONSUMED -> DISARMED
RECORDING -> ERROR
```

There is no retry, second session, or re-arm.

### 16.2 Failure during triggered session creation

A filesystem or initialization error can occur before a `SessionRecorder` becomes active.

In this case:

- the trigger remains consumed and DISARMED;
- no second start attempt occurs;
- `RecordingManager` stores a deterministic per-device recording failure entry in its existing failure collection;
- the failure entry identifies `start_source = TRIGGER`;
- it includes device ID, failed cycle ID, failed UTC, error type, and error detail;
- `session_dir` is empty when no session directory became usable;
- `RecordingManager` publishes a `DiagnosticEvent` named `TRIGGERED_RECORDING_START_ERROR`.

The system never reports RECORDING if triggered session creation failed.

## 17. Backend component boundaries

### 17.1 New `src/emonio_viewer/recording/trigger.py`

This module contains only trigger-specific logic:

- trigger enums or validated constants;
- immutable `TriggerConfig`;
- per-device trigger runtime state representation;
- canonical field extraction;
- LEVEL comparison;
- CROSSING comparison;
- continuity handling;
- deterministic evaluation result.

It does not import Modbus transport code or acquisition worker code.

The evaluator is independently unit-testable.

### 17.2 Existing `src/emonio_viewer/recording/recorder.py`

`RecordingManager` remains the owner of:

- active recorders per device;
- trigger state per device;
- manual/trigger ownership conflicts;
- event-consumer ordering;
- triggered start from the exact firing sample;
- trigger-start failure reporting.

Add one narrow exact-sample start path, for example:

```text
_start_from_sample(device_id, sample, interval_s, trigger_evidence)
```

The final name can follow existing code style, but the interface must accept the exact sample directly.

Manual `start()` continues to use `RuntimeStore` for its existing latest-sample behavior. Triggered start does not use `RuntimeStore` to select the first sample.

### 17.3 Existing `src/emonio_viewer/recording/session.py`

Make only the change required to add optional triggered-start provenance.

When trigger provenance is absent, manual session metadata remains structurally unchanged.

### 17.4 Paths that do not change

The design does not require changes to:

- `src/emonio_viewer/modbus/*`
- `src/emonio_viewer/measurement/*`
- `src/emonio_viewer/acquisition/*`
- `src/emonio_viewer/runtime/events.py`
- `src/emonio_viewer/runtime/store.py`
- `src/emonio_viewer/scope/*`

If implementation evidence shows that one of these paths must change, implementation stops and this design is reviewed before such a change is made.

## 18. API design

Keep the existing manual recording endpoints.

Add:

```text
POST /api/v1/recording/trigger/configure
POST /api/v1/recording/trigger/arm
POST /api/v1/recording/trigger/disarm
```

The existing endpoint remains:

```text
GET /api/v1/recording/status
```

Its response adds:

```json
{
  "active": [],
  "errors": [],
  "triggers": []
}
```

Each trigger status record contains:

- device ID;
- state;
- complete current configuration when configured;
- armed UTC when ARMED;
- last fired cycle ID when available;
- last fired UTC when available;
- last fired value when available.

### 18.1 HTTP status rules

- Invalid trigger configuration: `400 Bad Request`.
- Unknown device: `404 Not Found`.
- ARM without valid configuration: `409 Conflict`.
- ARM while recording: `409 Conflict`.
- Recording commands disabled: `503 Service Unavailable`.
- Valid configure: `200` with resulting DISARMED trigger status.
- Valid ARM: `200` with ARMED trigger status.
- Valid DISARM: `200` with DISARMED trigger status.

Manual START keeps its current endpoint and response contract. A successful manual START while ARMED performs the disarm inside `RecordingManager`.

## 19. Frontend design

Keep the compact Session Recording strip unchanged except for state text that is already driven by recording status.

Add a `TRIGGERED RECORDING` section to the existing Recording drawer for the selected Emonio.

Controls:

```text
MODE         [ LEVEL | CROSSING ]
PHASE        [ A | B | C | TOTAL ]
MEASUREMENT  [ U | I | P | Q | S | PF | f ]
OPERATOR     [ > | >= | < | <= ]
THRESHOLD    [ numeric input ]
INTERVAL     [ existing valid recording intervals ]

[ ARM ] [ DISARM ]

STATUS: DISARMED
```

When armed, the status shows the complete condition. Example:

```text
ARMED · PHASE A · P > 1000 W · CROSSING
```

The backend status is authoritative.

The frontend does not simulate trigger evaluation from WebSocket measurements.

A control change sends a configure request. If the previous trigger was ARMED, the returned backend state is DISARMED.

The UI does not display ARMED until the ARM request succeeds.

When a triggered session starts, the existing recording status and session-card UI remain the authoritative indication of active recording.

Triggered session cards add start-source evidence when the backend returns it. Existing manual session cards remain valid.

Trigger-specific CSS is placed in a dedicated structured stylesheet or a clearly isolated recording-trigger section in the existing recording stylesheet. Unrelated workstation CSS is not rewritten.

## 20. State model

Trigger state and recording state are separate.

### 20.1 Trigger state

```text
DISARMED --ARM----------------------> ARMED
ARMED ----DISARM--------------------> DISARMED
ARMED ----CONFIG UPDATE-------------> DISARMED
ARMED ----MANUAL START--------------> DISARMED
ARMED ----QUALIFYING ONE-SHOT-------> DISARMED
RESTART ----------------------------> DISARMED
TRIGGER START ERROR-----------------> DISARMED
```

### 20.2 Recording state

```text
IDLE --MANUAL START-----------------> RECORDING
IDLE --TRIGGER FIRE + START OK------> RECORDING
IDLE --TRIGGER FIRE + START ERROR---> ERROR EVIDENCE
RECORDING --STOP--------------------> STOPPED
RECORDING --WRITE/STORAGE ERROR-----> ERROR
```

A trigger can be ARMED only when no recording is active for that Emonio.

## 21. Determinism and concurrency

All trigger ownership changes and recording ownership changes use the existing `RecordingManager` lock or one equivalent single synchronization boundary.

These operations are atomic from the RecordingManager point of view:

- configuration replacement and forced disarm;
- ARM conflict check and ARMED state creation;
- manual START and trigger disarm;
- trigger fire and one-shot consumption;
- triggered recorder creation from the firing sample;
- triggered start-failure recording;
- active recording failure removal and error publication.

The TriggerEngine does not create a worker thread.

The TriggerEngine does not use wall-clock polling.

A trigger evaluates only when canonical runtime events are consumed.

## 22. Required tests

### 22.1 Unit tests — trigger logic

Test:

- all four LEVEL operators;
- all four CROSSING operators;
- exact threshold equality behavior;
- first CROSSING sample cannot fire;
- fixed qualification count is one;
- no hysteresis;
- non-finite threshold rejected;
- non-finite selected value cannot fire;
- wrong device cannot affect trigger;
- A/B/C/TOTAL field extraction;
- U/I/P/Q/S/PF/f field extraction;
- DiagnosticEvent resets CROSSING continuity;
- cycle gap resets CROSSING continuity;
- stale pre-ARM cycle cannot fire;
- duplicate cycle cannot fire;
- decreasing cycle cannot fire;
- configuration update disarms.

### 22.2 RecordingManager integration tests

Test:

- LEVEL firing creates one session;
- CROSSING firing creates one session;
- exact firing sample is the first measurement row;
- recording `started_utc` equals firing `cycle_finished_utc`;
- trigger provenance contains exact firing cycle and exact value;
- no RuntimeStore re-read can substitute a newer sample;
- trigger is DISARMED after fire;
- one-shot does not fire a second time;
- manual START disarms ARMED trigger;
- ARM while recording is rejected;
- manual STOP leaves trigger DISARMED;
- triggered write error leaves trigger DISARMED;
- triggered start error leaves trigger DISARMED and creates failure evidence;
- independent Emonio triggers do not interfere;
- event gap cannot create a false CROSSING.

### 22.3 API tests

Test:

- configure validation;
- finite threshold validation;
- interval validation;
- ARM without configuration conflict;
- ARM response;
- DISARM response;
- 409 ARM conflict while recording;
- status serialization;
- manual START ownership rule;
- recording-command disable behavior.

### 22.4 Browser tests

Test:

- trigger controls call backend API only;
- A/B/C/TOTAL options;
- U/I/P/Q/S/PF/f options;
- operator options;
- mode options;
- ARMED status comes from backend status;
- configuration change while ARMED returns DISARMED state;
- device switching preserves independent backend trigger status;
- triggered session appears in normal recording status UI;
- trigger controls do not evaluate WebSocket samples locally.

### 22.5 Regression tests

All existing recording, measurement, history, Density, vector, device lifecycle, SCOPE, and read-only tests must continue to pass.

## 23. Acceptance gates

v0.4.16 remains `Testing` until all required evidence exists.

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

`main` is not part of this work. Development and field testing stay on `testing`.

## 24. Implementation sequence

Implementation uses test-driven development.

Sequence:

1. Add failing pure TriggerEngine tests.
2. Implement `recording/trigger.py` until the pure tests pass.
3. Add failing RecordingManager ownership and exact-first-sample tests.
4. Add the minimal RecordingManager integration.
5. Add failing session provenance and triggered-start-failure tests.
6. Add minimal trigger provenance and failure evidence.
7. Add failing API tests.
8. Add trigger API endpoints.
9. Add failing frontend API/state tests.
10. Add trigger controls in the existing Recording drawer with structured CSS.
11. Run focused trigger regression tests.
12. Run complete project acceptance.
13. Perform real-device field testing on `testing`.

No implementation step modifies `main`.

## 25. Success criteria

v0.4.16 Triggered Recording is successful only when all statements below are true:

- A numeric LEVEL condition starts recording from the first qualifying new canonical sample.
- A numeric CROSSING condition starts recording only from two proven consecutive post-ARM canonical samples.
- A gap cannot create a false crossing.
- The exact firing sample is the first recorded sample.
- The trigger fires once only.
- Manual recording and triggered recording cannot compete for one Emonio.
- Multiple Emonios remain independent.
- Restart never automatically re-arms a trigger.
- Recording failure never automatically retries or re-arms.
- Trigger start failure creates explicit failure evidence.
- Trigger provenance is recoverable from session evidence.
- Existing manual recording behavior remains functional.
- Canonical measurement and acquisition architecture remain unchanged.
