# Per-Device Acquisition Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe per-Emonio disconnect/reconnect lifecycle so one viewer can release one Emonio for another machine without stopping the complete viewer.

**Architecture:** Keep canonical measurement, Modbus decoding, SCOPE capture, recording math, and EventBus publication semantics unchanged. Add independent per-device worker stop ownership inside `AcquisitionCoordinator`, add a small backend lifecycle orchestration service for Recording → SCOPE → acquisition shutdown, and expose additive lifecycle state through HTTP/WebSocket status and frontend controls. Reconnect uses the existing canonical `AcquisitionWorker.run_cycle()` path and preserves cycle-ID continuity.

**Tech Stack:** Python 3.10+, `threading`, `asyncio`, `aiohttp==3.14.3`, existing read-only Modbus/TCP client, vanilla JavaScript, structured CSS, `pytest==8.4.1`.

**Spec:** `docs/superpowers/specs/2026-08-30-per-device-acquisition-lifecycle-design.md`

## Global Constraints

- Baseline is v0.4.13 at commit `af25c80e0aa82fedb969035fd5c615102dbe874c`.
- Target is v0.4.14 Candidate. v0.4.13 remains the trusted field baseline until two-machine field acceptance passes.
- Do not modify Modbus register addresses, decoder math, P/Q signs, quadrant classification, validation tolerances, active-worker fixed-deadline scheduling, exact sample timestamps, CSV precision, recording eligibility, recording boundary calculation, or SCOPE waveform semantics.
- Do not add Modbus write functions.
- Do not add automatic cross-machine arbitration, distributed locks, automatic Recording restart, automatic SCOPE restart, credential persistence, sample interpolation, resampling, gap filling, synthetic samples, or cycle-ID reset.
- Disconnect order is exactly Recording → SCOPE → acquisition.
- A failed stage stops all later stages. There is no automatic rollback.
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

- `src/emonio_viewer/acquisition/coordinator.py` — separate device registration from worker creation and add independent per-device stop controls while retaining global shutdown.
- `src/emonio_viewer/acquisition/connector.py` — existing target result reports existing registration without claiming a live connection.
- `src/emonio_viewer/recording/recorder.py` — add read-only `is_active(device_id)` query only.
- `src/emonio_viewer/server/keys.py` — add lifecycle service AppKey.
- `src/emonio_viewer/server/app.py` — inject lifecycle service.
- `src/emonio_viewer/server/api.py` — lifecycle endpoints and additive `acquisition_state` fields.
- `src/emonio_viewer/server/websocket.py` — add the authoritative acquisition lifecycle to live measurement envelopes without changing the measurement sample.
- `src/emonio_viewer/main.py` — construct lifecycle service and pass it to the app; preserve shutdown sequence.
- `frontend/index.html` — add acquisition status and selected-device lifecycle button.
- `frontend/css/layout.css` — target-strip/status layout for the new explicit lifecycle control only.
- `frontend/js/api.js` — disconnect/reconnect requests with structured lifecycle errors.
- `frontend/js/app.js` — render lifecycle state, keep disconnected devices visible, execute one backend lifecycle command, refresh Recording/SCOPE/backend state.
- `frontend/js/measurements.js` — render additive acquisition state only; do not alter measurement formatting.
- `tests/integration/test_target_connection.py` — existing-target semantics.
- `tests/integration/test_server.py` — lifecycle API and additive status fields.
- `tests/integration/test_websocket.py` — live payload additive lifecycle field.
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
- Modify: `tests/integration/test_multi_device.py`

**Interfaces:**
- Produces: `AcquisitionLifecycleState`, `AcquisitionStatus`, `AcquisitionTransitionError`.
- Produces: `AcquisitionCoordinator.acquisition_status(device_id: str) -> AcquisitionStatus`.
- Produces: `AcquisitionCoordinator.disconnect_device(device_id: str, join_timeout_s: float = 5.0) -> AcquisitionStatus`.
- Produces internal `_create_worker()` that creates a fresh client/worker without registering the device in `RuntimeStore`.
- Later tasks consume these interfaces without bypassing lifecycle checks.

- [ ] **Step 1: Write failing lifecycle-state and single-device disconnect tests**

Add tests that prove three independent devices can run, only one selected worker is stopped, the selected client is closed, the selected configuration remains registered, the other workers continue producing cycles, and status becomes `DISCONNECTED` only after the selected thread is dead.

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

Add a blocked-receive variant based on the existing `HangingModbusServer` test. It must prove that closing the selected client interrupts a blocked read and does not stop another device worker.

