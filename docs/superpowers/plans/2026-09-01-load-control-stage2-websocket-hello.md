# ARI Emonio Viewer Stage 2 WebSocket HELLO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add operator-selected real WebSocket connection and strict HELLO qualification for a discovered ARI load actuator, while keeping external control disabled and sending no COMMAND frame.

**Architecture:** Preserve the existing Stage-1 mock-control service and the existing read-only LAN discovery service. Extend the existing WebSocket transport with a backward-compatible two-step connection interface, then add one independent qualification service that resolves an operator-selected `node_id` from the latest LAN discovery evidence, opens the stored WebSocket locator, validates the first HELLO frame, and owns only qualification state. Wire that service through the active `app_v0416.py` compatibility application and expose a separate UI section for explicit qualification.

**Tech Stack:** Python 3.11+, `aiohttp`, `asyncio`, existing ARI load-control protocol V1 models, vanilla JavaScript, structured CSS, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-01-load-control-stage2-websocket-hello-design.md`

## Global Constraints

- Target branch: `testing`.
- Viewer baseline: ARI Emonio Viewer v0.4.19.
- Do not modify canonical P signs.
- Do not modify canonical Q signs.
- Do not modify quadrant semantics.
- Do not modify power-factor semantics.
- Do not modify measurement validation.
- Do not modify fixed-deadline acquisition.
- Do not modify Emonio polling.
- Do not modify Modbus transport or read-only behavior.
- Do not modify register maps or decoder logic.
- Do not modify recording semantics or CSV precision.
- Do not modify SCOPE measurement semantics.
- Protected production directories are `src/emonio_viewer/acquisition/**`, `src/emonio_viewer/measurement/**`, `src/emonio_viewer/modbus/**`, `src/emonio_viewer/recording/**`, and `src/emonio_viewer/scope/**`.
- Preserve the Stage-1 mock-control path in `src/emonio_viewer/load_control/service.py`.
- Preserve operator-triggered read-only mDNS discovery.
- The browser must submit only `node_id` for Stage-2 selection. It must not submit an IP address, port, path, or replacement WebSocket URL.
- The backend must resolve the selected node against `LanActuatorDiscoveryService.last_result`.
- The qualified actuator instance identity is `node_id + current boot_id`. IP address is only a transport locator.
- WebSocket connect timeout is `3.0 s`.
- First HELLO receive timeout is `2.0 s`.
- `p_max` discovery-to-HELLO comparison uses exact numeric equality after strict finite positive validation.
- No tolerance, clamp, repair, replacement, or default is permitted for HELLO qualification.
- No automatic actuator selection.
- No automatic binding.
- No automatic external-control enable.
- No automatic reconnect.
- Stage 2 must not send COMMAND under any condition.
- Stage 2 must not expose a command-send method.
- External control must remain `DISABLED` after successful HELLO qualification.
- Do not change the project version in this plan. Version promotion is a separate release decision.

---

## File Structure

### New production file

`src/emonio_viewer/load_control/qualification.py`

One responsibility: own real actuator connection qualification only. It shall contain the Stage-2 qualification state, qualification error type, immutable status snapshot, strict discovery-to-HELLO comparison, connection lifecycle, and read-only disconnect watcher. It shall not import measurement, Modbus, recording, SCOPE, controller, supervisor, COMMAND, or ACK code.

### Existing production files with small changes

`src/emonio_viewer/load_control/session_websocket.py`

Keep the current generic transport responsibility. Add `open()`, `receive_hello()`, and `wait_for_disconnect()` while preserving the current `connect()` behavior as a compatibility wrapper.

`src/emonio_viewer/server/keys.py`

Add one typed `web.AppKey` for the qualification service.

`src/emonio_viewer/server/load_control_api.py`

Add qualification service lookup and three Stage-2 routes. Keep all existing Stage-1 routes unchanged.

`src/emonio_viewer/server/app_v0416.py`

Construct or accept the qualification service, store it under the new AppKey, and close it during application cleanup. Do not change `main.py` or `main_v0416.py`.

`frontend/js/load-control-api.js`

Add three API helpers for qualification connect, status, and disconnect.

`frontend/js/load-control-ui.js`

Add explicit `SELECT / QUALIFY`, qualification evidence rendering, and `DISCONNECT`. Keep existing mock binding controls separate. Correct `Physical max` to `Advertised test limit`.

`frontend/css/load-control/load-control.css`

Add only Stage-2 qualification layout/state styles. Keep load-control styles in this structured CSS file.

### New and updated tests

`tests/unit/test_load_control_websocket_session.py`

Extend transport tests for two-step connection, first-frame HELLO, disconnect watching, and compatibility of `connect()`.

`tests/unit/test_load_control_hello_qualification.py`

Test the pure discovery-to-HELLO rules.

`tests/unit/test_load_control_stage2_service.py`

Test operator selection, lifecycle states, no automatic selection, reconnect rules, boot changes, disconnect invalidation, and zero sent frames.

`tests/unit/test_load_control_stage2_contract.py`

Test the architectural no-control/no-scientific-import boundary.

`tests/integration/test_load_control_stage2_api.py`

Test the new HTTP routes and application service boundary.

`tests/browser/test_load_control_contract.py`

Update the browser contract from Stage 1 wording to Stage 2 wording while preserving the existing mock-control and no-command assertions.

---

### Task 1: Extend the WebSocket Transport Without Breaking Stage 1

**Files:**
- Modify: `src/emonio_viewer/load_control/session_websocket.py`
- Modify: `tests/unit/test_load_control_websocket_session.py`

**Interfaces:**
- Consumes: existing `ActuatorDescriptor`, `HelloFrame`, `decode_frame()`, `ClientSession`, and explicit connect/receive timeout values.
- Produces: `async WebSocketActuatorSession.open() -> None`, `async WebSocketActuatorSession.receive_hello() -> HelloFrame`, `async WebSocketActuatorSession.wait_for_disconnect() -> None`, and the existing `async connect() -> HelloFrame` preserved as a compatibility wrapper.

- [ ] **Step 1: Add failing tests for the two-step transport interface.**

Add tests that prove the socket is open before HELLO is consumed and that `receive_hello()` still requires HELLO as the first application frame.

```python
def test_websocket_session_supports_open_then_receive_hello() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket([FakeMessage(WSMsgType.TEXT, encode_frame(_hello()))])
        client = FakeClientSession(websocket)
        session = WebSocketActuatorSession(
            _descriptor(),
            connect_timeout_s=0.25,
            receive_timeout_s=0.15,
            client_session_factory=lambda: client,
        )

        await session.open()
        assert session.connected is True
        assert websocket.messages

        hello = await session.receive_hello()
        assert hello == _hello()
        assert websocket.messages == []

        await session.disconnect()

    asyncio.run(scenario())
```

Add a first-frame rejection test with an encoded ACK or COMMAND frame and assert `ProtocolError` with `first actuator frame must be HELLO`.

- [ ] **Step 2: Run the new transport tests and verify RED.**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_websocket_session.py -q
```

Expected result: FAIL because `open()`, `receive_hello()`, and `wait_for_disconnect()` do not exist yet.

- [ ] **Step 3: Implement the minimal two-step transport.**

Refactor the current `connect()` body into these methods without changing timeout validation or cleanup behavior:

```python
async def open(self) -> None:
    if self.connected:
        raise RuntimeError("actuator WebSocket is already connected")
    self._client = self._client_session_factory()
    try:
        self._websocket = await self._wait_for(
            self._client.ws_connect(self.descriptor.location),
            self._connect_timeout_s,
        )
    except Exception:
        await self.disconnect()
        raise

async def receive_hello(self) -> HelloFrame:
    if not self.connected:
        raise ConnectionError("actuator WebSocket is not connected")
    if self._hello is not None:
        raise RuntimeError("actuator HELLO was already received")
    try:
        frame = decode_frame(await self._receive_text())
        if not isinstance(frame, HelloFrame):
            raise ProtocolError("first actuator frame must be HELLO")
        self._hello = frame
        return frame
    except Exception:
        await self.disconnect()
        raise

async def connect(self) -> HelloFrame:
    await self.open()
    return await self.receive_hello()
```

Add a transport-only disconnect watcher that sends no frame. It may consume inbound post-HELLO frames because Stage 2 has no post-HELLO application-frame responsibility. It returns only when the transport reports close, closed, or error:

```python
async def wait_for_disconnect(self) -> None:
    if not self.connected:
        raise ConnectionError("actuator WebSocket is not connected")
    while self.connected:
        message = await self._websocket.receive()
        if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
            return
```

Do not call `send_str()` from this method.

- [ ] **Step 4: Add a disconnect-watcher test.**

Extend `FakeWebSocket.receive()` data with a close message after HELLO. Prove that `wait_for_disconnect()` returns and `websocket.sent == []`.

```python
websocket = FakeWebSocket([
    FakeMessage(WSMsgType.TEXT, encode_frame(_hello())),
    FakeMessage(WSMsgType.CLOSE, ""),
])
await session.connect()
await session.wait_for_disconnect()
assert websocket.sent == []
```

- [ ] **Step 5: Run transport tests and verify GREEN.**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_websocket_session.py -q
```

Expected result: PASS, including the existing command/ACK compatibility test and wrong-boot command rejection test.

- [ ] **Step 6: Commit the transport change.**

```bash
git add src/emonio_viewer/load_control/session_websocket.py tests/unit/test_load_control_websocket_session.py
git commit -m "feat: expose staged actuator WebSocket connection"
```

---

### Task 2: Implement Pure HELLO Qualification Rules

**Files:**
- Create: `src/emonio_viewer/load_control/qualification.py`
- Create: `tests/unit/test_load_control_hello_qualification.py`

**Interfaces:**
- Consumes: `ActuatorDescriptor`, `ThreePhasePower`, `HelloFrame`.
- Produces: `QualificationState`, `LoadControlQualificationError`, `QualificationStatus`, and `qualify_hello(descriptor: ActuatorDescriptor, hello: HelloFrame) -> None`.

- [ ] **Step 1: Write failing tests for all discovery-to-HELLO comparisons.**

Create helpers that build one valid descriptor and one valid HELLO. Add parameterized tests for node mismatch, empty boot ID, wrong class, missing capability, and A/B/C `p_max` mismatch. Protocol structural invalidity remains covered by `test_load_control_protocol.py`; these tests cover the Stage-2 cross-check only.

```python
@pytest.mark.parametrize(
    "hello, expected",
    [
        (replace(_hello(), node_id="ARI-LOAD-OTHER"), "node_id"),
        (replace(_hello(), boot_id=""), "boot_id"),
        (replace(_hello(), device_class="OTHER"), "device_class"),
        (replace(_hello(), capabilities=()), "ACTIVE_LOAD_CONTROL"),
        (replace(_hello(), p_max=ThreePhasePower(999.0, 1000.0, 1000.0)), "p_max.a"),
        (replace(_hello(), p_max=ThreePhasePower(1000.0, 999.0, 1000.0)), "p_max.b"),
        (replace(_hello(), p_max=ThreePhasePower(1000.0, 1000.0, 999.0)), "p_max.c"),
    ],
)
def test_hello_qualification_rejects_discovery_mismatch(hello, expected) -> None:
    with pytest.raises(LoadControlQualificationError, match=expected):
        qualify_hello(_descriptor(), hello)
```

Add one valid test that returns `None` and changes no input object.

- [ ] **Step 2: Run the new qualification tests and verify RED.**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_hello_qualification.py -q
```

Expected result: FAIL because `qualification.py` does not exist.

- [ ] **Step 3: Add the Stage-2 types and exact qualification function.**

Use a separate state model. Do not reuse `SessionState` from the Stage-1 supervisor.

```python
from dataclasses import dataclass
from enum import Enum

class QualificationState(str, Enum):
    IDLE = "IDLE"
    DISCOVERED = "DISCOVERED"
    CONNECTING = "CONNECTING"
    HELLO_WAIT = "HELLO_WAIT"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    DISCONNECTED = "DISCONNECTED"

class LoadControlQualificationError(RuntimeError):
    pass
```

Use an immutable snapshot so API serialization cannot mutate service state:

```python
@dataclass(frozen=True)
class QualificationStatus:
    state: QualificationState
    connected: bool
    hello_qualified: bool
    selected_node_id: str | None
    node_id: str | None
    boot_id: str | None
    protocol_version: int | None
    device_class: str | None
    capabilities: tuple[str, ...]
    p_max: ThreePhasePower | None
    location: str | None
    last_error: str | None
```

Implement exact cross-checks:

```python
def qualify_hello(descriptor: ActuatorDescriptor, hello: HelloFrame) -> None:
    if hello.protocol_version != 1:
        raise LoadControlQualificationError("protocol_version mismatch")
    if hello.node_id != descriptor.node_id:
        raise LoadControlQualificationError("node_id mismatch")
    if not hello.boot_id:
        raise LoadControlQualificationError("boot_id must be non-empty")
    if hello.device_class != "ARI_LOAD_ACTUATOR":
        raise LoadControlQualificationError("device_class mismatch")
    if "ACTIVE_LOAD_CONTROL" not in hello.capabilities:
        raise LoadControlQualificationError("ACTIVE_LOAD_CONTROL capability missing")
    if hello.p_max.a != descriptor.p_max.a:
        raise LoadControlQualificationError("p_max.a mismatch")
    if hello.p_max.b != descriptor.p_max.b:
        raise LoadControlQualificationError("p_max.b mismatch")
    if hello.p_max.c != descriptor.p_max.c:
        raise LoadControlQualificationError("p_max.c mismatch")
```

Do not add tolerance logic. Do not copy descriptor values into HELLO.

- [ ] **Step 4: Run the pure qualification tests and protocol tests.**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_hello_qualification.py tests/unit/test_load_control_protocol.py -q
```

Expected result: PASS.

- [ ] **Step 5: Commit the qualification rule layer.**

```bash
git add src/emonio_viewer/load_control/qualification.py tests/unit/test_load_control_hello_qualification.py
git commit -m "feat: add strict actuator HELLO qualification"
```

---

### Task 3: Add the Independent Stage-2 Qualification Service

**Files:**
- Modify: `src/emonio_viewer/load_control/qualification.py`
- Create: `tests/unit/test_load_control_stage2_service.py`
- Create: `tests/unit/test_load_control_stage2_contract.py`

**Interfaces:**
- Consumes: `LanActuatorDiscoveryService.last_result`, `WebSocketActuatorSession`, `qualify_hello()`.
- Produces: `LoadControlQualificationService.connect(node_id: str) -> QualificationStatus`, `status() -> QualificationStatus`, `disconnect() -> QualificationStatus`, and `close() -> None`.

- [ ] **Step 1: Write the service lifecycle tests before service code.**

Use a fake discovery service with a mutable `last_result` tuple and a fake session factory. The fake session must record state transitions and sent frames. Cover these cases as separate tests:

```text
IDLE before operator selection
no automatic selection from one discovered descriptor
selected node missing -> conflict error
duplicate selected node_id -> conflict error
successful state order DISCOVERED -> CONNECTING -> HELLO_WAIT -> QUALIFIED
valid HELLO stores node_id + boot_id
second connect while open -> conflict error
disconnect -> DISCONNECTED and qualified identity cleared
reconnect requires receive_hello again
same node_id with new boot_id -> new qualified boot instance
remote disconnect watcher -> DISCONNECTED
successful qualification sends zero frames
rejected qualification sends zero frames
close sends zero frames
```

For state-order evidence, let the fake session callbacks inspect `service.status().state` when `open()` and `receive_hello()` are entered.

- [ ] **Step 2: Run the service tests and verify RED.**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_stage2_service.py -q
```

Expected result: FAIL because `LoadControlQualificationService` does not exist.

- [ ] **Step 3: Implement the service constructor and descriptor resolver.**

Use explicit defaults and dependency injection:

```python
class LoadControlQualificationService:
    def __init__(
        self,
        lan_discovery_service: LanActuatorDiscoveryService,
        *,
        connect_timeout_s: float = 3.0,
        receive_timeout_s: float = 2.0,
        session_factory=WebSocketActuatorSession,
        create_task=asyncio.create_task,
    ) -> None:
        self._lan_discovery_service = lan_discovery_service
        self._connect_timeout_s = connect_timeout_s
        self._receive_timeout_s = receive_timeout_s
        self._session_factory = session_factory
        self._create_task = create_task
        self._state = QualificationState.IDLE
        self._selected_descriptor = None
        self._hello = None
        self._session = None
        self._watch_task = None
        self._last_error = None
```

Resolve exactly one descriptor:

```python
def _resolve_descriptor(self, node_id: str) -> ActuatorDescriptor:
    if not isinstance(node_id, str) or not node_id:
        raise LoadControlQualificationError("node_id is required")
    matches = tuple(
        item for item in self._lan_discovery_service.last_result
        if item.node_id == node_id
    )
    if not matches:
        raise LoadControlQualificationError("selected node_id is not in the latest LAN discovery result")
    if len(matches) != 1:
        raise LoadControlQualificationError("selected node_id is ambiguous in the latest LAN discovery result")
    return matches[0]
```

Do not accept a location parameter from the caller.

- [ ] **Step 4: Implement the deterministic connect state sequence.**

The order must be observable and fixed:

```python
async def connect(self, node_id: str) -> QualificationStatus:
    if self._session is not None and self._session.connected:
        raise LoadControlQualificationError("a Stage-2 actuator connection is already open")

    descriptor = self._resolve_descriptor(node_id)
    self._selected_descriptor = descriptor
    self._hello = None
    self._last_error = None
    self._state = QualificationState.DISCOVERED

    session = self._session_factory(
        descriptor,
        connect_timeout_s=self._connect_timeout_s,
        receive_timeout_s=self._receive_timeout_s,
    )
    self._session = session

    try:
        self._state = QualificationState.CONNECTING
        await session.open()
        self._state = QualificationState.HELLO_WAIT
        hello = await session.receive_hello()
        qualify_hello(descriptor, hello)
        self._hello = hello
        self._state = QualificationState.QUALIFIED
        self._watch_task = self._create_task(self._watch_disconnect(session))
        return self.status()
    except Exception as exc:
        self._hello = None
        self._last_error = str(exc)
        self._state = QualificationState.REJECTED
        await session.disconnect()
        self._session = None
        return self.status()
```

Transport/protocol/HELLO failures return a `REJECTED` status. Operator precondition conflicts from `_resolve_descriptor()` or an already open session raise `LoadControlQualificationError` before a transport attempt.

- [ ] **Step 5: Implement status serialization and qualified identity clearing.**

`status()` must never present rejected HELLO identity as qualified data. Keep selection evidence separate:

```python
def status(self) -> QualificationStatus:
    hello = self._hello if self._state is QualificationState.QUALIFIED else None
    return QualificationStatus(
        state=self._state,
        connected=bool(self._session is not None and self._session.connected),
        hello_qualified=hello is not None,
        selected_node_id=(self._selected_descriptor.node_id if self._selected_descriptor else None),
        node_id=(hello.node_id if hello else None),
        boot_id=(hello.boot_id if hello else None),
        protocol_version=(hello.protocol_version if hello else None),
        device_class=(hello.device_class if hello else None),
        capabilities=(hello.capabilities if hello else ()),
        p_max=(hello.p_max if hello else None),
        location=(self._selected_descriptor.location if self._selected_descriptor else None),
        last_error=self._last_error,
    )
```

- [ ] **Step 6: Implement disconnect and remote-disconnect invalidation.**

The watcher must not reconnect and must not send a frame:

```python
async def _watch_disconnect(self, session) -> None:
    try:
        await session.wait_for_disconnect()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if session is self._session:
            self._last_error = str(exc)
    finally:
        if session is self._session:
            await session.disconnect()
            self._session = None
            self._hello = None
            self._state = QualificationState.DISCONNECTED
```

Operator disconnect must cancel the watcher before closing the same session so the watcher cannot race the explicit state update:

```python
async def disconnect(self) -> QualificationStatus:
    watch_task = self._watch_task
    self._watch_task = None
    if watch_task is not None and watch_task is not asyncio.current_task():
        watch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watch_task

    session = self._session
    self._session = None
    self._hello = None
    self._last_error = None
    if session is not None:
        await session.disconnect()
        self._state = QualificationState.DISCONNECTED
    elif self._state is not QualificationState.IDLE:
        self._state = QualificationState.DISCONNECTED
    return self.status()

async def close(self) -> None:
    await self.disconnect()
```

Keep the selected descriptor as selection evidence after disconnect, but keep qualified HELLO identity cleared.

- [ ] **Step 7: Add the architecture contract test.**

Create a source contract that proves `qualification.py` has no control/scientific dependency and no command-send API:

```python
from pathlib import Path


def test_stage2_qualification_has_no_measurement_or_command_authority() -> None:
    source = Path("src/emonio_viewer/load_control/qualification.py").read_text(encoding="utf-8")
    for forbidden in (
        "emonio_viewer.measurement",
        "emonio_viewer.modbus",
        "emonio_viewer.recording",
        "emonio_viewer.scope",
        "LoadControlSupervisor",
        "MeasurementSample",
        "CommandFrame",
        "AckFrame",
        "send_command(",
    ):
        assert forbidden not in source
```

Also assert the existing `tests/unit/test_load_control_stage1_contract.py` still passes unchanged.

- [ ] **Step 8: Run Stage-2 unit tests and Stage-1 control contracts.**

Run:

```bash
python3 -m pytest \
  tests/unit/test_load_control_hello_qualification.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage2_contract.py \
  tests/unit/test_load_control_stage1_contract.py \
  tests/unit/test_load_control_websocket_session.py -q
```

Expected result: PASS.

- [ ] **Step 9: Commit the Stage-2 service.**

```bash
git add src/emonio_viewer/load_control/qualification.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage2_contract.py
git commit -m "feat: add isolated actuator qualification service"
```

---

### Task 4: Add Stage-2 HTTP API and Active Application Wiring

**Files:**
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/load_control_api.py`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Create: `tests/integration/test_load_control_stage2_api.py`
- Modify: `tests/unit/test_load_control_lan_discovery_app_wiring.py`

**Interfaces:**
- Consumes: `LoadControlQualificationService`, existing `LanActuatorDiscoveryService`, `register_load_control_routes()`.
- Produces: `LOAD_CONTROL_QUALIFICATION_SERVICE_KEY` and three HTTP routes.

- [ ] **Step 1: Write failing API tests.**

Create a fake qualification service with `connect`, `status`, and `disconnect`. Add these tests:

```text
GET /api/v1/load-control/lan-qualification/status -> current snapshot
POST /api/v1/load-control/lan-qualification/connect with node_id -> service.connect(node_id)
POST connect without node_id -> 400
POST connect with unknown/ambiguous/already-open service conflict -> 409
POST /api/v1/load-control/lan-qualification/disconnect -> service.disconnect()
existing /lan-discovery/scan route remains present and unchanged
```

Use an exact JSON serializer helper for `QualificationStatus` in the server module. Expected qualified JSON:

```python
{
    "state": "QUALIFIED",
    "connected": True,
    "hello_qualified": True,
    "selected_node_id": "ARI-LOAD-001",
    "node_id": "ARI-LOAD-001",
    "boot_id": "BOOT-001",
    "protocol_version": 1,
    "device_class": "ARI_LOAD_ACTUATOR",
    "capabilities": ["ACTIVE_LOAD_CONTROL"],
    "p_max": {"a": 1000.0, "b": 1000.0, "c": 1000.0},
    "location": "ws://192.168.1.141:8080/load-control",
    "last_error": None,
}
```

- [ ] **Step 2: Run API tests and verify RED.**

Run:

```bash
python3 -m pytest tests/integration/test_load_control_stage2_api.py -q
```

Expected result: FAIL because the key and routes do not exist.

- [ ] **Step 3: Add the typed AppKey.**

In `server/keys.py`, import `LoadControlQualificationService` and add:

```python
LOAD_CONTROL_QUALIFICATION_SERVICE_KEY = web.AppKey(
    "load_control_qualification_service",
    LoadControlQualificationService,
)
```

Do not change existing keys.

- [ ] **Step 4: Add API lookup, serialization, and routes.**

Register exactly:

```python
app.router.add_post("/api/v1/load-control/lan-qualification/connect", connect_lan_actuator)
app.router.add_get("/api/v1/load-control/lan-qualification/status", get_lan_qualification_status)
app.router.add_post("/api/v1/load-control/lan-qualification/disconnect", disconnect_lan_actuator)
```

Add `_qualification_service(request)` parallel to `_lan_discovery_service(request)`.

Serialize `QualificationStatus` explicitly. Do not return `dataclasses.asdict()` because enum and nested model representation must remain an API decision:

```python
def _qualification_json(status: QualificationStatus) -> dict:
    p_max = status.p_max
    return {
        "state": status.state.value,
        "connected": status.connected,
        "hello_qualified": status.hello_qualified,
        "selected_node_id": status.selected_node_id,
        "node_id": status.node_id,
        "boot_id": status.boot_id,
        "protocol_version": status.protocol_version,
        "device_class": status.device_class,
        "capabilities": list(status.capabilities),
        "p_max": None if p_max is None else {"a": p_max.a, "b": p_max.b, "c": p_max.c},
        "location": status.location,
        "last_error": status.last_error,
    }
```

Connect handler:

```python
async def connect_lan_actuator(request: web.Request) -> web.Response:
    body = await _body(request)
    node_id = _required_text(body, "node_id")
    try:
        status = await _qualification_service(request).connect(node_id)
    except LoadControlQualificationError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response(_qualification_json(status))
```

Status and disconnect handlers call only the qualification service. They must not call `_service(request).configure_binding()`, `enable()`, or any command function.

- [ ] **Step 5: Wire the qualification service into `app_v0416.py`.**

Extend `create_app()` with an injectable optional parameter:

```python
qualification_service: LoadControlQualificationService | None = None,
```

After `lan_discovery_service` is constructed, create the qualification service from that same instance:

```python
if qualification_service is None:
    qualification_service = LoadControlQualificationService(lan_discovery_service)
app[LOAD_CONTROL_QUALIFICATION_SERVICE_KEY] = qualification_service
```

Add cleanup only:

```python
async def stop_load_control_qualification(_app: web.Application) -> None:
    await qualification_service.close()

app.on_cleanup.append(stop_load_control_qualification)
```

Do not add a qualification startup action. It must remain idle until an operator POSTs connect.

- [ ] **Step 6: Extend the active-app wiring contract.**

Update `test_load_control_lan_discovery_app_wiring.py` to assert the active app contains both the LAN discovery service and the new qualification service key, and that `main.py` / `main_v0416.py` remain unchanged by this task.

- [ ] **Step 7: Run API and existing load-control integration tests.**

Run:

```bash
python3 -m pytest \
  tests/integration/test_load_control_stage2_api.py \
  tests/integration/test_load_control_lan_discovery_api.py \
  tests/integration/test_load_control_api.py \
  tests/unit/test_load_control_lan_discovery_app_wiring.py -q
```

Expected result: PASS.

- [ ] **Step 8: Commit API and application wiring.**

```bash
git add src/emonio_viewer/server/keys.py \
  src/emonio_viewer/server/load_control_api.py \
  src/emonio_viewer/server/app_v0416.py \
  tests/integration/test_load_control_stage2_api.py \
  tests/unit/test_load_control_lan_discovery_app_wiring.py
git commit -m "feat: expose actuator HELLO qualification API"
```

---

### Task 5: Add Explicit Stage-2 Operator UI Without Touching Mock Binding

**Files:**
- Modify: `frontend/js/load-control-api.js`
- Modify: `frontend/js/load-control-ui.js`
- Modify: `frontend/css/load-control/load-control.css`
- Modify: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Consumes: the three Stage-2 HTTP endpoints and the existing LAN scan result cards.
- Produces: explicit per-node qualification action, qualification status evidence, and disconnect action.

- [ ] **Step 1: Change the browser contract first.**

Replace the Stage-1-only wording assertions with exact Stage-2 expectations while preserving the existing mock-control assertions.

Require these strings and IDs:

```python
assert "STAGE 2 · REAL WEBSOCKET HELLO QUALIFICATION · CONTROL DISABLED" in ui
assert "SELECT / QUALIFY" in ui
assert "Advertised test limit:" in ui
assert "Physical max:" not in ui
assert 'id="lc-qualification-state"' in ui
assert 'id="lc-qualification-node"' in ui
assert 'id="lc-qualification-boot"' in ui
assert 'id="lc-qualification-protocol"' in ui
assert 'id="lc-qualification-class"' in ui
assert 'id="lc-qualification-capability"' in ui
assert 'id="lc-qualification-limits"' in ui
assert 'id="lc-qualification-location"' in ui
assert 'id="lc-qualification-error"' in ui
assert 'id="lc-qualification-disconnect"' in ui
assert "/api/v1/load-control/lan-qualification/connect" in api
assert "/api/v1/load-control/lan-qualification/status" in api
assert "/api/v1/load-control/lan-qualification/disconnect" in api
assert "/api/v1/load-control/command" not in api
assert "sendCommand" not in api
```

Keep assertions for the existing mock binding, enable, disable, LAN scan, and no manual command inputs.

- [ ] **Step 2: Run the browser contract and verify RED.**

Run:

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
```

Expected result: FAIL on Stage-2 strings and API paths.

- [ ] **Step 3: Add three frontend API helpers.**

In `load-control-api.js` add:

```javascript
export function connectLanQualification(nodeId) {
  return requestJson("/api/v1/load-control/lan-qualification/connect", {
    method: "POST",
    body: JSON.stringify({ node_id: nodeId }),
  });
}

export function getLanQualificationStatus() {
  return requestJson("/api/v1/load-control/lan-qualification/status");
}

export function disconnectLanQualification() {
  return requestJson("/api/v1/load-control/lan-qualification/disconnect", {
    method: "POST",
    body: "{}",
  });
}
```

Do not add a generic arbitrary WebSocket URL helper.

- [ ] **Step 4: Add a separate qualification section to the UI.**

Change the header to:

```text
STAGE 2 · REAL WEBSOCKET HELLO QUALIFICATION · CONTROL DISABLED
```

Change the stage note so it states that LAN discovery and HELLO qualification are real, but COMMAND transport remains unavailable for the real actuator and external control remains disabled.

Add a separate section after LAN discovery with these evidence fields:

```html
<section class="load-control-section" aria-label="LAN actuator qualification">
  <div class="load-control-section-header"><h3>LAN actuator qualification</h3><span>control disabled</span></div>
  <div class="load-control-value-grid">
    <div><span>State</span><strong id="lc-qualification-state">IDLE</strong></div>
    <div><span>Node</span><strong id="lc-qualification-node">—</strong></div>
    <div><span>Boot</span><strong id="lc-qualification-boot">—</strong></div>
    <div><span>Protocol</span><strong id="lc-qualification-protocol">—</strong></div>
    <div><span>Device class</span><strong id="lc-qualification-class">—</strong></div>
    <div><span>Capability</span><strong id="lc-qualification-capability">—</strong></div>
    <div><span>Advertised test limit</span><strong id="lc-qualification-limits">—</strong></div>
    <div><span>Locator</span><strong id="lc-qualification-location">—</strong></div>
  </div>
  <div id="lc-qualification-error" class="load-control-status-text" aria-live="polite"></div>
  <div class="load-control-actions">
    <button id="lc-qualification-disconnect" type="button">DISCONNECT</button>
  </div>
</section>
```

Do not reuse `lc-actuator`, `lc-save-binding`, or `saveBinding()` for the real LAN selection.

- [ ] **Step 5: Add explicit `SELECT / QUALIFY` to each LAN result card.**

In `renderLanResults()`, change only the wording and action content:

```javascript
limits.textContent = `Advertised test limit: ${powerTriplet(item.p_max)}`;

const qualify = document.createElement("button");
qualify.type = "button";
qualify.textContent = "SELECT / QUALIFY";
qualify.addEventListener("click", () => runLanQualification(item.node_id));

card.append(identity, location, details, limits, qualify);
```

No item is selected or qualified during `renderLanResults()` itself.

- [ ] **Step 6: Add deterministic qualification rendering and actions.**

Extend frontend state with `qualification: null`.

Implement rendering with qualified identity fields only when the API provides them:

```javascript
function renderLanQualification(status) {
  state.qualification = status || null;
  element("lc-qualification-state").textContent = status?.state || "IDLE";
  element("lc-qualification-node").textContent = status?.node_id || status?.selected_node_id || "—";
  element("lc-qualification-boot").textContent = status?.boot_id || "—";
  element("lc-qualification-protocol").textContent = status?.protocol_version ?? "—";
  element("lc-qualification-class").textContent = status?.device_class || "—";
  element("lc-qualification-capability").textContent = Array.isArray(status?.capabilities)
    ? status.capabilities.join(", ") || "—"
    : "—";
  element("lc-qualification-limits").textContent = powerTriplet(status?.p_max);
  element("lc-qualification-location").textContent = status?.location || "—";
  const error = element("lc-qualification-error");
  error.textContent = status?.last_error || "";
  error.dataset.error = status?.last_error ? "true" : "false";
}
```

Implement explicit actions:

```javascript
async function runLanQualification(nodeId) {
  const status = await connectLanQualification(nodeId);
  renderLanQualification(status);
}

async function refreshLanQualification() {
  renderLanQualification(await getLanQualificationStatus());
}

async function runLanQualificationDisconnect() {
  renderLanQualification(await disconnectLanQualification());
}
```

Call `refreshLanQualification()` when the panel opens as part of `refreshAll()`. Do not call `connectLanQualification()` from refresh, scan, rendering, or startup.

- [ ] **Step 7: Keep external control disabled for the real qualification path.**

Do not change the existing mock `ENABLE EXTERNAL CONTROL` implementation in this task. The Stage-2 qualification action must not call `enableLoadControl()`, `setLoadControlBinding()`, or any command API.

The qualification section must explicitly display `control disabled` in its header.

- [ ] **Step 8: Add structured CSS only in the existing load-control CSS file.**

Add small selectors for qualification state and LAN result buttons under the existing `.load-control-*` namespace. Do not add inline styles and do not modify global CSS files.

- [ ] **Step 9: Run browser contracts.**

Run:

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
python3 -m pytest tests/browser -q
```

Expected result: PASS.

- [ ] **Step 10: Commit the Stage-2 UI.**

```bash
git add frontend/js/load-control-api.js \
  frontend/js/load-control-ui.js \
  frontend/css/load-control/load-control.css \
  tests/browser/test_load_control_contract.py
git commit -m "feat: add explicit actuator HELLO qualification UI"
```

---

### Task 6: Prove No Automatic Binding, Enable, or COMMAND Path Exists

**Files:**
- Modify: `tests/unit/test_load_control_stage2_contract.py`
- Modify: `tests/integration/test_load_control_stage2_api.py`
- Modify: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Consumes: completed Stage-2 service, API, and UI.
- Produces: regression evidence that the Stage-2 path cannot silently acquire control authority.

- [ ] **Step 1: Add service-level no-control assertions.**

Inspect the qualification service source and public object surface:

```python
def test_stage2_service_exposes_no_command_method() -> None:
    assert not hasattr(LoadControlQualificationService, "send_command")
    assert not hasattr(LoadControlQualificationService, "enable")
    assert not hasattr(LoadControlQualificationService, "configure_binding")
```

Keep the source-token contract from Task 3.

- [ ] **Step 2: Add API-level separation assertions.**

In the Stage-2 API tests, use a fake Stage-1 load-control service whose `configure_binding()`, `enable()`, and `disable()` methods raise `AssertionError` if called. Execute qualification connect/status/disconnect. The test passes only if none of those Stage-1 methods is called.

- [ ] **Step 3: Add browser-level no-automatic-action assertions.**

Keep these exact source contracts:

```python
assert "connectLanQualification(item.node_id)" not in ui
assert "runLanQualification(item.node_id)" in ui
assert "setLoadControlBinding" in ui
assert "enableLoadControl" in ui
assert "/api/v1/load-control/command" not in api
```

The first assertion prevents direct connection during rendering; the second permits only the explicit click-handler path.

- [ ] **Step 4: Run the control-authority boundary tests.**

Run:

```bash
python3 -m pytest \
  tests/unit/test_load_control_stage2_contract.py \
  tests/integration/test_load_control_stage2_api.py \
  tests/browser/test_load_control_contract.py -q
```

Expected result: PASS.

- [ ] **Step 5: Commit the boundary evidence.**

```bash
git add tests/unit/test_load_control_stage2_contract.py \
  tests/integration/test_load_control_stage2_api.py \
  tests/browser/test_load_control_contract.py
git commit -m "test: prove Stage 2 has no control authority"
```

---

### Task 7: Run Protected-File and Full Regression Gates

**Files:**
- No production file changes are expected in this task.
- Verification only.

**Interfaces:**
- Consumes: all Stage-2 implementation commits.
- Produces: deterministic source-diff and full repository acceptance evidence for a Stage-2 software candidate.

- [ ] **Step 1: Verify the protected scientific production directories are unchanged from the audited v0.4.19 code baseline.**

The audited production baseline before the design-document commits is:

```text
4e66d549b813ac3a1bdcacf413d6c41721b2bf1e
```

Run:

```bash
git diff --name-only 4e66d549b813ac3a1bdcacf413d6c41721b2bf1e...HEAD -- \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/measurement \
  src/emonio_viewer/modbus \
  src/emonio_viewer/recording \
  src/emonio_viewer/scope
```

Expected output: no paths.

If any path is printed, stop. Do not accept the Stage-2 candidate until the unexpected protected-file change is explained and explicitly reviewed.

- [ ] **Step 2: Verify the production change boundary.**

Run:

```bash
git diff --name-only 975671816984697f0dc09b81de26c3a79bc87e62...HEAD -- src frontend
```

Expected production paths are only:

```text
frontend/css/load-control/load-control.css
frontend/js/load-control-api.js
frontend/js/load-control-ui.js
src/emonio_viewer/load_control/qualification.py
src/emonio_viewer/load_control/session_websocket.py
src/emonio_viewer/server/app_v0416.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/load_control_api.py
```

Any additional production path requires explicit review before field testing.

- [ ] **Step 3: Run the focused Stage-2 suite.**

Run:

```bash
python3 -m pytest \
  tests/unit/test_load_control_websocket_session.py \
  tests/unit/test_load_control_hello_qualification.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage2_contract.py \
  tests/unit/test_load_control_stage1_contract.py \
  tests/integration/test_load_control_lan_discovery_api.py \
  tests/integration/test_load_control_stage2_api.py \
  tests/browser/test_load_control_contract.py -q
```

Expected result: PASS.

- [ ] **Step 4: Run the complete existing repository acceptance script.**

Run:

```bash
bash tools/ari-emonio-acceptance.sh
```

The script must complete all six existing gates:

```text
[1/6] Unit tests
[2/6] Integration tests
[3/6] Frontend contract
[4/6] Read-only source gate
[5/6] Python compilation
[6/6] Scientific sign path
```

Expected final line:

```text
ARI Emonio Viewer Acceptance: PASS
```

Do not invent pass counts. Record the counts actually printed by the workstation run.

- [ ] **Step 5: Verify no uncommitted production changes remain.**

Run:

```bash
git status -sb
git diff --check
```

Expected: clean working tree for the committed implementation and no whitespace errors.

- [ ] **Step 6: Record the candidate commit but do not claim field PASS.**

Run:

```bash
git rev-parse HEAD
```

Record that SHA as the Stage-2 software candidate only after all automated gates pass.

Do not merge to `main`. Do not claim real ESP32 WebSocket field PASS yet.

---

### Task 8: Execute the Real ESP32 Stage-2 Field Acceptance

**Files:**
- No source changes during the acceptance run.

**Interfaces:**
- Consumes: Stage-2 software candidate on `testing`, ESP32 ARI Load Test Actuator v0.1.1, existing WLAN/mDNS environment.
- Produces: operator field evidence for real WebSocket connection and HELLO qualification only.

- [ ] **Step 1: Start the existing ESP32 actuator and confirm its existing discovery evidence.**

Required precondition evidence remains:

```text
WiFi joined
DHCP address assigned
mDNS _ari-emonio-load._tcp.local. advertised
WebSocket server listening on port 8080
path /load-control
```

Do not treat the DHCP address as identity.

- [ ] **Step 2: Start the Stage-2 Viewer candidate and run `SCAN LAN`.**

Confirm the Viewer lists `ARI-LOAD-001` and displays:

```text
Advertised test limit: A 1000.0 W · B 1000.0 W · C 1000.0 W
```

Confirm no LAN item is already selected or connected before operator action.

- [ ] **Step 3: Press `SELECT / QUALIFY` for `ARI-LOAD-001`.**

Expected ESP32 serial evidence:

```text
[WS] Viewer connected
[WS] HELLO sent
```

Expected Viewer evidence after qualification:

```text
State: QUALIFIED
Node: ARI-LOAD-001
Boot: BOOT-...
Protocol: 1
Device class: ARI_LOAD_ACTUATOR
Capability: ACTIVE_LOAD_CONTROL
Advertised test limit: 1000 / 1000 / 1000 W
```

The external control path must still show `DISABLED`.

- [ ] **Step 4: Confirm Stage 2 sent no COMMAND.**

Inspect ESP32 serial output for the full qualification interval. There must be no actuator evidence of a received COMMAND.

Do not infer this from the Viewer UI alone.

- [ ] **Step 5: Test disconnect invalidation.**

Disconnect the Stage-2 WebSocket using the Viewer action or reboot the ESP32. Confirm the Viewer leaves `QUALIFIED` and reports `DISCONNECTED`. Confirm the old boot ID is no longer presented as qualified identity.

- [ ] **Step 6: Test new boot qualification.**

After ESP32 reboot, run LAN discovery if needed and explicitly qualify `ARI-LOAD-001` again. Confirm the new `boot_id` differs from the old one and that the Viewer reaches `QUALIFIED` only after the new HELLO is received.

- [ ] **Step 7: Stop at the Stage-2 gate.**

If all field checks pass, record Stage-2 field acceptance evidence. Do not add COMMAND, ACK, binding, sequence handling, automatic reconnect, or physical output in this implementation plan.

Stage 3 requires a separate architecture review for:

```text
explicit real actuator binding
-> controlled COMMAND
-> deterministic ACK
-> sequence / duplicate / out-of-order qualification
```
