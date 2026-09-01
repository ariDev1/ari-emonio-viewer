# ARI Emonio Viewer External Load Control Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Viewer-side external load-control supervisor with deterministic mock discovery and mock actuator transport only, while preserving the trusted Emonio measurement architecture.

**Architecture:** Add an isolated `emonio_viewer.load_control` subsystem that consumes immutable canonical `MeasurementSample` and `DiagnosticEvent` objects from the existing non-blocking `RuntimeEventBus`. Controller mathematics and safety state remain deterministic and I/O-free. A service owns persistence, JSONL evidence, mock discovery, mock actuator session, runtime-event consumption, API status, and shutdown behavior.

**Tech Stack:** Python 3.10+, dataclasses, asyncio, standard-library JSON/path primitives, existing `aiohttp==3.14.3` server stack, pytest 8.4.1, plain ES modules, structured CSS.

**Spec:** `docs/superpowers/specs/2026-09-01-load-control-supervisor-design.md`

## Global Constraints

- Work on branch `testing` only.
- Protected production-code baseline: `e3e33ec959d6304ca8471ab1c0f217884b64ed18`.
- Do not merge or modify `main`.
- Do not modify Modbus acquisition, register maps, decoder logic, canonical measurement signs, P/Q quadrant semantics, validation, fixed-deadline acquisition, SCOPE semantics, or existing CSV precision.
- These paths must remain byte-identical to the protected production-code baseline: `src/emonio_viewer/modbus`, `src/emonio_viewer/measurement`, `src/emonio_viewer/acquisition`, `src/emonio_viewer/runtime/events.py`, `src/emonio_viewer/runtime/store.py`, and `src/emonio_viewer/scope`.
- Stage 1 contains no mDNS network implementation, no real WebSocket actuator client, no ESP32 firmware, no PWM logic, and no physical power-stage control path.
- Stage 1 uses `MockActuatorDiscovery` and `MockActuatorSession` only.
- Control starts `DISABLED` on every Viewer process start.
- Persistent binding and safety configuration never restore control authority.
- Only canonical `MeasurementSample.quality == VALID` is eligible for active control.
- P and Q remain separate. Q is telemetry only. Every `Q_comp_request_*` is exactly `0 var`.
- V1 active-load requests are non-negative only.
- One normal command can be unacknowledged at a time. Safe commands can preempt it.
- Last valid actuator acknowledgement is the authoritative applied-load state.
- A transmitted command is never evidence of applied state.
- V1 control law: `P_request_raw = P_acknowledged + P_reserve - P_measured`, independently for A, B, and C.
- Do not add gain, PID, averaging, smoothing, interpolation, hysteresis, synthetic samples, or invented timing constants.
- Control freshness and acknowledgement timeouts are explicit volatile mock-stage qualification inputs. They have no default and are not persisted.
- Safety-critical configuration changes are allowed only while `DISABLED`.
- The browser has no endpoint or field for direct actuator `P_A`, `P_B`, or `P_C` demand.
- Preserve the known unrelated `tests/browser/test_header_status_layout.py` issue as a separate baseline observation. Do not change that test or the existing header layout.
- Use ASD-STE / Simplified Technical English for operator-visible text.

---

## Execution Preflight

Before Task 1, use the Superpowers worktree workflow and create an isolated worktree from the exact current `testing` HEAD.

Run:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
python3 -m pytest tests/unit -q
python3 -m pytest tests/integration -q
python3 -m pytest tests/browser -q
```

Record the exact baseline result of `tests/browser/test_header_status_layout.py` separately. Do not change that test during this plan.

Run the protected-path gate:

```bash
git diff --exit-code e3e33ec959d6304ca8471ab1c0f217884b64ed18 HEAD -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: exit code `0`.

## File Structure

Create:

```text
src/emonio_viewer/load_control/__init__.py
src/emonio_viewer/load_control/model.py
src/emonio_viewer/load_control/config_store.py
src/emonio_viewer/load_control/controller.py
src/emonio_viewer/load_control/state_machine.py
src/emonio_viewer/load_control/protocol.py
src/emonio_viewer/load_control/evidence.py
src/emonio_viewer/load_control/discovery.py
src/emonio_viewer/load_control/session.py
src/emonio_viewer/load_control/supervisor.py
src/emonio_viewer/load_control/service.py
src/emonio_viewer/server/load_control_api.py
frontend/css/load-control.css
frontend/js/load-control-api.js
frontend/js/load-control-ui.js
tests/fixtures/load_control_samples.py
tests/unit/test_load_control_model.py
tests/unit/test_load_control_config_store.py
tests/unit/test_load_control_controller.py
tests/unit/test_load_control_state_machine.py
tests/unit/test_load_control_protocol.py
tests/unit/test_load_control_evidence.py
tests/unit/test_load_control_mock.py
tests/unit/test_load_control_supervisor.py
tests/unit/test_load_control_service.py
tests/unit/test_load_control_stage1_contract.py
tests/integration/test_load_control_api.py
tests/integration/test_load_control_runtime.py
tests/browser/test_load_control_contract.py
```

Modify only where required:

```text
src/emonio_viewer/main.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/app.py
src/emonio_viewer/server/app_v0416.py
frontend/index.html
tests/unit/test_launcher.py
```

No `WebSocketActuatorSession` or `MdnsActuatorDiscovery` implementation is created in this stage.

---

### Task 1: Immutable Models and Atomic Persistent Configuration

**Files:**
- Create: `src/emonio_viewer/load_control/__init__.py`
- Create: `src/emonio_viewer/load_control/model.py`
- Create: `src/emonio_viewer/load_control/config_store.py`
- Create: `tests/unit/test_load_control_model.py`
- Create: `tests/unit/test_load_control_config_store.py`

**Interfaces:**
- `ThreePhasePower(a: float, b: float, c: float)`.
- `LoadControlTiming(control_sample_max_age_s: float, ack_timeout_s: float)`.
- `PersistentLoadControlConfig(bound_emonio_device_id: str | None, bound_actuator_node_id: str | None, p_reserve: float | None, operator_limit_a: float | None, operator_limit_b: float | None, operator_limit_c: float | None)`.
- `LoadControlConfigStore.load() -> PersistentLoadControlConfig`.
- `LoadControlConfigStore.replace(config: PersistentLoadControlConfig) -> None`.
- Enums: `ControlMode`, `SessionState`, `SafeState`, `LimitState`, `ActuatorCapability`, `TripReason`.
- Immutable status/identity types: `ActuatorDescriptor`, `ActuatorSessionIdentity`, `LoadControlStatus`.

