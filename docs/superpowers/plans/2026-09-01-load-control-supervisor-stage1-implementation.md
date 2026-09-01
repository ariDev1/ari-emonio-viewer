# ARI Emonio Viewer External Load Control Supervisor Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Viewer-side external load-control supervisor with deterministic mock discovery and mock actuator transport only, while preserving the trusted Emonio measurement architecture.

**Architecture:** Add an isolated `emonio_viewer.load_control` subsystem that consumes immutable canonical `MeasurementSample` and `DiagnosticEvent` objects from the existing non-blocking `RuntimeEventBus`. Pure modules own the controller, protocol data, and safety state. `LoadControlService` serializes operator commands and runtime events, persists only approved binding/safety configuration, writes independent JSONL evidence, and talks only to deterministic mock discovery/session adapters in Stage 1.

**Tech Stack:** Python 3.10+, standard library `dataclasses`, `asyncio`, `json`, `pathlib`, existing `aiohttp==3.14.3`, pytest 8.4.1, plain ES modules, structured CSS. Do not add `pytest-asyncio`; async tests use the repository's existing `asyncio.run(...)` pattern.

**Spec:** `docs/superpowers/specs/2026-09-01-load-control-supervisor-design.md`

## Global Constraints

- Work on branch `testing` only.
- Protected production-code baseline: `e3e33ec959d6304ca8471ab1c0f217884b64ed18`.
- Do not merge or modify `main`.
- Do not modify `src/emonio_viewer/modbus`, `src/emonio_viewer/measurement`, `src/emonio_viewer/acquisition`, `src/emonio_viewer/runtime/events.py`, `src/emonio_viewer/runtime/store.py`, or `src/emonio_viewer/scope`.
- Preserve read-only Modbus behavior, canonical measurement signs, P/Q quadrant semantics, validation, fixed-deadline acquisition, SCOPE semantics, and CSV precision.
- Stage 1 contains no mDNS network implementation, no real WebSocket actuator client, no ESP32 firmware, no PWM, and no physical power-stage path.
- Stage 1 uses only `MockActuatorDiscovery` and `MockActuatorSession`.
- Control starts `DISABLED` on every Viewer process start.
- Persistent binding never restores enable state, sequence state, boot state, acknowledged demand, or safe confirmation.
- Only fresh `MeasurementSample.quality == VALID` data from the bound Emonio can drive active control.
- P and Q remain separate. Q is telemetry only. `Q_comp_request_A/B/C` are always exactly `0 var`.
- Active-load requests are non-negative only.
- Controller baseline: `P_request_raw = P_acknowledged + P_reserve - P_measured`, independently for A/B/C.
- Effective limit per phase: `min(actuator_max, operator_max)`.
- Do not add gain, PID, averaging, interpolation, smoothing, hysteresis, deadband, random plant behavior, or invented control timing values.
- `control_sample_max_age_s` and `ack_timeout_s` are explicit volatile Stage-1 qualification inputs. No default is allowed and neither value is persisted.
- Only one normal command can be outstanding. A safe command can preempt it.
- Last valid ACK is authoritative applied-load state. A sent command is not applied-state evidence.
- Safety-critical configuration changes are permitted only while `DISABLED`.
- The browser never directly sets phase load requests.
- Do not modify the known unrelated `tests/browser/test_header_status_layout.py` failure or the current header layout.
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

Record the exact baseline result for `tests/browser/test_header_status_layout.py` separately.

Verify protected paths before source work:

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

## File Map

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

Modify:

```text
src/emonio_viewer/main.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/app.py
src/emonio_viewer/server/app_v0416.py
frontend/index.html
tests/unit/test_launcher.py
```

---

### Task 1: Core Models and Atomic Persistent Configuration

**Files:**
- Create: `src/emonio_viewer/load_control/__init__.py`
- Create: `src/emonio_viewer/load_control/model.py`
- Create: `src/emonio_viewer/load_control/config_store.py`
- Test: `tests/unit/test_load_control_model.py`
- Test: `tests/unit/test_load_control_config_store.py`

**Interfaces:**

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

@dataclass(frozen=True, slots=True)
class PersistentLoadControlConfig:
    bound_emonio_device_id: str | None = None
    bound_actuator_node_id: str | None = None
    p_reserve: float | None = None
    operator_limit_a: float | None = None
    operator_limit_b: float | None = None
    operator_limit_c: float | None = None

class LoadControlConfigStore:
    def load(self) -> PersistentLoadControlConfig: ...
    def replace(self, config: PersistentLoadControlConfig) -> None: ...
```

Also define exact enums: `ControlMode(DISABLED, ENABLED, TRIPPED)`, `SessionState(UNBOUND, DISCOVERING, UNAVAILABLE, CONNECTING, VERIFYING, READY, SESSION_FAULT)`, `SafeState(NOT_REQUIRED, SAFE_UNCONFIRMED, SAFE_CONFIRMED)`, `LimitState(NONE, LIMITED_MIN, LIMITED_MAX)`, `ActuatorCapability(ACTIVE_LOAD_CONTROL, REACTIVE_COMPENSATION)`, and the approved `TripReason` values.

- [ ] **Step 1: Write failing validation tests**

```python
import math
import pytest

from emonio_viewer.load_control.model import LoadControlTiming, PersistentLoadControlConfig, ThreePhasePower


def test_three_phase_power_preserves_mapping():
    value = ThreePhasePower(1.0, 2.0, 3.0)
    assert (value.a, value.b, value.c) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_reserve_must_be_finite_and_positive(bad):
    with pytest.raises(ValueError):
        PersistentLoadControlConfig(p_reserve=bad)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_mock_timing_must_be_finite_and_positive(bad):
    with pytest.raises(ValueError):
        LoadControlTiming(bad, 1.0)
    with pytest.raises(ValueError):
        LoadControlTiming(1.0, bad)
