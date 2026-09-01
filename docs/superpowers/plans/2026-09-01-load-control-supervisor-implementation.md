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
- The first implementation contains no mDNS network implementation, no real WebSocket actuator client, no ESP32 firmware, no PWM logic, and no physical power-stage control path.
- The first implementation uses `MockActuatorDiscovery` and `MockActuatorSession` only.
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
- Control freshness and acknowledgement timeouts are explicit volatile mock-stage qualification inputs. They have no production default and are not persisted.
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
- Produce: `ThreePhasePower`, `ControlMode`, `SessionState`, `SafeState`, `LimitState`, `ActuatorCapability`, `TripReason`, `ActuatorDescriptor`, `ActuatorSessionIdentity`, `LoadControlTiming`, `PersistentLoadControlConfig`, `LoadControlStatus`.
- Produce: `LoadControlConfigStore.load() -> PersistentLoadControlConfig`.
- Produce: `LoadControlConfigStore.replace(config: PersistentLoadControlConfig) -> None`.

- [ ] **Step 1: Write failing model-validation tests**

```python
import math
import pytest

from emonio_viewer.load_control.model import LoadControlTiming, PersistentLoadControlConfig, ThreePhasePower


def test_three_phase_power_preserves_mapping():
    value = ThreePhasePower(a=1.0, b=2.0, c=3.0)
    assert (value.a, value.b, value.c) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_config_rejects_invalid_reserve(bad):
    with pytest.raises(ValueError):
        PersistentLoadControlConfig(p_reserve=bad)


def test_timing_requires_explicit_positive_values():
    timing = LoadControlTiming(control_sample_max_age_s=1.25, ack_timeout_s=0.75)
    assert timing.control_sample_max_age_s == 1.25
    assert timing.ack_timeout_s == 0.75
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/unit/test_load_control_model.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement frozen models and validation**

```python
@dataclass(frozen=True, slots=True)
class ThreePhasePower:
    a: float
    b: float
    c: float


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

`LoadControlTiming` is a separate frozen type. It rejects non-finite and non-positive values and is never serialized by the persistent store.

- [ ] **Step 4: Write store tests**

```python
def test_store_round_trips_without_timing(tmp_path):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    config = PersistentLoadControlConfig(
        bound_emonio_device_id="emonio-example",
        bound_actuator_node_id="ARI-LOAD-MOCK-001",
        p_reserve=30.0,
        operator_limit_a=600.0,
        operator_limit_b=600.0,
        operator_limit_c=600.0,
    )
    store.replace(config)
    assert store.load() == config
    text = path.read_text(encoding="utf-8")
    assert "ack_timeout_s" not in text
    assert "control_sample_max_age_s" not in text
```

Also test invalid JSON, wrong schema version, wrong field set, temporary-file cleanup, and old-content preservation if `os.replace` fails.

- [ ] **Step 5: Implement strict schema and atomic replacement**

Use schema version `1`, `json.dump(..., indent=2, sort_keys=True)`, `flush`, `os.fsync`, and `os.replace`. Match the existing atomic persistence pattern without modifying `RememberedDeviceRegistry`.

- [ ] **Step 6: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py -q
git add src/emonio_viewer/load_control tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py
git commit -m "feat: add load control models and configuration store"
```

---

### Task 2: Deterministic Unity Controller

**Files:**
- Create: `src/emonio_viewer/load_control/controller.py`
- Create: `tests/unit/test_load_control_controller.py`

**Interfaces:**
- Produce `PhaseControlResult`, `ThreePhaseControlResult`.
- Produce `calculate_phase_request(*, measured_p: float, p_reserve: float, acknowledged_p: float, p_limit: float) -> PhaseControlResult`.
- Produce `calculate_three_phase_request(...) -> ThreePhaseControlResult`.

- [ ] **Step 1: Write arithmetic tests**

```python
def test_export_from_zero_load_requests_450_w():
    result = calculate_phase_request(measured_p=-420.0, p_reserve=30.0, acknowledged_p=0.0, p_limit=1000.0)
    assert result.error == 450.0
    assert result.raw_request == 450.0
    assert result.limited_request == 450.0


