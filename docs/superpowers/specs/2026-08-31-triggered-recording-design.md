# ARI Emonio Viewer v0.4.16 Testing — Negative-Condition Monitor Design

Date: 2026-08-31  
Status: APPROVED ARCHITECTURE — FORMAL SPECIFICATION FOR REVIEW  
Target branch: `testing`  
Target version: `v0.4.16 Testing`  
Supersedes: the earlier v0.4.16 one-shot LEVEL/CROSSING trigger design

## 1. Purpose

Add a continuous per-Emonio negative-condition monitor for three-phase electrical measurements.

The primary engineering question is:

> When did negative active power or negative power factor occur, on which phase, and what happened during that interval?

The monitor must detect every supported negative-condition event during one enabled monitoring period. It must automatically start recording when the first monitored negative condition becomes active. It must keep one coherent recording while one or more monitored conditions are active. It must stop the monitor-owned recording when all monitored conditions are inactive. It must then remain enabled and wait for the next event.

The monitor uses only exact canonical `MeasurementSample` evidence. It does not modify measurement values. It does not infer crossings across missing evidence.

## 2. Scientific invariants

The implementation must preserve these rules:

- Modbus/TCP stays read-only.
- Acquisition timing stays unchanged.
- Register maps and decoders stay unchanged.
- Canonical measurement validation stays unchanged.
- Canonical P and Q signs and quadrants stay unchanged.
- Monitor decisions use exact canonical numeric values.
- Display rounding never affects monitor decisions.
- No smoothing, averaging, interpolation, resampling, hysteresis, debounce, epsilon, sign correction, or synthetic samples are permitted.
- A transition is exact only when consecutive canonical cycle evidence proves it.
- A missing cycle, invalid cycle, non-finite selected P/PF value, or same-device diagnostic continuity break prevents an exact crossing claim across that break.
- The exact activating sample is the first measurement sample of a successful monitor-owned recording.
- One Emonio has at most one active recording session.
- Manual operator actions have higher authority than automatic monitoring.

## 3. Existing architecture evidence

`RecordingManager` already owns one `RuntimeEventBus` subscriber and consumes canonical `MeasurementSample` and `DiagnosticEvent` objects.

`SessionRecorder.create()` already accepts a specific first sample and sends it through the normal recording path.

The Runtime Event Bus uses bounded subscriber queues. A queue can drop an older event. Monitor transition logic must therefore prove continuity from canonical cycle identity and diagnostic evidence, not only from event arrival order.

The browser history is display state. It is not authoritative recording evidence and must not become a monitor source.

## 4. Selected architecture

The monitor evaluator runs inside the existing `RecordingManager` consumer path.

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
        +--> per-Emonio negative-condition monitor
                 |
                 +--> update A/B/C condition state
                 +--> write exact/bounded event evidence
                 +--> start one recording when first condition activates
                 +--> keep same recording while any condition is active
                 +--> stop monitor-owned recording when all conditions clear
                 +--> remain enabled and wait for next event
```

This keeps one evidence consumer, one recording owner, and one synchronization boundary for manual and automatic recording.

Rejected designs:

- One independent recording per phase is rejected because overlapping phase events would duplicate measurement evidence and create competing session ownership.
- A browser monitor is rejected because browser history is not recording authority.
- Continuous unconditional recording is rejected because it defeats event-triggered acquisition and produces unnecessary data.

## 5. Monitor scope

The first monitor version supports these conditions:

```text
P < 0
PF < 0
P < 0 OR PF < 0
```

Supported phases:

```text
A
B
C
```

`TOTAL` is not part of v0.4.16 negative-condition monitoring. The purpose is to identify which physical phase produced the negative condition.

The threshold is fixed at exact numeric `0.0`. There is no user-defined threshold in this monitor version.

Recording interval uses the existing valid recording intervals and must be greater than or equal to the Emonio acquisition interval.

## 6. Monitor configuration

One Emonio owns one monitor configuration.

Conceptual configuration:

```text
NegativeMonitorConfig
  device_id
  condition             P_NEGATIVE | PF_NEGATIVE | P_OR_PF_NEGATIVE
  phases                non-empty subset of A, B, C
  recording_interval_s  finite positive float