```

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest tests/unit/test_load_control_model.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement model validation**

`PersistentLoadControlConfig` accepts partial configuration, but any supplied binding ID must be non-empty text and any supplied reserve/operator limit must be finite and `> 0`. `LoadControlTiming` is separate and never part of the persistent model.

- [ ] **Step 4: Write exact atomic-store tests**

```python
import os
import pytest

from emonio_viewer.load_control.config_store import LoadControlConfigStore, LoadControlConfigStoreError
from emonio_viewer.load_control.model import PersistentLoadControlConfig


def test_missing_file_loads_empty_config(tmp_path):
    assert LoadControlConfigStore(tmp_path / "load-control.json").load() == PersistentLoadControlConfig()


def test_store_round_trip_excludes_timing(tmp_path):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    config = PersistentLoadControlConfig("emonio-example", "ARI-LOAD-MOCK-001", 30.0, 600.0, 700.0, 800.0)
    store.replace(config)
    assert store.load() == config
    text = path.read_text(encoding="utf-8")
    assert "control_sample_max_age_s" not in text
    assert "ack_timeout_s" not in text


def test_replace_failure_keeps_old_file(tmp_path, monkeypatch):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    original = PersistentLoadControlConfig(p_reserve=30.0)
    store.replace(original)
    def fail_replace(_src, _dst):
        raise OSError("replace failed")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(LoadControlConfigStoreError):
        store.replace(PersistentLoadControlConfig(p_reserve=40.0))
    assert LoadControlConfigStore(path).load() == original
```

Also add exact-schema rejection for wrong JSON type, wrong field set, unsupported schema version, and invalid persisted numeric data.

- [ ] **Step 5: Implement atomic store**

Use schema version `1`, exact top-level keys `schema_version` and `config`, deterministic `json.dump(..., indent=2, sort_keys=True)`, sibling `.tmp` file, `flush`, `os.fsync`, `os.replace`, and temporary-file cleanup in `finally`.

- [ ] **Step 6: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py -q
git add src/emonio_viewer/load_control/__init__.py src/emonio_viewer/load_control/model.py src/emonio_viewer/load_control/config_store.py tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py
git commit -m "feat: add load control models and configuration store"
```

---

### Task 2: Deterministic Controller and Control State Machine

**Files:**
- Create: `src/emonio_viewer/load_control/controller.py`
- Create: `src/emonio_viewer/load_control/state_machine.py`
- Test: `tests/unit/test_load_control_controller.py`
- Test: `tests/unit/test_load_control_state_machine.py`

**Interfaces:**

```python
def calculate_phase_request(*, measured_p: float, p_reserve: float, acknowledged_p: float, p_limit: float) -> PhaseControlResult: ...

def calculate_three_phase_request(*, measured_p: ThreePhasePower, p_reserve: float, acknowledged_p: ThreePhasePower, p_limit: ThreePhasePower) -> ThreePhaseControlResult: ...

class ControlStateMachine:
    def enable(self) -> None: ...
    def disable(self) -> None: ...
    def trip(self, reason: TripReason) -> None: ...
    def mark_safe_unconfirmed(self) -> None: ...
    def mark_safe_confirmed(self) -> None: ...
```

- [ ] **Step 1: Write failing controller tests**

```python
def test_export_from_zero_load_requests_450_w():
    result = calculate_phase_request(measured_p=-420.0, p_reserve=30.0, acknowledged_p=0.0, p_limit=1000.0)
    assert (result.error, result.raw_request, result.limited_request) == (450.0, 450.0, 450.0)


def test_next_request_uses_acknowledged_applied_load():
    result = calculate_phase_request(measured_p=25.0, p_reserve=30.0, acknowledged_p=450.0, p_limit=1000.0)
    assert result.raw_request == 455.0


def test_phase_limits_are_independent():
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

- [ ] **Step 2: Verify RED and implement approved math**

```python
error = p_reserve - measured_p
raw_request = acknowledged_p + error
limited_request = min(max(raw_request, 0.0), p_limit)
```

Reject all non-finite inputs, `p_reserve <= 0`, `acknowledged_p < 0`, and `p_limit <= 0`. Report `limited_min` and `limited_max`; saturation itself is not a trip.

- [ ] **Step 3: Write failing state tests**

```python
def test_control_starts_disabled():
    assert ControlStateMachine().mode is ControlMode.DISABLED


def test_disable_from_enabled_is_not_trip():
    machine = ControlStateMachine()
    machine.enable()
    machine.disable()
    assert machine.mode is ControlMode.DISABLED


def test_disable_cannot_clear_trip():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.disable()
    assert machine.mode is ControlMode.TRIPPED
    assert machine.trip_reason is TripReason.ACTUATOR_CONNECTION_LOST
```

- [ ] **Step 4: Implement state transitions**

`enable()` only changes state; the supervisor owns the enable gate. `disable()` is idempotent while disabled and does not leave `TRIPPED`. Safe confirmation is independent of control mode.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py tests/unit/test_load_control_state_machine.py -q
git add src/emonio_viewer/load_control/controller.py src/emonio_viewer/load_control/state_machine.py tests/unit/test_load_control_controller.py tests/unit/test_load_control_state_machine.py
git commit -m "feat: add load control math and state machine"
```

---

### Task 3: Strict Protocol V1 and Append-Only Evidence

**Files:**
- Create: `src/emonio_viewer/load_control/protocol.py`
- Create: `src/emonio_viewer/load_control/evidence.py`
- Test: `tests/unit/test_load_control_protocol.py`
- Test: `tests/unit/test_load_control_evidence.py`

