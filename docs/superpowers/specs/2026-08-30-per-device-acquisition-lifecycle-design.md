# ARI Emonio Viewer — Per-Device Acquisition Lifecycle Design

Date: 2026-08-30
Status: DESIGN FOR REVIEW
Baseline: v0.4.13 (`af25c80e0aa82fedb969035fd5c615102dbe874c`)
Target development version: v0.4.14 Candidate

## 1. Purpose

The viewer must let an operator release one Emonio from one machine without closing the complete viewer.

This is required for a multi-machine workflow.

Field evidence confirmed this behavior:

1. Machine A acquired three Emonios.
2. Recording and SCOPE were stopped for `emonio-d08a08` on Machine A.
3. Machine B already knew `emonio-d08a08`, but it did not receive measurement data.
4. Machine B showed `CONNECTED / EXISTING`.
5. Machine A was then closed completely.
6. Machine B received `emonio-d08a08` measurements immediately.

The root cause is that Recording STOP and SCOPE STOP do not stop the canonical Modbus acquisition worker. Machine A keeps the persistent Modbus/TCP acquisition connection until the complete acquisition coordinator stops.

A second defect is also confirmed in the source: for an already registered target, the current connect path returns `already_connected=True` without a new live Modbus qualification. Therefore `CONNECTED / EXISTING` does not prove that live measurement data exists.

## 2. Design principles

The change must preserve the trusted v0.4.13 measurement architecture.

The implementation must be:

- deterministic;
- per-device;
- measurable;
- reversible;
- read-only at the Emonio protocol level;
- explicit in the UI;
- isolated from scientific measurement calculations.

The implementation must not restart or disturb other Emonios when one Emonio is disconnected or reconnected.

## 3. Protected behavior

The following behavior must not change:

- Modbus read-only function-code restriction;
- register map and register addresses;
- measurement decoding;
- canonical A/B/C/TOTAL measurement structure;
- P/Q sign handling;
- quadrant classification;
- flow classification;
- validation tolerances;
- fixed-deadline acquisition scheduling for an active worker;
- exact measurement timestamps;
- SCOPE waveform acquisition semantics;
- CSV value precision;
- recording-point eligibility;
- recording boundary calculation;
- recording failure-state integrity;
- EventBus measurement publication semantics.

The change is a lifecycle-control change. It is not a scientific calculation change.

## 4. Separate acquisition lifecycle from measurement health

The viewer must not use one word such as `CONNECTED` for two different facts.

The implementation must keep two separate state concepts.

### 4.1 Acquisition lifecycle

This state answers: **Is this viewer actively owning and running acquisition for this Emonio?**

Required states:

- `RUNNING` — the per-device acquisition worker is active. The worker can have a live socket or can be retrying after a transport failure.
- `DISCONNECTING` — a controlled per-device shutdown is in progress.
- `DISCONNECTED` — the per-device acquisition worker is not running and its Modbus socket is closed.
- `CONNECTING` — an operator-requested reconnect qualification is in progress.
- `ERROR` — the requested lifecycle transition failed and the viewer cannot claim the requested final state.

`RUNNING` does not mean that the Emonio currently produces valid samples. Measurement health must remain separate.

### 4.2 Measurement health

The existing `RuntimeStore` / `DeviceStateMachine` remains the authority for measurement health:

- `CONNECTING`
- `ONLINE`
- `DEGRADED`
- `STALE`
- `OFFLINE`
- existing startup/stop states where applicable

A device can therefore be:

- acquisition `RUNNING` + measurement `ONLINE`;
- acquisition `RUNNING` + measurement `OFFLINE`;
- acquisition `DISCONNECTED` + an exact last sample retained for reference.

The implementation must not erase the last exact sample when an operator disconnects a device. The UI must make clear that the sample is not live.

## 5. Per-device acquisition ownership

`AcquisitionCoordinator` remains the owner of Modbus acquisition workers and Modbus clients.

It must gain a real per-device lifecycle.

The coordinator must be able to:

- query the acquisition lifecycle of one device;
- stop one worker without stopping other workers;
- close one worker's Modbus client;
- verify that one worker thread terminated;
- keep the device configuration registered after disconnect;
- create a fresh acquisition worker and client for reconnect;
- preserve cycle-ID continuity from the last published sample;
- keep the current global `stop()` behavior for complete viewer shutdown.

The existing single global stop event is not sufficient for this requirement. Each active device needs independent stop control. Global shutdown can still stop all per-device workers.

The coordinator must not remove a disconnected device from its configuration list.

## 6. Controlled DISCONNECT sequence

The operator command `DISCONNECT EMONIO` must use one deterministic sequence for the selected device.

The sequence is:

1. Detect whether Recording is active for the device.
2. If Recording is active, stop it by using the existing normal Recording stop path.
3. Confirm that the recording session is closed and its final session metadata was written.
4. Stop the SCOPE session for the device by using the existing normal SCOPE stop path. SCOPE stop is allowed to be idempotent when no session exists.
5. Request stop of only that device's acquisition worker.
6. Close only that device's Modbus/TCP client so that a blocking read can terminate.
7. Join only that device's acquisition thread.
8. Confirm that the thread is not alive.
9. Confirm that the coordinator lifecycle state is `DISCONNECTED`.
10. Return the final structured state to the UI.

The device remains remembered and remains visible in the device selector.

No other device worker, recording session, SCOPE session, history, or socket may be changed.

## 7. Disconnect failure rules

The sequence is one-way. There is no automatic rollback.

If Recording stop fails:

- SCOPE stop must not start;
- acquisition disconnect must not start;
- the device must not be reported as `DISCONNECTED`;
- the response must identify `RECORDING` as the failed stage.

If Recording stop succeeds but SCOPE stop fails:

- Recording remains stopped;
- acquisition disconnect must not start;
- the device must not be reported as `DISCONNECTED`;
- the response must identify `SCOPE` as the failed stage.

If Recording and SCOPE stop successfully but acquisition shutdown fails:

- Recording remains stopped;
- SCOPE remains stopped;
- the device must not be reported as `DISCONNECTED`;
- the response must identify `ACQUISITION` as the failed stage;
- the acquisition lifecycle must expose `ERROR` plus a diagnostic detail.

The software must never report `DISCONNECTED` before the worker is terminated and the Modbus client is closed.

## 8. RECONNECT behavior

Reconnect is acquisition-only.

Reconnect must not:

- restart Recording;
- restart SCOPE;
- restore a prior recording interval as an active recording command;
- restore SCOPE credentials;
- modify another Emonio.

The reconnect sequence is:

1. Require acquisition lifecycle `DISCONNECTED`.
2. Set acquisition lifecycle to `CONNECTING`.
3. Create a fresh read-only Modbus client and acquisition worker from the remembered `DeviceConfig`.
4. Use the existing canonical acquisition worker read path to obtain one complete qualification sample.
5. Use the next cycle ID after the last published cycle ID for this device.
6. If qualification succeeds, publish that exact sample by the existing store/EventBus path.
7. Start the normal fixed-deadline worker from the qualified cycle ID so that the next continuous sample uses the next cycle ID.
8. Set acquisition lifecycle to `RUNNING`.

If qualification fails:

- close the candidate client;
- do not start a worker thread;
- do not publish a synthetic sample;
- do not change Recording or SCOPE;
- return a connection failure with exact failure detail;
- leave the device safely reconnectable.

No interpolation, gap filling, sample synthesis, cycle-ID reset, or sign correction is permitted.

## 9. Existing target behavior

The current `CONNECTED / EXISTING` result is not scientifically sufficient and must be removed.

When the operator enters a target that already exists locally, the viewer must not claim a successful live connection only because the target is registered.

The response must expose both:

- acquisition lifecycle;
- measurement health / live-data state.

Examples of valid operator messages are:

- `EXISTING / ONLINE`
- `EXISTING / OFFLINE`
- `EXISTING / DISCONNECTED`
- `CONNECTING`
- `CONNECTION FAILED`

The exact UI text can be finalized during implementation, but it must not use `CONNECTED` unless the displayed evidence actually supports that statement.

