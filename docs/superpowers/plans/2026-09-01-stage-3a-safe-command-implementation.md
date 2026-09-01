# Stage 3A Safe Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one operator-initiated real Protocol V1 SAFE command and strict ACK qualification while keeping every nonzero real-control path disabled.

**Architecture:** Keep Stage 2 as the owner of the qualified real WebSocket. Refactor only the post-HELLO receive path so one task owns `websocket.receive()`, then expose narrow send/receive methods from the qualification service. Add a separate Stage-3A service that observes canonical runtime samples, constructs one fixed zero-output command, validates one ACK, and never calls the Stage-1 mock supervisor.

**Tech Stack:** Python 3.12, `asyncio`, `aiohttp`, existing `RuntimeEventBus`, Protocol V1 dataclasses, vanilla JavaScript, structured CSS, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-01-stage-3a-safe-command-design.md`

## Global Constraints

- Work only on branch `testing`.
- Design baseline is v0.4.21 Testing commit `253408a3bcf5d7ace83fd7f91b975611d1f49e24`.
- v0.4.21 is the field-qualified Stage-2 development baseline. Do not weaken it.
- Do not modify canonical P signs, Q signs, quadrant semantics, PF semantics, measurement validation, fixed-deadline acquisition, Modbus read-only behavior, register maps, decoder logic, recording, CSV precision, or SCOPE semantics.
- Do not modify `src/emonio_viewer/acquisition/**`, `src/emonio_viewer/measurement/**`, `src/emonio_viewer/modbus/**`, `src/emonio_viewer/recording/**`, `src/emonio_viewer/scope/**`, `src/emonio_viewer/runtime/events.py`, or `src/emonio_viewer/runtime/store.py`.
- Stage 3A must not add a new Modbus read or change acquisition timing.
- The real command is always `control_enabled=false`, `p_load_request=0/0/0 W`, and `q_comp_request=0/0/0`.
- The browser never supplies power values, sequence, measured data, node ID, or boot ID.
- One operator action can produce at most one COMMAND.
- No automatic retry, replay, reconnect, requalification, command generation, or nonzero request.
- ACK timeout is exactly 2.0 s.
- Sample wait timeout is exactly `2 * poll_interval_s` for the selected Emonio.
- A passing SAFE ACK must report `result="APPLIED"` and `applied_p=0/0/0 W` exactly.
- Use the existing bounded `LoadControlDiagnosticLog`; do not persist Stage-3A state or source selection.
- Preserve the existing `DEVELOPMENT / MOCK CONTROL` path and keep it isolated from the real path.

---

## File Structure

### New files

- `src/emonio_viewer/load_control/stage3a.py` — owns volatile source selection, canonical-sample boundary, one SAFE exchange, sequence allocation, ACK validation, and Stage-3A state.
- `tests/unit/test_load_control_stage3a_service.py` — deterministic service tests for source/sample/command/ACK/concurrency behavior.
- `tests/integration/test_load_control_stage3a_api.py` — API boundary tests proving the browser cannot submit command authority fields.

### Modified files

- `src/emonio_viewer/load_control/session_websocket.py` — one post-HELLO receive owner and inbound protocol queue.
- `src/emonio_viewer/load_control/qualification.py` — starts the receive owner and exposes narrow qualified transport methods; no control calculation.
- `tests/unit/test_load_control_websocket_session.py` — single-reader, STATUS, ACK, malformed-frame, disconnect, and heartbeat-preservation tests.
- `tests/unit/test_load_control_stage2_service.py` — prove Stage-2 HELLO and remote-disconnect behavior remains intact after the receive refactor.
- `src/emonio_viewer/server/keys.py` — typed AppKey for the Stage-3A service.
- `src/emonio_viewer/server/app_v0416.py` — construct/start/close the Stage-3A service without changing the active launcher.
- `src/emonio_viewer/server/load_control_api.py` — Stage-3A status/source/SAFE-test endpoints.
- `frontend/js/load-control-api.js` — small Stage-3A API wrappers.
- `frontend/js/load-control-ui.js` — source selector, state/evidence fields, and one `SEND SAFE TEST COMMAND` action.
- `frontend/css/load-control/load-control.css` — styles for the Stage-3A section only.
- `tests/browser/test_load_control_contract.py` — frontend contract and nonzero-authority prohibition.
- `tests/unit/test_release_identity.py`, `tests/unit/test_release_builder.py`, `pyproject.toml`, `src/emonio_viewer/__init__.py`, `README.md` — identify the field-test candidate as v0.4.22 Testing after feature acceptance passes.

---

### Task 1: Give the real WebSocket one post-HELLO receive owner

**Files:**
- Modify: `src/emonio_viewer/load_control/session_websocket.py`
- Modify: `tests/unit/test_load_control_websocket_session.py`

**Interfaces:**
- Consumes: existing `HelloFrame`, `AckFrame`, `StatusFrame`, `decode_frame()`, heartbeat-enabled `aiohttp` WebSocket.
- Produces: `start_receive_loop() -> None`, `receive_frame(timeout_s: float) -> AckFrame | StatusFrame`, and `wait_for_disconnect() -> None` where no caller except the receive loop calls `websocket.receive()` after HELLO.

- [ ] **Step 1: Write failing single-owner tests**

Add tests that prove the post-HELLO receiver consumes ACK/STATUS frames, `wait_for_disconnect()` does not call `receive()` itself, and malformed or non-application post-HELLO frames fail closed.

```python
async def scenario():
    websocket = FakeWebSocket([
        FakeMessage(WSMsgType.TEXT, encode_frame(_hello())),
        FakeMessage(WSMsgType.TEXT, encode_frame(_ack())),
        FakeMessage(WSMsgType.CLOSE, ""),
    ])
    session, _client = _session(websocket)
    await session.connect()
    session.start_receive_loop()
    assert await session.receive_frame(0.15) == _ack()
    await session.wait_for_disconnect()
    assert websocket.receive_calls == 3
```

Also add a STATUS case and a malformed JSON case. Update `FakeWebSocket.receive()` to increment `receive_calls`.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
pytest -q tests/unit/test_load_control_websocket_session.py
```

Expected: FAIL because `start_receive_loop()` and `receive_frame()` do not exist and the current disconnect watcher still owns `receive()`.

- [ ] **Step 3: Implement the minimal receive owner**

Use one background task after HELLO. Keep transport-only responsibility inside `WebSocketActuatorSession`.

```python
PostHelloFrame = AckFrame | StatusFrame

self._inbound: asyncio.Queue[PostHelloFrame | Exception] = asyncio.Queue()
self._disconnect_event = asyncio.Event()
self._receiver_task: asyncio.Task[None] | None = None


def start_receive_loop(self) -> None:
    if self._hello is None or not self.connected:
        raise ConnectionError("actuator HELLO is not qualified for receive loop")
    if self._receiver_task is not None:
        raise RuntimeError("actuator receive loop is already running")
    self._receiver_task = asyncio.create_task(self._receive_loop())
```

The `_receive_loop()` must be the only post-HELLO caller of `self._websocket.receive()`. For TEXT frames, decode the frame and accept only `AckFrame` or `StatusFrame`. Put accepted frames into `_inbound`. For CLOSE/CLOSED/ERROR, set the disconnect event. For malformed JSON, binary application data, HELLO, or COMMAND after HELLO, put the `ProtocolError` into `_inbound`, set the disconnect event, and terminate the loop.

Implement `receive_frame(timeout_s)` with the existing positive-seconds validation and `asyncio.wait_for(self._inbound.get(), timeout_s)`. If the queue item is an exception, raise it unchanged.

Change `wait_for_disconnect()` to wait only on `_disconnect_event`.

Change `disconnect()` to cancel/await the receiver task before closing the WebSocket and client, then clear queue/event/session state. Do not send any application frame during cleanup.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
pytest -q tests/unit/test_load_control_websocket_session.py
```

Expected: PASS, including the existing heartbeat option assertion `{"autoping": True, "heartbeat": 2.0}`.

- [ ] **Step 5: Commit**

```bash
git add src/emonio_viewer/load_control/session_websocket.py tests/unit/test_load_control_websocket_session.py
git commit -m "refactor: give actuator websocket one receive owner"
```

---

### Task 2: Preserve Stage 2 and expose a narrow qualified transport boundary

**Files:**
- Modify: `src/emonio_viewer/load_control/qualification.py`
- Modify: `tests/unit/test_load_control_stage2_service.py`

**Interfaces:**
- Consumes: Task 1 `WebSocketActuatorSession.start_receive_loop()` and `receive_frame(timeout_s)`.
- Produces:
  - `qualified_hello() -> HelloFrame | None`
  - `async send_qualified_command(command: CommandFrame) -> None`
  - `async receive_qualified_frame(timeout_s: float) -> AckFrame | StatusFrame`

- [ ] **Step 1: Write failing Stage-2 preservation and boundary tests**

Extend `FakeSession` with `start_receive_loop()`, `send_command()`, and `receive_frame()` counters. Require Stage 2 to start the receiver only after `HELLO_QUALIFIED` and to send nothing during qualification.

```python
status = await service.connect("ARI-LOAD-001")
assert status.state is QualificationState.QUALIFIED
assert factory.created[0].receive_loop_starts == 1
assert factory.created[0].sent == []
assert service.qualified_hello() == _hello()
```

Add tests that `send_qualified_command()` and `receive_qualified_frame()` reject when the service is not `QUALIFIED`, and that remote disconnect still clears `hello_qualified` and produces `WS_DISCONNECTED reason="remote"`.

- [ ] **Step 2: Run the focused tests and confirm RED**

```bash
pytest -q tests/unit/test_load_control_stage2_service.py
```

Expected: FAIL because the narrow transport methods and receiver start are not implemented.

- [ ] **Step 3: Implement the Stage-2 boundary**

After `qualify_hello(descriptor, hello)` succeeds and `_hello` is assigned, call `session.start_receive_loop()` before creating `_watch_disconnect(session)`.

Expose only the qualified identity and transport operations:

```python
def qualified_hello(self) -> HelloFrame | None:
    return self._hello if self._state is QualificationState.QUALIFIED else None

async def send_qualified_command(self, command: CommandFrame) -> None:
    if self._state is not QualificationState.QUALIFIED or self._session is None:
        raise LoadControlQualificationError("actuator is not HELLO-qualified")
    await self._session.send_command(command)

async def receive_qualified_frame(self, timeout_s: float) -> AckFrame | StatusFrame:
    if self._state is not QualificationState.QUALIFIED or self._session is None:
        raise LoadControlQualificationError("actuator is not HELLO-qualified")
    return await self._session.receive_frame(timeout_s)
```

Do not expose the raw WebSocket object or raw session object.

- [ ] **Step 4: Run Stage-2 and WebSocket tests**

```bash
pytest -q tests/unit/test_load_control_stage2_service.py tests/unit/test_load_control_websocket_session.py
```

Expected: PASS. Stage-2 qualification must still send zero application frames.

- [ ] **Step 5: Commit**

```bash
git add src/emonio_viewer/load_control/qualification.py tests/unit/test_load_control_stage2_service.py
git commit -m "refactor: expose qualified actuator transport boundary"
```

---

### Task 3: Add the Stage-3A source/sample and SAFE command service

**Files:**
- Create: `src/emonio_viewer/load_control/stage3a.py`
- Create: `tests/unit/test_load_control_stage3a_service.py`

**Interfaces:**
- Consumes: `RuntimeEventBus`, `RuntimeConfig.devices`, `LoadControlQualificationService`, `MeasurementSample`, `DiagnosticEvent`, `LoadControlDiagnosticLog`.
- Produces:

```python
class Stage3AState(str, Enum):
    IDLE = "IDLE"
    SOURCE_SELECTED = "SOURCE_SELECTED"
    READY = "READY"
    WAITING_FOR_SAMPLE = "WAITING_FOR_SAMPLE"
    COMMAND_SENT = "COMMAND_SENT"
    WAITING_FOR_ACK = "WAITING_FOR_ACK"
    PASSED = "PASSED"
    REJECTED = "REJECTED"

@dataclass(frozen=True, slots=True)
class Stage3AStatus:
    state: Stage3AState
    selected_source_id: str | None
    sample_cycle_id: int | None
    command_sequence: int | None
    ack_result: str | None
    rejection_reason: str | None
    admissible: bool

class Stage3AError(RuntimeError):
    pass

class Stage3ASafeCommandService:
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    def sources(self) -> tuple[DeviceConfig, ...]: ...
    def status(self) -> Stage3AStatus: ...
    async def select_source(self, device_id: str) -> Stage3AStatus: ...
    async def run_safe_test(self) -> Stage3AStatus: ...
```

- [ ] **Step 1: Write failing source and sample-boundary tests**

Use `real_sample` from `tests/conftest.py` and `dataclasses.replace()` to advance cycle IDs. Test:

```python
await service.start()
await service.select_source("emonio-example")
bus.publish(replace(real_sample, identity=replace(real_sample.identity, cycle_id=40)))
request = asyncio.create_task(service.run_safe_test())
await asyncio.sleep(0)
bus.publish(replace(real_sample, identity=replace(real_sample.identity, cycle_id=41)))
```

Require cycle 41, never 40, to become provenance. Add tests for no source, unknown source, invalid `poll_interval_s`, invalid sample ignored, acquisition diagnostic rejection, source change while active rejected, and timeout equal to `2 * poll_interval_s`.

- [ ] **Step 2: Run the new service tests and confirm RED**

```bash
pytest -q tests/unit/test_load_control_stage3a_service.py
```

Expected: FAIL because `stage3a.py` does not exist.

- [ ] **Step 3: Implement source tracking and request arming only**

At `start()`, subscribe to the existing bus. Keep the most recent observed cycle per configured source. Never publish measurement events.

At `select_source()`, accept only an enabled device in `RuntimeConfig.devices`; store only the device ID in memory. Do not write any file.

At `run_safe_test()`, require a selected source, a previously observed cycle boundary for that source, and a currently qualified HELLO. Capture the HELLO `node_id` and `boot_id`, set `WAITING_FOR_SAMPLE`, and wait for the first later VALID sample from that source. Use:

```python
sample_wait_timeout_s = 2.0 * source_config.poll_interval_s
```

If no later VALID sample arrives, set terminal `REJECTED` with `NO_NEW_VALID_SAMPLE` and return without calling `send_qualified_command()`.

- [ ] **Step 4: Add failing exact SAFE command tests**

Require the built `CommandFrame` to copy canonical sample evidence without transformation:

```python
assert command.control_enabled is False
assert command.p_reserve == 0.0
assert command.p_load_request == ThreePhasePower(0.0, 0.0, 0.0)
assert command.q_comp_request == ThreePhasePower(0.0, 0.0, 0.0)
assert command.measured_p == ThreePhasePower(
    sample.phase_a.measurement.p,
    sample.phase_b.measurement.p,
    sample.phase_c.measurement.p,
)
assert command.measured_q == ThreePhasePower(
    sample.phase_a.measurement.q,
    sample.phase_b.measurement.q,
    sample.phase_c.measurement.q,
)
```

Require `measurement_cycle_id` and `measurement_utc` from the accepted sample, and node/boot from the captured qualified HELLO.

- [ ] **Step 5: Implement command construction and monotonic sequence allocation**

Allocate the sequence before the send attempt and increment the next sequence immediately so a failed send never reuses the number. Start at 1 for each new Viewer process.

Before sending, re-read `qualification_service.qualified_hello()`. If it is absent or its node/boot differs from the captured identity, reject with `ACTUATOR_NOT_QUALIFIED` or `ACTUATOR_DISCONNECTED` and send nothing.

Append deterministic diagnostic events through the shared diagnostic log:

```text
SAFE_SOURCE_SELECTED
SAFE_TEST_REQUESTED
SAFE_SAMPLE_WAIT_STARTED
SAFE_SAMPLE_ACCEPTED
SAFE_COMMAND_SENT
```

Include exact source ID, sample cycle, node, boot, sequence, measured P/Q, and fixed request values as specified.

- [ ] **Step 6: Run source/command tests and confirm GREEN**

```bash
pytest -q tests/unit/test_load_control_stage3a_service.py
```

Expected: source, sample-boundary, timeout, provenance, zero-command, and sequence tests PASS. ACK tests may still be RED until Task 4.

- [ ] **Step 7: Commit**

```bash
git add src/emonio_viewer/load_control/stage3a.py tests/unit/test_load_control_stage3a_service.py
git commit -m "feat: add Stage 3A safe command service"
```

---

### Task 4: Add strict ACK qualification and terminal failure behavior

**Files:**
- Modify: `src/emonio_viewer/load_control/stage3a.py`
- Modify: `tests/unit/test_load_control_stage3a_service.py`

**Interfaces:**
- Consumes: Task 2 `receive_qualified_frame(timeout_s)` and Task 3 outstanding `CommandFrame`.
- Produces: strict ACK acceptance with deterministic rejection categories and no retry.

- [ ] **Step 1: Write the failing ACK matrix**

Create one passing ACK and mutate one field at a time. Require these exact rejection categories:

```text
ACK_PROTOCOL_MISMATCH
ACK_SESSION_MISMATCH
ACK_NODE_MISMATCH
ACK_BOOT_MISMATCH
ACK_SEQUENCE_MISMATCH
ACK_RESULT_MISMATCH
ACK_APPLIED_P_MISMATCH
```

Also test `ACK_TIMEOUT`, `ACTUATOR_DISCONNECTED`, `UNEXPECTED_ACTUATOR_FRAME`, nonzero applied P, STATUS-before-ACK, late ACK after timeout, and no automatic retry.

- [ ] **Step 2: Run the ACK tests and confirm RED**

```bash
pytest -q tests/unit/test_load_control_stage3a_service.py -k 'ack or status or disconnect or retry'
```

Expected: FAIL until ACK validation is implemented.

- [ ] **Step 3: Implement the 2.0 s ACK deadline and exact validator**

After `send_qualified_command()` returns successfully, append `SAFE_COMMAND_SENT`, set `WAITING_FOR_ACK`, and start a monotonic 2.0 s deadline.

Loop on `receive_qualified_frame(remaining_s)`. If a `StatusFrame` arrives, log it and continue without extending the original deadline. If an `AckFrame` arrives, append `SAFE_ACK_RECEIVED` and validate exact fields.

Use a deterministic validator in this order:

```python
if ack.protocol_version != 1: return "ACK_PROTOCOL_MISMATCH"
if ack.viewer_session_id != command.viewer_session_id: return "ACK_SESSION_MISMATCH"
if ack.node_id != command.node_id: return "ACK_NODE_MISMATCH"
if ack.boot_id != command.boot_id: return "ACK_BOOT_MISMATCH"
if ack.sequence != command.sequence: return "ACK_SEQUENCE_MISMATCH"
if ack.result != "APPLIED": return "ACK_RESULT_MISMATCH"
if ack.applied_p != ThreePhasePower(0.0, 0.0, 0.0): return "ACK_APPLIED_P_MISMATCH"
return None
```

On exact match, append `SAFE_ACK_QUALIFIED` then `SAFE_TEST_PASSED` and set `PASSED`.

On any mismatch, timeout, send failure, disconnect, or protocol error, append one `SAFE_TEST_REJECTED reason="..."` and set `REJECTED`. Never call `send_qualified_command()` again for the same operator request.

A later explicit `run_safe_test()` may start a new exchange only after normal admissibility checks. It must record a new cycle boundary and use the next unused sequence.

- [ ] **Step 4: Run all Stage-3A service tests**

```bash
pytest -q tests/unit/test_load_control_stage3a_service.py
```

Expected: PASS.

- [ ] **Step 5: Re-run Stage-2 and WebSocket regression tests**

```bash
pytest -q tests/unit/test_load_control_websocket_session.py tests/unit/test_load_control_stage2_service.py tests/unit/test_load_control_stage3a_service.py
```

Expected: PASS with no automatic reconnect and no Stage-2 application COMMAND.

- [ ] **Step 6: Commit**

```bash
git add src/emonio_viewer/load_control/stage3a.py tests/unit/test_load_control_stage3a_service.py
git commit -m "feat: qualify Stage 3A safe command acknowledgements"
```

---

### Task 5: Wire Stage 3A into the server with a zero-authority API

**Files:**
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Modify: `src/emonio_viewer/server/load_control_api.py`
- Create: `tests/integration/test_load_control_stage3a_api.py`

**Interfaces:**
- Consumes: `Stage3ASafeCommandService` from Task 3/4.
- Produces:
  - `GET /api/v1/load-control/stage3a/status`
  - `GET /api/v1/load-control/stage3a/sources`
  - `POST /api/v1/load-control/stage3a/source` with only `{"emonio_device_id":"..."}`
  - `POST /api/v1/load-control/stage3a/safe-test` with exactly `{}`

- [ ] **Step 1: Write failing API tests**

Test that sources are read-only, source selection is explicit, and the SAFE-test endpoint rejects any non-empty body.

```python
response = await client.post(
    "/api/v1/load-control/stage3a/safe-test",
    json={"p_load_request": {"a": 1.0, "b": 0.0, "c": 0.0}},
)
assert response.status == 400
```

Repeat with `control_enabled`, `sequence`, `node_id`, `boot_id`, `measured_p`, `measured_q`, `measurement_cycle_id`, and `measurement_utc` fields. The only accepted SAFE-test body is `{}`.

- [ ] **Step 2: Run the new API tests and confirm RED**

```bash
pytest -q tests/integration/test_load_control_stage3a_api.py
```

Expected: FAIL because the routes and app key do not exist.

- [ ] **Step 3: Add the typed service key and app lifecycle**

In `server/keys.py` add:

```python
from emonio_viewer.load_control.stage3a import Stage3ASafeCommandService

STAGE3A_SAFE_COMMAND_SERVICE_KEY = web.AppKey(
    "stage3a_safe_command_service",
    Stage3ASafeCommandService,
)
```

In `app_v0416.create_app()`, add an optional `stage3a_service` parameter for tests. If absent, construct it with `bus`, `config`, the existing `qualification_service`, and `qualification_service.diagnostic_log`.

Start it on app startup and close it on cleanup before closing the qualification service. Do not change `emonio_viewer.main_v0416:main`.

- [ ] **Step 4: Add the four API handlers**

Add a `_stage3a_service(request)` accessor and JSON serializer. The SAFE-test handler must enforce an empty object before calling the service:

```python
body = await _body(request)
if body:
    raise web.HTTPBadRequest(text="SAFE test request must not contain command fields")
status = await _stage3a_service(request).run_safe_test()
```

Map `Stage3AError` to HTTP 409. Keep all protocol identity and command fields backend-owned.

- [ ] **Step 5: Run API and app regression tests**

```bash
pytest -q tests/integration/test_load_control_stage3a_api.py tests/integration/test_load_control_stage2_api.py tests/integration/test_load_control_api.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/emonio_viewer/server/keys.py src/emonio_viewer/server/app_v0416.py src/emonio_viewer/server/load_control_api.py tests/integration/test_load_control_stage3a_api.py
git commit -m "feat: expose Stage 3A safe qualification API"
```

---

### Task 6: Add the Stage-3A UI without exposing command values

**Files:**
- Modify: `frontend/js/load-control-api.js`
- Modify: `frontend/js/load-control-ui.js`
- Modify: `frontend/css/load-control/load-control.css`
- Modify: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Consumes: Task 5 Stage-3A API.
- Produces: explicit volatile Emonio selector, Stage-3A status evidence, and one `SEND SAFE TEST COMMAND` action.

- [ ] **Step 1: Write failing frontend contract tests**

Require the source selector to start with an empty placeholder and prohibit auto-selection. Require exact visible text:

```text
STAGE 3A · SAFE PROTOCOL QUALIFICATION
NONZERO REAL CONTROL DISABLED
0 / 0 / 0 W
SEND SAFE TEST COMMAND
```

Require that the JavaScript SAFE-test request function sends exactly `{}` and contains no UI input for active-power request, Q request, sequence, node override, boot override, measured P/Q, cycle ID, or measurement timestamp.

- [ ] **Step 2: Run the frontend contract test and confirm RED**

```bash
pytest -q tests/browser/test_load_control_contract.py
```

Expected: FAIL because Stage-3A UI/API functions do not exist.

- [ ] **Step 3: Add small API wrappers**

In `load-control-api.js` add:

```javascript
export function getStage3AStatus() {
  return requestJson("/api/v1/load-control/stage3a/status");
}

export function getStage3ASources() {
  return requestJson("/api/v1/load-control/stage3a/sources");
}

export function selectStage3ASource(emonioDeviceId) {
  return requestJson("/api/v1/load-control/stage3a/source", {
    method: "POST",
    body: JSON.stringify({ emonio_device_id: emonioDeviceId }),
  });
}

export function runStage3ASafeTest() {
  return requestJson("/api/v1/load-control/stage3a/safe-test", {
    method: "POST",
    body: "{}",
  });
}
```

- [ ] **Step 4: Add the SAFE command qualification section**

Keep the existing LAN/HELLO sections. Change the primary panel eyebrow to `STAGE 3A · SAFE PROTOCOL QUALIFICATION` and the header safety badge to `NONZERO REAL CONTROL DISABLED`.

Add one section after HELLO qualification and before the diagnostic log. It contains:

- Emonio source selector with placeholder `Choose Emonio source`;
- Stage-3A state;
- selected source;
- accepted sample cycle;
- last/outstanding sequence;
- ACK result or rejection reason;
- fixed request text `0 / 0 / 0 W`;
- `SEND SAFE TEST COMMAND` button.

Do not auto-select the first source. Disable the button unless backend status reports `admissible=true` and no exchange is active. One click calls `runStage3ASafeTest()` once, disables the button until the response returns, then refreshes Stage-3A status and the diagnostic log.

Do not add any numeric power input.

- [ ] **Step 5: Add structured CSS only in the existing load-control stylesheet**

Use new classes under the existing `.load-control-*` namespace. Do not add inline styles and do not modify unrelated CSS files.

- [ ] **Step 6: Run frontend contract tests**

```bash
pytest -q tests/browser/test_load_control_contract.py tests/browser/test_frontend_contract.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/js/load-control-api.js frontend/js/load-control-ui.js frontend/css/load-control/load-control.css tests/browser/test_load_control_contract.py
git commit -m "feat: add Stage 3A safe qualification UI"
```

---

### Task 7: Add cross-boundary regression tests for one-command-only behavior

**Files:**
- Modify: `tests/integration/test_load_control_stage3a_api.py`
- Modify: `tests/unit/test_load_control_stage3a_service.py`
- Modify: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Consumes: complete Tasks 1-6 implementation.
- Produces: measurable proof that one operator request cannot fan out into multiple commands and terminal failures cannot auto-retry.

- [ ] **Step 1: Add one-command-only tests**

Cover all of these cases with a fake qualification transport that records sent frames:

```text
valid sample + valid ACK -> exactly 1 COMMAND
valid sample + ACK timeout -> exactly 1 COMMAND
valid sample + bad ACK -> exactly 1 COMMAND
send failure -> exactly 1 attempted sequence, 0 retry
source timeout -> 0 COMMAND
source acquisition failure -> 0 COMMAND
actuator disconnect before send -> 0 COMMAND
second concurrent browser request -> HTTP 409 and no second COMMAND
```

- [ ] **Step 2: Add diagnostic-log ordering assertions**

For PASS, require this order:

```text
SAFE_TEST_REQUESTED
SAFE_SAMPLE_WAIT_STARTED
SAFE_SAMPLE_ACCEPTED
SAFE_COMMAND_SENT
SAFE_ACK_RECEIVED
SAFE_ACK_QUALIFIED
SAFE_TEST_PASSED
```

For failure, require one terminal `SAFE_TEST_REJECTED` and no later `SAFE_TEST_PASSED` for that sequence.

- [ ] **Step 3: Run the Stage-3A focused suite**

```bash
pytest -q \
  tests/unit/test_load_control_websocket_session.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage3a_service.py \
  tests/integration/test_load_control_stage3a_api.py \
  tests/browser/test_load_control_contract.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_load_control_stage3a_service.py tests/integration/test_load_control_stage3a_api.py tests/browser/test_load_control_contract.py
git commit -m "test: lock Stage 3A one-command safety boundary"
```

---

### Task 8: Identify the field-test candidate as v0.4.22 Testing

**Files:**
- Modify: `tests/unit/test_release_identity.py`
- Modify: `tests/unit/test_release_builder.py`
- Modify: `pyproject.toml`
- Modify: `src/emonio_viewer/__init__.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-7 passing implementation.
- Produces: unambiguous v0.4.22 Testing identity for field evidence while keeping v0.4.21 documented as the trusted Stage-2 baseline.

- [ ] **Step 1: Change release tests first and confirm RED**

Require project/package identity `0.4.22`, README label `v0.4.22 Testing`, and candidate archive `ARI_Emonio_Viewer_v0.4.22_Candidate.zip`.

Run:

```bash
pytest -q tests/unit/test_release_identity.py tests/unit/test_release_builder.py
```

Expected: FAIL against current v0.4.21 metadata.

- [ ] **Step 2: Update version metadata**

Set:

```toml
version = "0.4.22"
```

and:

```python
__version__ = "0.4.22"
```

Update README so `testing` is identified as `v0.4.22 Testing`. State that v0.4.21 remains the field-qualified Stage-2 baseline until v0.4.22 field acceptance succeeds. Do not claim Stage 3A field qualification.

- [ ] **Step 3: Run release tests and confirm GREEN**

```bash
pytest -q tests/unit/test_release_identity.py tests/unit/test_release_builder.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_release_identity.py tests/unit/test_release_builder.py pyproject.toml src/emonio_viewer/__init__.py README.md
git commit -m "release: identify v0.4.22 Stage 3A testing candidate"
```

---

### Task 9: Run full acceptance and protected-path gates before field use

**Files:**
- No production file changes unless a test exposes a defect.

**Interfaces:**
- Consumes: exact v0.4.22 candidate commit.
- Produces: automated evidence only. It does not produce field qualification.

- [ ] **Step 1: Run the complete repository acceptance**

```bash
./tools/ari-emonio-acceptance.sh
```

Expected: all six acceptance sections PASS: unit, integration, frontend contract, read-only source gate, Python compilation, and scientific sign path.

- [ ] **Step 2: Run the protected scientific path gate**

```bash
git diff --exit-code b539efe7eb3a11d53a3b291254ddd0c50a2cf3df HEAD -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: no output and exit status 0.

- [ ] **Step 3: Verify the active launcher remains unchanged**

```bash
grep -q 'emonio_viewer.main_v0416:main' pyproject.toml
```

Expected: exit status 0.

- [ ] **Step 4: Inspect the implementation diff for scope**

```bash
git diff --stat 253408a3bcf5d7ace83fd7f91b975611d1f49e24..HEAD
git diff --name-only 253408a3bcf5d7ace83fd7f91b975611d1f49e24..HEAD
```

Expected: only Stage-3A load-control, server wiring, frontend load-control, tests, docs, and release metadata files. No protected scientific path may appear.

- [ ] **Step 5: Push the exact candidate and require GitHub `Testing Acceptance` success**

```bash
git push origin testing
```

Record the exact commit SHA and the successful workflow run. Do not call automated acceptance a field PASS.

---

### Task 10: Perform the first Stage-3A field qualification without physical output

**Files:**
- No source changes during the test.

**Interfaces:**
- Consumes: exact accepted v0.4.22 Testing commit and the software-only ARI Load Test Actuator.
- Produces: field evidence for the first real zero-output COMMAND/ACK exchange only.

- [ ] **Step 1: Establish normal Stage-2 evidence**

Start Viewer v0.4.22, confirm normal Emonio acquisition, run LAN scan, explicitly select `ARI-LOAD-001`, and `CONNECT / QUALIFY` it. Confirm HELLO remains qualified and control authority is not nonzero-enabled.

- [ ] **Step 2: Select one Emonio explicitly**

Use the Stage-3A selector. Do not accept any automatic selection.

- [ ] **Step 3: Press `SEND SAFE TEST COMMAND` once**

Expected Viewer evidence:

```text
SAFE_TEST_REQUESTED
SAFE_SAMPLE_WAIT_STARTED
SAFE_SAMPLE_ACCEPTED
SAFE_COMMAND_SENT
SAFE_ACK_RECEIVED
SAFE_ACK_QUALIFIED
SAFE_TEST_PASSED
```

The accepted sample cycle must be later than the recorded request boundary.

- [ ] **Step 4: Verify the exact protocol evidence**

Confirm the one sent COMMAND has:

```text
control_enabled=false
p_load_request=0/0/0 W
q_comp_request=0/0/0
```

Confirm the ACK arrives within 2.0 s with:

```text
result=APPLIED
applied_p=0/0/0 W
```

Confirm node ID, boot ID, viewer session ID, protocol version, and sequence match exactly.

- [ ] **Step 5: Verify no second command appears**

Wait longer than the normal Emonio poll interval and ACK timeout. The diagnostic log and actuator serial log must show no automatic second COMMAND.

- [ ] **Step 6: Capture independent ESP32 serial evidence**

Record the received COMMAND and emitted ACK from the actuator side. Viewer log alone is not independent proof of what firmware received.

- [ ] **Step 7: Run the required negative field checks before Stage 3B**

At minimum, separately qualify:

```text
ACK timeout -> REJECTED, no retry
ACK identity mismatch -> REJECTED, no retry
actuator reboot/disconnect -> old Stage-3A exchange invalidated, no auto-reconnect
```

Do not authorize nonzero commands until these field checks pass and a separate Stage-3B design is approved.
