# Per-Device Acquisition Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe per-Emonio disconnect/reconnect lifecycle so one viewer can release one Emonio for another machine without stopping the complete viewer.

**Architecture:** Keep canonical measurement, Modbus decoding, SCOPE capture, recording math, and EventBus publication semantics unchanged. Add per-device stop ownership inside `AcquisitionCoordinator`, add a small backend lifecycle orchestration service for Recording → SCOPE → acquisition shutdown, and expose additive lifecycle state through API and frontend controls. Reconnect uses the existing canonical `AcquisitionWorker.run_cycle()` path and preserves cycle-ID continuity.

**Tech Stack:** Python 3.10+, `threading`, `asyncio`, `aiohttp==3.14.3`, existing read-only Modbus/TCP client, vanilla JavaScript, structured CSS, `pytest==8.4.1`.

**Spec:** `docs/superpowers/specs/2026-08-30-per-device-acquisition-lifecycle-design.md`

## Global Constraints

- Baseline is v0.4.13 at commit `af25c80e0aa82fedb969035fd5c615102dbe874c`.
- Target is v0.4.14 Candidate. v0.4.13 remains the trusted field baseline until two-machine field acceptance passes.
- Do not modify Modbus register addresses, decoder math, P/Q signs, quadrant classification, validation tolerances, active-worker fixed-deadline scheduling, exact sample timestamps, CSV precision, recording eligibility, recording boundary calculation, or SCOPE waveform semantics.
- Do not add Modbus write functions.
- Do not add automatic cross-machine arbitration, distributed locks, automatic Recording restart, automatic SCOPE restart, credential persistence, sample interpolation, resampling, gap filling, synthetic samples, or cycle-ID reset.
- Disconnect order is exactly Recording → SCOPE → acquisition.
- A failed stage stops later stages. There is no automatic rollback.
- A disconnected Emonio stays registered, remembered, and visible.
- Reconnect starts acquisition only. Recording and SCOPE stay stopped.
- Commands for one device must not stop, reconnect, or reset another device.
- `main` must not be modified during candidate development.

---

## File Structure

**Create**

- `src/emonio_viewer/acquisition/lifecycle.py` — acquisition lifecycle enum, immutable status, and transition error.
- `src/emonio_viewer/lifecycle/__init__.py` — lifecycle package marker.
- `src/emonio_viewer/lifecycle/model.py` — cross-subsystem lifecycle result model and failure-stage enum.
- `src/emonio_viewer/lifecycle/service.py` — serialized per-device Recording → SCOPE → acquisition orchestration.
- `tests/integration/test_device_acquisition_lifecycle.py` — real multi-device coordinator disconnect/reconnect tests.
- `tests/unit/test_device_lifecycle_service.py` — deterministic orchestration order/failure tests.
- `tests/browser/test_device_lifecycle_contract.py` — frontend markup/API/state wording contract.

**Modify**

- `src/emonio_viewer/acquisition/coordinator.py` — replace single worker-stop ownership with independent per-device stop controls while retaining global shutdown.
- `src/emonio_viewer/acquisition/connector.py` — existing target result reports existing registration without claiming a live connection.
- `src/emonio_viewer/recording/recorder.py` — add read-only `is_active(device_id)` query only.
- `src/emonio_viewer/server/keys.py` — add lifecycle service AppKey.
- `src/emonio_viewer/server/app.py` — inject lifecycle service.
- `src/emonio_viewer/server/api.py` — lifecycle endpoints and additive `acquisition_state` fields.
- `src/emonio_viewer/main.py` — construct lifecycle service and pass it to the app; preserve shutdown sequence.
- `frontend/index.html` — add acquisition status and selected-device lifecycle button.
- `frontend/css/layout.css` — target-strip/status layout for the new explicit lifecycle control only.
- `frontend/js/api.js` — disconnect/reconnect requests with structured lifecycle errors.
- `frontend/js/app.js` — render lifecycle state, keep disconnected devices visible, execute one backend lifecycle command, refresh Recording/SCOPE/backend state.
- `frontend/js/measurements.js` — render additive acquisition state only; do not alter measurement formatting.
- `tests/integration/test_target_connection.py` — existing-target semantics.
- `tests/integration/test_server.py` — lifecycle API and additive status fields.
- `tests/integration/test_lifecycle.py` — global shutdown compatibility.
- `tests/integration/test_multi_device.py` — per-device isolation regression where useful.
- `tests/browser/test_frontend_async_state.py` — extend test harness stubs only for new lifecycle functions and ensure stale responses cannot overwrite selected-device lifecycle state.
- `tests/browser/test_frontend_contract.py` — structured CSS/file set and explicit lifecycle controls.
- `README.md` — v0.4.13 trusted baseline plus v0.4.14 Candidate description.
- `pyproject.toml` — `0.4.14`.
- `src/emonio_viewer/__init__.py` — `0.4.14`.
- `tests/unit/test_release_identity.py` — v0.4.14 candidate identity while keeping v0.4.13 trusted.
- `tests/unit/test_release_builder.py` — v0.4.14 candidate archive name.

