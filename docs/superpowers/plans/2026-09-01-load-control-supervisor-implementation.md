# ARI Emonio Viewer External Load Control Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Viewer-side external load-control supervisor with deterministic mock discovery and mock actuator transport only, while preserving the trusted Emonio measurement architecture.

**Architecture:** Add an isolated `emonio_viewer.load_control` subsystem that consumes immutable canonical `MeasurementSample` and `DiagnosticEvent` objects from the existing non-blocking `RuntimeEventBus`. Keep controller mathematics, safety state, protocol data, persistence, evidence, mock discovery, and mock actuator session in focused modules. The active Viewer composition root creates the service, the server exposes thin operator/status endpoints, and the frontend displays control evidence without any direct per-phase actuator command API.

**Tech Stack:** Python 3.10+, dataclasses, asyncio, standard-library JSON/path/thread-safe primitives, existing `aiohttp==3.14.3` server stack, pytest 8.4.1, plain ES modules, structured CSS.

**Spec:** `docs/superpowers/specs/2026-09-01-load-control-supervisor-design.md`

## Global Constraints

- Work on branch `testing` only.
- The protected production-code baseline is commit `e3e33ec959d6304ca8471ab1c0f217884b64ed18`.
- Do not merge or modify `main`.
- Do not modify Modbus acquisition, register maps, decoder logic, canonical measurement signs, P/Q quadrant semantics, validation, fixed-deadline acquisition, SCOPE semantics, or existing CSV precision.
- `src/emonio_viewer/modbus`, `src/emonio_viewer/measurement`, `src/emonio_viewer/acquisition`, `src/emonio_viewer/runtime/events.py`, `src/emonio_viewer/runtime/store.py`, and `src/emonio_viewer/scope` must remain byte-identical to the protected production-code baseline.
- The first implementation must contain no mDNS network implementation, no real WebSocket actuator client, no ESP32 firmware, no PWM logic, and no physical power-stage control path.
- The first implementation must use deterministic `MockActuatorDiscovery` and `MockActuatorSession` only.
- External control starts `DISABLED` on every Viewer process start.
- Persistent binding and safety configuration never restore control authority.
- Only canonical `MeasurementSample.quality == VALID` is eligible for active control.
- P and Q remain scientifically separate. Q is telemetry only in this stage. Every `Q_comp_request_*` is exactly `0 var`.
- V1 active-load requests are non-negative only.
- One normal command can be unacknowledged at a time. Safe commands can preempt it.
- The last valid actuator acknowledgement is the authoritative applied-load state.
- A sent command is never treated as evidence that the actuator applied it.
- The control law baseline is `P_request_raw = P_acknowledged + P_reserve - P_measured` independently for A, B, and C.
- No controller gain, PID term, averaging, smoothing, interpolation, hysteresis, synthetic sample, or invented timing constant is permitted.
- Control freshness and acknowledgement timeouts are separate, explicit, volatile qualification inputs in the mock stage. The Viewer shall not invent default values.
- All safety-critical configuration changes are allowed only while `DISABLED`.
- The browser shall never expose a direct endpoint or control that sets `P_A`, `P_B`, or `P_C` actuator demand.
- Preserve the known unrelated `tests/browser/test_header_status_layout.py` issue as a separate baseline observation. Do not modify that test or the existing header layout as part of this work.
- Use ASD-STE / Simplified Technical English in operator-visible text and documentation.

---

## Execution Preflight

Before Task 1, create an isolated worktree from the exact `testing` HEAD by using the Superpowers worktree workflow. Then record the current baseline without changing source files.

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

Also run the protected-path comparison before implementation:

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

Do not add a `WebSocketActuatorSession` class or `MdnsActuatorDiscovery` class in this stage. Their interfaces are defined, but their network implementations are outside this implementation plan.

---

### Task 1: Immutable Control Models and Atomic Persistent Configuration

**Files:**
- Create: `src/emonio_viewer/load_control/__init__.py`
- Create: `src/emonio_viewer/load_control/model.py`
- Create: `src/emonio_viewer/load_control/config_store.py`
- Create: `tests/unit/test_load_control_model.py`
- Create: `tests/unit/test_load_control_config_store.py`

