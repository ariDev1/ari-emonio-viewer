# Stage4C Control History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, read-only Stage4C Control History that exposes canonical P, controller decisions, PWM command/ACK evidence, causal ordering, and safety/lifecycle events over time.

**Architecture:** Extend the existing shared bounded `LoadControlDiagnosticLog` with structured observational evidence. Do not add a second backend history store. Build a separate frontend-only 10-minute/1200-record control-history cache that consumes the existing diagnostics GET route and cannot issue commands.

**Tech Stack:** Python 3.12, aiohttp, pytest 8.4.1, browser ES modules, Node-based frontend contract/math tests, structured CSS.

**Spec:** `docs/superpowers/specs/2026-09-07-stage4c-control-history.md`

## Global Constraints

- Work only on repository `ariDev1/ari-emonio-viewer`, branch `testing`.
- Approved baseline before design docs: `2a54d0194ee21c9db39137495378ec523a702d3f`.
- Keep version `0.4.25` unless separately approved.
- Do not modify protected acquisition, measurement, Modbus, runtime event/store, SCOPE, recording, canonical sign, or quadrant paths.
- No new control authority and no new POST route.
- Canonical P is copied from Stage4C evidence; never recalculate it for history.
- Preserve UTC and monotonic timestamp domains without fabricated conversion.
- Use test-first red/green cycles.

---

### Task 1: Preserve structured diagnostic evidence

**Files:**
- Modify: `tests/unit/test_load_control_diagnostic_log.py`
- Modify: `tests/integration/test_load_control_stage2_api.py`
- Modify: `src/emonio_viewer/load_control/diagnostic_log.py`
- Modify: `src/emonio_viewer/server/load_control_api.py`

**Interfaces:**
- Produces: `DiagnosticEvent.fields: tuple[tuple[str, object], ...]`.
- Produces: diagnostics JSON event property `fields` as a JSON object.
- Preserves: `sequence`, `utc`, `event`, and `line` exactly as before.

- [ ] **Step 1: Write failing unit tests**

Add assertions that a diagnostic event retains ordered structured fields while preserving the exact existing `line`.

```python
assert event.fields == (
    ("protocol", 1),
    ("device_class", "ARI_LOAD_ACTUATOR"),
    ("capability", "ACTIVE_LOAD_CONTROL"),
)
```

Also prove bounded eviction and sequence behavior remain unchanged.

- [ ] **Step 2: Write failing API test**

Assert `/api/v1/load-control/lan-diagnostics/log` returns:

```python
{
    "sequence": 1,
    "utc": "...Z",
    "event": "...",
    "line": "...",
    "fields": {"key": "value"},
}
```

- [ ] **Step 3: Run focused tests and verify RED**

Run the existing GitHub `testing` acceptance workflow on the test-only commit. Expected: FAIL because `DiagnosticEvent.fields` and API `fields` do not exist.

- [ ] **Step 4: Implement minimal structured retention**

In `DiagnosticEvent`, add immutable ordered fields:

```python
fields: tuple[tuple[str, object], ...]
```

In `append()`, build one tuple from existing validated kwargs and use the same values for the existing line formatter.

In `_diagnostic_event_json()`, add:

```python
"fields": dict(item.fields),
```

Do not change formatting, validation, sequence, UTC, or deque size.

- [ ] **Step 5: Verify GREEN**

Run focused tests, then the full repository acceptance workflow.

---

### Task 2: Attribute Stage4C PWM command and ACK evidence

**Files:**
- Modify: `tests/unit/test_load_control_manual_pwm.py`
- Modify: `src/emonio_viewer/load_control/manual_pwm.py`

**Interfaces:**
- Consumes: existing `owner` argument to `_run_pwm()` / `run_reserved_pwm()`.
- Produces: `owner` field on `PWM_COMMAND_SENT` and `PWM_ACK_QUALIFIED`.

- [ ] **Step 1: Write failing tests**

For a reserved command, assert the diagnostic sequence includes:

```python
("PWM_COMMAND_SENT", {"owner": "STAGE4C_ZERO_EXPORT", ...})
("PWM_ACK_QUALIFIED", {"owner": "STAGE4C_ZERO_EXPORT", ...})
```