- [ ] **Step 1: Write failing model tests**

```python
import math
import pytest

from emonio_viewer.load_control.model import LoadControlTiming, PersistentLoadControlConfig, ThreePhasePower


def test_three_phase_power_preserves_mapping():
    value = ThreePhasePower(a=1.0, b=2.0, c=3.0)
    assert (value.a, value.b, value.c) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_persistent_config_rejects_invalid_reserve(bad):
    with pytest.raises(ValueError):
        PersistentLoadControlConfig(p_reserve=bad)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_timing_rejects_invalid_limits(bad):
    with pytest.raises(ValueError):
        LoadControlTiming(control_sample_max_age_s=bad, ack_timeout_s=1.0)
    with pytest.raises(ValueError):
        LoadControlTiming(control_sample_max_age_s=1.0, ack_timeout_s=bad)
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/unit/test_load_control_model.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement the immutable model core**

```python
@dataclass(frozen=True, slots=True)
class ThreePhasePower:
    a: float
    b: float
    c: float


@dataclass(frozen=True, slots=True)
class LoadControlTiming:
    control_sample_max_age_s: float
    ack_timeout_s: float

    def __post_init__(self) -> None:
        for name in ("control_sample_max_age_s", "ack_timeout_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")


@dataclass(frozen=True, slots=True)
class PersistentLoadControlConfig:
    bound_emonio_device_id: str | None = None
    bound_actuator_node_id: str | None = None
    p_reserve: float | None = None
    operator_limit_a: float | None = None
    operator_limit_b: float | None = None
    operator_limit_c: float | None = None

    def __post_init__(self) -> None:
        for name in ("bound_emonio_device_id", "bound_actuator_node_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty text or None")
        for name in ("p_reserve", "operator_limit_a", "operator_limit_b", "operator_limit_c"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value <= 0.0):
                raise ValueError(f"{name} must be finite and > 0")
```

Define enum values exactly as the approved design: control `DISABLED/ENABLED/TRIPPED`; session `UNBOUND/DISCOVERING/UNAVAILABLE/CONNECTING/VERIFYING/READY/SESSION_FAULT`; safe `NOT_REQUIRED/SAFE_UNCONFIRMED/SAFE_CONFIRMED`.

- [ ] **Step 4: Write exact store tests**

```python
def test_store_empty_file_state_is_empty_config(tmp_path):
    store = LoadControlConfigStore(tmp_path / "load-control.json")
    assert store.load() == PersistentLoadControlConfig()


def test_store_round_trips_without_timing(tmp_path):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    config = PersistentLoadControlConfig(
        bound_emonio_device_id="emonio-example",
        bound_actuator_node_id="ARI-LOAD-MOCK-001",
        p_reserve=30.0,
        operator_limit_a=600.0,
        operator_limit_b=700.0,
        operator_limit_c=800.0,
    )
    store.replace(config)
    assert store.load() == config
    text = path.read_text(encoding="utf-8")
    assert "ack_timeout_s" not in text
    assert "control_sample_max_age_s" not in text


def test_store_rejects_wrong_schema(tmp_path):
    path = tmp_path / "load-control.json"
    path.write_text('{"schema_version":2,"config":{}}\n', encoding="utf-8")
    with pytest.raises(LoadControlConfigStoreError):
        LoadControlConfigStore(path).load()


def test_replace_failure_preserves_old_file(tmp_path, monkeypatch):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    original = PersistentLoadControlConfig(p_reserve=30.0)
    store.replace(original)
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(LoadControlConfigStoreError):
        store.replace(PersistentLoadControlConfig(p_reserve=40.0))
    assert LoadControlConfigStore(path).load() == original
```

- [ ] **Step 5: Implement strict schema and atomic replacement**

Use schema version `1`, exact top-level fields `schema_version` and `config`, deterministic JSON, `flush`, `os.fsync`, temporary sibling file, and `os.replace`. Delete the temporary file in `finally`.

- [ ] **Step 6: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py -q
git add src/emonio_viewer/load_control tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py
git commit -m "feat: add load control models and configuration store"
```

---

### Task 2: Deterministic Unity Controller and Small State Machine

**Files:**
- Create: `src/emonio_viewer/load_control/controller.py`
- Create: `src/emonio_viewer/load_control/state_machine.py`
- Create: `tests/unit/test_load_control_controller.py`
- Create: `tests/unit/test_load_control_state_machine.py`

**Interfaces:**
- `calculate_phase_request(*, measured_p: float, p_reserve: float, acknowledged_p: float, p_limit: float) -> PhaseControlResult`.
- `calculate_three_phase_request(*, measured_p: ThreePhasePower, p_reserve: float, acknowledged_p: ThreePhasePower, p_limit: ThreePhasePower) -> ThreePhaseControlResult`.
- `ControlStateMachine.enable()`, `.disable()`, `.trip(reason)`, `.mark_safe_unconfirmed()`, `.mark_safe_confirmed()`.

- [ ] **Step 1: Write failing controller tests**

```python
def test_export_from_zero_load_requests_450_w():
    result = calculate_phase_request(measured_p=-420.0, p_reserve=30.0, acknowledged_p=0.0, p_limit=1000.0)
    assert (result.error, result.raw_request, result.limited_request) == (450.0, 450.0, 450.0)


def test_next_request_uses_acknowledged_state():
    result = calculate_phase_request(measured_p=25.0, p_reserve=30.0, acknowledged_p=450.0, p_limit=1000.0)
    assert result.raw_request == 455.0


def test_zero_and_maximum_clamps_are_explicit():
    low = calculate_phase_request(measured_p=250.0, p_reserve=30.0, acknowledged_p=100.0, p_limit=1000.0)
    high = calculate_phase_request(measured_p=-900.0, p_reserve=30.0, acknowledged_p=0.0, p_limit=600.0)
    assert (low.limited_request, low.limited_min) == (0.0, True)
    assert (high.raw_request, high.limited_request, high.limited_max) == (930.0, 600.0, True)


def test_three_phase_calculation_keeps_phase_mapping():
    result = calculate_three_phase_request(
        measured_p=ThreePhasePower(-420.0, 25.0, 100.0),
        p_reserve=30.0,
        acknowledged_p=ThreePhasePower(0.0, 450.0, 50.0),
        p_limit=ThreePhasePower(600.0, 700.0, 800.0),
    )
    assert result.a.limited_request == 450.0
    assert result.b.limited_request == 455.0
    assert result.c.limited_request == 0.0
```

