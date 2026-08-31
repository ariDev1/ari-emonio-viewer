# ARI Emonio Viewer v0.4.16 Testing — Triggered Recording Design

Date: 2026-08-31  
Status: APPROVED DESIGN — CLARIFIED DURING PLAN SELF-REVIEW  
Target branch: `testing`  
Baseline before design work: `b539efe7eb3a11d53a3b291254ddd0c50a2cf3df`  
Target version: `v0.4.16 Testing`

## 1. Purpose

Add deterministic one-shot triggered recording without changing the canonical measurement path.

The trigger uses the exact canonical `MeasurementSample` objects that already reach the recording subsystem. It does not change measured values. It does not create synthetic samples. It does not infer a threshold crossing across missing evidence.

Existing manual recording remains available. Pre-trigger recording is not part of this version.

## 2. Scientific invariants

The implementation must preserve these rules:

- Modbus/TCP stays read-only.
- Acquisition timing stays unchanged.
- Register maps and decoders stay unchanged.
- Canonical measurement validation stays unchanged.
- Canonical P and Q signs and quadrants stay unchanged.
- Trigger comparison uses exact canonical numeric values.
- Display rounding never affects trigger evaluation.
- No smoothing, averaging, interpolation, resampling, hysteresis, or synthetic samples are permitted.
- Qualification count is fixed at one qualifying canonical sample.
- One firing creates at most one recording session.
- The exact firing sample is the first sample of a successful triggered recording.

## 3. Existing architecture evidence

`RecordingManager` already owns one `RuntimeEventBus` subscriber and consumes canonical `MeasurementSample` and `DiagnosticEvent` objects.

`SessionRecorder.create()` already accepts a specific first sample and sends it through the normal recording path.

The Runtime Event Bus uses bounded subscriber queues. A queue can drop an older event. CROSSING logic must therefore prove continuity from cycle identity and diagnostic evidence, not only from event arrival order.

## 4. Selected architecture

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
        +--> armed trigger state
                 |
                 +--> no fire: retain required runtime evidence
                 |
                 +--> fire: SessionRecorder.create(exact firing sample)
```

This keeps one recording owner per Emonio, one ordered evidence consumer, and one synchronization boundary for manual and triggered recording.

Rejected designs:

- A separate backend trigger subscriber is rejected because two bounded queues can observe different event loss and timing.
- A browser trigger is rejected because browser history is display state, not authoritative recording evidence.

## 5. Supported trigger scope

Measurements:

| UI | Canonical field |
| --- | --- |
| U | `vrms` |
| I | `irms` |
| P | `p` |
| Q | `q` |
| S | `s` |
| PF | `pf` |
| f | `frequency` |

Blocks:

- A
- B
- C
- TOTAL

Operators:

- `>`
- `>=`
- `<`
- `<=`

Modes:

- `LEVEL`
- `CROSSING`

Deferred:

- Pre-trigger recording.
- Automatic re-arm.
- Repeating triggers.
- Hysteresis.
- Configurable debounce or N-sample qualification.
- Dedicated P/Q sign-change trigger types.
- Dedicated quadrant-transition trigger type.
- Compound Boolean conditions.
- Time-based conditions.

## 6. Trigger configuration

The backend configuration is immutable while ARMED:

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

The server rejects unknown enum values, non-finite thresholds, non-finite intervals, intervals `<= 0`, and intervals lower than the Emonio acquisition interval.

Any accepted configuration update first forces that Emonio to DISARMED state and then stores the new configuration. A new explicit ARM command is required.

## 7. Per-Emonio runtime state

Each Emonio owns independent trigger state.

```text
TriggerRuntimeState
  config
  armed_utc
  arm_floor_cycle_id     optional
  previous_cycle_id      optional
  previous_value         optional
  previous_sample_utc    optional