---

### Task 1: Add Explicit Per-Device Acquisition Lifecycle State

**Files:**
- Create: `src/emonio_viewer/acquisition/lifecycle.py`
- Create: `tests/integration/test_device_acquisition_lifecycle.py`
- Modify: `src/emonio_viewer/acquisition/coordinator.py`
- Modify: `tests/integration/test_lifecycle.py`

**Interfaces:**
- Produces: `AcquisitionLifecycleState`, `AcquisitionStatus`, `AcquisitionTransitionError`.
- Produces: `AcquisitionCoordinator.acquisition_status(device_id: str) -> AcquisitionStatus`.
- Produces: `AcquisitionCoordinator.disconnect_device(device_id: str, join_timeout_s: float = 5.0) -> AcquisitionStatus`.
- Later tasks consume these interfaces without reading coordinator internals.

- [ ] **Step 1: Write failing lifecycle-state and single-device disconnect tests**

Add tests that prove three independent devices can run, only one selected worker is stopped, the selected client is closed, the selected configuration remains registered, the other workers continue producing cycles, and status becomes `DISCONNECTED` only after the thread is dead.

```python
from emonio_viewer.acquisition.lifecycle import AcquisitionLifecycleState


def test_disconnect_one_device_keeps_other_workers_running(three_device_coordinator):
    coordinator, store, devices = three_device_coordinator
    coordinator.start()
    try:
        wait_until(lambda: all(store.get_device(d.id).cycles_valid >= 2 for d in devices))
        before = {d.id: store.get_device(d.id).cycles_valid for d in devices}

        status = coordinator.disconnect_device(devices[1].id)
        assert status.state is AcquisitionLifecycleState.DISCONNECTED
        assert coordinator.get_device_config(devices[1].id) == devices[1]
        assert coordinator._threads[devices[1].id].is_alive() is False
        assert coordinator._workers[devices[1].id].client.is_connected is False

        wait_until(lambda: store.get_device(devices[0].id).cycles_valid > before[devices[0].id])
        wait_until(lambda: store.get_device(devices[2].id).cycles_valid > before[devices[2].id])
    finally:
        coordinator.stop()
```

Also add a blocked-receive variant based on the existing `HangingModbusServer` test so per-device disconnect proves that closing the selected client interrupts a blocked read without stopping other workers.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_lifecycle.py -q
```

Expected: failures because lifecycle types and `disconnect_device()` do not exist.

- [ ] **Step 3: Add acquisition lifecycle model**

Create exactly these public types:

```python
from dataclasses import dataclass
from enum import Enum


class AcquisitionLifecycleState(str, Enum):
    RUNNING = "RUNNING"
    DISCONNECTING = "DISCONNECTING"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class AcquisitionStatus:
    device_id: str
    state: AcquisitionLifecycleState
    detail: str | None = None


class AcquisitionTransitionError(RuntimeError):
    def __init__(self, status: AcquisitionStatus) -> None:
        super().__init__(status.detail or status.state.value)
        self.status = status
```

- [ ] **Step 4: Refactor coordinator ownership without changing worker science**

Keep `AcquisitionWorker.run()` unchanged. In the coordinator, retain the global shutdown event only as a global guard, and add one stop event per registered device. `_start_worker()` must create/clear only the selected device stop event and pass it to `_run_worker(worker, stop_event, connection_offset)`.

Required coordinator invariants:

```python
self._worker_stops: dict[str, threading.Event]
self._lifecycle: dict[str, AcquisitionStatus]
self._connection_offsets: dict[str, int]
```

Initial registered devices are `DISCONNECTED` before `start()`. `start()` starts each enabled worker and sets it to `RUNNING`.

`disconnect_device()` must:

```python
with self._lock:
    status = self.acquisition_status(device_id)
    if status.state is not AcquisitionLifecycleState.RUNNING:
        raise AcquisitionTransitionError(
            AcquisitionStatus(device_id, status.state, "acquisition is not RUNNING")
        )
    self._lifecycle[device_id] = AcquisitionStatus(
        device_id, AcquisitionLifecycleState.DISCONNECTING
    )
    stop_event = self._worker_stops[device_id]
    worker = self._workers[device_id]
    thread = self._threads[device_id]