- [ ] **Step 2: Run controller RED**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py -q
```

- [ ] **Step 3: Implement only approved controller math**

```python
def calculate_phase_request(*, measured_p, p_reserve, acknowledged_p, p_limit):
    for value in (measured_p, p_reserve, acknowledged_p, p_limit):
        if not math.isfinite(value):
            raise ValueError("control inputs must be finite")
    if p_reserve <= 0.0 or acknowledged_p < 0.0 or p_limit <= 0.0:
        raise ValueError("invalid control limits")
    error = p_reserve - measured_p
    raw = acknowledged_p + error
    limited = min(max(raw, 0.0), p_limit)
    return PhaseControlResult(
        error=error,
        raw_request=raw,
        limited_request=limited,
        limited_min=raw < 0.0,
        limited_max=raw > p_limit,
    )
```

- [ ] **Step 4: Write failing state-machine tests**

```python
def test_startup_is_disabled():
    assert ControlStateMachine().mode is ControlMode.DISABLED


def test_disable_does_not_clear_trip():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.disable()
    assert machine.mode is ControlMode.TRIPPED
    assert machine.trip_reason is TripReason.ACTUATOR_CONNECTION_LOST


def test_explicit_enable_can_leave_trip_after_external_gate_passes():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.enable()
    assert machine.mode is ControlMode.ENABLED
    assert machine.trip_reason is None
```

- [ ] **Step 5: Implement exact state transitions**

The state machine never performs readiness checks. The supervisor calls `enable()` only after its complete gate passes. `disable()` is idempotent in `DISABLED`; in `TRIPPED` it does not change mode or trip reason.

- [ ] **Step 6: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py tests/unit/test_load_control_state_machine.py -q
git add src/emonio_viewer/load_control/controller.py src/emonio_viewer/load_control/state_machine.py tests/unit/test_load_control_controller.py tests/unit/test_load_control_state_machine.py
git commit -m "feat: add load control math and state machine"
```

---

### Task 3: Strict Protocol V1 and Deterministic JSONL Evidence

**Files:**
- Create: `src/emonio_viewer/load_control/protocol.py`
- Create: `src/emonio_viewer/load_control/evidence.py`
- Create: `tests/unit/test_load_control_protocol.py`
- Create: `tests/unit/test_load_control_evidence.py`

**Interfaces:**
- `LOAD_CONTROL_PROTOCOL_VERSION = 1`.
- Frozen `HelloFrame`, `CommandFrame`, `AckFrame`, `StatusFrame`.
- `encode_frame(frame) -> str`, `decode_frame(text: str) -> HelloFrame | CommandFrame | AckFrame | StatusFrame`.
- `EvidenceEvent`, `EvidenceWriteError`, `JsonlEvidenceWriter.append()`, `.healthy`, `.recent()`.

- [ ] **Step 1: Write exact protocol round-trip test**

```python
def test_command_round_trip_preserves_all_three_phases():
    frame = CommandFrame(
        protocol_version=1,
        viewer_session_id="VIEWER-TEST-1",
        node_id="ARI-LOAD-MOCK-001",
        boot_id="MOCK-BOOT-001",
        sequence=7,
        emonio_device_id="emonio-example",
        measurement_cycle_id=42,
        measurement_utc="2026-09-01T10:00:00+00:00",
        command_utc="2026-09-01T10:00:00.010000+00:00",
        control_enabled=True,
        p_reserve=30.0,
        measured_p=ThreePhasePower(-420.0, 10.0, 50.0),
        measured_q=ThreePhasePower(100.0, -20.0, 0.0),
        p_load_request=ThreePhasePower(450.0, 20.0, 0.0),
        q_comp_request=ThreePhasePower(0.0, 0.0, 0.0),
    )
    assert decode_frame(encode_frame(frame)) == frame
```

- [ ] **Step 2: Write strict rejection tests**

```python
@pytest.mark.parametrize("payload", [
    '{"message_type":"COMMAND","protocol_version":99}',
    '{"message_type":"COMMAND","protocol_version":1,"extra":1}',
    '{"message_type":"ACK","protocol_version":1,"applied_p":{"a":NaN,"b":0,"c":0}}',
])
def test_invalid_protocol_payload_is_rejected(payload):
    with pytest.raises(ProtocolValidationError):
        decode_frame(payload)


def test_v1_command_rejects_nonzero_q_compensation():
    with pytest.raises(ProtocolValidationError):
        CommandFrame.create_validated(
            protocol_version=1,
            viewer_session_id="V",
            node_id="N",
            boot_id="B",
            sequence=1,
            emonio_device_id="E",
            measurement_cycle_id=1,
            measurement_utc="2026-09-01T10:00:00+00:00",
            command_utc="2026-09-01T10:00:00+00:00",
            control_enabled=True,
            p_reserve=30.0,
            measured_p=ThreePhasePower(0.0, 0.0, 0.0),
            measured_q=ThreePhasePower(1.0, 2.0, 3.0),
            p_load_request=ThreePhasePower(0.0, 0.0, 0.0),
            q_comp_request=ThreePhasePower(1.0, 0.0, 0.0),
        )
```

- [ ] **Step 3: Implement strict serializer/parser**

Use exact field sets per message type. Use `json.dumps(..., allow_nan=False, sort_keys=True, separators=(",", ":"))`. Do not infer missing safety fields.

- [ ] **Step 4: Write deterministic evidence tests**

```python
def test_jsonl_writer_writes_one_sorted_line(tmp_path):
    writer = JsonlEvidenceWriter(tmp_path / "control.jsonl")
    writer.append(EvidenceEvent(
        schema_version=1,
        viewer_session_id="VIEWER-1",
        occurred_utc="2026-09-01T10:00:00+00:00",
        event="CONTROL_COMMAND_CALCULATED",
        payload={"b": 2, "a": 1},
    ))
    assert (tmp_path / "control.jsonl").read_text(encoding="utf-8").splitlines() == [
        '{"event":"CONTROL_COMMAND_CALCULATED","occurred_utc":"2026-09-01T10:00:00+00:00","payload":{"a":1,"b":2},"schema_version":1,"viewer_session_id":"VIEWER-1"}'
    ]


def test_evidence_failure_marks_writer_unhealthy(tmp_path, monkeypatch):
    writer = JsonlEvidenceWriter(tmp_path / "control.jsonl")
    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")))
    with pytest.raises(EvidenceWriteError):
        writer.append(EvidenceEvent(1, "VIEWER-1", "2026-09-01T10:00:00+00:00", "TEST", {}))
    assert writer.healthy is False
```