**Interfaces:**

```python
LOAD_CONTROL_PROTOCOL_VERSION = 1

@dataclass(frozen=True, slots=True)
class HelloFrame:
    protocol_version: int
    node_id: str
    boot_id: str
    capabilities: tuple[str, ...]
    p_max: ThreePhasePower

@dataclass(frozen=True, slots=True)
class CommandFrame:
    protocol_version: int
    viewer_session_id: str
    node_id: str
    boot_id: str
    sequence: int
    emonio_device_id: str
    measurement_cycle_id: int
    measurement_utc: str
    command_utc: str
    control_enabled: bool
    p_reserve: float
    measured_p: ThreePhasePower
    measured_q: ThreePhasePower
    p_load_request: ThreePhasePower
    q_comp_request: ThreePhasePower

@dataclass(frozen=True, slots=True)
class AckFrame:
    protocol_version: int
    viewer_session_id: str
    node_id: str
    boot_id: str
    sequence: int
    ack_utc: str
    applied_p: ThreePhasePower
    result: str

def encode_frame(frame) -> str: ...
def decode_frame(text: str): ...
```

`StatusFrame` is asynchronous telemetry only and cannot authorize control.

- [ ] **Step 1: Write protocol round-trip and rejection tests**

```python
def test_command_round_trip_keeps_p_and_q_separate():
    frame = CommandFrame(
        1, "VIEWER-1", "ARI-LOAD-MOCK-001", "MOCK-BOOT-001", 7,
        "emonio-example", 42, "2026-09-01T10:00:00+00:00",
        "2026-09-01T10:00:00.010000+00:00", True, 30.0,
        ThreePhasePower(-420.0, 10.0, 50.0),
        ThreePhasePower(100.0, -20.0, 5.0),
        ThreePhasePower(450.0, 20.0, 0.0),
        ThreePhasePower(0.0, 0.0, 0.0),
    )
    assert decode_frame(encode_frame(frame)) == frame


@pytest.mark.parametrize("text", [
    '{"message_type":"COMMAND","protocol_version":99}',
    '{"message_type":"ACK","protocol_version":1,"applied_p":{"a":NaN,"b":0,"c":0}}',
])
def test_invalid_protocol_json_is_rejected(text):
    with pytest.raises(ProtocolValidationError):
        decode_frame(text)
```

Add an exact test that any non-zero V1 `q_comp_request` raises `ProtocolValidationError`. Add exact-field-set tests for missing or extra fields.

- [ ] **Step 2: Implement strict protocol serialization**

Use `json.dumps(..., allow_nan=False, sort_keys=True, separators=(",", ":"))`. Every message has exact `message_type` and `protocol_version`. Do not default missing safety fields.

- [ ] **Step 3: Write evidence tests**

```python
def test_jsonl_writer_appends_deterministic_line(tmp_path):
    writer = JsonlEvidenceWriter(tmp_path / "control.jsonl")
    event = EvidenceEvent(1, "VIEWER-1", "2026-09-01T10:00:00+00:00", "CONTROL_COMMAND_CALCULATED", {"b": 2, "a": 1})
    writer.append(event)
    line = (tmp_path / "control.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert line == '{"event":"CONTROL_COMMAND_CALCULATED","occurred_utc":"2026-09-01T10:00:00+00:00","payload":{"a":1,"b":2},"schema_version":1,"viewer_session_id":"VIEWER-1"}'


def test_fsync_failure_marks_writer_unhealthy(tmp_path, monkeypatch):
    writer = JsonlEvidenceWriter(tmp_path / "control.jsonl")
    def fail_fsync(_fd):
        raise OSError("disk failure")
    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(EvidenceWriteError):
        writer.append(EvidenceEvent(1, "VIEWER-1", "2026-09-01T10:00:00+00:00", "TEST", {}))
    assert writer.healthy is False
```

- [ ] **Step 4: Implement evidence writer**

Append one deterministic JSON object per line, flush and fsync every accepted event, keep a bounded recent-event deque, and never rewrite old evidence. A failed write sets `healthy=False`.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py tests/unit/test_load_control_evidence.py -q
git add src/emonio_viewer/load_control/protocol.py src/emonio_viewer/load_control/evidence.py tests/unit/test_load_control_protocol.py tests/unit/test_load_control_evidence.py
git commit -m "feat: add load control protocol and evidence"
```

---

### Task 4: Mock Discovery and Mock Session Only

**Files:**
- Create: `src/emonio_viewer/load_control/discovery.py`
- Create: `src/emonio_viewer/load_control/session.py`
- Test: `tests/unit/test_load_control_mock.py`
- Test: `tests/unit/test_load_control_stage1_contract.py`

**Interfaces:**

```python
class ActuatorDiscovery(Protocol):
    async def discover(self) -> tuple[ActuatorDescriptor, ...]: ...

class ActuatorSession(Protocol):
    async def connect(self, descriptor: ActuatorDescriptor) -> HelloFrame: ...
    async def send_command(self, command: CommandFrame) -> None: ...
    async def receive(self) -> AckFrame | StatusFrame: ...
    async def close(self) -> None: ...
```

Exact default mock descriptor:

```text
node_id = ARI-LOAD-MOCK-001
location = mock://ARI-LOAD-MOCK-001
boot_id = MOCK-BOOT-001
protocol_version = 1
capabilities = ACTIVE_LOAD_CONTROL
P_max = A:1000 W, B:1000 W, C:1000 W
```

These are test fixture values, not physical ratings.

**Test helpers in `tests/unit/test_load_control_mock.py`:**

```python
def descriptor(node_id: str, location: str) -> ActuatorDescriptor:
    return ActuatorDescriptor(node_id=node_id, location=location)


