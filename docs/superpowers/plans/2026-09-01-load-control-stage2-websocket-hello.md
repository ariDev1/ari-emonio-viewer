# ARI Emonio Viewer Stage 2 WebSocket HELLO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add operator-selected real WebSocket connection and strict HELLO qualification for a discovered ARI load actuator, while keeping external control disabled and sending no COMMAND frame.

**Architecture:** Keep the Stage-1 mock-control service and read-only LAN discovery service unchanged. Extend the existing WebSocket transport with a backward-compatible two-step connection interface. Add one independent qualification service that resolves an operator-selected `node_id` from the latest LAN discovery evidence, opens the stored WebSocket locator, validates the first HELLO frame, and owns qualification state only. Wire that service through the active `app_v0416.py` compatibility application and expose a separate Stage-2 UI section.

**Tech Stack:** Python 3.11+, `aiohttp`, `asyncio`, existing ARI load-control protocol V1 models, vanilla JavaScript, structured CSS, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-01-load-control-stage2-websocket-hello-design.md`

## Global Constraints

- Target branch: `testing`.
- Viewer baseline: ARI Emonio Viewer v0.4.19.
- Do not modify canonical P signs or Q signs.
- Do not modify quadrant or power-factor semantics.
- Do not modify measurement validation or fixed-deadline acquisition.
- Do not modify Emonio polling.
- Do not modify Modbus transport, read-only behavior, register maps, or decoder logic.
- Do not modify recording semantics or CSV precision.
- Do not modify SCOPE measurement semantics.
- Protected production directories are `src/emonio_viewer/acquisition/**`, `src/emonio_viewer/measurement/**`, `src/emonio_viewer/modbus/**`, `src/emonio_viewer/recording/**`, and `src/emonio_viewer/scope/**`.
- Preserve the Stage-1 mock-control path in `src/emonio_viewer/load_control/service.py`.
- Preserve operator-triggered read-only mDNS discovery.
- The browser submits only `node_id` for Stage-2 selection. It does not submit IP address, port, path, or replacement WebSocket URL.
- The backend resolves the selected node against `LanActuatorDiscoveryService.last_result`.
- Qualified actuator instance identity is `node_id + current boot_id`. IP address is only a locator.
- WebSocket connect timeout is `3.0 s`.
- First HELLO receive timeout is `2.0 s`.
- Discovery-to-HELLO `p_max` comparison uses exact numeric equality after strict finite positive validation.
- No tolerance, clamp, repair, substitution, or default is permitted.
- No automatic selection, binding, external-control enable, or reconnect.
- Stage 2 sends no COMMAND under any condition.
- Stage 2 exposes no command-send method.
- External control remains `DISABLED` after successful qualification.
- Do not change the project version in this plan. Version promotion is a separate decision.

---

## File Structure

### New production file

`src/emonio_viewer/load_control/qualification.py`

Responsibility: own real actuator HELLO qualification only. This file contains the Stage-2 state enum, qualification error, immutable status snapshot, discovery-to-HELLO cross-check, connection lifecycle, and read-only disconnect watcher. It does not import measurement, Modbus, recording, SCOPE, controller, supervisor, COMMAND, or ACK code.

### Existing production files with small changes

- `src/emonio_viewer/load_control/session_websocket.py`: add `open()`, `receive_hello()`, and `wait_for_disconnect()` while preserving existing `connect()` behavior.
- `src/emonio_viewer/server/keys.py`: add one typed AppKey for the qualification service.
- `src/emonio_viewer/server/load_control_api.py`: add qualification service lookup, serializer, and three Stage-2 routes.
- `src/emonio_viewer/server/app_v0416.py`: construct or accept the qualification service and close it during application cleanup.
- `frontend/js/load-control-api.js`: add qualification connect/status/disconnect helpers.
- `frontend/js/load-control-ui.js`: add explicit `SELECT / QUALIFY`, qualification evidence, and `DISCONNECT`; keep mock binding separate; correct `Physical max` wording.
- `frontend/css/load-control/load-control.css`: add only Stage-2 qualification styles under the existing load-control namespace.

### Test files

- Modify `tests/unit/test_load_control_protocol.py` for the complete invalid raw HELLO matrix.
- Modify `tests/unit/test_load_control_websocket_session.py` for staged connect, first-frame enforcement, binary/malformed first frame, and disconnect watcher.
- Create `tests/unit/test_load_control_hello_qualification.py` for valid but mismatched discovery/HELLO evidence.
- Create `tests/unit/test_load_control_stage2_service.py` for lifecycle and no-frame behavior.
- Create `tests/unit/test_load_control_stage2_contract.py` for the no-control/no-scientific-import boundary.
- Create `tests/integration/test_load_control_stage2_api.py` for HTTP/API separation.
- Modify `tests/unit/test_load_control_lan_discovery_app_wiring.py` for active app wiring.
- Modify `tests/browser/test_load_control_contract.py` for Stage-2 UI/API contract.

---

### Task 1: Complete the Raw HELLO Protocol Rejection Matrix

**Files:**
- Modify: `tests/unit/test_load_control_protocol.py`
- Production files: none

**Interfaces:**
- Consumes: existing `decode_frame()` and strict protocol V1 decoder.
- Produces: direct evidence that invalid raw HELLO frames are rejected before Stage-2 discovery comparison.

- [ ] **Step 1: Add a valid raw HELLO payload helper.**

```python
def _hello_payload():
    return {
        "message_type": "HELLO",
        "protocol_version": 1,
        "node_id": "ARI-LOAD-001",
        "boot_id": "BOOT-001",
        "device_class": "ARI_LOAD_ACTUATOR",
        "capabilities": ["ACTIVE_LOAD_CONTROL"],
        "p_max": {"a": 1000.0, "b": 1000.0, "c": 1000.0},
    }
```

- [ ] **Step 2: Add explicit decoder rejection tests.**

Add separate tests or one parameterized test for all of these raw HELLO failures:

```text
unknown message_type
protocol_version = 2
empty boot_id
missing p_max
p_max missing phase c
p_max with extra phase d
p_max.a = NaN
p_max.b = Infinity
p_max.c = 0.0
p_max.a = -1.0
extra top-level HELLO field
```

Use `json.dumps(payload)` for normal cases. For non-finite cases, Python JSON encoding may emit `NaN` or `Infinity`; pass the resulting text to `decode_frame()` and assert `ProtocolError` or the existing protocol validation exception type used by the decoder.

Example:

```python
def test_hello_decoder_rejects_wrong_protocol_version() -> None:
    payload = _hello_payload()
    payload["protocol_version"] = 2
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


def test_hello_decoder_rejects_missing_p_max() -> None:
    payload = _hello_payload()
    payload.pop("p_max")
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))
```

- [ ] **Step 3: Run the protocol test file.**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py -q
```

Expected: PASS with the current strict decoder. If one required invalid frame is accepted, stop and treat that as evidence that `protocol.py` needs an explicitly reviewed boundary expansion before modifying it.

- [ ] **Step 4: Commit test evidence only.**

```bash
git add tests/unit/test_load_control_protocol.py
git commit -m "test: complete Stage 2 HELLO rejection matrix"
```

---

### Task 2: Extend WebSocket Transport Without Breaking Existing Behavior

**Files:**
- Modify: `src/emonio_viewer/load_control/session_websocket.py`
- Modify: `tests/unit/test_load_control_websocket_session.py`

**Interfaces:**
- Consumes: existing `ActuatorDescriptor`, `HelloFrame`, `decode_frame()`, `ClientSession`, explicit connect and receive timeouts.
- Produces: `async open() -> None`, `async receive_hello() -> HelloFrame`, `async wait_for_disconnect() -> None`; existing `async connect() -> HelloFrame` remains a compatibility wrapper.

- [ ] **Step 1: Write failing tests for staged connection.**

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
        assert len(websocket.messages) == 1

        hello = await session.receive_hello()
        assert hello == _hello()
        assert websocket.messages == []

        await session.disconnect()

    asyncio.run(scenario())
```

Add tests that `receive_hello()` rejects:

```text
ACK as first application frame
malformed JSON text as first frame
binary first frame
```

For the binary case, broaden `FakeMessage.data` to `object` so the fake can represent bytes.

- [ ] **Step 2: Run the transport test file and verify RED.**

```bash
python3 -m pytest tests/unit/test_load_control_websocket_session.py -q
```

Expected: FAIL because the staged methods do not exist.

- [ ] **Step 3: Implement the minimal two-step interface.**

Refactor the current `connect()` body into these methods:

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

Do not change constructor validation or existing timeout values supplied by callers.

- [ ] **Step 4: Add a transport-only disconnect watcher.**

The watcher sends no application frame. Stage 2 has no post-HELLO application-frame consumer, so the watcher may consume post-HELLO inbound frames while waiting for transport close.

```python
async def wait_for_disconnect(self) -> None:
    if not self.connected:
        raise ConnectionError("actuator WebSocket is not connected")
    while self.connected:
        message = await self._websocket.receive()
        if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
            return
```

- [ ] **Step 5: Add watcher and compatibility tests.**

Use HELLO followed by `WSMsgType.CLOSE`. Assert `wait_for_disconnect()` returns and `websocket.sent == []`. Keep the existing `connect()` COMMAND/ACK test unchanged and passing to prove compatibility.

- [ ] **Step 6: Run the transport tests and verify GREEN.**

```bash
python3 -m pytest tests/unit/test_load_control_websocket_session.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add src/emonio_viewer/load_control/session_websocket.py tests/unit/test_load_control_websocket_session.py
git commit -m "feat: expose staged actuator WebSocket connection"
```

---

### Task 3: Add Pure Discovery-to-HELLO Qualification

**Files:**
- Create: `src/emonio_viewer/load_control/qualification.py`
- Create: `tests/unit/test_load_control_hello_qualification.py`

**Interfaces:**
- Consumes: structurally valid `ActuatorDescriptor` and `HelloFrame` instances.
- Produces: `QualificationState`, `LoadControlQualificationError`, `QualificationStatus`, and `qualify_hello(descriptor, hello) -> None`.

- [ ] **Step 1: Write failing cross-check tests.**

Invalid protocol version, empty boot ID, non-finite `p_max`, missing `p_max`, and non-positive `p_max` belong to Task 1 because the strict `HelloFrame` model can reject them before a `HelloFrame` exists. This task tests valid objects that disagree with discovery evidence.

```python
@pytest.mark.parametrize(
    "hello, expected",
    [
        (replace(_hello(), node_id="ARI-LOAD-OTHER"), "node_id"),
        (replace(_hello(), device_class="OTHER_CLASS"), "device_class"),
        (replace(_hello(), capabilities=("OTHER_CAPABILITY",)), "ACTIVE_LOAD_CONTROL"),
        (replace(_hello(), p_max=ThreePhasePower(999.0, 1000.0, 1000.0)), "p_max.a"),
        (replace(_hello(), p_max=ThreePhasePower(1000.0, 999.0, 1000.0)), "p_max.b"),
        (replace(_hello(), p_max=ThreePhasePower(1000.0, 1000.0, 999.0)), "p_max.c"),
    ],
)
def test_hello_qualification_rejects_discovery_mismatch(hello, expected) -> None:
    with pytest.raises(LoadControlQualificationError, match=expected):
        qualify_hello(_descriptor(), hello)
```

Add one valid exact-match test.

- [ ] **Step 2: Run and verify RED.**

```bash
python3 -m pytest tests/unit/test_load_control_hello_qualification.py -q
```

Expected: FAIL because `qualification.py` does not exist.

- [ ] **Step 3: Add the dedicated state and status types.**

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

- [ ] **Step 4: Implement exact cross-checks.**

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

Do not add tolerance or repair logic.

- [ ] **Step 5: Run the HELLO rule layers together.**

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py tests/unit/test_load_control_hello_qualification.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add src/emonio_viewer/load_control/qualification.py tests/unit/test_load_control_hello_qualification.py
git commit -m "feat: add strict actuator HELLO qualification"
```

---

### Task 4: Add the Independent Qualification Service

**Files:**
- Modify: `src/emonio_viewer/load_control/qualification.py`
- Create: `tests/unit/test_load_control_stage2_service.py`
- Create: `tests/unit/test_load_control_stage2_contract.py`

**Interfaces:**
- Consumes: `LanActuatorDiscoveryService.last_result`, `WebSocketActuatorSession`, `qualify_hello()`.
- Produces: `LoadControlQualificationService.connect(node_id: str) -> QualificationStatus`, `status() -> QualificationStatus`, `disconnect() -> QualificationStatus`, `close() -> None`.

- [ ] **Step 1: Write service lifecycle tests before service code.**

Use a fake discovery service with mutable `last_result` and a fake session factory. Test each case separately:

```text
initial state IDLE
one discovered node is not selected automatically
missing selected node_id raises LoadControlQualificationError
duplicate selected node_id raises LoadControlQualificationError
state order is DISCOVERED -> CONNECTING -> HELLO_WAIT -> QUALIFIED
protocol/transport receive exception becomes REJECTED
valid HELLO stores node_id and boot_id
second connect while socket is open raises LoadControlQualificationError
disconnect clears qualified HELLO identity and produces DISCONNECTED
reconnect calls receive_hello again
same node_id with a new boot_id becomes a new qualified boot instance
remote close invalidates QUALIFIED and produces DISCONNECTED
successful qualification sends zero frames
rejected qualification sends zero frames
explicit disconnect sends zero frames
close sends zero frames
```

For parser/transport rejection, configure the fake session `receive_hello()` to raise `ProtocolError("invalid HELLO")` and `asyncio.TimeoutError()` in separate tests.

- [ ] **Step 2: Run and verify RED.**

```bash
python3 -m pytest tests/unit/test_load_control_stage2_service.py -q
```

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement constructor and exact descriptor resolution.**

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

Resolve selection only from latest discovery evidence:

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

No URL argument exists on `connect()`.

- [ ] **Step 4: Implement deterministic connection qualification.**

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

This path does not call `send_command()`.

- [ ] **Step 5: Implement status with selection evidence separate from qualified identity.**

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

Rejected HELLO content is never returned as qualified identity.

- [ ] **Step 6: Implement remote and explicit disconnect handling.**

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
            self._watch_task = None
            self._state = QualificationState.DISCONNECTED
```

For explicit disconnect, cancel the watcher first, close the current session, clear HELLO, and use `DISCONNECTED` if a selection/connection existed. Keep the selected descriptor only as non-qualified selection evidence. `close()` calls the same cleanup path. Do not reconnect.

- [ ] **Step 7: Add architecture boundary tests.**

```python
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


def test_stage2_service_exposes_no_control_method() -> None:
    assert not hasattr(LoadControlQualificationService, "send_command")
    assert not hasattr(LoadControlQualificationService, "enable")
    assert not hasattr(LoadControlQualificationService, "configure_binding")
```

- [ ] **Step 8: Run Stage-2 service and Stage-1 preservation tests.**

```bash
python3 -m pytest \
  tests/unit/test_load_control_protocol.py \
  tests/unit/test_load_control_websocket_session.py \
  tests/unit/test_load_control_hello_qualification.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage2_contract.py \
  tests/unit/test_load_control_stage1_contract.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit.**

```bash
git add src/emonio_viewer/load_control/qualification.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage2_contract.py
git commit -m "feat: add isolated actuator qualification service"
```

---

### Task 5: Add Stage-2 API and Active Application Wiring

**Files:**
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/load_control_api.py`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Create: `tests/integration/test_load_control_stage2_api.py`
- Modify: `tests/unit/test_load_control_lan_discovery_app_wiring.py`

**Interfaces:**
- Consumes: `LoadControlQualificationService` and existing `LanActuatorDiscoveryService`.
- Produces: `LOAD_CONTROL_QUALIFICATION_SERVICE_KEY` plus connect/status/disconnect routes.

- [ ] **Step 1: Write failing API tests.**

Use a fake qualification service and test:

```text
GET /api/v1/load-control/lan-qualification/status
POST /api/v1/load-control/lan-qualification/connect with node_id
POST connect without node_id -> 400
POST connect with service precondition conflict -> 409
POST /api/v1/load-control/lan-qualification/disconnect
existing /lan-discovery/scan still works
qualification routes never call Stage-1 configure_binding(), enable(), or disable()
```

Use a fake Stage-1 service whose `configure_binding()`, `enable()`, and `disable()` raise `AssertionError` if a Stage-2 route calls them.

- [ ] **Step 2: Run and verify RED.**

```bash
python3 -m pytest tests/integration/test_load_control_stage2_api.py -q
```

Expected: FAIL because the key/routes do not exist.

- [ ] **Step 3: Add the typed AppKey.**

```python
LOAD_CONTROL_QUALIFICATION_SERVICE_KEY = web.AppKey(
    "load_control_qualification_service",
    LoadControlQualificationService,
)
```

- [ ] **Step 4: Add exact JSON serialization and routes.**

Register:

```python
app.router.add_post("/api/v1/load-control/lan-qualification/connect", connect_lan_actuator)
app.router.add_get("/api/v1/load-control/lan-qualification/status", get_lan_qualification_status)
app.router.add_post("/api/v1/load-control/lan-qualification/disconnect", disconnect_lan_actuator)
```

Serialize explicitly:

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

Connect handler accepts only `node_id`:

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

Do not call binding, enable, or command code.

- [ ] **Step 5: Wire the service through `app_v0416.py`.**

Add optional injection:

```python
qualification_service: LoadControlQualificationService | None = None,
```

After the LAN discovery service exists:

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

Do not add a qualification startup action. Do not change `main.py` or `main_v0416.py`.

- [ ] **Step 6: Update app wiring contract.**

Assert the active app contains the existing LAN discovery key and the new qualification key. Preserve the existing Stage-1 service key and routes.

- [ ] **Step 7: Run API and existing load-control integration tests.**

```bash
python3 -m pytest \
  tests/integration/test_load_control_stage2_api.py \
  tests/integration/test_load_control_lan_discovery_api.py \
  tests/integration/test_load_control_api.py \
  tests/unit/test_load_control_lan_discovery_app_wiring.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add src/emonio_viewer/server/keys.py \
  src/emonio_viewer/server/load_control_api.py \
  src/emonio_viewer/server/app_v0416.py \
  tests/integration/test_load_control_stage2_api.py \
  tests/unit/test_load_control_lan_discovery_app_wiring.py
git commit -m "feat: expose actuator HELLO qualification API"
```

---

### Task 6: Add Explicit Stage-2 UI Without Reusing Mock Binding

**Files:**
- Modify: `frontend/js/load-control-api.js`
- Modify: `frontend/js/load-control-ui.js`
- Modify: `frontend/css/load-control/load-control.css`
- Modify: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Consumes: Stage-2 connect/status/disconnect endpoints and existing LAN result cards.
- Produces: explicit per-node `SELECT / QUALIFY`, read-only qualification evidence, and `DISCONNECT`.

- [ ] **Step 1: Update browser contract first and verify RED.**

Require:

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
assert 'id="lc-command-a"' not in ui
assert 'id="lc-command-b"' not in ui
assert 'id="lc-command-c"' not in ui
```

Keep existing assertions that the mock binding, existing enable/disable paths, and LAN scan still exist.

Run:

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
```

Expected: FAIL before frontend implementation.

- [ ] **Step 2: Add frontend API helpers.**

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

No arbitrary WebSocket URL helper is permitted.

- [ ] **Step 3: Change Stage-2 wording and add a separate qualification section.**

Header:

```text
STAGE 2 · REAL WEBSOCKET HELLO QUALIFICATION · CONTROL DISABLED
```

The note states that LAN discovery and HELLO qualification are real, while real COMMAND transport remains unavailable and external control remains disabled.

Add fields for state, node, boot, protocol, device class, capability, advertised test limit, locator, error, and a `DISCONNECT` button. Use IDs from Step 1.

- [ ] **Step 4: Add explicit per-card qualification action.**

In `renderLanResults()`:

```javascript
limits.textContent = `Advertised test limit: ${powerTriplet(item.p_max)}`;

const qualify = document.createElement("button");
qualify.type = "button";
qualify.textContent = "SELECT / QUALIFY";
qualify.addEventListener("click", () => runLanQualification(item.node_id));

card.append(identity, location, details, limits, qualify);
```

Rendering a LAN result must not connect it.

- [ ] **Step 5: Add qualification render and actions.**

Extend state with `qualification: null`.

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

async function runLanQualification(nodeId) {
  renderLanQualification(await connectLanQualification(nodeId));
}

async function refreshLanQualification() {
  renderLanQualification(await getLanQualificationStatus());
}

async function runLanQualificationDisconnect() {
  renderLanQualification(await disconnectLanQualification());
}
```

Call only `refreshLanQualification()` from panel refresh. Do not call `connectLanQualification()` from startup, refresh, LAN scan, or result rendering.

- [ ] **Step 6: Keep mock controls separate.**

The Stage-2 action does not call `setLoadControlBinding()`, `enableLoadControl()`, `disableLoadControl()`, or a command function. Do not populate `lc-actuator` from Stage-2 selection.

- [ ] **Step 7: Add structured CSS only in `load-control.css`.**

Add small `.load-control-*` selectors for qualification evidence and result-card action spacing. Do not add inline styles and do not modify global CSS files.

- [ ] **Step 8: Run frontend contracts.**

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
python3 -m pytest tests/browser -q
```

Expected: PASS.

- [ ] **Step 9: Commit.**

```bash
git add frontend/js/load-control-api.js \
  frontend/js/load-control-ui.js \
  frontend/css/load-control/load-control.css \
  tests/browser/test_load_control_contract.py
git commit -m "feat: add explicit actuator HELLO qualification UI"
```

---

### Task 7: Run Protected-File and Complete Regression Gates

**Files:**
- No production changes.

**Interfaces:**
- Consumes: all Stage-2 implementation commits.
- Produces: deterministic software-candidate evidence only.

- [ ] **Step 1: Prove protected scientific directories are unchanged from the audited v0.4.19 code baseline.**

Baseline:

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

Expected output: empty. If any path appears, stop and require explicit review.

- [ ] **Step 2: Prove the production change boundary.**

Implementation-plan baseline commit is the commit that contains the approved spec before implementation-plan execution. Run:

```bash
git diff --name-only 975671816984697f0dc09b81de26c3a79bc87e62...HEAD -- src frontend
```

Expected production paths only:

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

Any additional production path requires explicit review.

- [ ] **Step 3: Run the focused Stage-2 matrix.**

```bash
python3 -m pytest \
  tests/unit/test_load_control_protocol.py \
  tests/unit/test_load_control_websocket_session.py \
  tests/unit/test_load_control_hello_qualification.py \
  tests/unit/test_load_control_stage2_service.py \
  tests/unit/test_load_control_stage2_contract.py \
  tests/unit/test_load_control_stage1_contract.py \
  tests/integration/test_load_control_lan_discovery_api.py \
  tests/integration/test_load_control_stage2_api.py \
  tests/browser/test_load_control_contract.py -q
```

Expected: PASS.

- [ ] **Step 4: Run the existing complete repository acceptance script.**

```bash
bash tools/ari-emonio-acceptance.sh
```

It must complete:

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

Record only counts printed by the actual run. Do not invent counts.

- [ ] **Step 5: Check repository cleanliness.**

```bash
git status -sb
git diff --check
git rev-parse HEAD
```

Record the HEAD SHA as the Stage-2 software candidate only after all automated gates pass. Do not merge to `main` and do not claim field PASS.

---

### Task 8: Real ESP32 Stage-2 Field Acceptance

**Files:**
- No source changes during acceptance.

**Interfaces:**
- Consumes: Stage-2 software candidate on `testing`, ESP32 ARI Load Test Actuator v0.1.1, existing WLAN/mDNS environment.
- Produces: field evidence for real WebSocket connection and HELLO qualification only.

- [ ] **Step 1: Confirm existing actuator discovery preconditions.**

Required evidence:

```text
WiFi joined
DHCP address assigned
mDNS _ari-emonio-load._tcp.local. advertised
WebSocket server listening on port 8080
path /load-control
```

DHCP address remains a locator, not identity.

- [ ] **Step 2: Run `SCAN LAN`.**

Confirm `ARI-LOAD-001` appears with:

```text
Advertised test limit: A 1000.0 W · B 1000.0 W · C 1000.0 W
```

Confirm no actuator is selected or connected automatically.

- [ ] **Step 3: Press `SELECT / QUALIFY` for `ARI-LOAD-001`.**

Expected ESP32 evidence:

```text
[WS] Viewer connected
[WS] HELLO sent
```

Expected Viewer evidence:

```text
State: QUALIFIED
Node: ARI-LOAD-001
Boot: BOOT-...
Protocol: 1
Device class: ARI_LOAD_ACTUATOR
Capability: ACTIVE_LOAD_CONTROL
Advertised test limit: 1000 / 1000 / 1000 W
```

External control remains `DISABLED`.

- [ ] **Step 4: Confirm no COMMAND was received.**

Inspect ESP32 serial output over the complete qualification interval. There must be no evidence of a received COMMAND. Do not infer this from Viewer UI alone.

- [ ] **Step 5: Confirm disconnect invalidates qualification.**

Use Viewer `DISCONNECT` or reboot the ESP32. Confirm Viewer state leaves `QUALIFIED` and becomes `DISCONNECTED`. The old boot ID must no longer appear as qualified identity.

- [ ] **Step 6: Confirm reboot requires a new HELLO.**

After ESP32 reboot, run discovery if needed and explicitly qualify `ARI-LOAD-001` again. Confirm a new `boot_id` and confirm `QUALIFIED` appears only after the new HELLO is received.

- [ ] **Step 7: Stop at Stage 2.**

If all field checks pass, record Stage-2 field acceptance. Do not add COMMAND, ACK, binding, sequence logic, automatic reconnect, or physical output.

Stage 3 requires a separate architecture review for:

```text
explicit real actuator binding
-> controlled COMMAND
-> deterministic ACK
-> sequence / duplicate / out-of-order qualification
```