For an operator/manual command, assert `owner` is `None`.

- [ ] **Step 2: Verify RED**

Run the focused unit test on the test-only commit. Expected: FAIL because current PWM diagnostics do not expose owner.

- [ ] **Step 3: Implement minimal owner threading**

Pass `owner` into `_wait_for_pwm_ack()` and append it to only the existing command-sent and qualified-ACK diagnostic events.

Do not change ownership checks, sequence allocation, command frames, ACK qualification, or actuator behavior.

- [ ] **Step 4: Verify GREEN**

Run focused unit tests and full acceptance.

---

### Task 3: Add Stage4C causal, settling, and decision timing evidence

**Files:**
- Modify: `tests/unit/test_load_control_stage4c_service.py`
- Modify: `tests/unit/test_load_control_stage4c_resolution_heartbeat.py`
- Modify: `tests/unit/test_load_control_stage4c_authority_limits.py`
- Modify: `src/emonio_viewer/load_control/zero_export_service.py`

**Interfaces:**
- Produces event: `ZERO_EXPORT_CAUSAL_BOUNDARY_ARMED`.
- Produces event: `ZERO_EXPORT_SETTLING_SAMPLE`.
- Extends event: `ZERO_EXPORT_DECISION` with exact sample timing and resulting state/reason.

- [ ] **Step 1: Write failing causal-boundary test**

After a qualified PWM ACK, assert evidence contains:

```python
ZERO_EXPORT_CAUSAL_BOUNDARY_ARMED
```

with existing monotonic `causal_after_ns`, `freshness_deadline_ns`, source, phase, command sequence, and `WAITING_FOR_SAMPLE` state.

- [ ] **Step 2: Write failing settling-sample test**

For the first accepted post-ACK sample, assert:

```python
ZERO_EXPORT_SETTLING_SAMPLE
```

contains the real sample cycle ID, `cycle_finished_utc`, `cycle_finished_monotonic_ns`, source, phase, and `SETTLING` state. Assert no `ZERO_EXPORT_DECISION` is produced for that same cycle.

- [ ] **Step 3: Write failing decision-evidence test**

For the next causal valid sample, assert `ZERO_EXPORT_DECISION` preserves:

```python
cycle_id
cycle_finished_utc
cycle_finished_monotonic_ns
measured_p_w
controller_state
reason
```

Assert `measured_p_w` equals the selected phase P already consumed by Stage4C.

Cover HOLD/TARGET_BAND, LIMIT_LOW, LIMIT_HIGH, and normal controlling decisions so state evidence is not inferred by the frontend.

- [ ] **Step 4: Verify RED**

Run focused Stage4C tests. Expected: FAIL because the new observational fields/events do not exist.

- [ ] **Step 5: Implement minimal observational logging**

Append causal-boundary evidence inside `_arm_after_ack()` after the existing state becomes `WAITING_FOR_SAMPLE`.

Append settling evidence only inside the existing `_settling_pending` branch after the state becomes `SETTLING`.

For decision evidence, set the already-determined controller state before logging and include the exact sample UTC/monotonic finish timestamps plus `controller_state` and `reason`.

Do not change `calculate_zero_export_step()`, timing thresholds, stale handling, authority limits, or command decisions.

- [ ] **Step 6: Verify GREEN**

Run focused Stage4C tests and full acceptance.

---

### Task 4: Build pure read-only control-history model

**Files:**
- Create: `tests/browser/test_load_control_stage4c_history_math.py`
- Create: `frontend/js/load-control-stage4c-history.js`

**Interfaces:**
- Consumes: `getLanDiagnosticLog(afterSequence, limit)` only.
- Produces: `Stage4CControlHistory`.
- Produces: `eventTimestampMs(event)`.
- Produces: `nearestControlHistoryItem(items, timestampMs)`.
- Produces: filtered immutable evidence records for rendering.

- [ ] **Step 1: Write failing history-model tests**

Test all of the following with Node-imported ES module functions:

- only `ZERO_EXPORT_*` events are directly included,
- PWM events require explicit `owner=STAGE4C_ZERO_EXPORT` or a previously observed matching Stage4C command sequence,
- lifecycle events require matching observed Stage4C actuator node identity,
- measurement events use exact `cycle_finished_utc`,
- command/ACK events use diagnostic UTC,
- a sequence jump creates an evidence-gap record,
- records older than 10 minutes are evicted,
- record count never exceeds 1200,
- nearest selection is deterministic,
- `0 %` remains an explicit OFF state and is not treated as active 5 % duty,
- missing optional fields remain `null`/unavailable and are not synthesized.

- [ ] **Step 2: Verify RED**

Expected: FAIL because the history module does not exist.

- [ ] **Step 3: Implement minimal pure model**

Create a model with constants:

```javascript
export const CONTROL_HISTORY_WINDOW_MS = 10 * 60 * 1000;
export const CONTROL_HISTORY_MAX_RECORDS = 1200;
export const STAGE4C_PWM_OWNER = "STAGE4C_ZERO_EXPORT";
```

The model stores only received evidence. It does not fetch measurements, recalculate P, or call any control function.

- [ ] **Step 4: Verify GREEN**

Run the new browser math tests and existing Stage4C frontend tests.

---

### Task 5: Render synchronized Stage4C Control History and inspector

**Files:**
- Create: `tests/browser/test_load_control_stage4c_history_contract.py`
- Create: `frontend/css/load-control/control-history.css`
- Modify: `frontend/js/load-control-stage4c-history.js`
- Modify: `src/emonio_viewer/server/app_v0416.py`

**Interfaces:**
- Consumes: pure history records from Task 4.
- Produces: display-only Stage4C history section under the existing zero-export controller.

- [ ] **Step 1: Write failing frontend contract tests**

Require:

- title `Stage4C Control History`,
- explicit `READ-ONLY CONTROL EVIDENCE · NO CONTROL AUTHORITY`,
- synchronized P, duty, and event SVG regions,
- separate requested and confirmed-actual duty series,
- explicit OFF state semantics,
- UTC and local-time inspector fields,
- cycle ID, canonical P, controller state/reason/action, requested duty, actual duty, compare/period ticks, command sequence, node/boot ID, and safety fields,
- `UNAVAILABLE` for missing optional evidence,
- evidence-gap display,
- dedicated `control-history.css`,
- no imports/calls to configure, enable, disable, reconnect, manual PWM, POST, or other control actions.

- [ ] **Step 2: Verify RED**

Expected: FAIL because the rendered history UI and stylesheet do not exist.

- [ ] **Step 3: Implement minimal rendering**

Use three SVGs with one shared time-domain calculation:

- P: discrete canonical P points and zero/deadband guides only.
- Duty: discrete requested and ACK-confirmed actual points; OFF uses a distinct class/shape.
- Events: vertical/point markers by evidence type.

Do not smooth, average, resample, or interpolate data.

Hover/click uses `nearestControlHistoryItem()` and updates one inspector.

Poll only `getLanDiagnosticLog()` and append new sequence values.

- [ ] **Step 4: Load dedicated assets**

In `app_v0416.py`, inject `control-history.css` and the history ES module after the existing Stage4C assets.

Do not change base `app.py` or protected paths.

- [ ] **Step 5: Verify GREEN**

Run focused browser tests, then full acceptance.

---

### Task 6: Final scientific verification

**Files:**
- No production-file changes expected.

- [ ] **Step 1: Run full repository acceptance**

Run:

```bash
./tools/ari-emonio-acceptance.sh
```

Expected: all suites PASS.

- [ ] **Step 2: Verify protected scientific path**

Run the same protected-path diff gate used by `.github/workflows/testing-acceptance.yml` against `b539efe7eb3a11d53a3b291254ddd0c50a2cf3df`.

Expected: no diff in protected paths.

- [ ] **Step 3: Verify branch and version**

Confirm remote changes exist only on `testing` and `pyproject.toml` remains version `0.4.25`.

- [ ] **Step 4: Review evidence semantics**

Confirm no watts-from-duty inference, no P recalculation, no artificial UTC conversion from monotonic timestamps, and no new control/reconnect authority.