**Interfaces:**
- Produces `ThreePhasePower`, `ControlMode`, `SessionState`, `SafeState`, `LimitState`, `ActuatorCapability`, `TripReason`, `ActuatorDescriptor`, `ActuatorSessionIdentity`, `LoadControlTiming`, `PersistentLoadControlConfig`, and `LoadControlStatus`.
- Produces `LoadControlConfigStore.load() -> PersistentLoadControlConfig` and `LoadControlConfigStore.replace(config: PersistentLoadControlConfig) -> None`.
- Later tasks import these types. No type in this task imports acquisition, Modbus, SCOPE, or recording code.

- [ ] **Step 1: Write failing model-validation tests**

Create tests that prove finite-positive safety values, optional persistent binding, and volatile timing separation.

```python
import math
import pytest

from emonio_viewer.load_control.model import (
    LoadControlTiming,
    PersistentLoadControlConfig,
    ThreePhasePower,
)


def test_three_phase_power_preserves_phase_mapping():
    value = ThreePhasePower(a=1.0, b=2.0, c=3.0)
    assert (value.a, value.b, value.c) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_persistent_config_rejects_invalid_reserve(bad):
    with pytest.raises(ValueError):
        PersistentLoadControlConfig(p_reserve=bad)


def test_timing_requires_explicit_positive_values():
    timing = LoadControlTiming(control_sample_max_age_s=1.25, ack_timeout_s=0.75)
    assert timing.control_sample_max_age_s == 1.25
    assert timing.ack_timeout_s == 0.75
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_model.py -q
```

Expected: import failure because `emonio_viewer.load_control.model` does not exist.

- [ ] **Step 3: Implement the immutable model types**

Use frozen dataclasses and enums. Keep `PersistentLoadControlConfig` partial so binding and safety values can be entered in separate disabled-only operator actions.

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

Define `LoadControlTiming` as a separate volatile type. It must reject non-finite or non-positive values and it must not appear in persisted JSON.

- [ ] **Step 4: Write atomic store tests**

Test empty load, exact schema, invalid JSON rejection, round-trip, temporary-file cleanup, and preservation of old content if `os.replace` fails.

```python
def test_config_store_round_trips_without_timing(tmp_path):
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
    assert "ack_timeout_s" not in path.read_text(encoding="utf-8")
    assert "control_sample_max_age_s" not in path.read_text(encoding="utf-8")
```

- [ ] **Step 5: Implement strict schema and atomic replacement**

Use schema version `1`, `json.dump(..., indent=2, sort_keys=True)`, `flush`, `os.fsync`, and `os.replace`, matching the existing scientific-software persistence style without modifying `RememberedDeviceRegistry`.

- [ ] **Step 6: Verify and commit**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py -q
```

Expected: PASS.

Commit:

```bash
git add src/emonio_viewer/load_control tests/unit/test_load_control_model.py tests/unit/test_load_control_config_store.py
git commit -m "feat: add load control models and configuration store"
```

---

### Task 2: Deterministic Three-Phase Unity Controller

**Files:**
- Create: `src/emonio_viewer/load_control/controller.py`
- Create: `tests/unit/test_load_control_controller.py`

**Interfaces:**
- Consumes `ThreePhasePower`.
- Produces `PhaseControlResult`, `ThreePhaseControlResult`.
- Produces `calculate_phase_request(*, measured_p: float, p_reserve: float, acknowledged_p: float, p_limit: float) -> PhaseControlResult`.
- Produces `calculate_three_phase_request(...) -> ThreePhaseControlResult`.

- [ ] **Step 1: Write the closed-loop arithmetic tests**

```python
def test_export_from_zero_load_requests_450_w():
    result = calculate_phase_request(
        measured_p=-420.0,
        p_reserve=30.0,
        acknowledged_p=0.0,
        p_limit=1000.0,
    )
    assert result.error == 450.0
    assert result.raw_request == 450.0
    assert result.limited_request == 450.0


def test_next_request_starts_from_acknowledged_applied_load():
    result = calculate_phase_request(
        measured_p=25.0,
        p_reserve=30.0,
        acknowledged_p=450.0,
        p_limit=1000.0,
    )
    assert result.raw_request == 455.0


def test_negative_request_clamps_to_zero_without_trip_semantics():
    result = calculate_phase_request(
        measured_p=250.0,
        p_reserve=30.0,
        acknowledged_p=100.0,
        p_limit=1000.0,
    )
    assert result.limited_request == 0.0
    assert result.limited_min is True
    assert result.limited_max is False