def run(coro):
    return asyncio.run(coro)
```

- [ ] **Step 1: Write discovery tests with repository async style**

```python
def test_discovery_only_reports_visible_nodes():
    async def scenario():
        a = descriptor("ARI-LOAD-MOCK-001", "mock://one")
        b = descriptor("ARI-LOAD-MOCK-002", "mock://two")
        discovery = MockActuatorDiscovery((a, b))
        assert await discovery.discover() == (a, b)
        discovery.set_visible((b,))
        assert await discovery.discover() == (b,)
        assert not hasattr(discovery, "selected_node_id")
    run(scenario())
```

- [ ] **Step 2: Write explicit session tests**

```python
def test_exact_ack_reports_requested_applied_load():
    async def scenario():
        session = MockActuatorSession.exact_ack(boot_id="MOCK-BOOT-001")
        hello = await session.connect(descriptor("ARI-LOAD-MOCK-001", "mock://one"))
        assert hello.boot_id == "MOCK-BOOT-001"
        command = stage1_test_command(sequence=5, p=ThreePhasePower(100.0, 200.0, 300.0))
        await session.send_command(command)
        ack = await session.receive()
        assert ack.sequence == 5
        assert ack.applied_p == ThreePhasePower(100.0, 200.0, 300.0)
    run(scenario())
```

Create fixed scenario constructors for no ACK, wrong sequence, wrong node ID, boot change, capability change, P-max change, connection loss, and applied-value offset. No scenario uses randomness.

- [ ] **Step 3: Implement only mock adapters**

Do not import `socket`, `zeroconf`, or `aiohttp.ClientSession` in `emonio_viewer.load_control`.

- [ ] **Step 4: Write source gate**

```python
def test_stage1_has_no_real_actuator_network_implementation():
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
- Test: `tests/unit/test_load_control_supervisor.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    events: tuple[EvidenceEvent, ...]
    command: CommandFrame | None
    status: LoadControlStatus

class LoadControlSupervisor:
    def request_enable(self, now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision: ...
    def request_disable(self, command_utc: datetime) -> SupervisorDecision: ...
    def on_measurement(self, sample: MeasurementSample, now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision: ...
    def on_diagnostic(self, event: DiagnosticEvent, command_utc: datetime) -> SupervisorDecision: ...
    def on_ack(self, ack: AckFrame, command_utc: datetime) -> SupervisorDecision: ...
    def on_session_ready(self, hello: HelloFrame, command_utc: datetime) -> SupervisorDecision: ...
    def on_session_lost(self, command_utc: datetime) -> SupervisorDecision: ...
    def on_time(self, now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision: ...
    def on_evidence_failure(self, command_utc: datetime) -> SupervisorDecision: ...
```

- [ ] **Step 1: Create canonical test sample helper**

```python
def sample_with_power(base, *, cycle_id, p_a, p_b, p_c, q_a=0.0, q_b=0.0, q_c=0.0, quality=SampleQuality.VALID, finished_ns=1_100_000_000):
    def block_with(block, p, q):
        return replace(block, measurement=replace(block.measurement, p=p, q=q))
    return replace(
        base,
        identity=replace(base.identity, cycle_id=cycle_id),
        timing=replace(base.timing, cycle_finished_monotonic_ns=finished_ns),
        phase_a=block_with(base.phase_a, p_a, q_a),
        phase_b=block_with(base.phase_b, p_b, q_b),
        phase_c=block_with(base.phase_c, p_c, q_c),
        quality=quality,
    )
```

- [ ] **Step 2: Write enable-gate matrix**

Create `ready_supervisor_factory(except_condition: str | None)` in the test file. It builds a supervisor with binding, reserve, limits, explicit timing, current `VALID` sample, qualified HELLO, exact matching identity, `ACTIVE_LOAD_CONTROL`, `SAFE_CONFIRMED`, and healthy evidence, then removes exactly one named condition.

```python
@pytest.mark.parametrize("missing", [
    "EMONIO_BINDING", "ACTUATOR_BINDING", "RESERVE", "OPERATOR_LIMITS",
    "TIMING", "SAMPLE", "SAMPLE_VALID", "SAMPLE_FRESH", "SESSION_READY",
    "IDENTITY", "CAPABILITY", "SAFE_CONFIRMED", "EVIDENCE_HEALTH",
])
def test_enable_gate_rejects_each_missing_condition(ready_supervisor_factory, missing):
    supervisor = ready_supervisor_factory(except_condition=missing)
    decision = supervisor.request_enable(2_000_000_000, utc(10, 0, 1))
    assert decision.status.control_mode is not ControlMode.ENABLED
    assert decision.status.last_enable_rejection.startswith("ENABLE_GATE_")
```

Add `test_enable_does_not_replay_pre_enable_sample`: after enable succeeds, no command is created until the next newly received cycle.

- [ ] **Step 3: Write sign, phase, P/Q separation test**

```python
def test_control_uses_acknowledged_state_and_phase_mapping(ready_enabled_supervisor, real_sample):
    ready_enabled_supervisor.set_acknowledged_p(ThreePhasePower(0.0, 450.0, 50.0))
    sample = sample_with_power(real_sample, cycle_id=10, p_a=-420.0, p_b=25.0, p_c=100.0, q_a=100.0, q_b=-20.0, q_c=5.0)
    decision = ready_enabled_supervisor.on_measurement(sample, 1_100_000_001, utc(10, 0, 2))
    assert decision.command.p_load_request == ThreePhasePower(450.0, 455.0, 0.0)
    assert decision.command.measured_q == ThreePhasePower(100.0, -20.0, 5.0)
    assert decision.command.q_comp_request == ThreePhasePower(0.0, 0.0, 0.0)
```