stop_event.set()
worker.client.close()
thread.join(timeout=join_timeout_s)
```

If `thread.is_alive()` remains true, set `ERROR`, include exact detail, and raise `AcquisitionTransitionError`. Only after thread termination set `DISCONNECTED`.

Before a successfully disconnected worker is replaced later, accumulate its `client.connections_opened` into `_connection_offsets[device_id]`. Publication for active workers must report `offset + worker.client.connections_opened` to `RuntimeStore`. This preserves the existing monotonic reconnect diagnostic across a fresh client object and counts one successful intentional reconnect exactly once when the new client first opens.

Do not call `RuntimeStore.register_device()` during disconnect.

- [ ] **Step 5: Make global `stop()` operate over per-device stop events**

Global shutdown must set the global stop guard, set every per-device stop event, close every current client, join every current thread, and tolerate devices already `DISCONNECTED`. It must preserve the existing error if any running thread fails to terminate.

- [ ] **Step 6: Run focused lifecycle tests**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_lifecycle.py tests/integration/test_multi_device.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/emonio_viewer/acquisition/lifecycle.py src/emonio_viewer/acquisition/coordinator.py tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_lifecycle.py tests/integration/test_multi_device.py
git commit -m "feat: add per-device acquisition disconnect lifecycle"
```

---

### Task 2: Add Deterministic Reconnect with Cycle-ID and Diagnostic Continuity

**Files:**
- Modify: `src/emonio_viewer/acquisition/coordinator.py`
- Modify: `tests/integration/test_device_acquisition_lifecycle.py`

**Interfaces:**
- Consumes: `AcquisitionLifecycleState`, `AcquisitionStatus`, `AcquisitionTransitionError`.
- Produces: `AcquisitionCoordinator.reconnect_device(device_id: str) -> AcquisitionStatus`.

- [ ] **Step 1: Write failing reconnect tests**

Required tests:

```python
def test_reconnect_uses_next_cycle_id_and_fresh_worker(coordinator_fixture):
    coordinator, store, device = coordinator_fixture
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(device.id).last_sample is not None)
        old_worker = coordinator._workers[device.id]
        before_cycle = store.get_device(device.id).last_sample.identity.cycle_id
        before_reconnects = store.get_device(device.id).metrics.reconnects

        coordinator.disconnect_device(device.id)
        status = coordinator.reconnect_device(device.id)
        assert status.state.value == "RUNNING"
        assert coordinator._workers[device.id] is not old_worker

        qualified = store.get_device(device.id).last_sample
        assert qualified.identity.cycle_id == before_cycle + 1
        assert store.get_device(device.id).metrics.reconnects == before_reconnects + 1
        wait_until(lambda: store.get_device(device.id).last_sample.identity.cycle_id >= before_cycle + 2)
    finally:
        coordinator.stop()
```

Add a failure test where the fake Emonio rejects reads. After failure, assert lifecycle returns to safe `DISCONNECTED`, no worker thread is started, candidate client is closed, last exact sample is unchanged, and no synthetic sample is published.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py -q
```

Expected: reconnect tests fail because `reconnect_device()` does not exist.

- [ ] **Step 3: Implement reconnect using the existing canonical worker path**

`reconnect_device()` must require `DISCONNECTED`, set `CONNECTING`, calculate `last_cycle_id` from `RuntimeStore.get_device(device_id).last_sample`, create a fresh `ReadOnlyModbusClient` and `AcquisitionWorker`, then run one qualification cycle synchronously through `AcquisitionWorker.run_cycle()`.

Use this cycle rule:

```python
last_sample = self._store.get_device(device_id).last_sample
last_cycle_id = 0 if last_sample is None else last_sample.identity.cycle_id
qualification_cycle_id = last_cycle_id + 1
worker = self._create_worker(
    device,
    starting_cycle_id=qualification_cycle_id,
)
sample = worker.run_cycle(qualification_cycle_id, 0.0)
```

Constructing the worker with `starting_cycle_id=qualification_cycle_id` is intentional: after qualification is published, the normal `run()` loop increments to `qualification_cycle_id + 1` for the first continuous sample.

On qualification success:

```python
connections = self._connection_offsets[device_id] + worker.client.connections_opened
self._store.publish_sample(sample, connections)
self._bus.publish(sample)
self._workers[device_id] = worker
self._start_worker(device_id, worker)
self._lifecycle[device_id] = AcquisitionStatus(device_id, AcquisitionLifecycleState.RUNNING)
```

On `AcquisitionCycleError` or `OSError`, close the candidate client, leave the existing remembered config and last sample intact, set `DISCONNECTED` with exact detail, and raise `AcquisitionTransitionError`. Do not use `ERROR` if candidate cleanup succeeds.

- [ ] **Step 4: Prevent duplicate starts and reconnect-after-global-stop**

Add explicit tests and guards for:

- reconnect when state is `RUNNING`;
- reconnect while `CONNECTING`;
- reconnect while selected previous thread is still alive;
- reconnect after global coordinator shutdown has started.

All must fail without creating a second worker.

- [ ] **Step 5: Run focused tests**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_worker.py tests/integration/test_multi_device.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/emonio_viewer/acquisition/coordinator.py tests/integration/test_device_acquisition_lifecycle.py
git commit -m "feat: add deterministic per-device reconnect"
```