- [ ] **Step 5: Implement append-only evidence writer**

Use append mode, `flush`, `os.fsync`, and a bounded in-memory deque for recent evidence. A failed append sets health false. Never rewrite an earlier event.

- [ ] **Step 6: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py tests/unit/test_load_control_evidence.py -q
git add src/emonio_viewer/load_control/protocol.py src/emonio_viewer/load_control/evidence.py tests/unit/test_load_control_protocol.py tests/unit/test_load_control_evidence.py
git commit -m "feat: add load control protocol and evidence"
```

---

### Task 4: Mock Discovery and Mock Session Boundary

**Files:**
- Create: `src/emonio_viewer/load_control/discovery.py`
- Create: `src/emonio_viewer/load_control/session.py`
- Create: `tests/unit/test_load_control_mock.py`
- Create: `tests/unit/test_load_control_stage1_contract.py`

**Interfaces:**
- `ActuatorDiscovery` Protocol: `async discover() -> tuple[ActuatorDescriptor, ...]`.
- `ActuatorSession` Protocol: `async connect(descriptor: ActuatorDescriptor) -> HelloFrame`, `async send_command(command: CommandFrame) -> None`, `async receive() -> AckFrame | StatusFrame`, `async close() -> None`.
- Stage-1 implementations: `MockActuatorDiscovery`, `MockActuatorSession` only.

**Exact Viewer mock fixture:**

```text
node_id: ARI-LOAD-MOCK-001
location: mock://ARI-LOAD-MOCK-001
boot_id: MOCK-BOOT-001
protocol_version: 1
capabilities: ACTIVE_LOAD_CONTROL
P_max_A: 1000 W
P_max_B: 1000 W
P_max_C: 1000 W
```

These are deterministic fixture values, not hardware ratings or controller constants.

- [ ] **Step 1: Write discovery authority tests**

```python
@pytest.mark.asyncio
async def test_discovery_does_not_select_or_rebind():
    a = mock_descriptor("ARI-LOAD-MOCK-001", "mock://one")
    b = mock_descriptor("ARI-LOAD-MOCK-002", "mock://two")
    discovery = MockActuatorDiscovery((a, b))
    assert await discovery.discover() == (a, b)
    assert not hasattr(discovery, "selected_node_id")


@pytest.mark.asyncio
async def test_bound_node_disappearance_does_not_promote_other_node():
    a = mock_descriptor("ARI-LOAD-MOCK-001", "mock://one")
    b = mock_descriptor("ARI-LOAD-MOCK-002", "mock://two")
    discovery = MockActuatorDiscovery((a, b))
    discovery.set_visible((b,))
    visible = await discovery.discover()
    assert [item.node_id for item in visible] == ["ARI-LOAD-MOCK-002"]
```

- [ ] **Step 2: Write explicit mock-session scenario tests**

```python
@pytest.mark.asyncio
async def test_mock_session_exact_ack_reports_applied_request():
    session = MockActuatorSession.exact_ack(boot_id="MOCK-BOOT-001")
    await session.connect(mock_descriptor("ARI-LOAD-MOCK-001", "mock://one"))
    command = safe_test_command(sequence=5, p=ThreePhasePower(100.0, 200.0, 300.0))
    await session.send_command(command)
    ack = await session.receive()
    assert ack.sequence == 5
    assert ack.applied_p == ThreePhasePower(100.0, 200.0, 300.0)


@pytest.mark.asyncio
async def test_mock_session_missing_ack_is_explicit():
    session = MockActuatorSession.no_ack(boot_id="MOCK-BOOT-001")
    await session.connect(mock_descriptor("ARI-LOAD-MOCK-001", "mock://one"))
    await session.send_command(safe_test_command(sequence=6, p=ThreePhasePower(0.0, 0.0, 0.0)))
    assert session.pending_receive_count == 0
```

Add named factory scenarios for wrong sequence, wrong node ID, boot change, capability change, limit change, connection loss, and applied-value offset. Each scenario uses fixed explicit values.

- [ ] **Step 3: Implement Protocols and deterministic mocks**

No random delay, random load error, smoothing, plant simulation, socket, mDNS, or HTTP/WebSocket client is allowed.

- [ ] **Step 4: Write mock-only source gate**

```python
from pathlib import Path


def test_stage1_has_no_real_actuator_transport_implementation():
    root = Path("src/emonio_viewer/load_control")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in ("WebSocketActuatorSession", "MdnsActuatorDiscovery", "zeroconf", "ClientSession"):
        assert forbidden not in source
```

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_mock.py tests/unit/test_load_control_stage1_contract.py -q
git add src/emonio_viewer/load_control/discovery.py src/emonio_viewer/load_control/session.py tests/unit/test_load_control_mock.py tests/unit/test_load_control_stage1_contract.py
git commit -m "feat: add deterministic mock actuator boundary"
```

---

### Task 5: Pure LoadControlSupervisor

**Files:**
- Create: `src/emonio_viewer/load_control/supervisor.py`
- Create: `tests/fixtures/load_control_samples.py`
- Create: `tests/unit/test_load_control_supervisor.py`

**Interfaces:**
- `SupervisorDecision(events: tuple[EvidenceEvent, ...], command: CommandFrame | None, status: LoadControlStatus)`.
- `LoadControlSupervisor.request_enable(now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`.
- `request_disable(command_utc: datetime) -> SupervisorDecision`.
- `on_measurement(sample: MeasurementSample, now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`.
- `on_diagnostic(event: DiagnosticEvent, command_utc: datetime) -> SupervisorDecision`.
- `on_ack(ack: AckFrame, command_utc: datetime) -> SupervisorDecision`.
- `on_session_ready(hello: HelloFrame, command_utc: datetime) -> SupervisorDecision`.
- `on_session_lost(command_utc: datetime) -> SupervisorDecision`.
- `on_time(now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`.
- `on_evidence_failure(command_utc: datetime) -> SupervisorDecision`.

- [ ] **Step 1: Create immutable sample test helper**