```

Last-fired evidence is retained separately for status display after the one-shot is consumed:

```text
last_fired_cycle_id
last_fired_utc
last_fired_value
```

ARMED state is runtime-only. Viewer restart always starts DISARMED. There is no auto-resume or automatic re-arm.

## 8. ARM semantics

ARM is explicit.

When ARM is accepted, `RecordingManager` reads the current `RuntimeStore` snapshot only to establish the post-ARM cycle floor. If a last canonical sample exists, its cycle ID becomes `arm_floor_cycle_id`.

A queued measurement with:

```text
cycle_id <= arm_floor_cycle_id
```

is pre-ARM evidence and is not evaluated.

If no canonical sample exists at ARM time, the first later eligible sample is the first post-ARM sample.

ARM while recording is rejected:

```text
RECORDING + ARM -> 409 CONFLICT
```

The active recording continues unchanged.

## 9. Operator ownership rules

Manual operator actions have higher authority than an armed trigger.

### 9.1 Manual START while ARMED

If normal manual START validation succeeds far enough to take recording ownership, the trigger is disarmed before manual session creation.

```text
ARMED + MANUAL START -> DISARMED + MANUAL RECORDING
```

If manual session creation then fails, the trigger stays DISARMED. There is no hidden return to ARMED.

### 9.2 Manual STOP is a master abort for the selected Emonio

Manual STOP always disarms an armed trigger for that Emonio.

If recording is active:

```text
RECORDING + STOP -> STOPPED + DISARMED
```

If no recording is active but a trigger is ARMED:

```text
ARMED + STOP -> DISARMED
```

This STOP request succeeds because it performed a real state transition.

If neither recording nor an armed trigger exists, the existing `recording not active` / 404 behavior remains.

The dedicated DISARM command remains available inside the trigger controls.

### 9.3 Configuration change while ARMED

Any accepted trigger configuration update causes:

```text
ARMED + CONFIG UPDATE -> DISARMED
```

## 10. Eligible trigger samples

The trigger evaluates only a canonical `MeasurementSample` for the same Emonio.

Eligible quality values are exactly:

- `VALID`
- `DEGRADED`

Any other quality cannot fire the trigger.

The selected numeric measurement value must be finite. A non-finite value cannot fire the trigger.

A sample from another Emonio does not change this trigger's state or CROSSING continuity evidence.

## 11. LEVEL semantics

LEVEL uses only the current eligible post-ARM sample.

The first eligible sample after ARM can fire immediately.

For threshold `T` and current exact value `x`:

```text
>   fires when x >  T
>=  fires when x >= T
<   fires when x <  T
<=  fires when x <= T
```

No previous value is required. A prior acquisition gap does not require inference for LEVEL because the decision uses only the current exact sample.

## 12. CROSSING semantics

The first eligible post-ARM sample establishes previous-state evidence only. It cannot fire.

For previous exact value `p`, current exact value `x`, and threshold `T`:

```text
>   fires when p <= T and x >  T
>=  fires when p <  T and x >= T
<   fires when p >= T and x <  T
<=  fires when p >  T and x <= T
```

No epsilon is used.

A crossing pair is valid only when:

```text
current.cycle_id == previous.cycle_id + 1
```

and no same-device `DiagnosticEvent` invalidated continuity between those samples.

Rules:

- A same-device `DiagnosticEvent` clears CROSSING previous-state evidence.
- A cycle gap clears previous evidence. The current eligible newer sample becomes a new baseline and cannot fire on that evaluation.
- A duplicate cycle ID is ignored and cannot fire.
- A stale/decreasing cycle ID is ignored and cannot fire.
- A sample from another Emonio does not alter the state.
- A pre-ARM queued cycle does not alter the state.

A crossing is never inferred across a gap.

## 13. Trigger firing transaction

When a trigger fires, `RecordingManager` performs these actions under its existing recording synchronization boundary:

1. Keep the exact firing `MeasurementSample` object.
2. Capture last-fired evidence from that sample.
3. Consume the one-shot trigger.
4. Set trigger state to DISARMED.
5. Create the recording session from that exact sample.
6. Set session `started_utc` to `sample.timing.cycle_finished_utc`.
7. Pass the exact same sample to the existing first-sample recording path.
8. Write trigger provenance to session evidence.

There is no `RuntimeStore` re-read between trigger evaluation and triggered session creation.

A newer sample cannot replace the firing sample as the first recorded sample.

## 14. Triggered session provenance

Manual sessions keep the current metadata structure. v0.4.16 does not add `start_source` to manual sessions.

Triggered sessions add these fields inside the existing `recording` object:

```json
{
  "recording": {
    "interval_s": 1.0,
    "start_source": "TRIGGER",
    "trigger": {
      "mode": "CROSSING",
      "block": "A",
      "measurement": "P",
      "operator": "GT",
      "threshold": 1000.0,
      "fired_cycle_id": 12345,
      "fired_utc": "canonical cycle_finished_utc",
      "fired_value": 1000.25
    }
  }
}
```

The triggered session also writes one `TRIGGER_FIRED` event with firing UTC, cycle ID, mode, block, measurement, operator, threshold, and exact firing value.

This event does not modify measurement CSV data.

## 15. Failure semantics

The trigger is consumed before triggered session creation.

If a triggered session later fails during recording I/O, existing recording ERROR handling remains in force. There is no retry, second session, or re-arm.

If triggered session creation itself fails before a usable recorder exists:

- trigger remains DISARMED;
- no second start attempt occurs;
- `RecordingManager` stores a deterministic per-device failure entry;
- failure identifies `start_source = TRIGGER`;
- failure includes device ID, failed cycle ID, failed UTC, error type, and error detail;
- `session_dir` is empty when no usable directory exists;
- one same-device `DiagnosticEvent` named `TRIGGERED_RECORDING_START_ERROR` is published.

The system never reports RECORDING when triggered session creation failed.

## 16. Backend component boundaries

Create `src/emonio_viewer/recording/trigger.py` for:

- trigger enums;
- immutable `TriggerConfig`;
- runtime trigger state representation;
- exact canonical field extraction;
- LEVEL comparison;
- CROSSING comparison;
- continuity handling;
- deterministic evaluation result.

Modify `src/emonio_viewer/recording/recorder.py` only for:

- per-device trigger configuration/state ownership;
- ARM/DISARM/configuration transitions;
- manual START/STOP ownership rules;
- event-consumer trigger evaluation;
- exact-sample triggered start;
- trigger-start failure reporting.

Modify `src/emonio_viewer/recording/session.py` only for optional triggered-start provenance.

No design change is required in:

- `src/emonio_viewer/modbus/*`
- `src/emonio_viewer/measurement/*`
- `src/emonio_viewer/acquisition/*`
- `src/emonio_viewer/runtime/events.py`
- `src/emonio_viewer/runtime/store.py`
- `src/emonio_viewer/scope/*`

If implementation evidence shows one of those protected paths must change, implementation stops and this design is reviewed first.

## 17. API contract

Keep existing manual recording endpoints.

Add:

```text
POST /api/v1/recording/trigger/configure
POST /api/v1/recording/trigger/arm
POST /api/v1/recording/trigger/disarm
```

Keep:

```text
GET /api/v1/recording/status
```

and add a `triggers` collection:

```json
{
  "active": [],
  "errors": [],
  "triggers": []
}
```

Each trigger status includes:

- device ID;
- state (`ARMED` or `DISARMED`);
- complete stored configuration;
- armed UTC when ARMED;
- last fired cycle ID when available;
- last fired UTC when available;
- last fired value when available.

HTTP rules:

- invalid configuration: 400;
- unknown device: 404;
- ARM without configuration: 409;
- ARM while recording: 409;
- commands disabled: 503;
- valid configure: 200 DISARMED;
- valid ARM: 200 ARMED;
- valid DISARM: 200 DISARMED;
- existing STOP while only ARMED: 200 DISARMED;
- existing STOP when neither recording nor ARMED: existing 404.

## 18. Frontend design

Keep the compact Session Recording strip.

Add trigger configuration inside the existing Recording drawer:

```text
TRIGGERED RECORDING
MODE         [ LEVEL | CROSSING ]
PHASE        [ A | B | C | TOTAL ]
MEASUREMENT  [ U | I | P | Q | S | PF | f ]
OPERATOR     [ > | >= | < | <= ]
THRESHOLD    [ numeric input ]
INTERVAL     [ existing valid recording intervals ]
STATE        DISARMED | ARMED
[CONFIGURE] [ARM] [DISARM]
LAST FIRED   cycle / UTC / exact value when available
```

Backend state is authoritative. After configure, ARM, DISARM, manual START, or manual STOP, the frontend refreshes `/api/v1/recording/status` before rendering final state.

The existing main STOP control is enabled when the selected Emonio is recording or has an ARMED trigger. If it is used for an armed-only Emonio, it sends the existing STOP command and shows the returned DISARMED state.

Trigger CSS stays in a separate structured `frontend/css/recording-trigger.css` file.

## 19. Tests and acceptance

Required automated evidence includes:

- exact field extraction for all supported measurements and blocks;
- threshold equality semantics for all four operators;
- LEVEL first-post-ARM firing;
- CROSSING first-sample baseline behavior;
- CROSSING consecutive-cycle requirement;
- reset on same-device diagnostic evidence;
- reset on cycle gap;
- stale/duplicate rejection;
- exact firing sample as first CSV sample even when RuntimeStore already contains a newer sample;
- one-shot behavior;
- per-Emonio isolation;
- manual START disarms trigger;
- manual STOP disarms trigger, including armed-only state;
- ARM while recording conflict;
- configuration update disarms trigger;
- restart returns DISARMED;
- triggered session provenance;
- trigger-start failure evidence;
- existing manual metadata compatibility;
- API validation/status;
- frontend controls and backend-authoritative state;
- canonical sign regression;
- read-only gate;
- complete project acceptance.

Before field testing, run `./tools/ari-emonio-acceptance.sh` and require explicit evidence for unit, integration, frontend/browser, read-only, Python compilation, scientific sign, and publication/package gates.

## 20. Release boundary

The feature is `v0.4.16 Testing` on branch `testing`.

It is not field-confirmed until real Emonio tests succeed.

It is not merged to `main`. `main` stays frozen unless the user explicitly changes that policy.