- [ ] **Step 2: Run the new tests and verify RED**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_lifecycle.py tests/integration/test_multi_device.py -q
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

- [ ] **Step 4: Separate permanent device registration from replaceable worker creation**

The current `_register_worker()` both registers a `RuntimeStore` device and creates a worker. Reconnect must not call `RuntimeStore.register_device()` again. Split these responsibilities.

Required coordinator ownership:

```python
self._devices: dict[str, DeviceConfig]
self._workers: dict[str, AcquisitionWorker]
self._threads: dict[str, threading.Thread]
self._worker_stops: dict[str, threading.Event]
self._lifecycle: dict[str, AcquisitionStatus]
self._connection_offsets: dict[str, int]
```

Add a private worker factory that has no registration side effect:

```python
def _create_worker(
    self,
    device: DeviceConfig,
    *,
    starting_cycle_id: int = 0,
) -> AcquisitionWorker:
    client = ReadOnlyModbusClient(
        device.host,
        device.port,
        device.unit_id,
        device.timeout_s,
    )
    return AcquisitionWorker(device, client, starting_cycle_id=starting_cycle_id)
```

Registration of a new device must happen exactly once: store config in `_devices`, call `RuntimeStore.register_device(device)`, initialize connection offset/lifecycle, and create its initial worker. `device_configs()` and `get_device_config()` must read `_devices`, not depend on the current worker object.

`add_device()` continues to register only a genuinely new device. Reconnect never calls `add_device()`.

- [ ] **Step 5: Refactor worker stop ownership without changing worker science**

Keep `AcquisitionWorker.run()` byte-identical if possible. The coordinator must pass a per-device `threading.Event` to it instead of the former global event. The global event remains only a whole-coordinator shutdown guard.

Initial registered devices are `DISCONNECTED` before `start()`. `start()` creates/clears each device stop event, starts each enabled worker, and sets lifecycle to `RUNNING`.

`disconnect_device()` must serialize state changes under `_lock`, then stop outside the lock:

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

If the thread remains alive, set lifecycle `ERROR` with exact detail and raise `AcquisitionTransitionError`. Do not claim `DISCONNECTED`.

After confirmed thread termination, and before setting `DISCONNECTED`, accumulate exactly once:

```python
self._connection_offsets[device_id] += worker.client.connections_opened
```

Then set `DISCONNECTED`. A second disconnect is rejected by lifecycle state, so the old connection count cannot be added twice.

For sample/failure publication from a running worker, report:

```python
connections_opened = connection_offset + worker.client.connections_opened
```

to `RuntimeStore`. This keeps the existing reconnect diagnostic monotonic when a later reconnect uses a fresh client object.

Do not call `RuntimeStore.register_device()` during disconnect.

- [ ] **Step 6: Make global `stop()` operate over per-device stop events**

Global shutdown must set the global shutdown guard, set every per-device stop event, close every current client, join every current running thread, and tolerate devices already `DISCONNECTED`. It must preserve the existing failure if any worker does not terminate.

- [ ] **Step 7: Run focused lifecycle tests**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_lifecycle.py tests/integration/test_multi_device.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

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
- Consumes: `AcquisitionLifecycleState`, `AcquisitionStatus`, `AcquisitionTransitionError`, coordinator `_create_worker()`.
- Produces: `AcquisitionCoordinator.reconnect_device(device_id: str) -> AcquisitionStatus`.

- [ ] **Step 1: Write failing reconnect tests**

Required success test:

```python
def test_reconnect_uses_next_cycle_id_and_fresh_worker(coordinator_fixture):
    coordinator, store, device = coordinator_fixture
    coordinator.start()
    try:
        wait_until(lambda: store.get_device(device.id).last_sample is not None)
        old_worker = coordinator._workers[device.id]
        before = store.get_device(device.id)
        before_cycle = before.last_sample.identity.cycle_id
        before_reconnects = before.metrics.reconnects

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

Add a failure test where the fake Emonio rejects reads. After failure, assert lifecycle returns to safe `DISCONNECTED`, no new worker thread is started, candidate client is closed, last exact sample is unchanged, and no synthetic sample is published.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py -q
```

Expected: reconnect tests fail because `reconnect_device()` does not exist.

- [ ] **Step 3: Implement reconnect using the existing canonical worker path**

`reconnect_device()` must require `DISCONNECTED`, reject if global shutdown has started, verify the previous thread is not alive, and set `CONNECTING` before network qualification.