---

### Task 3: Add Cross-Subsystem Lifecycle Orchestration

**Files:**
- Create: `src/emonio_viewer/lifecycle/__init__.py`
- Create: `src/emonio_viewer/lifecycle/model.py`
- Create: `src/emonio_viewer/lifecycle/service.py`
- Create: `tests/unit/test_device_lifecycle_service.py`
- Modify: `src/emonio_viewer/recording/recorder.py`

**Interfaces:**
- Consumes: coordinator `disconnect_device()`, `reconnect_device()`, `acquisition_status()`.
- Consumes: `RecordingManager.stop()`, `ScopeService.stop()`, `RuntimeStore.get_device()`.
- Produces: `LifecycleFailureStage`, `DeviceLifecycleResult`, `DeviceLifecycleCommandError`, `DeviceLifecycleService`.

- [ ] **Step 1: Add failing orchestration tests with call traces**

Use fakes that append exact call names. Required successful trace with active Recording and SCOPE:

```python
result = asyncio.run(service.disconnect("emonio-a"))
assert calls == ["recording.stop", "scope.stop", "acquisition.disconnect"]
assert result.recording_state == "STOPPED"
assert result.scope_state == "DISCONNECTED"
assert result.acquisition_state == "DISCONNECTED"
```

Required failure traces:

```python
# Recording stop fails
assert calls == ["recording.stop"]
assert error.result.failed_stage == "RECORDING"

# Scope stop fails after recording stopped
assert calls == ["recording.stop", "scope.stop"]
assert error.result.recording_state == "STOPPED"
assert error.result.failed_stage == "SCOPE"

# Acquisition stop fails after earlier stages succeeded
assert calls == ["recording.stop", "scope.stop", "acquisition.disconnect"]
assert error.result.recording_state == "STOPPED"
assert error.result.scope_state == "DISCONNECTED"
assert error.result.failed_stage == "ACQUISITION"
```

Also prove no-active-recording and no-active-SCOPE are valid, reconnect does not call Recording or SCOPE, and two simultaneous commands for the same device are serialized by one `asyncio.Lock`.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/unit/test_device_lifecycle_service.py -q
```

Expected: missing lifecycle package/service.

- [ ] **Step 3: Add read-only Recording activity query**

Add only:

```python
def is_active(self, device_id: str) -> bool:
    with self._lock:
        return device_id in self._active
```

Do not change `RecordingManager.stop()` or `SessionRecorder.stop()`.

- [ ] **Step 4: Add lifecycle result model**

```python
from dataclasses import dataclass
from enum import Enum


class LifecycleFailureStage(str, Enum):
    RECORDING = "RECORDING"
    SCOPE = "SCOPE"
    ACQUISITION = "ACQUISITION"


@dataclass(frozen=True, slots=True)
class DeviceLifecycleResult:
    device_id: str
    acquisition_state: str
    measurement_state: str
    recording_state: str
    scope_state: str
    failed_stage: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "acquisition_state": self.acquisition_state,
            "measurement_state": self.measurement_state,
            "recording_state": self.recording_state,
            "scope_state": self.scope_state,
            "failed_stage": self.failed_stage,
            "detail": self.detail,
        }


class DeviceLifecycleCommandError(RuntimeError):
    def __init__(self, result: DeviceLifecycleResult) -> None:
        super().__init__(result.detail or "device lifecycle command failed")
        self.result = result