- [ ] **Step 4: Write sequence, ACK authority, and intermediate-sample tests**

```python
def test_one_normal_command_and_no_delayed_replay(ready_enabled_supervisor, real_sample):
    first = ready_enabled_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=20, p_a=-100.0, p_b=0.0, p_c=0.0), 1_100_000_001, utc(10, 0, 2))
    assert first.command.sequence == 1
    second = ready_enabled_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=21, p_a=-200.0, p_b=0.0, p_c=0.0), 1_200_000_001, utc(10, 0, 3))
    assert second.command is None
    ready_enabled_supervisor.on_ack(valid_ack_for(first.command), utc(10, 0, 4))
    third = ready_enabled_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=22, p_a=-300.0, p_b=0.0, p_c=0.0), 1_300_000_001, utc(10, 0, 5))
    assert third.command.sequence == 2
    assert third.command.measurement_cycle_id == 22
```

Write fixed-value ACK tests for wrong Viewer session ID, node ID, boot ID, sequence, non-finite P, negative P, above-limit P, and unsuccessful result. Accepted ACK applied P becomes the next controller base state.

- [ ] **Step 5: Write safe preemption and safe-confirmation tests**

```python
def test_trip_preempts_outstanding_nonzero_command(ready_enabled_supervisor, real_sample):
    active = ready_enabled_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=30, p_a=-100.0, p_b=0.0, p_c=0.0), 1_100_000_001, utc(10, 0, 2))
    tripped = ready_enabled_supervisor.on_session_lost(utc(10, 0, 3))
    assert tripped.status.control_mode is ControlMode.TRIPPED
    assert tripped.command.sequence == active.command.sequence + 1
    assert tripped.command.p_load_request == ThreePhasePower(0.0, 0.0, 0.0)
    assert tripped.status.safe_state is SafeState.SAFE_UNCONFIRMED
```

Add an exact test that a successful matching safe ACK with applied `0/0/0` changes to `SAFE_CONFIRMED`, while any non-zero applied value does not.

- [ ] **Step 6: Write cycle, quality, timing, and trip tests**

```python
def test_unexplained_cycle_gap_trips(ready_enabled_supervisor, real_sample):
    ready_enabled_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=40, p_a=0.0, p_b=0.0, p_c=0.0), 1_100_000_001, utc(10, 0, 2))
    decision = ready_enabled_supervisor.on_measurement(sample_with_power(real_sample, cycle_id=42, p_a=0.0, p_b=0.0, p_c=0.0), 1_200_000_001, utc(10, 0, 3))
    assert decision.status.trip_reason is TripReason.CONTROL_SAMPLE_SEQUENCE_GAP


@pytest.mark.parametrize("quality", [SampleQuality.DEGRADED, SampleQuality.STALE, SampleQuality.INVALID])
def test_non_valid_quality_trips(ready_enabled_supervisor, real_sample, quality):
    sample = sample_with_power(real_sample, cycle_id=50, p_a=0.0, p_b=0.0, p_c=0.0, quality=quality)
    assert ready_enabled_supervisor.on_measurement(sample, 1_100_000_001, utc(10, 0, 2)).status.control_mode is ControlMode.TRIPPED
```

Add exact tests for acquisition timeout/protocol/decode/transport diagnostics, boot change, identity mismatch, capability loss, actuator-limit change, freshness deadline, ACK deadline, protocol error, and evidence failure. Each test asserts its exact trip reason.

- [ ] **Step 7: Write operator-disable tests**

```python
def test_disable_from_tripped_does_not_clear_trip(tripped_supervisor):
    original = tripped_supervisor.status().trip_reason
    decision = tripped_supervisor.request_disable(utc(10, 0, 9))
    assert decision.status.control_mode is ControlMode.TRIPPED
    assert decision.status.trip_reason is original
```

Also test `ENABLED -> DISABLED` with safe command and idempotent disable while already disabled.

- [ ] **Step 8: Implement supervisor and verify**

The supervisor has no file I/O and no network I/O. It owns command sequence allocation for its injected Viewer session ID and emits decisions only.

```bash
python3 -m pytest tests/unit/test_load_control_supervisor.py -q
git add src/emonio_viewer/load_control/supervisor.py tests/fixtures/load_control_samples.py tests/unit/test_load_control_supervisor.py
git commit -m "feat: add load control supervisor decisions"
```

---

### Task 6: Async LoadControlService and RuntimeEventBus Isolation

**Files:**
- Create: `src/emonio_viewer/load_control/service.py`
- Test: `tests/unit/test_load_control_service.py`

**Interfaces:**

```python
class LoadControlService:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def refresh_discovery(self) -> tuple[ActuatorDescriptor, ...]: ...
    async def set_binding(self, emonio_device_id: str, actuator_node_id: str) -> LoadControlStatus: ...
    async def set_safety_config(self, p_reserve: float, operator_limits: ThreePhasePower) -> LoadControlStatus: ...
    async def set_mock_timing(self, timing: LoadControlTiming) -> LoadControlStatus: ...
    async def enable(self) -> LoadControlStatus: ...
    async def disable(self) -> LoadControlStatus: ...
    def status(self) -> LoadControlStatus: ...
    def discovered_actuators(self) -> tuple[ActuatorDescriptor, ...]: ...
    def recent_evidence(self, limit: int = 100) -> tuple[dict, ...]: ...
```

Use one `asyncio.Lock` to serialize mutating service operations. Subscribe to `RuntimeEventBus` with its own bounded queue. On stop, unsubscribe first and place a private sentinel in the subscriber queue so `asyncio.to_thread(subscriber.get)` exits without a polling timeout. Mock session close similarly unblocks its receiver. Deadline tasks sleep only until explicit freshness/ACK deadlines and are rescheduled when those deadlines change.