Calculate the qualification cycle from the last exact published sample:

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

Constructing the worker with `starting_cycle_id=qualification_cycle_id` is intentional. After the qualification sample is published, the normal `run()` loop increments once, so the first continuous sample uses `qualification_cycle_id + 1`.

On qualification success:

```python
connections = self._connection_offsets[device_id] + worker.client.connections_opened
self._store.publish_sample(sample, connections)
self._bus.publish(sample)
self._workers[device_id] = worker
self._start_worker(device_id, worker, connection_offset=self._connection_offsets[device_id])
self._lifecycle[device_id] = AcquisitionStatus(
    device_id, AcquisitionLifecycleState.RUNNING
)
```

The first new client open makes total `connections_opened` one greater than the previous total, so existing `DeviceMetrics.set_connections_opened()` increments `reconnects` exactly once for a successful intentional reconnect.

On `AcquisitionCycleError` or `OSError`, close the candidate client. If cleanup succeeds, set lifecycle back to safe `DISCONNECTED` with the exact qualification failure detail and raise `AcquisitionTransitionError`. Do not publish the candidate sample and do not use `ERROR` when the failed candidate was fully cleaned up.

If candidate cleanup itself cannot be proved, set `ERROR` and include both qualification and cleanup detail.

- [ ] **Step 4: Prevent duplicate starts and reconnect-after-global-stop**

Add tests and guards for:

- reconnect when state is `RUNNING`;
- reconnect while `CONNECTING`;
- reconnect while previous thread is still alive;
- reconnect after global coordinator shutdown has started.

All cases must fail without creating a second worker/client owner.

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

- [ ] **Step 1: Add failing orchestration tests with exact call traces**

Successful active Recording + active SCOPE trace:

```python
result = asyncio.run(service.disconnect("emonio-a"))
assert calls == ["recording.stop", "scope.stop", "acquisition.disconnect"]
assert result.recording_state == "STOPPED"
assert result.scope_state == "DISCONNECTED"
assert result.acquisition_state == "DISCONNECTED"
```

Required failures:

```python
# Recording stop fails
assert calls == ["recording.stop"]
assert error.result.failed_stage == "RECORDING"

# SCOPE stop fails after Recording stopped
assert calls == ["recording.stop", "scope.stop"]
assert error.result.recording_state == "STOPPED"
assert error.result.failed_stage == "SCOPE"

# Acquisition stop fails after earlier stages succeeded
assert calls == ["recording.stop", "scope.stop", "acquisition.disconnect"]
assert error.result.recording_state == "STOPPED"
assert error.result.scope_state == "DISCONNECTED"
assert error.result.failed_stage == "ACQUISITION"
```

Also prove:

- no-active-Recording is valid;
- no-active-SCOPE is valid because SCOPE stop is idempotent;
- reconnect does not call Recording or SCOPE;
- commands for the same device serialize on one lock;
- commands for different devices use independent locks.

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

Do not change `RecordingManager.stop()`, `SessionRecorder.stop()`, CSV writing, recording eligibility, or boundary math.

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

Constructor:

```python
def __init__(self, recording, scope, coordinator, store) -> None:
    self._recording = recording
    self._scope = scope
    self._coordinator = coordinator
    self._store = store
    self._locks: dict[str, asyncio.Lock] = {}
```

Use `self._locks.setdefault(device_id, asyncio.Lock())` before the first await so a single event-loop thread deterministically chooses one lock per device.

`disconnect()` must hold only that device lock. If Recording is active, call existing `RecordingManager.stop(device_id)`. Then call existing idempotent `await ScopeService.stop(device_id)`. Then stop acquisition with:

```python
await asyncio.to_thread(self._coordinator.disconnect_device, device_id)
```

Do not block the aiohttp event loop on `thread.join()`.

`reconnect()` must hold the same per-device lock and call only:

```python
await asyncio.to_thread(self._coordinator.reconnect_device, device_id)
```

It must not call Recording or SCOPE start functions.

`status(device_id)` derives:

- acquisition state from coordinator;
- measurement state from `RuntimeStore`;
- Recording state from `RecordingManager.is_active()` (`RECORDING` or `STOPPED`);
- SCOPE state from `ScopeService.status()`.

If a stop step raises, later stages do not run. Build the result from actual post-failure subsystem state and set `failed_stage`. For a Recording stop exception, use `recording_state="ERROR"` in that command result because clean finalization was not proved; do not claim clean STOPPED from absence in `_active`. Do not add a second recorder cleanup path.

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