def test_next_request_uses_acknowledged_state():
    result = calculate_phase_request(measured_p=25.0, p_reserve=30.0, acknowledged_p=450.0, p_limit=1000.0)
    assert result.raw_request == 455.0


def test_minimum_clamp_is_zero():
    result = calculate_phase_request(measured_p=250.0, p_reserve=30.0, acknowledged_p=100.0, p_limit=1000.0)
    assert result.limited_request == 0.0
    assert result.limited_min is True


def test_maximum_saturation_is_visible():
    result = calculate_phase_request(measured_p=-900.0, p_reserve=30.0, acknowledged_p=0.0, p_limit=600.0)
    assert result.raw_request == 930.0
    assert result.limited_request == 600.0
    assert result.limited_max is True
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py -q
```

- [ ] **Step 3: Implement only approved math**

```python
raw = acknowledged_p + p_reserve - measured_p
limited = min(max(raw, 0.0), p_limit)
```

Reject non-finite inputs, `p_reserve <= 0`, `acknowledged_p < 0`, and `p_limit <= 0`.

- [ ] **Step 4: Add independent A/B/C mapping test**

Use different measured values and different limits on all phases. Assert no phase value crosses into another phase result.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py -q
git add src/emonio_viewer/load_control/controller.py tests/unit/test_load_control_controller.py
git commit -m "feat: add deterministic load control calculation"
```

---

### Task 3: Three-Domain Safety State

**Files:**
- Create: `src/emonio_viewer/load_control/state_machine.py`
- Create: `tests/unit/test_load_control_state_machine.py`

**Interfaces:**
- Produce `ControlStateMachine` with `enable()`, `disable()`, `trip(reason)`, `mark_safe_unconfirmed()`, `mark_safe_confirmed()`.
- Network/session state remains outside this state machine.

- [ ] **Step 1: Write transition tests**

```python
def test_startup_is_disabled():
    assert ControlStateMachine().mode is ControlMode.DISABLED


def test_trip_is_latched():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.disable()
    assert machine.mode is ControlMode.TRIPPED
    assert machine.trip_reason is TripReason.ACTUATOR_CONNECTION_LOST


def test_explicit_enable_can_leave_trip_after_supervisor_gate():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.enable()
    assert machine.mode is ControlMode.ENABLED
    assert machine.trip_reason is None
```

- [ ] **Step 2: Run RED and implement exact transitions**

`disable()` is idempotent in `DISABLED`. In `TRIPPED`, it can reassert safe state but cannot clear trip or change control mode.