**Test helper:**

```python
def run(coro):
    return asyncio.run(coro)
```

- [ ] **Step 1: Write service startup/isolation test**

```python
def test_service_is_independent_runtime_bus_consumer(real_sample, tmp_path):
    async def scenario():
        bus = RuntimeEventBus()
        service = build_test_service(bus=bus, tmp_path=tmp_path)
        await service.start()
        bus.publish(real_sample)
        await service.drain_test_tasks()
        assert service.status().last_measurement_cycle_id == real_sample.identity.cycle_id
        await service.stop()
    run(scenario())
```

The acquisition publisher is never changed to await the service.

- [ ] **Step 2: Write startup qualification and no-auto-transfer tests**

```python
def test_bound_mock_node_qualifies_safe_state(tmp_path):
    async def scenario():
        service = build_test_service(tmp_path=tmp_path, persisted_node="ARI-LOAD-MOCK-001", mock_scenario="EXACT_ACK")
        await service.start()
        status = service.status()
        assert status.control_mode is ControlMode.DISABLED
        assert status.session_state is SessionState.READY
        assert status.safe_state is SafeState.SAFE_CONFIRMED
        assert status.actuator_boot_id == "MOCK-BOOT-001"
        await service.stop()
    run(scenario())


def test_missing_bound_node_never_promotes_other_node(tmp_path):
    async def scenario():
        service, discovery = build_two_node_service(tmp_path=tmp_path, bound_node="ARI-LOAD-MOCK-001")
        await service.start()
        discovery.set_visible((ActuatorDescriptor("ARI-LOAD-MOCK-002", "mock://two"),))
        await service.refresh_discovery()
        assert service.status().bound_actuator_node_id == "ARI-LOAD-MOCK-001"
        assert service.status().session_state is SessionState.UNAVAILABLE
        await service.stop()
    run(scenario())
```

- [ ] **Step 3: Write persistence-before-memory test**

```python
def test_failed_persistence_keeps_previous_service_config(tmp_path):
    async def scenario():
        service = build_test_service(tmp_path=tmp_path)
        await service.start()
        before = service.status().persistent_config
        service.config_store.fail_next_replace(OSError("disk error"))
        with pytest.raises(LoadControlCommandError):
            await service.set_safety_config(40.0, ThreePhasePower(600.0, 600.0, 600.0))
        assert service.status().persistent_config == before
        await service.stop()
    run(scenario())
```

If the production store has no test-only fail hook, inject a failing store fake through the service constructor. Do not add a failure hook to production persistence solely for tests.

- [ ] **Step 4: Write evidence-before-send and source-isolation tests**

```python
def test_evidence_failure_blocks_nonzero_and_still_attempts_safe(real_sample, tmp_path):
    async def scenario():
        service = build_ready_enabled_service(tmp_path=tmp_path, evidence_writer=FailingEvidenceWriter())
        await service.start()
        service.bus.publish(sample_with_power(real_sample, cycle_id=70, p_a=-420.0, p_b=0.0, p_c=0.0))
        await service.drain_test_tasks()
        assert service.status().control_mode is ControlMode.TRIPPED
        assert all(cmd.p_load_request == ThreePhasePower(0.0, 0.0, 0.0) for cmd in service.mock_session.sent_commands)
        await service.stop()
    run(scenario())


def test_other_emonio_sample_cannot_drive_bound_controller(real_sample, tmp_path):
    async def scenario():
        service = build_ready_enabled_service(tmp_path=tmp_path, bound_emonio="emonio-example")
        await service.start()
        other = replace(real_sample, identity=replace(real_sample.identity, device_id="other-emonio", cycle_id=1))
        service.bus.publish(other)
        await service.drain_test_tasks()
        assert service.mock_session.nonzero_command_count == 0
        await service.stop()
    run(scenario())
```

- [ ] **Step 5: Write explicit timing tests**

```python
def test_service_has_no_mock_timing_until_operator_sets_it(tmp_path):
    service = build_test_service(tmp_path=tmp_path, timing=None)
    assert service.status().timing_qualified is False
```

Add deterministic-clock tests that set explicit `LoadControlTiming(1.0, 0.5)` and advance injected monotonic time beyond each deadline. These numbers belong only to the test case.

- [ ] **Step 6: Implement service execution ordering**

For non-zero commands: write calculation/send-attempt evidence first; if evidence fails, call supervisor evidence-failure transition and never send the non-zero command. For safe commands: attempt the safe send even when evidence is unhealthy. Persist binding/config before changing in-memory state. Do not persist mock timing.

- [ ] **Step 7: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_service.py -q
git add src/emonio_viewer/load_control/service.py tests/unit/test_load_control_service.py
git commit -m "feat: add isolated load control service"
```

---

### Task 7: Thin HTTP API, Viewer Composition, and Shutdown

**Files:**
- Create: `src/emonio_viewer/server/load_control_api.py`
- Modify: `src/emonio_viewer/server/keys.py`
- Modify: `src/emonio_viewer/server/app.py`
- Modify: `src/emonio_viewer/server/app_v0416.py`
- Modify: `src/emonio_viewer/main.py`
- Modify: `tests/unit/test_launcher.py`
- Test: `tests/integration/test_load_control_api.py`
- Test: `tests/integration/test_load_control_runtime.py`

**Routes:**

```text
GET  /api/v1/load-control/status
GET  /api/v1/load-control/discovered-actuators
GET  /api/v1/load-control/evidence/recent
POST /api/v1/load-control/binding
POST /api/v1/load-control/config
POST /api/v1/load-control/mock-timing
POST /api/v1/load-control/enable
POST /api/v1/load-control/disable
```

No `/api/v1/load-control/command` route exists.

**Integration test helper follows existing repository style:**

```python
async def _request(app, method: str, path: str, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body)
            payload = await response.json()
            return response.status, payload