### Task 4: Wire Lifecycle Service into Runtime, HTTP API, and WebSocket Status

**Files:**
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/app.py`
- Modify: `src/emonio_viewer/server/api.py`
- Modify: `src/emonio_viewer/server/websocket.py`
- Modify: `src/emonio_viewer/main.py`
- Modify: `tests/integration/test_server.py`
- Modify: `tests/integration/test_websocket.py`
- Modify: `tests/integration/test_lifecycle.py`

**Interfaces:**
- Consumes: `DeviceLifecycleService.disconnect()`, `.reconnect()`, `.status()`.
- Produces HTTP routes:
  - `POST /api/v1/devices/{device_id}/disconnect`
  - `POST /api/v1/devices/{device_id}/reconnect`
- Adds `acquisition_state` without changing existing measurement-health `state`.

- [ ] **Step 1: Write failing HTTP API tests**

Test successful lifecycle endpoint payload:

```python
assert payload["device_id"] == device_config.id
assert payload["acquisition_state"] == "DISCONNECTED"
assert payload["recording_state"] == "STOPPED"
assert payload["scope_state"] == "DISCONNECTED"
assert payload["failed_stage"] is None
```

Test a lifecycle failure returns structured JSON with actual partial completion and `failed_stage`. Unknown device remains 404.

Add tests that `GET /api/v1/devices`, `GET /api/v1/devices/{id}`, and diagnostics expose additive `acquisition_state` without renaming existing `state`.

- [ ] **Step 2: Write failing WebSocket additive-field test**

Extend `tests/integration/test_websocket.py` so a live measurement envelope contains:

```python
assert payload["acquisition_state"] == "RUNNING"
assert payload["state"] in {"ONLINE", "DEGRADED", "STALE", "OFFLINE", "CONNECTING"}
```

The sample body must remain byte/value-equivalent to the existing canonical serialization aside from the new envelope field.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/integration/test_server.py tests/integration/test_websocket.py -q
```

- [ ] **Step 4: Add AppKey and application injection**

In `server/keys.py`, add a typed AppKey for `DeviceLifecycleService`. Add optional `lifecycle_service=None` to `create_app()` to preserve isolated test construction. Production `run_viewer()` must always supply the real service.

When the optional service is absent in an isolated test app, lifecycle command routes return service unavailable. Status serializers can emit `acquisition_state: null`; production must never do so because `run_viewer()` always installs the service. New lifecycle tests must inject a fake or real lifecycle service and assert real states.

- [ ] **Step 5: Add lifecycle HTTP handlers**

Both routes validate the path device through `_device_config()` before calling the service.

For lifecycle command failures:

```python
except DeviceLifecycleCommandError as exc:
    return web.json_response(exc.result.as_dict(), status=502)
```

Map invalid transition conflicts such as duplicate disconnect/reconnect to HTTP 409 only when the structured coordinator error proves the request conflicts with current lifecycle state. Cleanup/transport failures remain 502.

- [ ] **Step 6: Add lifecycle state to read responses without changing measurement state**

Create one helper that returns the lifecycle state string from the service, or `None` only for isolated app instances where no service is installed.

Add `acquisition_state` to:

- `GET /api/v1/devices` items;
- `GET /api/v1/devices/{id}`;
- diagnostics;
- `sample_to_json()` envelope.

Change `sample_to_json()` to accept an explicit optional acquisition-state argument. Do not derive or mutate any measurement value inside it.

- [ ] **Step 7: Add lifecycle state to WebSocket envelopes**

`websocket_measurements()` must read the lifecycle service from the AppKey and pass its status for the event device into `sample_to_json()`. If the service is absent only in an isolated test app, pass `None`.

Do not publish a new EventBus event just for lifecycle status. HTTP refresh remains the source for status changes when no measurement event is emitted after disconnect.

- [ ] **Step 8: Construct the lifecycle service in `run_viewer()`**

After `ScopeService()` construction:

```python
lifecycle_service = DeviceLifecycleService(
    recording,
    scope_service,
    coordinator,
    store,
)
```

Pass it to `create_app()`. Do not route complete viewer shutdown through the per-device service. Existing complete shutdown remains authoritative.

- [ ] **Step 9: Verify global shutdown regression**

Keep existing whole-viewer shutdown trace expectations. Add a case with one device already `DISCONNECTED` and prove complete shutdown still succeeds and stops all remaining running workers.

- [ ] **Step 10: Run focused tests**