```

- [ ] **Step 5: Implement backend-authoritative sequence**

`DeviceLifecycleService` constructor:

```python
def __init__(self, recording, scope, coordinator, store) -> None:
    self._recording = recording
    self._scope = scope
    self._coordinator = coordinator
    self._store = store
    self._locks: dict[str, asyncio.Lock] = {}
```

`disconnect()` must hold only that device's lock and call existing subsystem stops in approved order. `ScopeService.stop()` is already idempotent for no runtime. `reconnect()` must call only `await asyncio.to_thread(self._coordinator.reconnect_device, device_id)`.

`status(device_id)` must derive:

- acquisition state from coordinator;
- measurement state from `RuntimeStore`;
- recording state from `RecordingManager.is_active()` (`RECORDING` or `STOPPED`);
- SCOPE state from `ScopeService.status()`.

If a stop step raises, build a result from actual post-failure subsystem states, set `failed_stage`, and raise `DeviceLifecycleCommandError`. Never fabricate a completed later stage.

- [ ] **Step 6: Run unit tests**

```bash
python -m pytest tests/unit/test_device_lifecycle_service.py tests/unit/test_recording_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/emonio_viewer/lifecycle src/emonio_viewer/recording/recorder.py tests/unit/test_device_lifecycle_service.py
git commit -m "feat: orchestrate device release across recording scope acquisition"
```

---

### Task 4: Wire Lifecycle Service into Runtime and API

**Files:**
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/app.py`
- Modify: `src/emonio_viewer/server/api.py`
- Modify: `src/emonio_viewer/main.py`
- Modify: `tests/integration/test_server.py`
- Modify: `tests/integration/test_lifecycle.py`

**Interfaces:**
- Consumes: `DeviceLifecycleService.disconnect()`, `.reconnect()`, `.status()`.
- Produces HTTP routes:
  - `POST /api/v1/devices/{device_id}/disconnect`
  - `POST /api/v1/devices/{device_id}/reconnect`
- Adds `acquisition_state` to device status responses.

- [ ] **Step 1: Write failing API tests**

Test successful endpoint payload contains exactly meaningful state fields:

```python
assert payload["device_id"] == device_config.id
assert payload["acquisition_state"] == "DISCONNECTED"
assert payload["measurement_state"] in {"ONLINE", "DEGRADED", "STALE", "OFFLINE", "CONNECTING"}
assert payload["recording_state"] == "STOPPED"
assert payload["scope_state"] == "DISCONNECTED"
assert payload["failed_stage"] is None
```

Test an orchestration failure returns JSON with partial completion and `failed_stage`, and unknown device remains 404.

Add tests that `GET /api/v1/devices`, `GET /api/v1/devices/{id}`, and diagnostics expose additive `acquisition_state` without renaming existing `state` measurement-health fields.

- [ ] **Step 2: Run API tests and verify RED**

```bash
python -m pytest tests/integration/test_server.py -q
```

- [ ] **Step 3: Add AppKey and application injection**

In `server/keys.py` add a typed AppKey for `DeviceLifecycleService`. Add optional `lifecycle_service=None` to `create_app()` and store it when supplied.

- [ ] **Step 4: Add lifecycle API handlers**

Both routes must validate the path device through `_device_config()` before calling the service.

Use structured JSON for lifecycle failures, not plain text:

```python
except DeviceLifecycleCommandError as exc:
    return web.json_response(exc.result.as_dict(), status=502)
```

Map invalid lifecycle state conflicts such as duplicate disconnect/reconnect to HTTP 409 when the coordinator error proves the requested transition is not currently valid. Keep transport/cleanup failure as 502.

- [ ] **Step 5: Add lifecycle state to read responses**

Do not replace `snapshot.state.value`. Add:

```python
"acquisition_state": _lifecycle(request).status(snapshot.device_id).acquisition_state,
```

`sample_to_json()` must receive/add the acquisition state without touching any sample values.

- [ ] **Step 6: Construct the lifecycle service in `run_viewer()`**

After `ScopeService()` construction:

```python
lifecycle_service = DeviceLifecycleService(recording, scope_service, coordinator, store)
```

Pass it to `create_app()`. Do not route complete viewer shutdown through this per-device service. Existing complete shutdown remains the authority for whole-process cleanup.

- [ ] **Step 7: Verify global shutdown regression**