```

- [ ] **Step 1: Write API status and authority tests**

```python
def test_load_control_status_reports_three_state_domains(app):
    status, body = asyncio.run(_request(app, "GET", "/api/v1/load-control/status"))
    assert status == 200
    for key in ("control_mode", "session_state", "safe_state", "trip_reason", "viewer_session_id", "bound_emonio_device_id", "bound_actuator_node_id", "actuator_boot_id", "protocol_version", "capabilities", "p_reserve", "operator_limits", "actuator_limits", "effective_limits", "last_measurement_cycle_id", "last_measurement_quality", "last_acknowledged_p", "outstanding_sequence", "last_acknowledged_sequence", "last_command", "last_ack", "last_trip", "evidence_health", "timing_qualified", "transport_mode"):
        assert key in body
    assert body["transport_mode"] == "MOCK"


def test_app_exposes_no_direct_power_command_route(app):
    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/api/v1/load-control/command" not in paths
```

- [ ] **Step 2: Write error-mapping tests**

```python
def test_binding_change_while_enabled_is_conflict(enabled_app):
    status, body = asyncio.run(_request(enabled_app, "POST", "/api/v1/load-control/binding", {"emonio_device_id":"emonio-example","actuator_node_id":"ARI-LOAD-MOCK-001"}))
    assert status == 409
    assert body["error"] == "CONTROL_BINDING_CHANGE_FORBIDDEN_WHILE_ENABLED"


def test_enable_rejection_preserves_exact_gate_code(unqualified_app):
    status, body = asyncio.run(_request(unqualified_app, "POST", "/api/v1/load-control/enable", {}))
    assert status == 409
    assert body["error"].startswith("ENABLE_GATE_")
```

Add `400` tests for malformed binding/config/timing bodies and `503` when the service key is absent.

- [ ] **Step 3: Wire composition root**

In `main.py`, generate exactly one `viewer_session_id = uuid.uuid4().hex` per Viewer process. Create the load-control config store at `config_path.parent / "load-control.json"`. Create the exact default mock descriptor from Task 4. Create the JSONL path at `PROJECT_ROOT / "load-control-evidence" / f"{viewer_session_id}.jsonl"`. Start `LoadControlService` before `coordinator.start()` so the event subscriber exists before the first acquisition event. Supply no timing default.

- [ ] **Step 4: Write launcher order tests**

```python
def test_load_control_starts_before_acquisition_workers(monkeypatch, tmp_path):
    trace = []
    asyncio.run(run_viewer_with_test_shutdown(tmp_path, trace, monkeypatch))
    assert trace.index("START_LOAD_CONTROL") < trace.index("START_WORKERS")
```

Use the existing trace-based launcher-test pattern; do not replace the launcher architecture.

- [ ] **Step 5: Write shutdown ordering test**

```python
def test_shutdown_revokes_control_before_runtime_owners():
    trace = []
    asyncio.run(shutdown_viewer_with_fakes(trace))
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

Mock exact ACK yields safe confirmed. Mock no-ACK yields safe unconfirmed and closes without indefinite waiting. No real-network timeout constant is introduced.

- [ ] **Step 6: Implement API and app wiring**

`load_control_api.py` maps request JSON to service methods and maps `LoadControlCommandError` codes to HTTP responses. It contains no control math and no actuator command construction. Add `LOAD_CONTROL_SERVICE_KEY` and register the same route module from `app.py` and active `app_v0416.py`.

- [ ] **Step 7: Verify and commit**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py -q
git add src/emonio_viewer/main.py src/emonio_viewer/server/keys.py src/emonio_viewer/server/app.py src/emonio_viewer/server/app_v0416.py src/emonio_viewer/server/load_control_api.py tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py
git commit -m "feat: expose mock load control service"
```

---

### Task 8: Compact Frontend Without Header Regression

**Files:**
- Create: `frontend/css/load-control.css`
- Create: `frontend/js/load-control-api.js`
- Create: `frontend/js/load-control-ui.js`
- Modify: `frontend/index.html`
- Test: `tests/browser/test_load_control_contract.py`

**UI contract:** Add a compact `details` panel directly after the existing Emonio target strip. Its summary always shows control mode, session state, and safe state. Do not add or modify current header controls.

- [ ] **Step 1: Write static DOM test**

```python
def test_load_control_panel_has_supervisory_controls_only():
    source = Path("frontend/index.html").read_text(encoding="utf-8")
    for element_id in ("load-control-panel", "load-control-mode", "load-control-session-state", "load-control-safe-state", "load-control-source", "load-control-actuator", "load-control-reserve", "load-control-limit-a", "load-control-limit-b", "load-control-limit-c", "load-control-sample-max-age", "load-control-ack-timeout", "load-control-enable", "load-control-disable", "load-control-last-trip"):
        assert f'id="{element_id}"' in source
    for forbidden in ("p_request_a", "p_request_b", "p_request_c"):
        assert forbidden not in source
```

- [ ] **Step 2: Write frontend API authority test**

```python
def test_load_control_api_module_has_no_direct_command_endpoint():
    source = Path("frontend/js/load-control-api.js").read_text(encoding="utf-8")
    for endpoint in ("/api/v1/load-control/status", "/api/v1/load-control/discovered-actuators", "/api/v1/load-control/binding", "/api/v1/load-control/config", "/api/v1/load-control/mock-timing", "/api/v1/load-control/enable", "/api/v1/load-control/disable"):
        assert endpoint in source
    assert "/api/v1/load-control/command" not in source