```python
def sample_with_power(base, *, cycle_id, p_a, p_b, p_c, q_a=0.0, q_b=0.0, q_c=0.0, quality=SampleQuality.VALID, finished_ns=1_100_000_000):
    def phase(block, p, q):
        measurement = replace(block.measurement, p=p, q=q)
        return replace(block, measurement=measurement)
    return replace(
        base,
        identity=replace(base.identity, cycle_id=cycle_id),
        timing=replace(base.timing, cycle_finished_monotonic_ns=finished_ns),
        phase_a=phase(base.phase_a, p_a, q_a),
        phase_b=phase(base.phase_b, p_b, q_b),
        phase_c=phase(base.phase_c, p_c, q_c),
        quality=quality,
    )
```

- [ ] **Step 2: Write table-driven enable-gate tests**

```python
@pytest.mark.parametrize("case", [
    "NO_EMONIO_BINDING",
    "NO_ACTUATOR_BINDING",
    "NO_RESERVE",
    "NO_OPERATOR_LIMITS",
    "TIMING_UNQUALIFIED",
    "NO_SAMPLE",
    "SAMPLE_NOT_VALID",
    "SAMPLE_STALE",
    "SESSION_NOT_READY",
    "IDENTITY_MISMATCH",
    "CAPABILITY_MISSING",
    "SAFE_NOT_CONFIRMED",
    "EVIDENCE_UNHEALTHY",
])
def test_enable_gate_rejects_one_missing_condition(case, ready_supervisor_factory):
    supervisor = ready_supervisor_factory(except_condition=case)
    decision = supervisor.request_enable(2_000_000_000, utc(10, 0, 1))
    assert decision.status.control_mode is not ControlMode.ENABLED
    assert decision.status.last_enable_rejection == case


def test_complete_enable_gate_enters_enabled(ready_supervisor):
    decision = ready_supervisor.request_enable(2_000_000_000, utc(10, 0, 1))
    assert decision.status.control_mode is ControlMode.ENABLED
```

- [ ] **Step 3: Write exact sign and phase test**

```python
def test_control_uses_ack_state_and_keeps_phases_independent(ready_supervisor, real_sample):
    ready_supervisor.set_acknowledged_p(ThreePhasePower(0.0, 450.0, 50.0))
    sample = sample_with_power(real_sample, cycle_id=10, p_a=-420.0, p_b=25.0, p_c=100.0, q_a=100.0, q_b=-20.0, q_c=5.0)
    decision = ready_supervisor.on_measurement(sample, 1_100_000_001, utc(10, 0, 2))
    assert decision.command.p_load_request == ThreePhasePower(450.0, 455.0, 0.0)
    assert decision.command.measured_q == ThreePhasePower(100.0, -20.0, 5.0)
    assert decision.command.q_comp_request == ThreePhasePower(0.0, 0.0, 0.0)
```

- [ ] **Step 4: Write sequence and intermediate-sample tests**

```python
def test_intermediate_samples_are_not_replayed(ready_supervisor, real_sample):
    first = ready_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=20, p_a=-100.0, p_b=0.0, p_c=0.0), 1_100_000_001, utc(10, 0, 2))
    assert first.command.sequence == 1
    second = ready_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=21, p_a=-200.0, p_b=0.0, p_c=0.0), 1_200_000_001, utc(10, 0, 3))
    assert second.command is None
    ready_supervisor.on_ack(valid_ack_for(first.command), utc(10, 0, 4))
    third = ready_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=22, p_a=-300.0, p_b=0.0, p_c=0.0), 1_300_000_001, utc(10, 0, 5))
    assert third.command.sequence == 2
    assert third.command.measurement_cycle_id == 22
```

- [ ] **Step 5: Write ACK authority and safe-preemption tests**

```python
def test_safe_command_supersedes_nonzero_command(ready_supervisor, real_sample):
    active = ready_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=30, p_a=-100.0, p_b=0.0, p_c=0.0), 1_100_000_001, utc(10, 0, 2))
    tripped = ready_supervisor.on_session_lost(utc(10, 0, 3))
    assert tripped.status.control_mode is ControlMode.TRIPPED
    assert tripped.command.sequence == active.command.sequence + 1
    assert tripped.command.p_load_request == ThreePhasePower(0.0, 0.0, 0.0)
    obsolete = ready_supervisor.on_ack(valid_ack_for(active.command), utc(10, 0, 4))
    assert obsolete.status.control_mode is ControlMode.TRIPPED
```

- [ ] **Step 6: Write cycle-gap and acquisition-failure tests**

```python
def test_unexplained_cycle_gap_trips(ready_supervisor, real_sample):
    ready_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=40, p_a=0.0, p_b=0.0, p_c=0.0), 1_100_000_001, utc(10, 0, 2))
    decision = ready_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=42, p_a=0.0, p_b=0.0, p_c=0.0), 1_200_000_001, utc(10, 0, 3))
    assert decision.status.trip_reason is TripReason.CONTROL_SAMPLE_SEQUENCE_GAP


def test_explicit_acquisition_failure_trips_immediately(ready_supervisor):
    event = DiagnosticEvent("emonio-example", 41, utc(10, 0, 3), "ACQUISITION_TIMEOUT", Severity.WARNING, "A: timeout")
    decision = ready_supervisor.on_diagnostic(event, utc(10, 0, 3))
    assert decision.status.control_mode is ControlMode.TRIPPED
```

- [ ] **Step 7: Write quality, deadline, identity, capability, and evidence-failure tests**

```python
@pytest.mark.parametrize("quality", [SampleQuality.DEGRADED, SampleQuality.STALE, SampleQuality.INVALID])
def test_non_valid_quality_trips(ready_supervisor, real_sample, quality):
    sample = sample_with_power(real_sample, cycle_id=50, p_a=0.0, p_b=0.0, p_c=0.0, quality=quality)
    assert ready_supervisor.on_measurement(sample, 1_100_000_001, utc(10, 0, 2)).status.control_mode is ControlMode.TRIPPED


def test_freshness_deadline_trips(ready_supervisor):
    decision = ready_supervisor.on_time(ready_supervisor.sample_deadline_ns + 1, utc(10, 0, 9))
    assert decision.status.trip_reason is TripReason.CONTROL_SAMPLE_STALE


def test_evidence_failure_trips_active_control(ready_supervisor):
    decision = ready_supervisor.on_evidence_failure(utc(10, 0, 9))
    assert decision.status.trip_reason is TripReason.CONTROL_EVIDENCE_WRITE_ERROR
```