Keep existing shutdown trace expectations. Add a case with one coordinator device already `DISCONNECTED` and prove complete viewer shutdown still succeeds and stops remaining running workers.

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/integration/test_server.py tests/integration/test_lifecycle.py tests/integration/test_scope_api.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/emonio_viewer/server src/emonio_viewer/main.py tests/integration/test_server.py tests/integration/test_lifecycle.py
git commit -m "feat: expose per-device lifecycle API"
```

---

### Task 5: Correct Existing-Target Connection Semantics

**Files:**
- Modify: `src/emonio_viewer/acquisition/connector.py`
- Modify: `src/emonio_viewer/server/api.py`
- Modify: `tests/integration/test_target_connection.py`
- Modify: `tests/integration/test_server.py`

**Interfaces:**
- Existing `DeviceConnector.connect()` still qualifies only new targets.
- Existing registered targets return registration identity without a false live-connection claim.

- [ ] **Step 1: Write failing existing-target test**

Build an already registered device with no available Modbus server and call `connector.connect()` for that target. The test must prove no `run_cycle()` qualification is attempted and API does not return a generic live `CONNECTED` claim.

Expected API semantics:

```python
assert payload["state"] == "EXISTING"
assert payload["already_connected"] is True
assert payload["acquisition_state"] in {"RUNNING", "DISCONNECTED", "ERROR"}
assert "measurement_state" in payload
```

A newly qualified device still returns `state == "CONNECTED"` because that request has direct qualification evidence.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/integration/test_target_connection.py tests/integration/test_server.py -q
```

- [ ] **Step 3: Keep connector behavior narrow**

Do not make `DeviceConnector.connect()` auto-reconnect an existing device. Keep the explicit lifecycle endpoint/button as the acquisition restart authority. Preserve `ConnectionResult(device, already_connected)` so other code does not require unnecessary redesign.

- [ ] **Step 4: Change only API wording/evidence fields**

For `already_connected=True`, return `state: "EXISTING"` plus actual lifecycle and measurement state from backend services/store. For a newly qualified target, return `state: "CONNECTED"` plus actual states.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/integration/test_target_connection.py tests/integration/test_server.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/emonio_viewer/acquisition/connector.py src/emonio_viewer/server/api.py tests/integration/test_target_connection.py tests/integration/test_server.py
git commit -m "fix: stop existing target status from claiming live connection"
```

---

### Task 6: Add Explicit Frontend Disconnect/Reconnect Control

**Files:**
- Create: `tests/browser/test_device_lifecycle_contract.py`
- Modify: `frontend/index.html`
- Modify: `frontend/css/layout.css`
- Modify: `frontend/js/api.js`
- Modify: `frontend/js/app.js`
- Modify: `frontend/js/measurements.js`
- Modify: `tests/browser/test_frontend_contract.py`
- Modify: `tests/browser/test_frontend_async_state.py`

**Interfaces:**
- Consumes API `acquisition_state` and lifecycle routes.
- Produces explicit status element `#acquisition-state` and button `#device-lifecycle-action`.

- [ ] **Step 1: Write frontend contract tests first**

Require:

```python
assert 'id="acquisition-state"' in html
assert 'id="device-lifecycle-action"' in html
assert "disconnectDevice" in api
assert "reconnectDevice" in api
assert "CONNECTED / EXISTING" not in app
assert "DISCONNECT EMONIO" in app
assert "RECONNECT EMONIO" in app
```

Also assert no new CSS file is introduced. `layout.css` remains responsible for target/status layout. Existing structured CSS file set stays unchanged.

- [ ] **Step 2: Run browser tests and verify RED**

```bash
python -m pytest tests/browser/test_device_lifecycle_contract.py tests/browser/test_frontend_contract.py -q
```

- [ ] **Step 3: Add API functions with structured error preservation**

Add:

```javascript
export function disconnectDevice(deviceId) {
  return lifecycleRequest(`/api/v1/devices/${encodeURIComponent(deviceId)}/disconnect`);
}

export function reconnectDevice(deviceId) {
  return lifecycleRequest(`/api/v1/devices/${encodeURIComponent(deviceId)}/reconnect`);
}
```

`lifecycleRequest()` must parse JSON on non-2xx and attach the structured lifecycle payload to `error.lifecycleResult` so the UI can show `failed_stage` and exact detail.

- [ ] **Step 4: Add explicit acquisition status and lifecycle button**

In the status bar add one `Acquisition` field with `id="acquisition-state"`. In `target-strip`, add one button `id="device-lifecycle-action"`. Update the desktop grid columns in `layout.css`; preserve existing narrow-screen fallback.

- [ ] **Step 5: Keep disconnected devices in the selector**