def test_maximum_saturation_does_not_keep_hidden_raw_state():
    result = calculate_phase_request(
        measured_p=-900.0,
        p_reserve=30.0,
        acknowledged_p=0.0,
        p_limit=600.0,
    )
    assert result.raw_request == 930.0
    assert result.limited_request == 600.0
    assert result.limited_max is True
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement only the approved unity calculation**

```python
raw = acknowledged_p + p_reserve - measured_p
limited = min(max(raw, 0.0), p_limit)
```

Reject any non-finite input and any `p_reserve <= 0`, `acknowledged_p < 0`, or `p_limit <= 0`. Do not add gain, deadband, rate limiting, smoothing, or averaging.

- [ ] **Step 4: Add independent A/B/C mapping test**

Use three different measured values and three different limits. Assert that no phase value appears in another phase result.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_controller.py -q
git add src/emonio_viewer/load_control/controller.py tests/unit/test_load_control_controller.py
git commit -m "feat: add deterministic load control calculation"
```

---

### Task 3: Small Safety State Machine

**Files:**
- Create: `src/emonio_viewer/load_control/state_machine.py`
- Create: `tests/unit/test_load_control_state_machine.py`

**Interfaces:**
- Consumes `ControlMode`, `SafeState`, and `TripReason`.
- Produces `ControlStateMachine` with `enable()`, `disable()`, `trip(reason)`, `mark_safe_unconfirmed()`, and `mark_safe_confirmed()`.
- State machine does not perform I/O and does not decide enable-gate readiness.

- [ ] **Step 1: Write transition tests**

```python
def test_startup_is_disabled():
    machine = ControlStateMachine()
    assert machine.mode is ControlMode.DISABLED


def test_trip_is_latched_until_explicit_enable():
    machine = ControlStateMachine()
    machine.enable()
    machine.trip(TripReason.ACTUATOR_CONNECTION_LOST)
    machine.disable()
    assert machine.mode is ControlMode.TRIPPED
    assert machine.trip_reason is TripReason.ACTUATOR_CONNECTION_LOST
    machine.enable()
    assert machine.mode is ControlMode.ENABLED
    assert machine.trip_reason is None


def test_operator_disable_from_enabled_is_not_trip():
    machine = ControlStateMachine()
    machine.enable()
    machine.disable()
    assert machine.mode is ControlMode.DISABLED
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/unit/test_load_control_state_machine.py -q
```

- [ ] **Step 3: Implement exact legal transitions**

`disable()` is idempotent in `DISABLED`. In `TRIPPED`, it reasserts safe state but does not change mode or clear `trip_reason`. `enable()` is callable by the supervisor only after its enable gate passes.

- [ ] **Step 4: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_state_machine.py -q
git add src/emonio_viewer/load_control/state_machine.py tests/unit/test_load_control_state_machine.py
git commit -m "feat: add load control safety state machine"
```

---

### Task 4: Versioned Strict Protocol Data Model

**Files:**
- Create: `src/emonio_viewer/load_control/protocol.py`
- Create: `tests/unit/test_load_control_protocol.py`

**Interfaces:**
- Protocol version constant: `LOAD_CONTROL_PROTOCOL_VERSION = 1`.
- Produces immutable `HelloFrame`, `CommandFrame`, `AckFrame`, `StatusFrame`.
- Produces `encode_frame(frame) -> str` and `decode_frame(text: str) -> HelloFrame | CommandFrame | AckFrame | StatusFrame`.
- The JSON serializer uses `allow_nan=False`, `sort_keys=True`, and compact separators.

- [ ] **Step 1: Write exact protocol-validation tests**

The `COMMAND` frame must include all three phases in one message and bind both measurement and actuator identity:

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
```

Assert round-trip equality. Add explicit rejection tests for:

- unknown protocol version;
- missing required field;
- extra required-schema field;
- wrong `node_id`, where identity validation is applied by the supervisor;
- non-finite numeric field;
- negative `applied_P_*` in `ACK`;
- `ACK` value above qualified actuator limit, where limit validation is applied by the supervisor;
- any non-zero `Q_comp_request_*` in V1.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py -q
```

- [ ] **Step 3: Implement strict frame schemas**