```bash
python -m pytest tests/integration/test_server.py tests/integration/test_websocket.py tests/integration/test_lifecycle.py tests/integration/test_scope_api.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/emonio_viewer/server src/emonio_viewer/main.py tests/integration/test_server.py tests/integration/test_websocket.py tests/integration/test_lifecycle.py
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

- [ ] **Step 1: Write failing existing-target tests**

Build an already registered device and call `connector.connect()` for that target. Prove no second worker or qualification is started for the existing registration.

API expectation for an existing device:

```python
assert payload["state"] == "EXISTING"
assert payload["already_connected"] is True
assert payload["acquisition_state"] in {
    "RUNNING", "DISCONNECTING", "DISCONNECTED", "CONNECTING", "ERROR"
}
assert "measurement_state" in payload
```

A newly qualified device still returns `state == "CONNECTED"` because that request has direct qualification evidence.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/integration/test_target_connection.py tests/integration/test_server.py -q
```

- [ ] **Step 3: Keep connector behavior narrow**

Do not make `DeviceConnector.connect()` auto-reconnect an existing device. Keep explicit lifecycle reconnect as the sole restart authority. Preserve `ConnectionResult(device, already_connected)` unless a test proves a stronger model is required.

- [ ] **Step 4: Change only API wording/evidence fields**

For `already_connected=True`, return:

- `state: "EXISTING"`;
- `already_connected: true`;
- actual `acquisition_state`;
- actual `measurement_state`.

For a newly qualified target, return `state: "CONNECTED"` plus actual states.

- [ ] **Step 5: Run focused tests**

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

Assert that no new CSS file is introduced. `layout.css` remains responsible for target/status layout and the existing structured CSS file set stays unchanged.

- [ ] **Step 2: Run browser tests and verify RED**

```bash
python -m pytest tests/browser/test_device_lifecycle_contract.py tests/browser/test_frontend_contract.py -q
```

- [ ] **Step 3: Add API functions with structured error preservation**

Add a lifecycle-specific request helper that parses JSON on non-2xx and attaches it to `error.lifecycleResult`.

```javascript
export function disconnectDevice(deviceId) {
  return lifecycleRequest(`/api/v1/devices/${encodeURIComponent(deviceId)}/disconnect`);
}

export function reconnectDevice(deviceId) {
  return lifecycleRequest(`/api/v1/devices/${encodeURIComponent(deviceId)}/reconnect`);
}
```

The frontend must be able to display `failed_stage` and exact detail. Do not reduce lifecycle failure JSON to a plain HTTP string.

- [ ] **Step 4: Add explicit acquisition status and lifecycle button**

In the status bar add one `Acquisition` field with `id="acquisition-state"`. In `target-strip`, add one button `id="device-lifecycle-action"`. Update desktop grid columns in `layout.css`; preserve existing narrow-screen fallback.

- [ ] **Step 5: Keep disconnected devices in the selector**

Maintain a backend device-state cache keyed by `device_id`. `populateDeviceSelector()` continues to use all enabled remembered runtime-config devices. If cached acquisition state is `DISCONNECTED`, option text is:

```javascript
`${device.name} · DISCONNECTED`
```

Do not delete the option and do not remove the device from runtime config.

- [ ] **Step 6: Render lifecycle control from backend state only**

Required mapping:

```text
RUNNING       -> DISCONNECT EMONIO, enabled
DISCONNECTED  -> RECONNECT EMONIO, enabled
DISCONNECTING -> DISCONNECTING..., disabled
CONNECTING    -> CONNECTING..., disabled
ERROR         -> DISCONNECT ERROR, disabled
```

`renderBackendStatus()` and `renderMeasurementPayload()` may set `#acquisition-state` from `acquisition_state` only when it is a non-empty string. A WebSocket payload with `null` from an isolated test app must not erase a known status. Do not change measurement formatting or values.

- [ ] **Step 7: Execute one backend command and refresh affected panels**

The lifecycle button handler calls exactly one backend lifecycle command. It must not call Recording STOP or SCOPE STOP directly from JavaScript.

After backend success or structured failure, refresh:

```javascript
await Promise.all([
  refreshBackendState(),
  refreshRecordingState(),
  refreshScopeStatus(deviceId),
]);
```

Then call `applySelectedDeviceConfig()` only if the selection generation is still current.

- [ ] **Step 8: Correct target status wording**

For an existing target response, use actual backend evidence. Example:

```javascript
if (result.state === "EXISTING") {
  const evidenceState = result.acquisition_state === "DISCONNECTED"
    ? "DISCONNECTED"
    : result.measurement_state;
  setTargetStatus(`EXISTING / ${evidenceState}`, "");
} else {
  setTargetStatus("CONNECTED / VERIFIED", "connected");
}
```

