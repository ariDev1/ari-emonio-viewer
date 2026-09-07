# Stage4C Control History Design Specification

**Approved:** 2026-09-07

**Repository:** `ariDev1/ari-emonio-viewer`

**Branch:** `testing`

**Approved baseline commit:** `2a54d0194ee21c9db39137495378ec523a702d3f`

## Goal

Add a read-only Stage4C Control History view that shows how canonical Emonio active-power measurements, Stage4C controller decisions, physical PWM command/ACK evidence, and safety/lifecycle events develop over time.

The view is scientific control evidence. It is not a dashboard decoration and it has no control authority.

## Protected scientific boundary

The implementation must not change:

- `src/emonio_viewer/acquisition/`
- `src/emonio_viewer/measurement/`
- `src/emonio_viewer/modbus/`
- `src/emonio_viewer/runtime/events.py`
- `src/emonio_viewer/runtime/store.py`
- `src/emonio_viewer/scope/`
- canonical P/Q signs or quadrant semantics
- acquisition timing
- Modbus read-only behavior
- recording or CSV precision
- Stage4C controller authority, search logic, timing, safety, or reconnect behavior

## Evidence authority

The existing `LoadControlDiagnosticLog` remains the authoritative bounded control-evidence stream.

Do not add a second backend controller-history store.

The existing Stage4C controller and manual PWM service already share the same diagnostic-log instance. Preserve this architecture.

## Required backend observability additions

### Structured diagnostic fields

Retain every diagnostic field in structured form in `DiagnosticEvent` while preserving the existing copyable `line`, event sequence, UTC timestamp, and bounded eviction behavior.

The public diagnostics GET response may expose the structured fields. Existing response fields must remain unchanged.

### Stage4C PWM ownership evidence

`PWM_COMMAND_SENT` and `PWM_ACK_QUALIFIED` must identify the command owner. Stage4C reserved commands use the existing owner value `STAGE4C_ZERO_EXPORT`.

This field is evidence only. It must not change PWM ownership or command behavior.

### Causal-boundary evidence

When Stage4C arms after an acknowledged PWM state, append one observational event that preserves the existing monotonic causal boundary and freshness deadline.

Do not convert monotonic values into fabricated UTC timestamps.

### Settling-sample evidence

When Stage4C accepts the first causal post-ACK sample as the settling sample, append one observational event containing:

- source device ID
- selected phase
- sample cycle ID
- the sample's real `cycle_finished_utc`
- the sample's real `cycle_finished_monotonic_ns`
- controller state

Do not make a controller decision from this sample.

### Decision evidence

Existing `ZERO_EXPORT_DECISION` evidence must additionally expose the selected sample's real UTC and monotonic finish timestamps and the resulting controller state/reason at the decision point.

Canonical P must be the exact P value already consumed by Stage4C. Do not recalculate P in the history subsystem.

### Existing fault and lifecycle evidence

Reuse existing evidence such as:

- `ZERO_EXPORT_ENABLED`
- `ZERO_EXPORT_DISABLED`
- `ZERO_EXPORT_SAFE_BLOCK`
- `ZERO_EXPORT_LIMIT_LOW`
- `ZERO_EXPORT_RESOLUTION_LIMIT`
- `ZERO_EXPORT_RESOLUTION_LIMIT_ACTIVE`
- `PWM_COMMAND_SENT`
- `PWM_ACK_QUALIFIED`
- `PWM_COMMAND_REJECTED`
- `WS_DISCONNECTED`
- `HELLO_RECEIVED`

Do not add reconnect behavior.

## Timestamp domains

Keep timestamp domains explicit.

- Measurement points use the original measurement `cycle_finished_utc`.
- Command, ACK, and lifecycle markers use their diagnostic UTC timestamps.
- Causal validation remains based on existing monotonic nanoseconds.
- Monotonic values are displayed as evidence when useful, but they are never converted into artificial UTC values.

## Frontend history store

Create an independent read-only frontend control-history cache.

It must not use or modify the canonical measurement-history store.

Retention:

- target time window: 10 minutes
- hard count limit: 1200 evidence records
- oldest records are evicted deterministically

The frontend can only retain evidence that it actually received. If diagnostic sequence numbers show a gap, display an evidence-gap marker. Do not interpolate missing evidence.

## Stage4C evidence selection

Include all `ZERO_EXPORT_*` events.

Include PWM command/ACK evidence only when it is explicitly attributable to Stage4C by `owner=STAGE4C_ZERO_EXPORT`, or when a later PWM event has the same command sequence as an already observed Stage4C command.

Include actuator lifecycle evidence only when its node identity matches the Stage4C actuator identity observed in evidence. Do not infer missing identity.

## Graph requirements

Provide three synchronized time regions:

1. **Canonical P**
   - plot only canonical P values present in `ZERO_EXPORT_DECISION` evidence
   - use measurement `cycle_finished_utc`
   - show configured deadband when evidence provides it
   - show zero line
   - use discrete measured points

2. **PWM duty**
   - show requested duty separately from confirmed actual duty
   - use command UTC for requested points
   - use ACK UTC for confirmed actual points
   - show OFF `0 %` as a distinct physical state from active `5–95 %`
   - expose compare ticks and period ticks in the inspector
   - do not infer watts from duty

3. **Controller events**
   - show decisions, causal boundaries, settling samples, limit states, resolution-limit states, safe blocks, disconnects, and restart/HELLO evidence

No smoothing, averaging, resampling, or hidden interpolation is permitted.

## Inspector

Clicking or hovering near an evidence item must update a read-only inspector.

Show available fields only. Missing optional evidence must display `UNAVAILABLE`.

Where applicable show:

- event UTC
- local browser time
- event sequence
- measurement cycle ID
- source ID and phase
- canonical P
- controller state and reason
- controller action
- requested duty
- confirmed actual duty
- compare ticks
- period ticks
- command sequence
- node ID
- boot ID
- safety confirmation
- monotonic causal/sample timestamps

## Display-only contract

The history module must not import or call any function that can configure, enable, disable, reconnect, apply PWM, or otherwise alter control state.

It may use only read-only evidence retrieval.

No new POST route is permitted for this feature.

## CSS boundary

Use a dedicated structured stylesheet:

`frontend/css/load-control/control-history.css`

Do not place the feature styling in unrelated CSS files.

## Validation

Implementation is accepted only when:

1. new behavior is covered by failing tests before production changes,
2. focused tests pass after each implementation step,
3. full repository acceptance passes,
4. the protected scientific path gate remains clean,
5. repository `testing` remains the only modified remote branch,
6. no version bump is made unless separately approved.