Every frame contains `message_type` and `protocol_version`. Use exact field sets for protocol version 1. Do not infer missing safety fields. Do not use JSON default values for missing data.

- [ ] **Step 4: Add safe-command contract test**

A safe command has `control_enabled=False` and exact `p_load_request = 0/0/0 W` plus exact `q_comp_request = 0/0/0 var`.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_protocol.py -q
git add src/emonio_viewer/load_control/protocol.py tests/unit/test_load_control_protocol.py
git commit -m "feat: add load control protocol model"
```

---

### Task 5: Append-Only Deterministic JSONL Evidence

**Files:**
- Create: `src/emonio_viewer/load_control/evidence.py`
- Create: `tests/unit/test_load_control_evidence.py`

**Interfaces:**
- Produces `EvidenceWriteError`.
- Produces `EvidenceEvent`.
- Produces `JsonlEvidenceWriter.append(event: EvidenceEvent) -> None`, `healthy -> bool`, and `recent(limit: int = 100) -> tuple[dict, ...]`.
- Writer is independent of measurement CSV recording.

- [ ] **Step 1: Write deterministic serialization tests**

```python
def test_jsonl_writer_appends_one_sorted_json_object_per_event(tmp_path):
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

- [ ] **Step 2: Write evidence failure test**

Monkeypatch the low-level write or `os.fsync` to raise `OSError`. Assert `EvidenceWriteError` and `writer.healthy is False`.

- [ ] **Step 3: Run RED and implement**

Use append mode, one complete line per event, `flush`, and `os.fsync`. Keep an in-memory bounded deque for recent UI evidence. Never rewrite an earlier event as a different fact.