Add fixed-value tests for boot change, wrong node ID, protocol mismatch, capability loss, limit change, invalid active ACK, and acknowledgement deadline. Each must assert the exact `TripReason`.

- [ ] **Step 8: Write operator-disable state tests**

```python
def test_disable_from_tripped_does_not_clear_trip(tripped_supervisor):
    reason = tripped_supervisor.status().trip_reason
    decision = tripped_supervisor.request_disable(utc(10, 0, 9))
    assert decision.status.control_mode is ControlMode.TRIPPED
    assert decision.status.trip_reason is reason
```

- [ ] **Step 9: Implement supervisor and verify**

The supervisor performs no file I/O and no network I/O. It owns command sequence allocation for the injected Viewer session ID and returns decisions only.

```bash
python3 -m pytest tests/unit/test_load_control_supervisor.py -q
git add src/emonio_viewer/load_control/supervisor.py tests/fixtures/load_control_samples.py tests/unit/test_load_control_supervisor.py
git commit -m "feat: add load control supervisor decisions"
```

---

### Task 6: Async LoadControlService and RuntimeEventBus Isolation

**Files:**
- Create: `src/emonio_viewer/load_control/service.py`
- Create: `tests/unit/test_load_control_service.py`

**Interfaces:**
- `LoadControlService.start()`, `stop()`.
- `set_binding(emonio_device_id: str, actuator_node_id: str) -> LoadControlStatus`.
- `set_safety_config(p_reserve: float, operator_limits: ThreePhasePower) -> LoadControlStatus`.
- `set_mock_timing(timing: LoadControlTiming) -> LoadControlStatus`.
- `enable() -> LoadControlStatus`, `disable() -> LoadControlStatus`.
- `status() -> LoadControlStatus`.
- `discovered_actuators() -> tuple[ActuatorDescriptor, ...]`.
- `recent_evidence(limit: int = 100) -> tuple[dict, ...]`.

- [ ] **Step 1: Write event-bus isolation test**

```python
@pytest.mark.asyncio
async def test_service_subscribes_without_blocking_bus(real_sample, tmp_path):
    bus = RuntimeEventBus()
    service = build_test_service(bus=bus, tmp_path=tmp_path)
    await service.start()
    started = time.monotonic()
    bus.publish(real_sample)
    assert time.monotonic() - started < 0.05
    await service.stop()
```

The test threshold measures local non-blocking publication only; it is not a controller timing constant.

- [ ] **Step 2: Write exact startup qualification test**

```python
@pytest.mark.asyncio
async def test_bound_mock_node_qualifies_and_confirms_safe(tmp_path):
    service = build_test_service(tmp_path=tmp_path, persisted_node="ARI-LOAD-MOCK-001", mock_mode="EXACT_ACK")
    await service.start()
    status = service.status()
    assert status.control_mode is ControlMode.DISABLED
    assert status.session_state is SessionState.READY
    assert status.safe_state is SafeState.SAFE_CONFIRMED
    assert status.actuator_boot_id == "MOCK-BOOT-001"
    await service.stop()
```

- [ ] **Step 3: Write no-auto-transfer test**

```python
@pytest.mark.asyncio
async def test_missing_bound_node_does_not_use_other_visible_node(tmp_path):
    service, discovery = build_two_node_service(tmp_path=tmp_path, bound_node="ARI-LOAD-MOCK-001")
    await service.start()
    discovery.set_visible((mock_descriptor("ARI-LOAD-MOCK-002", "mock://two"),))
    await service.refresh_discovery()
    assert service.status().bound_actuator_node_id == "ARI-LOAD-MOCK-001"
    assert service.status().session_state is SessionState.UNAVAILABLE
    await service.stop()
```

- [ ] **Step 4: Write atomic service-config test**

```python
def test_service_does_not_replace_memory_when_persistence_fails(service, monkeypatch):
    before = service.status().persistent_config
    monkeypatch.setattr(service.config_store, "replace", lambda _config: (_ for _ in ()).throw(LoadControlConfigStoreError("write failed")))
    with pytest.raises(LoadControlCommandError):
        service.set_safety_config(40.0, ThreePhasePower(600.0, 600.0, 600.0))
    assert service.status().persistent_config == before
```

- [ ] **Step 5: Write evidence-before-nonzero-send test**

```python
@pytest.mark.asyncio
async def test_evidence_failure_blocks_nonzero_send_and_still_attempts_safe(ready_enabled_service, real_sample):
    ready_enabled_service.evidence_writer.fail_next_append(OSError("disk error"))
    ready_enabled_service.bus.publish(sample_with_power(real_sample, cycle_id=70, p_a=-420.0, p_b=0.0, p_c=0.0))
    await ready_enabled_service.drain()
    sent = ready_enabled_service.mock_session.sent_commands
    assert all(command.p_load_request == ThreePhasePower(0.0, 0.0, 0.0) for command in sent)
    assert ready_enabled_service.status().control_mode is ControlMode.TRIPPED
```

- [ ] **Step 6: Write source-isolation and explicit-deadline tests**

```python
@pytest.mark.asyncio
async def test_other_emonio_samples_do_not_drive_control(ready_enabled_service, real_sample):
    other = replace(real_sample, identity=replace(real_sample.identity, device_id="other-emonio", cycle_id=1))
    ready_enabled_service.bus.publish(other)
    await ready_enabled_service.drain()
    assert ready_enabled_service.mock_session.nonzero_command_count == 0


def test_service_has_no_timing_default(tmp_path):
    service = build_test_service(tmp_path=tmp_path, timing=None)
    assert service.status().timing_qualified is False
```

- [ ] **Step 7: Implement service ordering and lifecycle**

Persist configuration before replacing in-memory configuration. For normal non-zero decisions, required calculation/send-attempt evidence must append before session send. If evidence fails, feed `on_evidence_failure()` to supervisor and block the non-zero send. Required safe commands are attempted even when evidence is unhealthy.

- [ ] **Step 8: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_service.py -q
git add src/emonio_viewer/load_control/service.py tests/unit/test_load_control_service.py
git commit -m "feat: add isolated load control service"
```

---

### Task 7: Thin HTTP API, Viewer Composition, and Safe Shutdown

**Files:**
- Create: `src/emonio_viewer/server/load_control_api.py`
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/app.py`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Modify: `src/emonio_viewer/main.py`
- Modify: `tests/unit/test_launcher.py`
- Create: `tests/integration/test_load_control_api.py`
- Create: `tests/integration/test_load_control_runtime.py`