Maintain a backend device-state cache keyed by `device_id`. `populateDeviceSelector()` must continue to use all enabled remembered runtime-config devices. If the cached acquisition state is `DISCONNECTED`, option text must be:

```javascript
`${device.name} · DISCONNECTED`
```

Do not delete the option and do not remove the device from runtime config.

- [ ] **Step 6: Render lifecycle control from backend state only**

Required mapping:

```javascript
RUNNING       -> button text "DISCONNECT EMONIO", enabled
DISCONNECTED  -> button text "RECONNECT EMONIO", enabled
DISCONNECTING -> button text "DISCONNECTING...", disabled
CONNECTING    -> button text "CONNECTING...", disabled
ERROR         -> button text "DISCONNECT ERROR", disabled
```

`renderBackendStatus()` may set `#acquisition-state` from additive `device.acquisition_state`; it must not change measurement formatting or measurement values.

- [ ] **Step 7: Execute one backend command and then refresh all affected panels**

The button handler must call exactly one backend lifecycle command. It must not call Recording STOP or SCOPE STOP directly from JavaScript.

After backend completion or structured failure, refresh:

```javascript
await Promise.all([
  refreshBackendState(),
  refreshRecordingState(),
  refreshScopeStatus(deviceId),
]);
```

Then call `applySelectedDeviceConfig()` if the selection generation is still current.

- [ ] **Step 8: Correct target status wording**

For target connect response:

```javascript
if (result.state === "EXISTING") {
  setTargetStatus(`EXISTING / ${result.acquisition_state === "DISCONNECTED" ? "DISCONNECTED" : result.measurement_state}`, "");
} else {
  setTargetStatus("CONNECTED / VERIFIED", "connected");
}
```

Do not use `CONNECTED / EXISTING` anywhere.

- [ ] **Step 9: Extend async-state test harness**

Add stubs for `disconnectDevice` and `reconnectDevice`. Add a test where a lifecycle request for device A resolves after the selection has changed to B; it must not overwrite B's rendered lifecycle action/status.

- [ ] **Step 10: Run frontend tests**

```bash
python -m pytest tests/browser/test_device_lifecycle_contract.py tests/browser/test_frontend_contract.py tests/browser/test_frontend_async_state.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/index.html frontend/css/layout.css frontend/js/api.js frontend/js/app.js frontend/js/measurements.js tests/browser/test_device_lifecycle_contract.py tests/browser/test_frontend_contract.py tests/browser/test_frontend_async_state.py
git commit -m "feat: add explicit emonio disconnect reconnect controls"
```

---

### Task 7: Prove End-to-End Per-Device Isolation and Automatic Recording/SCOPE Stop

**Files:**
- Modify: `tests/integration/test_device_acquisition_lifecycle.py`
- Add or modify focused lifecycle API test in: `tests/integration/test_server.py`
- Reuse: `tests/integration/fake_emonio.py`

**Interfaces:**
- Exercises the complete backend path without frontend assumptions.

- [ ] **Step 1: Add an integration test with three fake Emonios**

Test sequence:

1. Start three workers.
2. Start a real RecordingManager recording for the middle device.
3. Use a fake SCOPE service that reports LIVE for the middle device and records stop order.
4. Call `DeviceLifecycleService.disconnect(middle_id)`.
5. Verify session metadata now contains `stopped_utc`.
6. Verify SCOPE stop occurred.
7. Verify middle acquisition is `DISCONNECTED`, client closed, worker dead.
8. Verify first and third devices continue increasing `cycles_valid`.
9. Reconnect middle device.
10. Verify its next published cycle ID is continuous.
11. Verify Recording is still stopped and SCOPE remains disconnected.

- [ ] **Step 2: Run and verify the test**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_server.py -q
```

Expected: PASS.

- [ ] **Step 3: Verify read-only protocol gate remains unchanged**

```bash
./tools/ari-emonio-read-only-gate.sh
```

Expected: PASS with no new Modbus write path.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_server.py
git commit -m "test: prove per-device release isolation end to end"
```

---

### Task 8: Bind v0.4.14 Candidate Identity and Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/emonio_viewer/__init__.py`
- Modify: `README.md`
- Modify: `tests/unit/test_release_identity.py`
- Modify: `tests/unit/test_release_builder.py`

**Interfaces:**
- Candidate archive name becomes `ARI_Emonio_Viewer_v0.4.14_Candidate.zip`.
- README explicitly keeps v0.4.13 as trusted field baseline.