- [ ] **Step 4: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_evidence.py -q
git add src/emonio_viewer/load_control/evidence.py tests/unit/test_load_control_evidence.py
git commit -m "feat: add load control evidence writer"
```

---

### Task 6: Deterministic Mock Discovery and Mock Actuator Session

**Files:**
- Create: `src/emonio_viewer/load_control/discovery.py`
- Create: `src/emonio_viewer/load_control/session.py`
- Create: `tests/unit/test_load_control_mock.py`
- Create: `tests/unit/test_load_control_stage1_contract.py`

**Interfaces:**
- `ActuatorDiscovery` is a `Protocol` with `async discover() -> tuple[ActuatorDescriptor, ...]`.
- `MockActuatorDiscovery` implements only in-memory discovery.
- `ActuatorSession` is a `Protocol` with `async connect(descriptor) -> HelloFrame`, `async send_command(command) -> None`, `async receive() -> AckFrame | StatusFrame`, and `async close() -> None`.
- `MockActuatorSession` implements only in-memory command/ack behavior.
- Default Viewer mock node identity is clearly marked `ARI-LOAD-MOCK-001`; its boot identity is mock-only and changes only when explicitly simulated.

- [ ] **Step 1: Write discovery tests**

Prove multiple mock nodes can exist, addresses can change without identity changes, and discovery never selects a node.

- [ ] **Step 2: Write session behavior tests**

Cover:

- exact ACK;
- delayed/no ACK;
- wrong sequence;
- wrong node ID;
- boot ID change;
- changed capability;
- changed actuator limit;
- connection loss;
- applied value offset.

Every behavior must be explicitly configured. There is no randomness.

- [ ] **Step 3: Run RED and implement the Protocols plus mocks**

Do not import `socket`, `zeroconf`, `aiohttp.ClientSession`, or any network client in the `load_control` package.

- [ ] **Step 4: Add the mock-only source contract**

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

### Task 7: Pure Supervisor Decisions, Cycle Integrity, and Acknowledgement Authority

**Files:**
- Create: `src/emonio_viewer/load_control/supervisor.py`
- Create: `tests/fixtures/load_control_samples.py`
- Create: `tests/unit/test_load_control_supervisor.py`

**Interfaces:**
- Consumes canonical `MeasurementSample` and `DiagnosticEvent` without modifying them.
- Consumes model, controller, state-machine, protocol, and session status types.
- Produces immutable `SupervisorDecision` objects that contain zero or more `EvidenceEvent` objects and at most one `CommandFrame`.
- Key methods:
  - `request_enable(now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`
  - `request_disable(command_utc: datetime) -> SupervisorDecision`
  - `on_measurement(sample: MeasurementSample, now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`
  - `on_diagnostic(event: DiagnosticEvent, command_utc: datetime) -> SupervisorDecision`
  - `on_ack(ack: AckFrame, command_utc: datetime) -> SupervisorDecision`
  - `on_session_ready(hello: HelloFrame, command_utc: datetime) -> SupervisorDecision`
  - `on_session_lost(command_utc: datetime) -> SupervisorDecision`
  - `on_time(now_monotonic_ns: int, command_utc: datetime) -> SupervisorDecision`
  - `on_evidence_failure(command_utc: datetime) -> SupervisorDecision`
- The supervisor owns command sequence allocation for the current injected `viewer_session_id`.

- [ ] **Step 1: Add a reusable immutable sample helper**

Use `dataclasses.replace` on the existing `real_sample` fixture to change only P/Q, quality, cycle ID, and monotonic finish time. Do not alter production measurement classes.

- [ ] **Step 2: Write enable-gate tests**

Prove enable rejection for each missing condition:

- no Emonio binding;
- no actuator binding;
- no reserve;
- incomplete operator limits;
- no timing qualification;
- no current sample;
- sample not `VALID`;
- stale sample;
- session not `READY`;
- wrong actuator identity;
- capability missing;
- invalid effective limit;
- safe state not confirmed;
- evidence health false.

Then prove one complete valid gate changes `DISABLED -> ENABLED`.

- [ ] **Step 3: Write phase/sign/controller integration tests**

Use `P_A=-420`, `P_B=25`, `P_C=100` with acknowledged loads `0`, `450`, `50`, reserve `30`, and separate limits. Assert exact A/B/C requests and no total-power redistribution.

- [ ] **Step 4: Write sequencing tests**

Prove:

- command sequence starts at 1 for an injected Viewer session;
- sequence increments for every `COMMAND`, including safe commands;
- one normal command can be outstanding;
- intermediate valid samples are safety-checked but do not generate delayed normal commands;
- the next newly completed valid sample after ACK generates the next normal command;
- measurement cycle ID is retained independently from command sequence.

- [ ] **Step 5: Write acknowledgement authority tests**

Prove exact identity tuple matching: Viewer session ID, node ID, boot ID, sequence. Prove accepted applied values become the next `P_acknowledged`. Prove obsolete ACK after safe preemption is recorded but cannot restore non-zero authority. Prove incompatible ACK while enabled causes `TRIPPED`.

- [ ] **Step 6: Write fault and safe-preemption tests**

Cover every approved trip source that can be represented without network timing:

- `DEGRADED`, `STALE`, `INVALID`;
- acquisition diagnostic event;
- unexplained cycle gap;
- actuator session loss;
- boot change;
- capability change;
- actuator limit change;
- malformed/incompatible acknowledgement;
- freshness deadline;
- acknowledgement deadline;
- evidence failure.

Assert every fault while enabled allocates a newer safe command when a session can transmit and sets `SAFE_UNCONFIRMED` until a valid exact-zero safe ACK is accepted.

- [ ] **Step 7: Write operator-disable tests**

Cover `ENABLED`, `DISABLED`, and `TRIPPED`. Prove disable never clears a latched trip.

- [ ] **Step 8: Run RED, implement minimal supervisor, and verify**

Run:

```bash
python3 -m pytest tests/unit/test_load_control_supervisor.py -q
```

Implement only the approved behavior. The supervisor must not write files or perform network operations.

- [ ] **Step 9: Commit**

```bash
git add src/emonio_viewer/load_control/supervisor.py tests/fixtures/load_control_samples.py tests/unit/test_load_control_supervisor.py
git commit -m "feat: add load control supervisor decisions"
```

---

### Task 8: Async LoadControlService and RuntimeEventBus Isolation

**Files:**
- Create: `src/emonio_viewer/load_control/service.py`
- Create: `tests/unit/test_load_control_service.py`

**Interfaces:**
- `LoadControlService` owns one RuntimeEventBus subscription, one supervisor, one discovery adapter, one session adapter, one evidence writer, and the persistent config store.
- Public async lifecycle: `start()`, `stop()`.
- Public operator methods: `set_binding(...)`, `set_safety_config(...)`, `set_mock_timing(...)`, `enable()`, `disable()`.
- Public status methods: `status()`, `discovered_actuators()`, `recent_evidence(limit=100)`.
- Configuration changes call the atomic store only while control mode is `DISABLED`.
- Mock timing is volatile and never written by `LoadControlConfigStore`.

- [ ] **Step 1: Write startup isolation test**

Create a real `RuntimeEventBus`, a mock discovery, a mock session, temporary config/evidence paths, and the service. Assert:

- service starts `DISABLED`;
- event-bus acquisition publication returns without waiting for service work;
- service subscribes independently;
- no protected runtime store change is required.

- [ ] **Step 2: Write mock binding/session qualification test**

Persist a binding to `ARI-LOAD-MOCK-001`. Start the service. Assert mock discovery locates the node, `HELLO` is qualified, session becomes `READY`, a safe command is issued, and only a valid exact-zero ACK changes safe state to `SAFE_CONFIRMED`.

- [ ] **Step 3: Write evidence-before-nonzero-send test**

Use a failing evidence writer. Enable from a previously qualified state, publish an eligible sample, and assert the mock session never receives the non-zero command. Assert the service trips and still attempts a safe command.

- [ ] **Step 4: Write event-stream tests**

Publish `MeasurementSample` and acquisition `DiagnosticEvent` objects through `RuntimeEventBus`. Assert source filtering by bound Emonio ID and exact cycle continuity. Publish samples for another Emonio and assert they do not affect controller state.

- [ ] **Step 5: Write deadline tests without invented constants**

Inject explicit `LoadControlTiming` values from the test. The service schedules freshness and acknowledgement deadline checks from those values. The production constructor has no numeric default for either value.

- [ ] **Step 6: Implement service execution ordering**

For a normal non-zero decision:

1. append required calculation/send-attempt evidence;
2. if evidence append fails, feed `on_evidence_failure` to supervisor and do not send non-zero demand;
3. if evidence succeeds, send the command through the mock session;
4. append sent/failure evidence after the send result.

For a required safe command, attempt the safe send even when evidence storage is unhealthy.

- [ ] **Step 7: Verify and commit**

```bash
python3 -m pytest tests/unit/test_load_control_service.py -q
git add src/emonio_viewer/load_control/service.py tests/unit/test_load_control_service.py
git commit -m "feat: add isolated load control service"
```

---

### Task 9: Thin HTTP API, Viewer Composition, and Safe Shutdown

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
- Add one `LOAD_CONTROL_SERVICE_KEY` to server keys.
- Add `register_load_control_routes(app)` to both app composition paths.
- Endpoints:
  - `GET /api/v1/load-control/status`
  - `GET /api/v1/load-control/discovered-actuators`
  - `GET /api/v1/load-control/evidence/recent`
  - `POST /api/v1/load-control/binding`
  - `POST /api/v1/load-control/config`
  - `POST /api/v1/load-control/mock-timing`
  - `POST /api/v1/load-control/enable`
  - `POST /api/v1/load-control/disable`
- No endpoint accepts direct actuator `P_A/P_B/P_C` request values.

- [ ] **Step 1: Write API contract tests**

Use an aiohttp test client with a real `LoadControlService` and mock components. Assert status includes:

```text
control_mode
session_state
safe_state
trip_reason
viewer_session_id
bound_emonio_device_id
bound_actuator_node_id
actuator_boot_id
protocol_version
capabilities
p_reserve
operator_limits
actuator_limits
effective_limits
last_measurement_cycle_id
last_measurement_utc
last_measurement_age_s
last_measurement_quality
last_acknowledged_p
outstanding_sequence
last_acknowledged_sequence
last_command
last_ack
last_trip
evidence_health
transport_mode
```

Assert `transport_mode == "MOCK"`.

- [ ] **Step 2: Write exact command error mapping tests**

Map service error codes to HTTP status without reinterpreting them in the handler. Test at least:

- invalid body -> 400;
- binding/config change while enabled -> 409;
- enable-gate rejection -> 409 with exact service error code;
- unavailable service -> 503.

- [ ] **Step 3: Write no-direct-command endpoint test**

Enumerate app routes and assert there is no `/api/v1/load-control/command` route.

- [ ] **Step 4: Write Viewer composition test**

In `main.py`, create:

- `LoadControlConfigStore(config_path.parent / "load-control.json")`;
- a new volatile Viewer session ID generated once per process;
- `MockActuatorDiscovery`;
- `MockActuatorSession` factory/session;
- `JsonlEvidenceWriter` under `PROJECT_ROOT / "load-control-evidence" / f"{viewer_session_id}.jsonl"`;
- `LoadControlService`.

Start the load-control service before acquisition workers so it cannot miss the first canonical runtime event. Do not give it a timing default.

- [ ] **Step 5: Write safe shutdown ordering test**

Extend launcher/shutdown tests so shutdown order is:

```text
STOP_LOAD_CONTROL_COMMANDS
STOP_LOAD_CONTROL
STOP_SCOPE
STOP_RECORDING_COMMANDS
STOP_RECORDERS
STOP_WORKERS
STOP_SERVER
```

`LoadControlService.stop()` must revoke non-zero authority, attempt a safe mock command if the session is qualified, record confirmed/unconfirmed result when evidence is healthy, unsubscribe from `RuntimeEventBus`, and finish within an injected bounded shutdown deadline in tests. Do not invent a production real-network deadline because there is no real transport in this stage.

- [ ] **Step 6: Implement thin API and composition**

`load_control_api.py` contains JSON/body adaptation and service error mapping only. It does not calculate power, mutate supervisor internals, or construct actuator commands.

- [ ] **Step 7: Verify and commit**

```bash
python3 -m pytest tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py -q
git add src/emonio_viewer/main.py src/emonio_viewer/server/keys.py src/emonio_viewer/server/app.py src/emonio_viewer/server/app_v0416.py src/emonio_viewer/server/load_control_api.py tests/integration/test_load_control_api.py tests/integration/test_load_control_runtime.py tests/unit/test_launcher.py
git commit -m "feat: expose mock load control service"
```

---

### Task 10: Compact Load Control Frontend Without Header Regression

**Files:**
- Create: `frontend/css/load-control.css`
- Create: `frontend/js/load-control-api.js`
- Create: `frontend/js/load-control-ui.js`
- Modify: `frontend/index.html`
- Create: `tests/browser/test_load_control_contract.py`

**Interfaces:**
- Frontend consumes only the load-control HTTP API.
- Add one compact `details` panel directly after the existing Emonio target strip. Do not add or change a button in the current status header.
- Summary remains visible and shows `CONTROL`, control mode, session state, and safe state.
- Expanded panel shows binding, safety configuration, volatile mock timing qualification, A/B/C measured P, A/B/C acknowledged load, A/B/C last requested load, limits, sequence evidence, and last trip.

- [ ] **Step 1: Write static browser contract tests**

Assert `index.html` contains IDs for:

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

Assert there are no inputs named or identified as direct actuator requests such as `p_request_a`, `p_request_b`, or `p_request_c`.

- [ ] **Step 2: Write JS contract tests**

Assert UI code calls only the approved endpoints. `ENABLE` and `DISABLE` remain separate actions. Configuration controls disable whenever backend status is `ENABLED`.

- [ ] **Step 3: Implement structured CSS**

Keep all new rules in `frontend/css/load-control.css`. Do not modify existing header CSS. Use the existing design tokens and compact density. Do not add inline styles.

- [ ] **Step 4: Implement UI behavior**

`load-control-api.js` owns fetch functions. `load-control-ui.js` owns DOM state and periodic status refresh. Display numeric values as evidence; do not recalculate controller power in JavaScript.

Operator-visible mock timing labels must say that the values are mock-stage qualification inputs and are not persisted for hardware use.

- [ ] **Step 5: Verify browser scope and commit**

```bash
python3 -m pytest tests/browser/test_load_control_contract.py -q
python3 -m pytest tests/browser/test_header_status_layout.py -q
```

Record the header test result and compare it with the preflight baseline. Do not change the header test to force a different result.

Commit:

```bash
git add frontend/index.html frontend/css/load-control.css frontend/js/load-control-api.js frontend/js/load-control-ui.js tests/browser/test_load_control_contract.py
git commit -m "feat: add load control status interface"
```

---

### Task 11: Full Mock-Stage Scientific and Safety Acceptance

**Files:**
- Modify only tests if an acceptance gap is found. Do not refactor protected production paths.
- Use existing `tools/ari-emonio-acceptance.sh` without weakening its gates.

**Interfaces:**
- This task produces evidence that the first stage is mock-only, deterministic, and isolated.

- [ ] **Step 1: Run the complete new load-control unit set**

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

- [ ] **Step 3: Re-run existing unit and integration suites**

```bash
python3 -m pytest tests/unit -q
python3 -m pytest tests/integration -q
```

Expected: no new failure.

- [ ] **Step 4: Run the frontend suite and preserve the known unrelated baseline separately**

```bash
python3 -m pytest tests/browser -q
```

Compare the exact result with the preflight result. Any new frontend failure is a regression and blocks acceptance. Do not fix or suppress the unrelated pre-existing header-layout issue inside this task.

- [ ] **Step 5: Run read-only, compilation, and scientific sign gates**

```bash
python3 -m pytest tests/unit/test_read_only_contract.py -q
python3 -m compileall -q src tests
python3 -m pytest tests/integration/test_end_to_end_sign.py -q
```

Expected: PASS.

- [ ] **Step 6: Prove protected scientific paths are unchanged**

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
grep -R "WebSocketActuatorSession\|MdnsActuatorDiscovery\|zeroconf" src/emonio_viewer/load_control && exit 1 || true
```

Expected: stage contract PASS and no matching real-network implementation.

- [ ] **Step 8: Inspect exact changed paths**

```bash
git status --short
git diff --stat e3e33ec959d6304ca8471ab1c0f217884b64ed18..HEAD
git diff --name-only e3e33ec959d6304ca8471ab1c0f217884b64ed18..HEAD
```

Verify that changes are limited to the new load-control subsystem, its API/composition wiring, its frontend, tests, and approved documentation.

- [ ] **Step 9: Commit final acceptance-only corrections if any**

If Task 11 required test-only or narrow integration corrections, commit those exact files with a focused message. If no files changed, do not create an empty commit.

---

## Required First-Stage Acceptance Evidence

The first implementation is not accepted until fresh test evidence demonstrates all of these points:

1. Startup control mode is always `DISABLED`.
2. Persistent binding does not restore enable state, sequence state, boot state, acknowledged demand, or safe confirmation.
3. One selected Emonio source is isolated from other Emonio devices.
4. Only `VALID` and fresh canonical samples can drive control.
5. A/B/C phase mapping is exact.
6. Negative measured P produces the correct additional active-load demand under the approved sign convention.
7. The controller starts from last acknowledged applied load, not last transmitted load.
8. V1 requests remain `>= 0 W` and are clamped by `min(actuator limit, operator limit)`.
9. Saturation is visible and does not trip by itself.
10. One normal command can be outstanding.
11. Intermediate measurements are safety-checked but never replayed as delayed commands.
12. Command sequence and Emonio cycle ID remain separate.
13. Every command binds Viewer session ID, node ID, boot ID, and sequence.
14. Wrong identity, boot, protocol, or active sequence is rejected.
15. Actuator reboot invalidates previous acknowledged load state.
16. A fault while enabled latches `TRIPPED`.
17. Cleared faults do not automatically re-enable control.
18. Operator disable from enabled requests safe state but is not a trip.
19. Operator disable cannot clear an existing trip.
20. Safe commands preempt an outstanding non-zero command.
21. `SAFE_UNCONFIRMED` and `SAFE_CONFIRMED` remain distinct.
22. Only an exact successful zero-applied ACK confirms safe state.
23. Q telemetry is preserved and Q compensation requests remain exactly zero.
24. Evidence distinguishes measured, calculated, transmitted, and acknowledged values.
25. Evidence write failure prevents new non-zero command transmission and trips active control.
26. Evidence failure does not suppress a required safe-command attempt.
27. Mock discovery never grants authority and never changes persistent binding.
28. No real actuator network client exists in the first stage.
29. No browser endpoint or field directly commands phase power.
30. Existing read-only Modbus, scientific sign, SCOPE, and CSV paths remain unchanged.

## Execution Handoff

After this plan is approved for execution, use one of these workflows:

1. **Subagent-Driven (recommended):** Use `superpowers:subagent-driven-development`. Execute one task at a time with a fresh worker and two-stage review.
2. **Inline Execution:** Use `superpowers:executing-plans`. Execute tasks in this session in reviewable batches with checkpoints.

Do not begin implementation until the execution workflow is selected.