**Interfaces:**
- Add `LOAD_CONTROL_SERVICE_KEY`.
- Routes:
  - `GET /api/v1/load-control/status`
  - `GET /api/v1/load-control/discovered-actuators`
  - `GET /api/v1/load-control/evidence/recent`
  - `POST /api/v1/load-control/binding`
  - `POST /api/v1/load-control/config`
  - `POST /api/v1/load-control/mock-timing`
  - `POST /api/v1/load-control/enable`
  - `POST /api/v1/load-control/disable`

- [ ] **Step 1: Write status and no-direct-command API tests**

```python
async def test_status_reports_mock_control_domains(client):
    response = await client.get("/api/v1/load-control/status")
    assert response.status == 200
    body = await response.json()
    for key in (
        "control_mode", "session_state", "safe_state", "trip_reason",
        "viewer_session_id", "bound_emonio_device_id", "bound_actuator_node_id",
        "actuator_boot_id", "protocol_version", "capabilities", "p_reserve",
        "operator_limits", "actuator_limits", "effective_limits",
        "last_measurement_cycle_id", "last_measurement_quality",
        "last_acknowledged_p", "outstanding_sequence", "last_acknowledged_sequence",
        "last_command", "last_ack", "last_trip", "evidence_health", "timing_qualified",
        "transport_mode",
    ):
        assert key in body
    assert body["transport_mode"] == "MOCK"


async def test_no_direct_phase_command_route(app):
    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/api/v1/load-control/command" not in paths
```

- [ ] **Step 2: Write operator error mapping tests**

```python
async def test_binding_change_while_enabled_is_conflict(client, enabled_service):
    response = await client.post("/api/v1/load-control/binding", json={
        "emonio_device_id": "emonio-example",
        "actuator_node_id": "ARI-LOAD-MOCK-001",
    })
    assert response.status == 409
    assert (await response.json())["error"] == "CONTROL_BINDING_CHANGE_FORBIDDEN_WHILE_ENABLED"


async def test_unqualified_enable_returns_exact_gate_reason(client):
    response = await client.post("/api/v1/load-control/enable", json={})
    assert response.status == 409
    assert (await response.json())["error"].startswith("ENABLE_GATE_")
```

- [ ] **Step 3: Wire composition root with exact mock fixture**

In `main.py`, generate one `viewer_session_id` with `uuid.uuid4().hex`. Create `LoadControlConfigStore(config_path.parent / "load-control.json")`, the exact stage-1 mock descriptor from Task 4, `MockActuatorDiscovery`, `MockActuatorSession`, `JsonlEvidenceWriter(PROJECT_ROOT / "load-control-evidence" / f"{viewer_session_id}.jsonl")`, and `LoadControlService`. Start the service before acquisition workers. Do not supply timing defaults.

- [ ] **Step 4: Write launcher composition test**

```python
async def test_load_control_starts_before_workers(monkeypatch, tmp_path):
    trace = []
    monkeypatch_load_control_and_runtime(trace, tmp_path)
    await run_viewer_until_cancelled(tmp_path / "emonio-viewer.toml")
    assert trace.index("START_LOAD_CONTROL") < trace.index("START_WORKERS")
```

Use the existing launcher test style and existing injected trace mechanism. Do not change acquisition startup code except the composition ordering around it.

- [ ] **Step 5: Write safe shutdown-order tests**

```python
async def test_shutdown_revokes_load_control_before_other_runtime_owners():
    trace = []
    await shutdown_viewer_with_fakes(trace)
    assert trace == [
        "STOP_LOAD_CONTROL_COMMANDS",
        "STOP_LOAD_CONTROL",
        "STOP_SCOPE",
        "STOP_RECORDING_COMMANDS",
        "STOP_RECORDERS",
        "STOP_WORKERS",
        "STOP_SERVER",
    ]
```

For mock exact ACK, shutdown records safe confirmed. For mock no-ACK, it records safe unconfirmed and closes without indefinite waiting. No real-network shutdown timeout is introduced.

- [ ] **Step 6: Implement thin API and app wiring**

`load_control_api.py` adapts HTTP bodies to service methods and maps service errors. It contains no controller math and no command construction. Both `app.py` and active `app_v0416.py` accept an optional load-control service and register the same load-control route module.

- [ ] **Step 7: Verify and commit**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py -q
git add src/emonio_viewer/main.py src/emonio_viewer/server/keys.py src/emonio_viewer/server/app.py src/emonio_viewer/server/app_v0416.py src/emonio_viewer/server/load_control_api.py tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py
git commit -m "feat: expose mock load control service"
```

---

### Task 8: Compact Load Control Frontend Without Header Changes

**Files:**
- Create: `frontend/css/load-control.css`
- Create: `frontend/js/load-control-api.js`
- Create: `frontend/js/load-control-ui.js`
- Modify: `frontend/index.html`
- Create: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Add one compact `details` panel immediately after the current Emonio target strip.
- Do not add or change controls in the current status header.
- Summary always shows control mode, session state, and safe state.
- Expanded panel shows bindings, reserve, operator limits, volatile mock timing, A/B/C measured P, A/B/C acknowledged load, A/B/C last request, limits, sequence evidence, evidence health, and last trip.

- [ ] **Step 1: Write static DOM contract test**

```python
def test_load_control_panel_has_required_controls_and_no_direct_power_command():
    source = Path("frontend/index.html").read_text(encoding="utf-8")
    for element_id in (
        "load-control-panel", "load-control-mode", "load-control-session-state",
        "load-control-safe-state", "load-control-source", "load-control-actuator",
        "load-control-reserve", "load-control-limit-a", "load-control-limit-b",
        "load-control-limit-c", "load-control-sample-max-age", "load-control-ack-timeout",
        "load-control-enable", "load-control-disable", "load-control-last-trip",
    ):
        assert f'id="{element_id}"' in source
    for forbidden in ("p_request_a", "p_request_b", "p_request_c"):
        assert forbidden not in source
```

- [ ] **Step 2: Write JS endpoint and authority contract test**

```python
def test_load_control_js_uses_only_supervisory_endpoints():
    source = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")
    for required in (
        "/api/v1/load-control/status",
        "/api/v1/load-control/discovered-actuators",
        "/api/v1/load-control/binding",
        "/api/v1/load-control/config",
        "/api/v1/load-control/mock-timing",
        "/api/v1/load-control/enable",
        "/api/v1/load-control/disable",
    ):
        assert required in source
    assert "/api/v1/load-control/command" not in source