```

- [ ] **Step 3: Implement structured CSS**

Put all new rules in `frontend/css/load-control.css`. Reuse existing variables and density. Do not edit existing header CSS and do not add inline style attributes.

- [ ] **Step 4: Implement API/UI modules**

`load-control-api.js` performs HTTP requests only. `load-control-ui.js` renders backend state and disables binding/config/timing controls when `control_mode === "ENABLED"`. It does not recalculate P. Display: bound source/node, measured P A/B/C, acknowledged load A/B/C, last requested load A/B/C, effective limits, sequences, evidence health, and last trip. Mock timing label is exactly `MOCK TIMING · VOLATILE · NOT QUALIFIED FOR HARDWARE`.

- [ ] **Step 5: Verify frontend scope and commit**

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
python3 -m pytest tests/browser/test_header_status_layout.py -q
```

Compare the header result with preflight; do not alter the existing header test or layout.

```bash
git add frontend/index.html frontend/css/load-control.css frontend/js/load-control-api.js frontend/js/load-control-ui.js tests/browser/test_load_control_contract.py
git commit -m "feat: add load control status interface"
```

---

### Task 9: Full Stage-1 Acceptance and Protected-Path Evidence

**Files:**
- Do not alter protected scientific paths.
- Do not weaken `tools/ari-emonio-acceptance.sh`.

- [ ] **Step 1: Run all new load-control unit tests**

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

- [ ] **Step 2: Run new integration and frontend tests**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py -q
python3 -m pytest tests/browser/test_load_control_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Run existing unit/integration regression suites**

```bash
python3 -m pytest tests/unit -q
python3 -m pytest tests/integration -q
```

Expected: no new failure.

- [ ] **Step 4: Run browser regression with the known header test separated**

```bash
python3 -m pytest tests/browser --ignore=tests/browser/test_header_status_layout.py -q
python3 -m pytest tests/browser/test_header_status_layout.py -q
```

The first command must PASS. The second command must reproduce the preflight baseline result. If the preflight header test unexpectedly passed, it must still pass here.

- [ ] **Step 5: Run read-only, compilation, and sign gates**

```bash
python3 -m pytest tests/unit/test_read_only_contract.py -q
python3 -m compileall -q src tests
python3 -m pytest tests/integration/test_end_to_end_sign.py -q
```

Expected: PASS.

- [ ] **Step 6: Prove protected paths are unchanged**

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

- [ ] **Step 7: Prove no real actuator network implementation exists**

```bash
python3 -m pytest tests/unit/test_load_control_stage1_contract.py -q
if grep -R -E "WebSocketActuatorSession|MdnsActuatorDiscovery|zeroconf" src/emonio_viewer/load_control; then
  echo "real actuator network implementation found in mock-only stage" >&2
  exit 1
fi
```

Expected: test PASS and grep finds no forbidden implementation.

- [ ] **Step 8: Inspect changed-path scope**

```bash
git status --short
git diff --stat e3e33ec959d6304ca8471ab1c0f217884b64ed18..HEAD
git diff --name-only e3e33ec959d6304ca8471ab1c0f217884b64ed18..HEAD
```

Only the new load-control subsystem, thin API/composition wiring, compact frontend, tests, and approved docs are permitted.

- [ ] **Step 9: Commit only evidence-driven final corrections**

If fresh acceptance evidence required a narrow correction, commit those exact files. If no files changed, do not create an empty commit.

---

## Required Stage-1 Acceptance Evidence

Fresh evidence must prove:

1. Startup is always `DISABLED`.
2. Persistent binding does not persist control authority or acknowledged state.
3. One bound Emonio source is isolated from all other Emonio devices.
4. Only fresh `VALID` canonical samples can drive control.
5. A/B/C mapping is exact.
6. Negative P uses the approved sign and load calculation.
7. Controller state starts from last acknowledged applied load.
8. Requests are non-negative and use lower actuator/operator limit.
9. Saturation is visible and does not trip by itself.
10. Only one normal command can be outstanding.
11. Intermediate samples are safety-checked and never replayed as delayed commands.
12. Measurement cycle ID and actuator command sequence remain separate.
13. Command identity binds Viewer session, node, boot, and sequence.
14. Invalid identity/protocol/ACK data cannot become authoritative state.
15. Actuator boot change invalidates previous acknowledged state.
16. Safety faults latch `TRIPPED`.
17. Cleared faults never auto-enable control.
18. Operator disable from enabled requests safe state but is not a trip.
19. Operator disable cannot clear a trip.
20. Safe commands preempt outstanding non-zero commands.
21. `SAFE_UNCONFIRMED` and `SAFE_CONFIRMED` remain distinct.
22. Only a successful exact-zero applied ACK confirms safety.
23. Q telemetry remains present and Q compensation requests remain zero.
24. Evidence keeps measured, calculated, transmitted, and acknowledged facts distinct.
25. Evidence failure blocks new non-zero command transmission and trips active control.
26. Evidence failure does not suppress a required safe-command attempt.
27. Discovery never grants authority or changes binding.
28. Loss of the bound node never transfers control to another node.
29. No real actuator network implementation exists.
30. No browser endpoint or field directly commands phase power.
31. Existing read-only Modbus, scientific sign, SCOPE, and CSV behavior remains unchanged.

## Execution Handoff

After this plan is approved for execution, select one workflow:

1. **Subagent-Driven (recommended):** Use `superpowers:subagent-driven-development`. Execute one task at a time with a fresh worker and two-stage review.
2. **Inline Execution:** Use `superpowers:executing-plans`. Execute tasks in this session in reviewable batches with checkpoints.

Do not begin implementation until the execution workflow is selected.