For an already registered device whose acquisition lifecycle is `RUNNING`, the target-connect action must not create a second worker.

For an already registered device whose acquisition lifecycle is `DISCONNECTED`, the operator should be able to reconnect it without registering it again.

## 10. API design

Add explicit per-device lifecycle commands. The preferred API surface is:

- `POST /api/v1/devices/{device_id}/disconnect`
- `POST /api/v1/devices/{device_id}/reconnect`

Read APIs that report devices must add acquisition lifecycle as an additive field. Existing measurement fields must keep their current meaning.

Lifecycle command responses must be structured. They must include at least:

- `device_id`;
- `acquisition_state`;
- `measurement_state` when available;
- `recording_state`;
- `scope_state`;
- `failed_stage` when a command fails;
- failure `detail` when a command fails.

HTTP failure responses must not hide partial completion. Example: if Recording stopped but SCOPE stop failed, the response must show that Recording is stopped and that the failed stage is SCOPE.

## 11. Orchestration boundary

The acquisition coordinator must own only acquisition worker/client lifecycle.

A small lifecycle orchestration service should coordinate the cross-subsystem disconnect sequence:

- RecordingManager;
- ScopeService;
- AcquisitionCoordinator.

This service must not contain measurement decoding or scientific calculations.

The HTTP API should call this service instead of duplicating shutdown sequencing in frontend code.

The frontend must send one disconnect command. The backend is the authority for the shutdown sequence.

This prevents a browser refresh, network delay, or frontend race from changing the required order.

## 12. Recording requirements

The lifecycle service must use the existing `RecordingManager.stop(device_id)` behavior.

It must not implement a second recording-close path.

Existing final metadata generation, writer close, missed-point accounting, and failure behavior remain authoritative.

A successful device disconnect with an active recording must therefore produce the same valid final recording artifacts as an explicit operator Recording STOP.

## 13. SCOPE requirements

The lifecycle service must use the existing asynchronous `ScopeService.stop(device_id)` behavior.

It must not implement a second SCOPE transport-close path.

The existing SCOPE task cancellation and client cleanup remain authoritative.

After reconnect, SCOPE remains disconnected until the operator explicitly starts it again.

## 14. Diagnostics and counters

Per-device disconnect/reconnect must not reset existing scientific or diagnostic counters without explicit reason.

In particular:

- valid-cycle count must not reset;
- invalid-cycle count must not reset;
- latency history must not be replaced by synthetic values;
- the last exact sample must remain available;
- reconnect diagnostics must not decrease when a new client object is created.

If an intentional acquisition reconnect is counted as a reconnect, it must increment the existing reconnect diagnostic exactly once. The implementation must test and document this behavior.

## 15. Frontend behavior

A remembered disconnected Emonio remains visible in the device selector.

The selected-device controls must provide an explicit lifecycle action:

- `DISCONNECT EMONIO` while acquisition is running;
- `RECONNECT EMONIO` while acquisition is disconnected.

During `DISCONNECTING` or `CONNECTING`, lifecycle controls must be disabled to prevent duplicate commands.

The UI must show the acquisition lifecycle separately from measurement health.

If a disconnect command stops Recording automatically, the Recording panel must update from the backend result and normal status refresh. It must not fabricate a local stopped state before backend confirmation.

If a disconnect command stops SCOPE automatically, the SCOPE panel must update from backend state in the same way.

The last measurement can remain visible after disconnect, but it must be clearly identified as non-live through lifecycle/health status and sample age.

## 16. Concurrency rules

Per-device lifecycle commands must be serialized for the same device.

The software must prevent these races:

- two simultaneous disconnect commands for one device;
- disconnect and reconnect at the same time for one device;
- a second worker start while the first worker is still alive;
- reconnect while a previous disconnect cannot prove thread termination.

Commands for different devices must remain independent.

Disconnecting `emonio-d08a08` must not block normal acquisition for the other Emonios except for normal short Python scheduling effects.

## 17. Shutdown behavior

Complete viewer shutdown must remain safe.

Global shutdown must still:

- disable new recording commands as currently required;
- stop/finalize active recordings;
- stop SCOPE sessions;
- stop all acquisition workers;
- close all clients;
- join all non-daemon service threads according to the existing shutdown contract.

Per-device lifecycle support must not weaken this path.

A device that is already `DISCONNECTED` must not cause global shutdown to fail only because no worker thread exists for it.

## 18. Test requirements

Implementation must use TDD.

Minimum new tests:

### Coordinator tests

- disconnect one of three workers and verify the other two stay alive;
- verify only the selected Modbus client is closed;
- verify selected worker thread terminates;
- verify device configuration remains registered;
- verify reconnect creates a fresh worker/client;
- verify cycle-ID continuity across disconnect/reconnect;
- verify no second worker can start for the same device;
- verify global stop still stops all running workers and tolerates already disconnected devices.

### Lifecycle orchestration tests

- active Recording is stopped before SCOPE;
- SCOPE is stopped before acquisition;
- no-active-recording case is valid;
- no-active-SCOPE case is valid;
- Recording-stop failure prevents later stages;
- SCOPE-stop failure prevents acquisition stop;
- acquisition-stop failure reports partial completion and does not claim `DISCONNECTED`;
- reconnect does not restart Recording;
- reconnect does not restart SCOPE.

### API tests

- disconnect endpoint returns structured final state;
- reconnect endpoint returns structured final state;
- existing target no longer returns a false live-connected claim;
- device read APIs expose acquisition lifecycle additively;
- unknown device IDs return the existing appropriate error class.

### Frontend tests

- disconnected device remains in selector;
- control label changes between DISCONNECT and RECONNECT;
- transition states disable duplicate commands;
- `CONNECTED / EXISTING` wording is removed;
- offline existing device is not presented as live-connected;
- Recording and SCOPE panels refresh from backend state after disconnect.

### Regression and acceptance

The complete existing acceptance suite must pass.

Protected scientific-sign tests, read-only gate, compilation, unit, integration, and frontend/browser suites must all pass.

A deterministic candidate ZIP and SHA-256 must be produced after implementation.

## 19. Field acceptance

Software tests are not sufficient for final trust.

Required field acceptance with two machines:

1. Machine A runs acquisition for all three Emonios.
2. Machine B also knows all three Emonios.
3. Start Recording and SCOPE for `emonio-d08a08` on Machine A.
4. Press `DISCONNECT EMONIO` for `emonio-d08a08` on Machine A.
5. Confirm Recording closes cleanly on Machine A.
6. Confirm SCOPE stops cleanly on Machine A.
7. Confirm Machine A shows `emonio-d08a08` as `DISCONNECTED` and keeps it in the selector.
8. Confirm the other two Emonios on Machine A continue without interruption.
9. Confirm Machine B begins to receive `emonio-d08a08` measurements without closing Machine A.
10. Disconnect/release `emonio-d08a08` from Machine B as required by the test setup.
11. Press `RECONNECT EMONIO` on Machine A.
12. Confirm live canonical measurement resumes.
13. Confirm Recording remains stopped.
14. Confirm SCOPE remains stopped.
15. Confirm no cycle-ID reset or synthetic history point is observed.

Only after this field test passes can v0.4.14 Candidate be promoted to the trusted baseline.

## 20. Non-goals

This change does not add:

- automatic cross-machine arbitration;
- network discovery of which computer owns an Emonio;
- distributed locks;
- automatic Recording restart;
- automatic SCOPE restart;
- automatic credential reuse;
- sample interpolation;
- history synchronization between computers;
- changes to Emonio firmware;
- Modbus write operations.

The Emonio itself remains the external authority that determines whether another TCP client can acquire it after the first viewer releases its connection.

## 21. Reversibility

All implementation work must occur on the feature branch created from trusted v0.4.13.

`main` must remain unchanged until:

- implementation is complete;
- all automated acceptance passes;
- deterministic package verification passes;
- the two-machine field workflow passes;
- the operator explicitly approves integration.

The trusted v0.4.13 baseline remains available unchanged throughout development.