Do not use `CONNECTED / EXISTING` anywhere.

- [ ] **Step 9: Extend async-state test harness**

Add stubs for `disconnectDevice` and `reconnectDevice`. Add a test where a lifecycle request for device A resolves after selection changes to B. It must not overwrite B's lifecycle status, action button, or measurement rendering.

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
- Modify: `tests/integration/test_server.py`
- Reuse: `tests/integration/fake_emonio.py`

**Interfaces:**
- Exercises the complete backend path without frontend assumptions.

- [ ] **Step 1: Add an integration test with three fake Emonios**

Test sequence:

1. Start three acquisition workers.
2. Start a real `RecordingManager` recording for the middle device.
3. Use a fake SCOPE service that reports LIVE for the middle device and records stop order.
4. Call `DeviceLifecycleService.disconnect(middle_id)`.
5. Verify the recording `session.json` contains `stopped_utc` after clean finalization.
6. Verify SCOPE stop occurred before acquisition stop.
7. Verify middle acquisition is `DISCONNECTED`, selected client is closed, and selected worker thread is dead.
8. Verify first and third devices continue increasing `cycles_valid`.
9. Reconnect the middle device.
10. Verify its qualification and next continuous cycle IDs are sequential from the last pre-disconnect cycle.
11. Verify Recording is still stopped.
12. Verify SCOPE remains disconnected.

- [ ] **Step 2: Run the focused integration tests**

```bash
python -m pytest tests/integration/test_device_acquisition_lifecycle.py tests/integration/test_server.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the existing read-only source gate directly**

The repository has no separate `ari-emonio-read-only-gate.sh`. Use the exact command already used by the acceptance script:

```bash
python3 -m pytest tests/unit/test_read_only_contract.py -q
```

Expected: PASS. No new Modbus write path is permitted.

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
- Candidate archive becomes `ARI_Emonio_Viewer_v0.4.14_Candidate.zip`.
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

Release builder test must require `ARI_Emonio_Viewer_v0.4.14_Candidate.zip` and the matching internal directory prefix.

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

Do not claim v0.4.14 field trust yet.

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

Confirm no protected scientific implementation files changed except the explicitly approved acquisition coordinator lifecycle. In particular, these must remain unchanged unless a failing test proves otherwise and the user re-approves the scope:

- `src/emonio_viewer/measurement/`
- `src/emonio_viewer/modbus/decoder.py`
- `src/emonio_viewer/modbus/protocol.py`
- `src/emonio_viewer/modbus/register_map.py`
- `src/emonio_viewer/modbus/transport.py`
- `src/emonio_viewer/scope/client.py`
- `src/emonio_viewer/scope/model.py`
- `src/emonio_viewer/scope/protocol.py`
- `src/emonio_viewer/recording/csv_writer.py`
- `src/emonio_viewer/recording/session.py`
- quadrant and validation math.

`src/emonio_viewer/scope/service.py` should also remain unchanged because the lifecycle service uses its existing `stop()` path.

- [ ] **Step 2: Run complete source publication and acceptance gates**

```bash
./tools/ari-emonio-publication-gate.sh
./tools/ari-emonio-acceptance.sh
```

Required result: every unit, integration, frontend/browser, read-only, Python compilation, and scientific sign-path gate passes.

- [ ] **Step 3: Build the candidate twice from the same commit**

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

Use system `unzip` so Unix executable mode bits are preserved:

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

From the source repository after packaged verification:

```bash
cd <source-repository-root>
sha256sum dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip
cat dist/ARI_Emonio_Viewer_v0.4.14_Candidate.zip.sha256
git rev-parse HEAD
```

The two SHA-256 values must match exactly. Report the exact candidate commit and archive hash. Do not promote `main`.

- [ ] **Step 6: Field acceptance on two machines**

Perform the approved 15-step field sequence from the specification. The critical proof is:

- Machine A can disconnect `emonio-d08a08` while its other Emonios continue;
- any active Recording for `d08a08` is finalized first;
- any active SCOPE session for `d08a08` is stopped second;
- Machine B begins receiving `d08a08` without closing Machine A;
- after Machine B releases the device, Machine A can reconnect it;
- canonical acquisition resumes with continuous cycle IDs;
- Recording and SCOPE do not restart automatically.

Only after this field evidence passes may v0.4.14 be called trusted and considered for a fast-forward merge to `main`.