```

- [ ] **Step 3: Implement structured CSS**

Create only `frontend/css/load-control.css` for new rules. Reuse existing CSS variables. Do not edit existing header CSS and do not add inline styles.

- [ ] **Step 4: Implement API module and UI module**

`load-control-api.js` contains fetch functions only. `load-control-ui.js` renders backend status and disables binding/config/timing controls whenever backend `control_mode === "ENABLED"`. JavaScript does not recalculate power.

Operator-visible timing text must state: `MOCK TIMING · VOLATILE · NOT QUALIFIED FOR HARDWARE`.

- [ ] **Step 5: Verify frontend scope**

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
python3 -m pytest tests/browser/test_header_status_layout.py -q
```

Compare the header result with preflight. Do not alter the existing header test or header layout.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html frontend/css/load-control.css frontend/js/load-control-api.js frontend/js/load-control-ui.js tests/browser/test_load_control_contract.py
git commit -m "feat: add load control status interface"
```

---

### Task 9: Full Mock-Stage Acceptance

**Files:**
- Change only narrow load-control tests/integration code if fresh evidence finds a defect.
- Do not weaken `tools/ari-emonio-acceptance.sh`.

- [ ] **Step 1: Run all load-control unit tests**

```bash
python3 -m pytest \
  tests/unit/test_load_control_model.py \
  tests/unit/test_load_control_config_store.py \
  tests/unit/test_load_control_controller.py \
  tests/unit/test_load_control_state_machine.py \
  tests/unit/test_load_control_protocol.py \
  tests/unit/test_load_control_evidence.py \
  tests/unit/test_load_control_mock.py \
  tests/unit/test_load_control_supervisor.py \
  tests/unit/test_load_control_service.py \
  tests/unit/test_load_control_stage1_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: Run load-control integration and frontend tests**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py -q
python3 -m pytest tests/browser/test_load_control_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Run existing suites**

```bash
python3 -m pytest tests/unit -q
python3 -m pytest tests/integration -q
python3 -m pytest tests/browser -q
```

Any new failure blocks acceptance. Compare the browser result with preflight and keep the unrelated pre-existing header-layout result separate.

- [ ] **Step 4: Run read-only, compilation, and sign gates**

```bash
python3 -m pytest tests/unit/test_read_only_contract.py -q
python3 -m compileall -q src tests
python3 -m pytest tests/integration/test_end_to_end_sign.py -q
```

Expected: PASS.

- [ ] **Step 5: Prove protected paths unchanged**

```bash
git diff --exit-code e3e33ec959d6304ca8471ab1c0f217884b64ed18 HEAD -- \
  src/emonio_viewer/modbus \
  src/emonio_viewer/measurement \
  src/emonio_viewer/acquisition \
  src/emonio_viewer/runtime/events.py \
  src/emonio_viewer/runtime/store.py \
  src/emonio_viewer/scope
```

Expected: exit code `0`.

- [ ] **Step 6: Prove no real actuator network implementation exists**

```bash
python3 -m pytest tests/unit/test_load_control_stage1_contract.py -q
if grep -R -E "WebSocketActuatorSession|MdnsActuatorDiscovery|zeroconf" src/emonio_viewer/load_control; then
  echo "real actuator network implementation found in mock-only stage" >&2
  exit 1
fi
```

Expected: test PASS and grep finds no forbidden implementation.

- [ ] **Step 7: Inspect exact changed paths**

```bash
git status --short
git diff --stat e3e33ec959d6304ca8471ab1c0f217884b64ed18..HEAD
git diff --name-only e3e33ec959d6304ca8471ab1c0f217884b64ed18..HEAD
```

Changes must remain limited to the new load-control subsystem, thin API/composition wiring, compact frontend, tests, and approved documentation.

- [ ] **Step 8: Commit only evidence-driven final corrections**

If fresh acceptance evidence required a narrow correction, commit exactly those files with a focused message. If no files changed, do not create an empty commit.

---

## Required First-Stage Acceptance Evidence

Fresh evidence must demonstrate all of these points:

1. Startup control mode is always `DISABLED`.
2. Persistent binding never restores enable state, command sequence, boot state, acknowledged demand, or safe confirmation.
3. One selected Emonio source is isolated from other Emonio devices.
4. Only fresh `VALID` canonical samples can drive control.
5. A/B/C mapping is exact.
6. Negative measured P produces the approved additional-load result.
7. Controller state starts from last acknowledged applied load, not last transmitted load.
8. Requests stay `>= 0 W` and use `min(actuator limit, operator limit)`.
9. Saturation is visible and is not a trip by itself.
10. Only one normal command can be outstanding.
11. Intermediate samples are safety-checked but never replayed as delayed commands.
12. Emonio cycle ID and actuator command sequence remain separate.
13. Every command binds Viewer session ID, node ID, boot ID, and sequence.
14. Wrong identity, boot, protocol, or active sequence is rejected.
15. Actuator reboot invalidates previous acknowledged load state.
16. Faults while enabled latch `TRIPPED`.
17. Cleared faults never automatically re-enable control.
18. Operator disable from enabled requests safe state but is not a trip.
19. Operator disable cannot clear an existing trip.
20. Safe commands preempt an outstanding non-zero command.
21. `SAFE_UNCONFIRMED` and `SAFE_CONFIRMED` remain distinct.
22. Only a successful exact-zero applied ACK confirms safe state.
23. Q telemetry remains present and Q compensation requests remain zero.
24. Evidence distinguishes measured, calculated, transmitted, and acknowledged values.
25. Evidence write failure blocks new non-zero transmission and trips active control.
26. Evidence failure does not suppress a required safe-command attempt.
27. Mock discovery never grants authority and never changes persistent binding.
28. Loss of the bound mock actuator never transfers control to another discovered node.
29. No real actuator network client exists in stage 1.
30. No browser endpoint or field directly commands phase power.
31. Existing read-only Modbus, scientific sign, SCOPE, and CSV paths remain unchanged.

## Execution Handoff

After this plan is approved for execution, use one workflow:

1. **Subagent-Driven (recommended):** Use `superpowers:subagent-driven-development`. Execute one task at a time with a fresh worker and two-stage review.
2. **Inline Execution:** Use `superpowers:executing-plans`. Execute tasks in this session in reviewable batches with checkpoints.

Do not begin implementation until the execution workflow is selected.