# ARI Emonio Viewer — Per-Device Acquisition Lifecycle Design

Date: 2026-08-30
Status: DESIGN FOR REVIEW
Baseline: v0.4.13 (`af25c80e0aa82fedb969035fd5c615102dbe874c`)
Target: v0.4.14 Candidate

## 1. Purpose

The viewer must let an operator release one Emonio from one machine without closing the complete viewer.

Field evidence confirmed the problem:

1. Machine A acquired three Emonios.
2. Recording and SCOPE were stopped for `emonio-d08a08` on Machine A.
3. Machine B already knew `emonio-d08a08`, but it received no measurement data.
4. Machine B showed `CONNECTED / EXISTING`.
5. Machine A was closed completely.
6. Machine B received `emonio-d08a08` measurements immediately.

The source confirms two causes.

First, Recording STOP and SCOPE STOP do not stop the canonical Modbus acquisition worker. Machine A keeps the persistent Modbus/TCP acquisition connection until the acquisition coordinator stops.

Second, the current target-connect path returns `already_connected=True` for an existing local device without new live Modbus qualification. Therefore `CONNECTED / EXISTING` does not prove that live measurements exist.

## 2. Required outcome

The selected Emonio gets an explicit per-device acquisition lifecycle.

The operator can:

- disconnect one Emonio;
- keep that Emonio remembered and visible;
- let another machine acquire it;
- reconnect it later without registering it again.

Disconnect must stop active work in this fixed order:

1. Recording.
2. SCOPE.
3. Modbus acquisition.

Reconnect must start measurement acquisition only. It must not restart Recording or SCOPE.

## 3. Protected behavior

This change is a lifecycle-control change. It is not a scientific calculation change.

The implementation must not change:

- Modbus read-only function-code restriction;
- register map or register addresses;
- measurement decoding;
- canonical A/B/C/TOTAL measurement structure;
- P/Q signs;
- quadrant classification;
- flow classification;
- validation tolerances;
- fixed-deadline scheduling of an active worker;
- exact measurement timestamps;
- SCOPE waveform semantics;
- CSV value precision;
- recording-point eligibility;
- recording boundary calculation;
- recording failure-state integrity;
- EventBus measurement publication semantics.

No Modbus write operation is permitted.

## 4. Two separate state concepts

The viewer must not use one state word for two different facts.

### 4.1 Acquisition lifecycle

This state answers: **Is this viewer running acquisition ownership for this Emonio?**

Required states:

- `RUNNING` — the per-device acquisition worker is active. Its transport can be connected or retrying.
- `DISCONNECTING` — controlled shutdown is in progress.
- `DISCONNECTED` — no per-device worker is running and the Modbus socket is closed.
- `CONNECTING` — operator-requested reconnect qualification is in progress.
- `ERROR` — disconnect failed and the viewer cannot prove that acquisition was released.

`ERROR` is not used for a normal reconnect qualification failure. If reconnect qualification fails and the candidate client is closed, the safe final state is `DISCONNECTED` with failure detail. The operator can retry.

### 4.2 Measurement health

The existing `RuntimeStore` and `DeviceStateMachine` remain the authority for measurement health, including:

- `CONNECTING`;
- `ONLINE`;
- `DEGRADED`;
- `STALE`;
- `OFFLINE`.

A device can therefore be acquisition `RUNNING` while measurement health is `OFFLINE`.

A disconnected device can keep its last exact sample for reference. The UI must make clear that this sample is not live.

The per-device disconnect feature must not reset the existing measurement-health state machine.

## 5. AcquisitionCoordinator responsibility

`AcquisitionCoordinator` remains the owner of Modbus workers and Modbus clients.

It must gain per-device lifecycle control.

The coordinator must be able to:

- report lifecycle state for one device;
- stop one worker only;
- close one Modbus client only;
- join one worker thread only;
- prove that the selected worker is no longer alive;
- keep the `DeviceConfig` registered after disconnect;
- create a fresh worker/client for reconnect;
- preserve cycle-ID continuity;
- keep the current complete-viewer `stop()` behavior.

The current single global stop event is not sufficient. Each running device needs independent stop control. Global shutdown can still stop all per-device workers.

A disconnected device must remain in `device_configs()`.

## 6. Backend lifecycle orchestration

A small backend lifecycle service must coordinate cross-subsystem actions.

It depends on:

- `RecordingManager`;
- `ScopeService`;
- `AcquisitionCoordinator`.

The service must not contain measurement decoding, validation, sign logic, quadrant logic, or recording mathematics.

The frontend sends one lifecycle command. The backend is the authority for the sequence.

This prevents browser timing or refresh behavior from changing the shutdown order.

## 7. DISCONNECT EMONIO sequence

For one selected device, the backend must do this:

1. Check whether Recording is active.
2. If active, call the existing normal Recording stop path.
3. Confirm that Recording stop returned successfully.
4. Call the existing normal SCOPE stop path. This call can be idempotent when no SCOPE session exists.
5. Set acquisition lifecycle to `DISCONNECTING`.
6. Signal only this device worker to stop.
7. Close only this device Modbus client so a blocking read can terminate.
8. Join only this device worker thread.
9. Verify that the thread is not alive.
10. Set lifecycle to `DISCONNECTED`.
11. Return the exact final subsystem states to the UI.

The device stays remembered and stays visible in the selector.

Other Emonios must continue their own acquisition, Recording, and SCOPE operation without lifecycle changes.

## 8. Disconnect failure rules

The sequence is one-way. There is no automatic rollback.

### Recording stop failure

If Recording stop fails:

- do not stop SCOPE;
- do not stop acquisition;
- do not report `DISCONNECTED`;
- report failed stage `RECORDING`.

### SCOPE stop failure

If Recording stopped but SCOPE stop fails:

- Recording remains stopped;
- do not stop acquisition;
- do not report `DISCONNECTED`;
- report failed stage `SCOPE`.

### Acquisition stop failure

If Recording and SCOPE stopped but acquisition shutdown cannot prove worker termination:

- Recording remains stopped;
- SCOPE remains stopped;
- report failed stage `ACQUISITION`;
- set acquisition lifecycle to `ERROR`;
- include exact diagnostic detail;
- do not allow normal reconnect while the old worker can still be alive.

The software must never report `DISCONNECTED` until the worker is terminated and the Modbus client is closed.

## 9. RECONNECT EMONIO sequence

Reconnect is acquisition-only.

The backend must:

1. Require acquisition lifecycle `DISCONNECTED`.
2. Set lifecycle to `CONNECTING`.
3. Create a fresh read-only Modbus client from remembered `DeviceConfig`.
4. Create a fresh canonical `AcquisitionWorker`.
5. Use the existing worker read path for one complete qualification sample.
6. Use the next cycle ID after the last published cycle ID.
7. If qualification succeeds, publish that exact sample through the existing RuntimeStore/EventBus path.
8. Start normal fixed-deadline acquisition from the qualified cycle ID.
9. Set lifecycle to `RUNNING`.

The next continuous sample must use the next cycle ID after the qualification sample.

Reconnect must not:

- restart Recording;
- restart SCOPE;
- restore an old Recording session;
- reuse SCOPE credentials;
- create a synthetic history point;
- reset cycle IDs;
- change another Emonio.

### Reconnect qualification failure

If qualification fails:

- close the candidate Modbus client;
- do not start a worker thread;
- do not publish a synthetic sample;
- do not start Recording or SCOPE;
- return exact connection-failure detail;
- return lifecycle to `DISCONNECTED`;
- keep the device available for another reconnect attempt.

## 10. Existing target behavior

`CONNECTED / EXISTING` must be removed because it can report a live connection without live evidence.

For an existing local target, the API and UI must expose both:

- acquisition lifecycle;
- measurement health.

Acceptable operator messages include:

- `EXISTING / ONLINE`;
- `EXISTING / OFFLINE`;
- `EXISTING / DISCONNECTED`;
- `CONNECTING`;
- `CONNECTION FAILED`.

The implementation must not show `CONNECTED` only because a configuration entry exists.

If an existing device is acquisition `RUNNING`, target-connect must not create a second worker.

If an existing device is `DISCONNECTED`, the operator must be able to reconnect it without registering it again.

## 11. API surface

Preferred new commands:

- `POST /api/v1/devices/{device_id}/disconnect`
- `POST /api/v1/devices/{device_id}/reconnect`

Device read APIs must add acquisition lifecycle as an additive field. Existing measurement fields keep their current meaning.

Lifecycle responses must include at least:

- `device_id`;
- `acquisition_state`;
- `measurement_state` when available;
- `recording_state`;
- `scope_state`;
- `failed_stage` when applicable;
- `detail` when applicable.

A failure response must show partial completion. Example: if Recording stopped and SCOPE stop failed, the response must show Recording stopped and `failed_stage: SCOPE`.

## 12. Recording integrity

The lifecycle service must use the existing `RecordingManager.stop(device_id)` behavior.

It must not create another recording-close implementation.

Existing writer close, final metadata, missed-point accounting, and failure semantics remain authoritative.

A disconnect-triggered Recording stop must produce the same valid final artifacts as an explicit Recording STOP.

## 13. SCOPE integrity

The lifecycle service must use the existing `ScopeService.stop(device_id)` behavior.

It must not create another SCOPE cleanup path.

Existing task cancellation and client cleanup remain authoritative.

After reconnect, SCOPE remains stopped until the operator explicitly starts it.

## 14. Diagnostics and counters

Disconnect/reconnect must not reset existing counters without explicit reason.

Required behavior:

- valid-cycle count does not reset;
- invalid-cycle count does not reset;
- latency evidence is not replaced by synthetic values;
- last exact sample remains available;
- reconnect diagnostics do not decrease when a fresh client object is created.

If intentional per-device reacquisition is counted as a reconnect, it must increment the existing reconnect diagnostic exactly once. This behavior must have an explicit test.

## 15. Frontend behavior