- [ ] **Step 3: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_state_machine.py -q
git add src/emonio_viewer/load_control/state_machine.py tests/unit/test_load_control_state_machine.py
git commit -m "feat: add load control safety state machine"
```

---

### Task 4: Strict Protocol V1 Data Model

**Files:**
- Create: `src/emonio_viewer/load_control/protocol.py`
- Create: `tests/unit/test_load_control_protocol.py`

**Interfaces:**
- Constant: `LOAD_CONTROL_PROTOCOL_VERSION = 1`.
- Produce frozen `HelloFrame`, `CommandFrame`, `AckFrame`, `StatusFrame`.
- Produce `encode_frame(frame) -> str` and `decode_frame(text: str) -> HelloFrame | CommandFrame | AckFrame | StatusFrame`.
- Serializer uses `allow_nan=False`, `sort_keys=True`, `separators=(",", ":")`.

- [ ] **Step 1: Write round-trip and rejection tests**

```python
command = CommandFrame(
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
assert decode_frame(encode_frame(command)) == command
```

Add rejection tests for unknown protocol version, wrong field set, missing field, non-finite numeric value, negative applied P in `ACK`, and non-zero V1 Q compensation request.

- [ ] **Step 2: Run RED and implement exact schemas**

Every frame has `message_type` and `protocol_version`. Do not supply silent defaults for missing safety fields.

- [ ] **Step 3: Add safe-command test**

A safe command has `control_enabled=False`, exact `P=0/0/0 W`, and exact `Q_comp=0/0/0 var`.

- [ ] **Step 4: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py -q
git add src/emonio_viewer/load_control/protocol.py tests/unit/test_load_control_protocol.py
git commit -m "feat: add load control protocol model"
```

---

### Task 5: Append-Only JSONL Evidence

**Files:**
- Create: `src/emonio_viewer/load_control/evidence.py`
- Create: `tests/unit/test_load_control_evidence.py`

**Interfaces:**
- Produce `EvidenceWriteError`, `EvidenceEvent`, `JsonlEvidenceWriter`.
- `append(event) -> None`, `healthy -> bool`, `recent(limit: int = 100) -> tuple[dict, ...]`.

- [ ] **Step 1: Write deterministic line test**

```python
def test_writer_appends_sorted_json_line(tmp_path):
    writer = JsonlEvidenceWriter(tmp_path / "control.jsonl")
    writer.append(EvidenceEvent(
        schema_version=1,
        viewer_session_id="VIEWER-1",
        occurred_utc="2026-09-01T10:00:00+00:00",
        event="CONTROL_COMMAND_CALCULATED",
        payload={"b": 2, "a": 1},
    ))
    line = (tmp_path / "control.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert line == '{"event":"CONTROL_COMMAND_CALCULATED","occurred_utc":"2026-09-01T10:00:00+00:00","payload":{"a":1,"b":2},"schema_version":1,"viewer_session_id":"VIEWER-1"}'
```

- [ ] **Step 2: Write failure-health test**

Inject an `OSError` from the low-level write or `os.fsync`. Assert `EvidenceWriteError` and `healthy is False`.

- [ ] **Step 3: Implement append-only writer**

Use append mode, one event per line, `flush`, and `os.fsync`. Keep a bounded in-memory deque for recent UI evidence. Never rewrite an earlier event.

- [ ] **Step 4: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_evidence.py -q
git add src/emonio_viewer/load_control/evidence.py tests/unit/test_load_control_evidence.py
git commit -m "feat: add load control evidence writer"
```

---

### Task 6: Mock Discovery and Mock Actuator Session

**Files:**
- Create: `src/emonio_viewer/load_control/discovery.py`
- Create: `src/emonio_viewer/load_control/session.py`
- Create: `tests/unit/test_load_control_mock.py`
- Create: `tests/unit/test_load_control_stage1_contract.py`

**Interfaces:**
- `ActuatorDiscovery` Protocol: `async discover() -> tuple[ActuatorDescriptor, ...]`.
- `ActuatorSession` Protocol: `async connect(descriptor) -> HelloFrame`, `async send_command(command) -> None`, `async receive() -> AckFrame | StatusFrame`, `async close() -> None`.
- `MockActuatorDiscovery` and `MockActuatorSession` are the only stage-1 implementations.

**Exact default mock fixture used by the Viewer:**

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

These are deterministic mock fixture values only. They are not hardware ratings or controller constants.

- [ ] **Step 1: Write discovery tests**

Prove multiple mock nodes can exist, mock location can change without node identity change, disappearance of the bound node does not select another node, and discovery never grants control authority.

- [ ] **Step 2: Write session scenario tests**

Cover exact ACK, missing ACK, wrong sequence, wrong node ID, boot change, capability change, limit change, connection loss, and explicit applied-value offset. No random behavior is allowed.

- [ ] **Step 3: Implement Protocols and mocks**

Do not import `socket`, `zeroconf`, or `aiohttp.ClientSession` in the load-control package.

- [ ] **Step 4: Add stage-1 source contract**

```python
from pathlib import Path


def test_stage1_has_no_real_actuator_transport_implementation():
    root = Path("src/emonio_viewer/load_control")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "WebSocketActuatorSession" not in source
    assert "MdnsActuatorDiscovery" not in source
    assert "zeroconf" not in source
    assert "ClientSession" not in source
```

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_mock.py tests/unit/test_load_control_stage1_contract.py -q
git add src/emonio_viewer/load_control/discovery.py src/emonio_viewer/load_control/session.py tests/unit/test_load_control_mock.py tests/unit/test_load_control_stage1_contract.py
git commit -m "feat: add deterministic mock actuator boundary"
```

---

### Task 7: Pure Supervisor Decisions and Safety Logic

**Files:**
- Create: `src/emonio_viewer/load_control/supervisor.py`
- Create: `tests/fixtures/load_control_samples.py`
- Create: `tests/unit/test_load_control_supervisor.py`

**Interfaces:**
- Consume canonical `MeasurementSample` and `DiagnosticEvent` objects without mutation.
- Produce immutable `SupervisorDecision` with zero or more `EvidenceEvent` values and at most one `CommandFrame`.
- Methods:
  - `request_enable(now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`
  - `request_disable(command_utc: datetime) -> SupervisorDecision`
  - `on_measurement(sample: MeasurementSample, now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`
  - `on_diagnostic(event: DiagnosticEvent, command_utc: datetime) -> SupervisorDecision`
  - `on_ack(ack: AckFrame, command_utc: datetime) -> SupervisorDecision`
  - `on_session_ready(hello: HelloFrame, command_utc: datetime) -> SupervisorDecision`
  - `on_session_lost(command_utc: datetime) -> SupervisorDecision`
  - `on_time(now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`
  - `on_evidence_failure(command_utc: datetime) -> SupervisorDecision`

- [ ] **Step 1: Add immutable test sample helper**

Use `dataclasses.replace` on `real_sample` to change P/Q, quality, cycle ID, and monotonic finish time. Do not change production measurement classes.

- [ ] **Step 2: Write enable-gate tests**

Prove rejection for: missing Emonio binding, missing actuator binding, missing reserve, incomplete operator limits, missing mock timing qualification, missing current sample, non-VALID sample, stale sample, non-READY session, identity mismatch, capability missing, invalid effective limit, safe state not confirmed, and evidence health false. Then prove one complete valid gate enters `ENABLED`.

- [ ] **Step 3: Write phase/sign/controller integration test**

Use `P_A=-420`, `P_B=25`, `P_C=100`, acknowledged loads `0`, `450`, `50`, reserve `30`, and separate limits. Assert exact A/B/C results and no total-power redistribution.

- [ ] **Step 4: Write sequence and outstanding-command tests**

Prove sequence starts at `1` for an injected Viewer session, increments for every command including safe commands, allows only one normal outstanding command, observes intermediate samples without delayed command replay, and keeps measurement cycle ID separate from command sequence.

- [ ] **Step 5: Write acknowledgement authority tests**

Validate Viewer session ID, node ID, boot ID, sequence, finite non-negative applied P, and actuator limit. Accepted applied values become the next authoritative acknowledged state. Obsolete ACK after safe preemption is recorded but cannot restore authority. Incompatible active ACK trips.

- [ ] **Step 6: Write trip and safe-preemption tests**

Cover `DEGRADED`, `STALE`, `INVALID`, acquisition diagnostic event, cycle gap, session loss, boot change, capability change, actuator-limit change, invalid acknowledgement, freshness deadline, acknowledgement deadline, and evidence failure. Assert a newer safe command is created when session transmission is available.

- [ ] **Step 7: Write operator-disable tests**

Cover `ENABLED`, `DISABLED`, and `TRIPPED`. Disable cannot clear a latched trip.

- [ ] **Step 8: Run RED, implement, verify, commit**

```bash
python3 -m pytest tests/unit/test_load_control_supervisor.py -q
git add src/emonio_viewer/load_control/supervisor.py tests/fixtures/load_control_samples.py tests/unit/test_load_control_supervisor.py
git commit -m "feat: add load control supervisor decisions"
```

The supervisor performs no file I/O and no network I/O.

---

### Task 8: Async LoadControlService and RuntimeEventBus Isolation

**Files:**
- Create: `src/emonio_viewer/load_control/service.py`
- Create: `tests/unit/test_load_control_service.py`

**Interfaces:**
- `LoadControlService` owns one RuntimeEventBus subscription, one supervisor, one discovery adapter, one session adapter, one evidence writer, and one persistent config store.
- Async lifecycle: `start()`, `stop()`.
- Operator methods: `set_binding(...)`, `set_safety_config(...)`, `set_mock_timing(...)`, `enable()`, `disable()`.
- Status methods: `status()`, `discovered_actuators()`, `recent_evidence(limit=100)`.

- [ ] **Step 1: Write startup isolation test**

Use a real `RuntimeEventBus` and mock components. Assert service starts `DISABLED`, subscribes independently, and `bus.publish(sample)` does not wait for service work.

- [ ] **Step 2: Write binding and session-qualification test**

Persist a binding to `ARI-LOAD-MOCK-001`. Start the service. Assert discovery locates that exact node, HELLO qualifies it, session becomes `READY`, safe demand is issued, and only a valid successful exact-zero ACK establishes `SAFE_CONFIRMED`.

- [ ] **Step 3: Write no-automatic-transfer test**

Remove the bound mock node while another compatible node remains. Assert the service reports the bound actuator unavailable and never binds or connects to the other node.

- [ ] **Step 4: Write atomic service-configuration test**

Force `LoadControlConfigStore.replace()` to fail. Assert service in-memory configuration remains the previous valid configuration. Persist first, then replace the service's in-memory configuration only after persistence succeeds.

- [ ] **Step 5: Write evidence-before-nonzero-send test**

Use a failing evidence writer. Publish an eligible control sample. Assert mock session receives no non-zero command. Assert service trips and still attempts a safe command.

- [ ] **Step 6: Write event-source isolation tests**

Publish source and non-source `MeasurementSample` plus acquisition `DiagnosticEvent` objects. Assert only the bound Emonio affects control state. Assert exact cycle continuity on the bound source.

- [ ] **Step 7: Write explicit-deadline tests**

Inject `LoadControlTiming` in each test. No constructor numeric default is allowed. Test freshness and acknowledgement expiry using injected monotonic clocks.

- [ ] **Step 8: Implement service ordering**

For a normal non-zero decision:

1. write required calculation/send-attempt evidence;
2. if evidence write fails, feed `on_evidence_failure` to supervisor and block non-zero send;
3. if evidence succeeds, send through `MockActuatorSession`;
4. record send result when evidence remains available.

For a required safe command, attempt the safe send even if evidence is unhealthy.

- [ ] **Step 9: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_service.py -q
git add src/emonio_viewer/load_control/service.py tests/unit/test_load_control_service.py
git commit -m "feat: add isolated load control service"
```

---

### Task 9: Thin API, Viewer Composition, and Safe Shutdown

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
- Endpoints:
  - `GET /api/v1/load-control/status`
  - `GET /api/v1/load-control/discovered-actuators`
  - `GET /api/v1/load-control/evidence/recent`
  - `POST /api/v1/load-control/binding`
  - `POST /api/v1/load-control/config`
  - `POST /api/v1/load-control/mock-timing`
  - `POST /api/v1/load-control/enable`
  - `POST /api/v1/load-control/disable`
- No `/api/v1/load-control/command` endpoint exists.

- [ ] **Step 1: Write status API test**

Assert status exposes control mode, session state, safe state, trip reason, Viewer session ID, bindings, boot ID, protocol version, capabilities, reserve, operator/actuator/effective limits, last measurement identity/quality/age, last acknowledged P, outstanding sequence, last acknowledged sequence, last command, last ACK, last trip, evidence health, timing qualification, and `transport_mode="MOCK"`.

- [ ] **Step 2: Write operator-command API tests**

Test invalid body -> `400`, configure/bind while enabled -> `409`, enable-gate rejection -> `409` with exact service error code, unavailable service -> `503`.

- [ ] **Step 3: Write no-direct-command route test**

Enumerate routes and assert `/api/v1/load-control/command` is absent.

- [ ] **Step 4: Wire the Viewer composition root**

In `main.py`, create exactly one new volatile Viewer session ID per process. Create:

```text
LoadControlConfigStore(config_path.parent / "load-control.json")
MockActuatorDiscovery(default mock descriptor)
MockActuatorSession
JsonlEvidenceWriter(PROJECT_ROOT / "load-control-evidence" / f"{viewer_session_id}.jsonl")
LoadControlService
```

Start `LoadControlService` before acquisition workers so its event-bus subscriber exists before the first canonical acquisition event. Do not supply timing values at startup.

- [ ] **Step 5: Write safe shutdown ordering test**

Expected high-level order:

```text
STOP_LOAD_CONTROL_COMMANDS
STOP_LOAD_CONTROL
STOP_SCOPE
STOP_RECORDING_COMMANDS
STOP_RECORDERS
STOP_WORKERS
STOP_SERVER
```

For the mock stage, `LoadControlService.stop()` revokes non-zero authority and attempts a safe command. If the mock is configured for immediate ACK, record `SAFE_CONFIRMED`. If no ACK is available, record `SAFE_UNCONFIRMED` and close the mock session without waiting indefinitely. No real-network shutdown timeout is introduced in this stage.

- [ ] **Step 6: Implement thin API and composition**

`load_control_api.py` contains body/JSON adaptation and service error mapping only. It does not calculate power or construct actuator commands.

- [ ] **Step 7: Verify and commit**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py -q
git add src/emonio_viewer/main.py src/emonio_viewer/server/keys.py src/emonio_viewer/server/app.py src/emonio_viewer/server/app_v0416.py src/emonio_viewer/server/load_control_api.py tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py
git commit -m "feat: expose mock load control service"
```

---

### Task 10: Compact Frontend Without Header Changes

**Files:**
- Create: `frontend/css/load-control.css`
- Create: `frontend/js/load-control-api.js`
- Create: `frontend/js/load-control-ui.js`
- Modify: `frontend/index.html`
- Create: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Add one compact `details` panel directly after the current Emonio target strip.
- Do not add or change a control in the current status header.
- Summary always shows `CONTROL`, control mode, session state, and safe state.
- Expanded panel shows bindings, reserve, operator limits, volatile mock timing qualification, A/B/C measured P, A/B/C acknowledged load, A/B/C last requested load, effective limits, sequences, evidence health, and last trip.

- [ ] **Step 1: Write static contract test**

Assert `index.html` contains:

```text
load-control-panel
load-control-mode
load-control-session-state
load-control-safe-state
load-control-source
load-control-actuator
load-control-reserve
load-control-limit-a
load-control-limit-b
load-control-limit-c
load-control-sample-max-age
load-control-ack-timeout
load-control-enable
load-control-disable
load-control-last-trip
```

Assert no direct actuator-request input such as `p_request_a`, `p_request_b`, or `p_request_c` exists.

- [ ] **Step 2: Write JS contract tests**

Assert code calls approved load-control endpoints only. Configuration controls are disabled when backend status is `ENABLED`.

- [ ] **Step 3: Implement structured CSS**

Put all new styling in `frontend/css/load-control.css`. Use existing variables and density. Do not modify existing header CSS and do not add inline styles.

- [ ] **Step 4: Implement UI behavior**

`load-control-api.js` owns HTTP functions. `load-control-ui.js` owns DOM state and status refresh. JavaScript displays backend calculations; it does not recalculate control power.

The mock timing UI text must state that timing values are volatile mock-stage qualification inputs and are not persisted for hardware use.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
python3 -m pytest tests/browser/test_header_status_layout.py -q
```

Compare the header test result with the preflight baseline. Do not change the header test to force a different result.

```bash
git add frontend/index.html frontend/css/load-control.css frontend/js/load-control-api.js frontend/js/load-control-ui.js tests/browser/test_load_control_contract.py
git commit -m "feat: add load control status interface"
```

---

### Task 11: Full Mock-Stage Acceptance

**Files:**
- Change only narrow tests/integration code if fresh evidence finds a load-control acceptance defect.
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

- [ ] **Step 2: Run load-control integration and browser tests**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py -q
python3 -m pytest tests/browser/test_load_control_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Re-run existing suites**

```bash
python3 -m pytest tests/unit -q
python3 -m pytest tests/integration -q
python3 -m pytest tests/browser -q
```

Any new failure blocks acceptance. Compare the browser result with the preflight result and keep the unrelated pre-existing header-layout result separate.

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

- [ ] **Step 6: Prove stage 1 has no real actuator network implementation**

```bash
python3 -m pytest tests/unit/test_load_control_stage1_contract.py -q
if grep -R -E "WebSocketActuatorSession|MdnsActuatorDiscovery|zeroconf" src/emonio_viewer/load_control; then
  echo "real actuator network implementation found in mock-only stage" >&2
  exit 1
fi
```

Expected: stage contract PASS and grep finds no forbidden implementation.

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