```

The server rejects:

- unknown device ID;
- unknown condition;
- empty phase set;
- a phase outside A/B/C;
- non-finite recording interval;
- interval `<= 0`;
- interval lower than the device acquisition interval.

There is no clamping and no automatic substitution.

Configuration is runtime-only in v0.4.16.

Changing controls in the browser does not silently change backend state. The operator must press `APPLY`.

If `APPLY` is accepted while the monitor is enabled:

```text
monitor -> OFF
new configuration stored
explicit ENABLE MONITOR required
```

This prevents a live monitoring rule from changing without an explicit operator action.

## 7. Per-phase and per-measurement condition state

The monitor evaluates every selected phase independently.

For `P_NEGATIVE`, it tracks P on each selected phase.

For `PF_NEGATIVE`, it tracks PF on each selected phase.

For `P_OR_PF_NEGATIVE`, it tracks P and PF independently on each selected phase. It logs P and PF transitions independently. The phase aggregate is active when either selected measurement is negative.

Example:

```text
Phase B:
  P  < 0   active
  PF >= 0  inactive
  aggregate phase state = NEGATIVE P
```

If both are negative:

```text
Phase B aggregate state = NEGATIVE P + PF
```

The Emonio aggregate monitor condition is active when at least one selected phase-measurement condition is active.

## 8. Exact transition semantics

For one selected measurement `x`, threshold `0.0`, previous exact valid canonical value `p`, and current exact valid canonical value `x`:

```text
NEGATIVE_START when p >= 0 and x < 0
NEGATIVE_END   when p <  0 and x >= 0
```

No epsilon is used.

A transition is exact only when:

```text
current.cycle_id == previous.cycle_id + 1
```

and no same-device diagnostic evidence invalidated continuity between the two samples.

A selected P/PF value must be finite. A non-finite selected value cannot activate, clear, or prove a condition. It invalidates continuity for that selected phase-measurement condition and the next finite value becomes new baseline evidence.

The event time for an exact transition is the current sample `cycle_finished_utc`.

The exact current value is stored as event evidence.

When more than one monitor event is produced by the same sample, event order is deterministic:

```text
phase order: A, B, C
measurement order: P, PF
```

## 9. Monitor enable and first-sample semantics

Viewer restart starts with the monitor OFF.

The operator must explicitly enable the monitor.

ENABLE does not evaluate the pre-existing RuntimeStore sample as new evidence. Monitor evaluation starts with samples received after ENABLE.

Immediately after ENABLE and before the first eligible sample:

```text
state = WAITING
evidence_initialized = false
```

`WAITING` in this short interval means the monitor is enabled and waiting for its first new canonical evidence. It does not claim that all selected conditions are normal.

The first eligible canonical sample after ENABLE establishes the current state of all selected phase-measurement conditions and sets:

```text
evidence_initialized = true
```

If a selected value is non-negative:

```text
state = NORMAL
no negative event
```

If a selected value is already negative:

```text
state = NEGATIVE
write NEGATIVE_PRESENT_AT_MONITOR_START
```

`NEGATIVE_PRESENT_AT_MONITOR_START` is not an exact crossing. The actual transition may have occurred before monitoring started.

If at least one monitored value is already negative on that first sample, a monitor-owned recording starts from that exact first observed negative sample unless an existing manual recording already owns the device.

If several conditions are negative on the same first sample, only one recording session starts. One event is written for each negative selected phase-measurement condition in deterministic event order.

## 10. Normal automatic recording ownership

Monitor states are:

```text
OFF
WAITING
RECORDING
WAITING_FOR_CLEAR
```

Meanings:

- `OFF`: condition monitoring is disabled.
- `WAITING`: monitoring is enabled and automatic start is permitted. Before first evidence, `evidence_initialized=false`; after initialization, no monitored condition is active.
- `RECORDING`: one or more monitored conditions are active and evidence is being written to an active recording session.
- `WAITING_FOR_CLEAR`: one or more monitored conditions are active, but automatic recording is suppressed because the operator stopped the session or a recording failure occurred.

Normal automatic sequence:

```text
WAITING
  |
  | first monitored condition activates
  v
RECORDING
  |
  | other conditions can activate or clear
  | same session continues
  |
  | final active condition clears
  v
stop monitor-owned session
  |
  v