A disconnected remembered Emonio remains visible in the selector.

The selected-device lifecycle control must show:

- `DISCONNECT EMONIO` for acquisition `RUNNING`;
- `RECONNECT EMONIO` for acquisition `DISCONNECTED`.

During `DISCONNECTING` and `CONNECTING`, duplicate lifecycle actions are disabled.

For lifecycle `ERROR`, the UI must show the failure detail and must not offer a normal reconnect if the backend cannot prove that the old worker is terminated.

Acquisition lifecycle and measurement health must be shown as separate facts.

The Recording and SCOPE panels must update from backend-confirmed state after disconnect. The frontend must not invent a local success state before the backend returns success.

The last measurement may remain visible after disconnect, but lifecycle state and sample age must make clear that it is not live.

## 16. Concurrency rules

Lifecycle commands for the same device must be serialized.

The implementation must prevent:

- two simultaneous disconnect commands for one device;
- disconnect and reconnect at the same time for one device;
- a second worker while the first worker is alive;
- reconnect after a failed disconnect when worker termination is not proven.

Commands for different devices remain independent.

Disconnecting `emonio-d08a08` must not stop or restart another device worker.

## 17. Complete viewer shutdown

Global shutdown must remain safe.

It must still cleanly handle:

- active recordings;
- active SCOPE sessions;
- all running acquisition workers;
- all open clients;
- service threads.

A device that is already `DISCONNECTED` must not make global shutdown fail only because it has no active worker thread.

Per-device lifecycle support must not weaken the existing shutdown contract.

## 18. TDD requirements

Implementation must use test-driven development.

### Coordinator tests

- disconnect one of three workers and keep the other two alive;
- close only the selected client;
- terminate only the selected thread;
- keep selected `DeviceConfig` registered;
- reconnect with a fresh worker/client;
- preserve cycle-ID continuity;
- prevent duplicate worker start;
- keep global stop correct with a mix of running and disconnected devices.

### Lifecycle-service tests

- Recording stops before SCOPE;
- SCOPE stops before acquisition;
- no-active-Recording is valid;
- no-active-SCOPE is valid;
- Recording failure blocks later steps;
- SCOPE failure blocks acquisition stop;
- acquisition failure reports partial completion and does not claim `DISCONNECTED`;
- reconnect does not restart Recording;
- reconnect does not restart SCOPE;
- reconnect qualification failure returns safely to `DISCONNECTED`.

### API tests

- disconnect returns structured final state;
- reconnect returns structured final state;
- existing target no longer gives false live-connected status;
- device reads expose acquisition lifecycle additively;
- unknown device behavior remains correct.

### Frontend tests

- disconnected device remains visible;
- control changes between DISCONNECT and RECONNECT;
- transition states prevent duplicate commands;
- `CONNECTED / EXISTING` is removed;
- existing offline device is not shown as live-connected;
- Recording and SCOPE views refresh from backend state.

### Full regression

The complete existing acceptance suite must pass:

- unit;
- integration;
- frontend/browser;
- read-only source gate;
- Python compilation;
- scientific sign path.

The implementation must also pass deterministic release-package verification and produce a new SHA-256.

## 19. Two-machine field acceptance

Final trust requires this real workflow:

1. Machine A acquires all three Emonios.
2. Machine B also knows all three Emonios.
3. Start Recording and SCOPE for `emonio-d08a08` on Machine A.
4. Press `DISCONNECT EMONIO` for `emonio-d08a08` on Machine A.
5. Confirm Recording closes cleanly.
6. Confirm SCOPE stops cleanly.
7. Confirm Machine A keeps `emonio-d08a08` visible as `DISCONNECTED`.
8. Confirm the other two Machine A Emonios continue without interruption.
9. Confirm Machine B begins receiving `emonio-d08a08` measurements without closing Machine A.
10. Release `emonio-d08a08` from Machine B for the return test.
11. Press `RECONNECT EMONIO` on Machine A.
12. Confirm canonical measurement resumes.
13. Confirm Recording remains stopped.
14. Confirm SCOPE remains stopped.
15. Confirm no cycle-ID reset or synthetic history sample appears.

Only after this workflow passes can v0.4.14 Candidate become the trusted baseline.

## 20. Non-goals

This change does not add:

- cross-machine automatic arbitration;
- discovery of which computer owns an Emonio;
- distributed locks;
- automatic Recording restart;
- automatic SCOPE restart;
- credential reuse;
- history synchronization between computers;
- interpolation or gap filling;
- Emonio firmware changes;
- Modbus writes.

The Emonio remains the external authority that determines when another TCP client can acquire it after the first viewer releases its connection.

## 21. Reversibility and Git safety

All implementation work must stay on `feature/v0.4.14-device-acquisition-lifecycle` until field acceptance.

`main` must remain unchanged until:

- implementation is complete;
- automated acceptance passes;
- deterministic package verification passes;
- the two-machine field workflow passes;
- the operator explicitly approves integration.

Trusted v0.4.13 remains the stable baseline during development.