- [ ] **Step 1: Write release identity expectations first**

Update tests to require:

```python
assert project["project"]["version"] == "0.4.14"
assert __version__ == "0.4.14"
assert "trusted field baseline is **v0.4.13**" in readme
assert "**v0.4.14 Candidate**" in readme
assert "trusted field baseline is **v0.4.14**" not in readme
```

Release builder test must require `ARI_Emonio_Viewer_v0.4.14_Candidate.zip` and matching internal directory prefix.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/unit/test_release_identity.py tests/unit/test_release_builder.py -q
```

- [ ] **Step 3: Update version identity**

Set project and package version to `0.4.14`.

- [ ] **Step 4: Update README conservatively**

Use:

```markdown
The trusted field baseline is **v0.4.13**.
**v0.4.14 Candidate** adds explicit per-Emonio acquisition disconnect/reconnect for controlled multi-machine handoff. Disconnect cleanly stops active Recording, then SCOPE, then only the selected Modbus acquisition worker. Reconnect restores canonical acquisition only.
```

Do not claim field trust yet.

- [ ] **Step 5: Run release identity tests**

```bash
python -m pytest tests/unit/test_release_identity.py tests/unit/test_release_builder.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/emonio_viewer/__init__.py README.md tests/unit/test_release_identity.py tests/unit/test_release_builder.py
git commit -m "chore: bind v0.4.14 candidate identity"
```

---

### Task 9: Full Verification, Deterministic Package, and Candidate Evidence

**Files:**
- No source design expansion is permitted in this task.
- Generated artifacts stay under `dist/` and are not committed.

**Interfaces:**
- Produces verified candidate commit SHA, full acceptance evidence, deterministic ZIP, and SHA-256.

- [ ] **Step 1: Inspect the branch diff against trusted v0.4.13**

```bash
git diff --stat af25c80e0aa82fedb969035fd5c615102dbe874c...HEAD
git diff --name-only af25c80e0aa82fedb969035fd5c615102dbe874c...HEAD
```

Confirm no protected measurement implementation files changed except the explicitly approved acquisition lifecycle coordinator. In particular, `measurement/`, Modbus decoder/register map/protocol, SCOPE client/protocol/model science, recording CSV writer/session math, quadrant math, and validation must remain unchanged.

- [ ] **Step 2: Run complete source acceptance**

```bash
./tools/ari-emonio-publication-gate.sh
./tools/ari-emonio-acceptance.sh
```

Required result: every unit, integration, frontend/browser, read-only, Python compilation, and scientific sign-path gate passes.

- [ ] **Step 3: Build candidate twice from the same commit**

```bash
rm -rf dist build
python tools/build-release.py
cp dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip /tmp/ari-v0414-first.zip
cp dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip.sha256 /tmp/ari-v0414-first.zip.sha256
rm -rf dist build
python tools/build-release.py
cmp /tmp/ari-v0414-first.zip dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip
cmp /tmp/ari-v0414-first.zip.sha256 dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip.sha256
```

Expected: both `cmp` commands exit 0.

- [ ] **Step 4: Verify packaged candidate in a clean extraction**

Use system `unzip` so executable mode bits are preserved:

```bash
rm -rf /tmp/ari-v0414-package /tmp/ari-v0414-venv
mkdir -p /tmp/ari-v0414-package
unzip -q dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip -d /tmp/ari-v0414-package
python3 -m venv /tmp/ari-v0414-venv
/tmp/ari-v0414-venv/bin/pip install -e '/tmp/ari-v0414-package/ARI_Emonio_Viewer_v0.4.14_Candidate[dev]'
cd /tmp/ari-v0414-package/ARI_Emonio_Viewer_v0.4.14_Candidate
./tools/ari-emonio-acceptance.sh
```

Expected: packaged acceptance PASS.

- [ ] **Step 5: Record deterministic evidence**

```bash
sha256sum dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip
cat dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip.sha256
git rev-parse HEAD
```

The two SHA-256 values must match exactly. Report the exact candidate commit and archive hash. Do not promote `main`.

- [ ] **Step 6: Field acceptance on two machines**

Perform the approved 15-step field sequence from the specification. The key proof is that Machine A can disconnect `emonio-d08a08` while its other Emonios continue, Machine B immediately begins receiving `d08a08`, and a later reconnect on Machine A resumes canonical acquisition without automatically restarting Recording or SCOPE.

Only after this field evidence passes may v0.4.14 be called trusted and considered for a fast-forward merge to `main`.