WAITING
```

There is no automatic DISARM after one event. The monitor stays enabled until explicit DISABLE MONITOR or Viewer restart.

## 11. Overlapping phase and measurement events

A new negative event during an active recording does not create another session.

Example:

```text
A P  NEGATIVE_START -> start session
B PF NEGATIVE_START -> same session, log event
A P  NEGATIVE_END   -> same session continues
C P  NEGATIVE_START -> same session continues
B PF NEGATIVE_END   -> same session continues
C P  NEGATIVE_END   -> stop monitor-owned session
monitor -> WAITING
```

This produces one coherent evidence package for the complete overlapping three-phase event interval.

## 12. Gap and invalid-cycle semantics

Any continuity break destroys exact transition evidence across that break.

Continuity breaks include:

- missing canonical cycle ID;
- invalid/stale sample that cannot be used as transition evidence;
- non-finite selected P/PF value;
- same-device `DiagnosticEvent` that represents acquisition evidence loss;
- event-delivery loss visible to the recording consumer.

The monitor does not fabricate `NEGATIVE_START` or `NEGATIVE_END` across such a break.

If a monitor-owned recording is active when continuity is lost, the session remains open. The evidence gap is recorded through the existing recording diagnostic/event path.

The first eligible sample after the gap re-establishes current condition state.

For each selected phase-measurement condition:

- current value negative -> `NEGATIVE_PRESENT_AFTER_GAP`;
- previous known state negative and current value non-negative -> `NEGATIVE_NOT_PRESENT_AFTER_GAP`;
- previous known state normal and current value non-negative -> no negative-condition event is required.

`NEGATIVE_PRESENT_AFTER_GAP` means a negative condition is observed after the gap. It does not claim the exact start time.

`NEGATIVE_NOT_PRESENT_AFTER_GAP` means a previously observed negative condition is no longer present. It does not claim the exact end time.

For a condition that was negative before the gap and is non-negative after the gap:

```text
last valid negative sample time < actual end <= first valid non-negative sample time
```

For a condition that was normal before the gap and is negative after the gap:

```text
last valid non-negative sample time < actual start <= first valid negative sample time
```

These are bounded intervals, not exact crossing times.

If the monitor is `WAITING` and the first valid post-gap sample proves one or more selected conditions are negative, a monitor-owned recording starts from that exact post-gap sample and writes `NEGATIVE_PRESENT_AFTER_GAP` evidence. It does not write a fabricated `NEGATIVE_START`.

If the first valid post-gap sample proves that all monitored conditions are non-negative, a monitor-owned recording that remained open through the gap may stop on that sample after writing any required `NEGATIVE_NOT_PRESENT_AFTER_GAP` evidence.

## 13. Disconnect and reconnect semantics

A real device disconnect is a continuity break.

The monitor configuration and enabled state remain in memory during a temporary disconnect. No automatic event is inferred while the device has no canonical measurement evidence.

If a monitor-owned recording is active, the session remains open and existing disconnect/acquisition evidence is recorded.

On the first eligible sample after reconnect:

- current selected value negative -> `NEGATIVE_PRESENT_AFTER_RECONNECT`;
- previously known negative condition now non-negative -> `NEGATIVE_NOT_PRESENT_AFTER_RECONNECT`;
- previously known normal condition still non-negative -> no negative-condition event is required.

No crossing is fabricated across the disconnected interval.

If the monitor is `WAITING` and the first valid post-reconnect sample proves one or more selected conditions are negative, a monitor-owned recording starts from that exact sample and writes `NEGATIVE_PRESENT_AFTER_RECONNECT` evidence.

If all monitored conditions are non-negative after reconnect, a monitor-owned recording that remained open through the disconnect may stop on that first valid post-reconnect sample after writing required boundary evidence.

## 14. Event evidence format

The existing `events.csv` schema remains compatible:

```text
utc,event,severity,cycle_id,detail
```

Negative-condition evidence uses the existing columns as follows:

- `utc`: canonical `cycle_finished_utc` for measurement-based monitor events;
- `event`: one of the defined negative-condition event names;
- `severity`: `INFO` for normal condition transitions/presence evidence, unless a separate failure event requires `ERROR`;
- `cycle_id`: exact canonical cycle ID;
- `detail`: deterministic structured key-value evidence.

The monitor detail format is:

```text
phase=<A|B|C>;measurement=<P|PF>;value=<exact repr>;threshold=0.0;continuity=<EXACT|MONITOR_START|GAP_BOUNDARY|RECONNECT_BOUNDARY>
```

Required monitor event names:

```text
NEGATIVE_PRESENT_AT_MONITOR_START
NEGATIVE_START
NEGATIVE_END
NEGATIVE_PRESENT_AFTER_GAP
NEGATIVE_NOT_PRESENT_AFTER_GAP
NEGATIVE_PRESENT_AFTER_RECONNECT
NEGATIVE_NOT_PRESENT_AFTER_RECONNECT
```

When an active recording session exists, monitor events are written to that session `events.csv` in deterministic A/B/C then P/PF order.

When no recording session exists, there is no session `events.csv` to write. v0.4.16 does not add a second persistent monitor journal. The backend monitor status retains the latest monitor event as runtime evidence. A later persistent monitor journal is a separate feature if field use proves it is required.

This preserves the existing event CSV columns while providing explicit phase, measurement, exact value, fixed threshold, and continuity classification.

Measurement CSV columns and measurement numeric serialization remain unchanged.

## 15. Monitor-owned session provenance

A session started automatically by the monitor adds monitor provenance to the existing `recording` metadata object.

Conceptual structure:

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

If several conditions activate on the same sample, `start_phase` and `start_measurement` use the same deterministic A/B/C then P/PF event order.

All activating conditions are still written individually to `events.csv` after successful session creation.

Manual session metadata remains compatible with the existing manual recording format. A monitor enabled during a manual session writes monitor events into that existing session but does not convert the session owner to monitor-owned.

## 16. Manual operator authority

Manual operator actions have higher authority than automation.

### 16.1 Manual RECORD while monitor is enabled

Manual RECORD can start a session while the monitor is `WAITING`.

The monitor remains enabled and continues to evaluate exact canonical samples.

If a monitored condition becomes active during the manual session:

- the monitor writes the condition events into the same manual session;
- it does not create a second session;
- monitor state becomes `RECORDING` while one or more monitored conditions are active and evidence is being recorded.

When all monitored conditions clear, monitor state returns to `WAITING`. The manual session itself continues until the operator stops it.

### 16.2 ENABLE MONITOR while manual recording is already active

This is allowed.

The first eligible post-enable sample establishes monitor state.

If a selected condition is already negative, the monitor writes `NEGATIVE_PRESENT_AT_MONITOR_START` into the active manual session.

No second session is created.

### 16.3 Manual STOP

Manual STOP stops the active recording session.

The monitor remains enabled.

If no monitored condition is active after STOP:

```text
monitor -> WAITING
```

If one or more monitored conditions are still active:

```text
monitor -> WAITING_FOR_CLEAR
```

While `WAITING_FOR_CLEAR`, the monitor continues to evaluate runtime condition state but does not automatically create another session for the same continuous negative condition.

Because the operator explicitly closed the recording, a later clear transition during `WAITING_FOR_CLEAR` cannot be appended to that closed session. It is retained as `last_event` runtime monitor evidence. No separate persistent monitor journal is added in v0.4.16.

When all monitored conditions become non-negative:

```text
WAITING_FOR_CLEAR -> WAITING
```

The next new negative event can start a new automatic session.

This prevents automatic recording from immediately overriding an explicit operator STOP.

### 16.4 DISABLE MONITOR

DISABLE MONITOR stops condition monitoring and clears monitor runtime condition state.

If the active recording is manual-owned, DISABLE MONITOR does not stop the manual session.

If the active recording is monitor-owned, DISABLE MONITOR stops that recording cleanly and then sets monitor state to `OFF`.

## 17. Recording ownership representation

`RecordingManager` remains the single owner of recording sessions.

It must distinguish runtime recording ownership:

```text
MANUAL
NEGATIVE_CONDITION_MONITOR
```

This ownership is required so DISABLE MONITOR can stop only a monitor-owned session and leave a manual session unchanged.

There is never more than one active session per Emonio.

## 18. Automatic recording start failure

If an activating or negative-presence event occurs but monitor-owned session creation fails:

- keep the negative-condition evidence in monitor runtime `last_event`, failure status, and diagnostics as far as available;
- do not report RECORDING;
- do not retry automatically on every negative sample;
- monitor remains enabled;
- monitor state becomes `WAITING_FOR_CLEAR` if any monitored condition remains active;
- publish one explicit monitor recording-start failure diagnostic;
- store deterministic per-device failure status.

The monitor does not create a replacement session for the same continuous negative condition.

When all monitored conditions clear, the monitor returns to `WAITING`. The next new event may start a new session.

## 19. Recording write failure

If measurement, event, or metadata I/O fails during an active recording:

- existing recording failure handling remains authoritative;
- fail/close the session as far as possible;
- store explicit ERROR evidence;
- do not create an automatic replacement session for the same continuous negative condition;
- monitor remains enabled;
- if any monitored condition remains active, monitor enters `WAITING_FOR_CLEAR`;
- if all monitored conditions are inactive, monitor returns to `WAITING`.

There is no automatic retry loop.

## 20. Restart semantics

Monitor configuration and enabled state are runtime-only in v0.4.16.

Viewer restart always starts:

```text
MONITOR OFF
```

There is:

- no automatic re-enable;
- no automatic session recovery;
- no hidden persistence subsystem.

Persistent unattended monitoring can be designed later if there is a proven requirement.

## 21. Backend component boundaries

The existing pure trigger work can be reused only where it cleanly supports exact comparison and continuity semantics. The final v0.4.16 public model is the negative-condition monitor, not a generic one-shot trigger.

The final implementation should use a focused recording-subsystem module for:

- monitor configuration;
- per-phase/per-measurement condition state;
- exact negative transition evaluation;
- continuity classification;
- deterministic monitor event results.

`RecordingManager` owns:

- per-Emonio monitor configuration and runtime state;
- monitor ENABLE/DISABLE/APPLY transitions;
- manual/monitor recording ownership;
- event-consumer monitor evaluation;
- exact-sample automatic session start;
- automatic stop when all conditions clear;
- `WAITING_FOR_CLEAR` suppression;
- failure integration.

`SessionRecorder` remains the measurement/event writer and session metadata owner.

No design change is required in:

```text
src/emonio_viewer/modbus/*
src/emonio_viewer/measurement/*
src/emonio_viewer/acquisition/*
src/emonio_viewer/runtime/events.py
src/emonio_viewer/runtime/store.py
src/emonio_viewer/scope/*
```

If implementation evidence shows one of these protected paths must change, implementation stops and this design is reviewed first.

## 22. API contract

The obsolete one-shot trigger API is not part of the final v0.4.16 public contract.

Use monitor-specific endpoints:

```text
POST /api/v1/recording/monitor/configure
POST /api/v1/recording/monitor/enable
POST /api/v1/recording/monitor/disable
GET  /api/v1/recording/status
```

Configure request:

```json
{
  "device_id": "emonio-id",
  "condition": "P_OR_PF_NEGATIVE",
  "phases": ["A", "B", "C"],
  "recording_interval_s": 2.0
}
```

ENABLE/DISABLE request:

```json
{"device_id": "emonio-id"}
```

Recording status keeps existing `active` and `errors` collections and adds monitor status:

```json
{
  "active": [],
  "errors": [],
  "monitors": []
}
```

Each monitor status contains:

```text
device_id
state                   OFF | WAITING | RECORDING | WAITING_FOR_CLEAR
configuration           complete stored config or null
enabled_utc             null or UTC
evidence_initialized    true | false
phase_states            A/B/C current P/PF negative-state evidence as applicable
active_conditions       deterministic A/B/C then P/PF list
last_event              null or complete latest monitor event evidence
recording_owner         null | MANUAL | NEGATIVE_CONDITION_MONITOR
```

HTTP rules:

- invalid configuration: 400;
- unknown device: 404;
- ENABLE without configuration: 409;
- recording commands disabled: 503;
- valid APPLY/configure: 200 and monitor OFF;
- valid ENABLE: 200 WAITING with `evidence_initialized=false` until the next eligible sample;
- valid DISABLE: 200 OFF;
- existing manual RECORD/STOP endpoints remain available.

The old `/recording/trigger/*` routes must not remain as a second public automation model in the final v0.4.16 candidate.

## 23. Frontend design

Keep the existing compact Session Recording strip.

Replace the current one-shot trigger controls in the Recording drawer with:

```text
NEGATIVE-CONDITION MONITOR
CONDITION   [ P < 0 | PF < 0 | P < 0 OR PF < 0 ]
PHASES      [A] [B] [C]
INTERVAL    [existing valid recording intervals]

STATE       OFF | WAITING | RECORDING | WAITING FOR CLEAR

[APPLY] [ENABLE MONITOR] [DISABLE MONITOR]

PHASE STATE
A   NORMAL
B   NEGATIVE P
C   NEGATIVE PF

LAST EVENT
B · P · NEGATIVE_START
cycle 1254 · canonical UTC · exact value
```

Default phase selection is A+B+C.

Changing a field changes only the local form. `APPLY` commits the configuration to the backend.

The browser must not silently mutate an enabled monitor configuration.

Backend state is authoritative. After APPLY, ENABLE, DISABLE, manual RECORD, or manual STOP, the frontend refreshes `/api/v1/recording/status` before final rendering.

Monitor CSS remains in a separate structured recording-monitor stylesheet. Do not place monitor selectors throughout unrelated CSS files.

## 24. Required automated evidence

Required tests include:

- P exact negative-start and negative-end semantics;
- PF exact negative-start and negative-end semantics;
- P OR PF independent event logging and aggregate activity;
- A/B/C independent condition state;
- deterministic same-sample multi-condition ordering;
- first post-enable negative sample -> `NEGATIVE_PRESENT_AT_MONITOR_START`, not fabricated crossing;
- pre-enable RuntimeStore sample cannot fire or initialize the monitor;
- non-finite selected P/PF invalidates continuity and cannot change condition state;
- exact activating sample is first measurement row of a monitor-owned session;
- overlapping phase conditions share one session;
- session stops only when final active monitored condition clears;
- automatic re-wait after normal session completion;
- next independent negative event starts a new session without manual re-arm;
- cycle-gap continuity loss prevents exact crossing claim;
- negative first sample after gap starts recording with `NEGATIVE_PRESENT_AFTER_GAP`, not fabricated crossing;
- correct `*_AFTER_GAP` evidence;
- disconnect/reconnect continuity behavior;
- negative first sample after reconnect starts recording with `NEGATIVE_PRESENT_AFTER_RECONNECT`;
- correct `*_AFTER_RECONNECT` evidence;
- manual RECORD while monitor enabled uses one session and receives monitor events;
- ENABLE during manual recording does not create a second session;
- manual STOP while a condition is active -> `WAITING_FOR_CLEAR`;
- no immediate restart while waiting for clear;
- clear condition -> WAITING and updates runtime `last_event` even without an open session;
- next new event -> automatic recording allowed;
- DISABLE stops monitor-owned recording but not manual-owned recording;
- monitor start failure -> explicit failure + WAITING_FOR_CLEAR, no retry loop;
- recording write failure -> explicit ERROR and deterministic monitor state;
- restart -> monitor OFF;
- configuration APPLY while enabled -> monitor OFF;
- empty phase set rejected;
- invalid/non-finite interval rejected;
- monitor status is backend authoritative;
- current measurement CSV numeric precision remains unchanged;
- current canonical signs/quadrants remain unchanged;
- multi-Emonio monitor isolation;
- read-only gate remains PASS;
- complete project acceptance remains PASS.

## 25. Field test requirements

Field testing must use real Emonio measurement evidence.

Minimum field scenarios:

```text
1. Monitor P < 0 on A+B+C.
2. Cause one phase to cross from P >= 0 to P < 0.
3. Verify exact phase/event/cycle/UTC/value and automatic recording start.
4. Return that phase to P >= 0 and verify NEGATIVE_END and automatic stop.
5. Repeat a second independent negative-P event and verify automatic new session without re-enable.
6. Create overlapping negative P on two phases and verify one shared session.
7. Monitor PF < 0 and verify independent PF event evidence.
8. Monitor P < 0 OR PF < 0 and verify both measurement event types are distinguished.
9. Press manual STOP during an active negative condition and verify WAITING_FOR_CLEAR with no immediate restart.
10. Clear the condition and produce a new negative event; verify automatic recording resumes.
11. Verify manual recording remains functional.
12. Verify History, Density, Vector, Modbus evidence, Diagnostics, and SCOPE remain normal.
```

A candidate is not field-confirmed until this evidence succeeds on the real workflow.

## 26. Release and migration boundary

The feature remains `v0.4.16 Testing` on branch `testing`.

The partial one-shot trigger implementation already developed on `testing` is superseded by this specification. It is development evidence, not the final v0.4.16 architecture. Useful exact comparison, continuity, exact-sample start, API validation, and frontend patterns may be retained only when they fit this monitor design cleanly.

The final v0.4.16 candidate must not expose two competing automation models. One-shot ARMED/DISARMED trigger controls and public `/recording/trigger/*` routes are removed or replaced before acceptance.

The implementation must not be merged to `main` as part of this work.

`main` remains outside this development cycle unless the user explicitly changes that policy.