# ARI Emonio Viewer External Load Control Supervisor Design

Date: 2026-09-01
Status: APPROVED DESIGN SPECIFICATION
Repository: `ariDev1/ari-emonio-viewer`
Branch: `testing`
Design baseline commit: `e3e33ec959d6304ca8471ab1c0f217884b64ed18`

## 1. Purpose

This specification defines the Viewer-side architecture for a future external three-phase load-control actuator.

The primary objective is a scientifically correct, fail-safe, auditable supervisory controller that can later command one three-phase ESP32 actuator without weakening the trusted Emonio measurement architecture.

The first implementation stage does not control physical hardware. It proves the Viewer-side state machine, calculations, protocol model, evidence model, operator API, and failure behavior with deterministic mock components.

## 2. Protected architecture

The existing measurement path remains authoritative and unchanged:

`Emonio -> read-only Modbus/TCP -> canonical MeasurementSample -> RuntimeStore + RuntimeEventBus`

The new subsystem consumes completed canonical `MeasurementSample` events only after acquisition and validation are complete:

`RuntimeEventBus -> LoadControlService -> LoadControlSupervisor -> ActuatorSession`

The new subsystem shall not modify or become a dependency of:

- Modbus acquisition;
- Modbus register maps;
- decoder logic;
- canonical measurement signs;
- P/Q quadrant semantics;
- measurement validation;
- fixed-deadline acquisition;
- SCOPE measurement semantics;
- existing CSV precision or recording semantics.

Acquisition shall never wait for the load-control subsystem.

## 3. Control authority and persistent binding

One Viewer instance can control at most one selected three-phase actuator node.

The control relationship is an explicit persistent binding:

`one selected Emonio control source -> one selected actuator node`

The normal Viewer-selected display device is not the control source unless it is also the explicit control-source binding.

Changing the normal Viewer device selection shall not change control authority.

The persistent binding contains at least:

- bound Emonio device ID;
- bound actuator persistent node ID.

The binding can persist across Viewer restarts.

The following values can also persist as safety configuration:

- `P_reserve`;
- operator maximum active-load limit for Phase A;
- operator maximum active-load limit for Phase B;
- operator maximum active-load limit for Phase C.

The following values are always volatile and shall not persist across Viewer restarts:

- control-enabled state;
- Viewer session ID;
- command sequence number;
- actuator boot ID;
- outstanding command state;
- previous acknowledged actuator demand;
- safe-state confirmation.

The Viewer shall not automatically bind to another Emonio or actuator if a bound device disappears.

## 4. Startup rule

Every Viewer start begins with:

`control_mode = DISABLED`

Non-zero actuator demand is forbidden until an operator explicitly requests `ENABLE EXTERNAL CONTROL` and the complete enable gate passes.

Discovery and connection can occur automatically while control is disabled.

The required active-load demand after startup is always:

- Phase A = `0 W`;
- Phase B = `0 W`;
- Phase C = `0 W`.

The Viewer shall establish or re-establish safe-state confirmation before control can be enabled.

## 5. Component boundaries

The new package is conceptually:

```text
src/emonio_viewer/load_control/
    model.py
    state_machine.py
    controller.py
    supervisor.py
    discovery.py
    session.py
    protocol.py
    evidence.py
    service.py
```

### 5.1 `model.py`

Own immutable load-control data models:

- actuator identity;
- actuator capabilities;
- per-phase limits;
- three-phase active-load requests;
- acknowledgement state;
- control status;
- trip reason;
- safe-state confirmation.

### 5.2 `state_machine.py`

Own legal control-mode transitions and safety-state transitions. It contains no network code and no Modbus code.

### 5.3 `controller.py`

Own pure deterministic active-power calculations. It contains no network code, persistence code, API code, or acquisition code.

### 5.4 `supervisor.py`

Consume canonical runtime events for the bound Emonio. It checks identity, measurement quality, freshness, cycle continuity, acknowledgement state, and safety conditions. It calls the deterministic controller and decides whether a normal command or safe command is required.

### 5.5 `discovery.py`

Own actuator discovery. Discovery locates compatible nodes but never grants control authority.

### 5.6 `session.py`

Own one persistent actuator connection, session qualification, command transmission, heartbeat, acknowledgements, connection loss, and actuator status.

### 5.7 `protocol.py`

Own versioned protocol models, strict validation, serialization, parsing, and message identity. It contains no control calculations.

### 5.8 `evidence.py`

Own append-only deterministic load-control evidence.

### 5.9 `service.py`

Own subsystem lifecycle and expose read-only status plus explicit operator commands to the server layer. It subscribes independently to `RuntimeEventBus`.

## 6. Three independent state domains

The design intentionally separates control authority, network/session readiness, and physical safe-state evidence.

### 6.1 Control mode

The control-mode state machine has only:

- `DISABLED`;
- `ENABLED`;
- `TRIPPED`.

#### DISABLED

- Default after every Viewer start.
- Non-zero demand is forbidden.
- Required demand is `0/0/0 W`.
- Discovery and connection can continue.
- Operator can request enable.
- Enable succeeds only if the complete enable gate passes.

#### ENABLED

- Only fresh `VALID` samples from the bound Emonio can drive calculations.
- Non-zero active-load commands are permitted.
- Only one normal command can be unacknowledged at a time.
- Operator disable transitions to `DISABLED` and requests safe demand.
- Any safety fault transitions immediately to `TRIPPED` and requests safe demand.

#### TRIPPED

- Non-zero demand is forbidden.
- Required demand is `0/0/0 W`.
- Trip reason is latched.
- Automatic discovery, reconnect, and identity verification are permitted.
- Automatic return to `ENABLED` is forbidden.
- Only a new explicit operator enable request can clear the trip, and only if the complete enable gate passes.

### 6.2 Actuator session readiness

Session readiness is separate from control authority. Conceptual states are:

- `UNBOUND`;
- `DISCOVERING`;
- `UNAVAILABLE`;
- `CONNECTING`;
- `VERIFYING`;
- `READY`;
- `SESSION_FAULT`.

`READY` means only that the selected actuator connection and protocol session are qualified. It never means that active control is enabled.

A normal startup condition can therefore be:

`control_mode = DISABLED`

`session_state = READY`

### 6.3 Safe-state confirmation

Safe-state evidence is independent:

- `NOT_REQUIRED`;
- `SAFE_UNCONFIRMED`;
- `SAFE_CONFIRMED`.

`SAFE_UNCONFIRMED` means the Viewer requires `0/0/0 W` but does not yet have valid actuator evidence that this state is physically applied.

`SAFE_CONFIRMED` means the bound actuator has acknowledged the current safe command and reports applied active-load demand of exactly `0/0/0 W` according to protocol precision rules.

A sent safe command is not proof of safe applied state.

## 7. Enable gate

`ENABLE EXTERNAL CONTROL` is an atomic operation.

The Viewer shall enter `ENABLED` only when all required conditions are true:

- a control-source Emonio is bound;
- an actuator persistent node ID is bound;
- the bound Emonio has a current sample;
- the current sample quality is `VALID`;
- the current sample passes the dedicated control-freshness rule;
- the actuator session is `READY`;
- the connected actuator node ID matches the persistent binding;
- the current actuator boot ID is established;
- the protocol version is compatible;
- the actuator advertises `ACTIVE_LOAD_CONTROL`;
- effective per-phase active-load limits are valid;
- no protocol/session fault is active;
- no outstanding command from an incompatible session exists;
- safe state is `SAFE_CONFIRMED`.

If any condition fails, the Viewer remains in its current non-enabled mode and reports the exact rejection reason.

There is no partially enabled state.

## 8. Measurement eligibility

Only `MeasurementSample.quality == VALID` is eligible for active control.

While `ENABLED`, these conditions cause an immediate latched trip:

- `DEGRADED` sample;
- `STALE` sample;
- `INVALID` sample;
- acquisition failure;
- stale sample according to the dedicated control freshness limit;
- unexplained source cycle gap.

Measurement values can still be retained as telemetry and evidence when they are not eligible for control.

The load-control subsystem shall not alter a canonical measurement sample.

## 9. Dedicated control freshness

Control freshness is independent of the general Viewer display stale threshold.

The architecture has a dedicated `control_sample_max_age_s` qualification input.

The first mock-only implementation can inject this value explicitly for deterministic tests.

No real actuator transport can be activated until the control freshness value and related communication timing limits have been qualified from measured Viewer and network timing evidence.

Freshness shall use monotonic process timing, not wall-clock subtraction. The preferred source is the canonical sample cycle-finished monotonic timestamp compared with the current monotonic clock.

UTC timestamps remain evidence and protocol association fields.

If the monotonic age exceeds the qualified limit while `ENABLED`, the Viewer shall:

- transition to `TRIPPED`;
- require `0/0/0 W`;
- record exact observed age and configured limit.

## 10. Control objective

V1 uses one common positive import reserve independently on each phase:

`P_target_A = +P_reserve`

`P_target_B = +P_reserve`

`P_target_C = +P_reserve`

The controller does not use total active power to redistribute demand between phases.

This prevents one importing phase from hiding export on another phase.

## 11. Deterministic V1 control calculation

Each phase is calculated independently.

For a phase:

`error = P_reserve - P_measured`

The authoritative actuator state is the last valid acknowledgement of applied load:

`P_acknowledged`

The V1 scientific baseline uses unity correction:

`correction(error) = error`

Therefore:

`P_request_raw = P_acknowledged + P_reserve - P_measured`

Example:

`P_measured = -420 W`

`P_reserve = +30 W`

`P_acknowledged = 0 W`

Result:

`P_request_raw = 450 W`

After an acknowledged load of `450 W`, if the next measured power is `+25 W`:

`P_request_raw = 450 + 30 - 25 = 455 W`

This preserves closed-loop causality. The controller does not repeatedly calculate an absolute request from zero.

The first mock-only implementation adds no unqualified gain, PID term, averaging, interpolation, smoothing, deadband, hysteresis, synthetic samples, or plant noise.

Dynamic safeguards such as qualified gain, rate limiting, and deadband can be added only after real actuator response evidence exists. Real power-stage activation is outside the scope of this design stage.

## 12. Active-load direction and limits

V1 `ACTIVE_LOAD_CONTROL` commands are non-negative only:

`P_load_request_phase >= 0 W`

Negative active-load requests are forbidden.

A future bidirectional actuator requires a separate capability and separate protocol semantics.

Each phase has two maximum limits:

- actuator-advertised physical maximum;
- operator-configured safety maximum.

The effective limit is:

`P_limit_phase = min(P_actuator_max_phase, P_operator_max_phase)`

Every request is constrained to:

`0 W <= P_load_request_phase <= P_limit_phase`

If an actuator changes an advertised limit while control is `ENABLED`, the Viewer shall trip because the active capability contract changed.

Limit saturation is not a fault.

When a calculated request exceeds the effective maximum:

- transmit the effective maximum;
- remain `ENABLED` if no other fault exists;
- report `LIMITED_MAX` for that phase;
- record the unmet control error;
- do not maintain a hidden internal command above the permitted limit.

A minimum clamp to `0 W` is similarly reported as a normal limit condition.

## 13. Authoritative actuator state and acknowledgements

The controller uses the last valid actuator acknowledgement as authoritative applied-load state.

A transmitted command is not evidence that the actuator applied it.

Missing, stale, malformed, wrong-session, wrong-identity, or wrong-sequence acknowledgement data cannot become authoritative controller state.

The Viewer allows only one unacknowledged normal active-control command at a time.

While a normal command is outstanding:

- all bound-source measurement cycles are still observed;
- all measurement safety checks still run;
- all cycle-continuity checks still run;
- intermediate samples are logged;
- intermediate samples do not generate delayed normal commands.

After a valid acknowledgement establishes new actuator state, only the next newly completed eligible measurement can generate the next normal command.

The causal chain is:

`measurement -> command -> acknowledgement -> new measurement -> next command`

## 14. Safe command preemption

A safety action overrides the one-normal-command-in-flight rule.

If a fault or operator disable occurs while a non-zero normal command is outstanding:

- the previous command becomes superseded for control purposes;
- allocate a new command sequence;
- transmit a safe `0/0/0 W` command if the session permits transmission;
- enter `TRIPPED` for a fault or `DISABLED` for operator disable;
- set safe state to `SAFE_UNCONFIRMED` until a valid safe acknowledgement arrives.

A late acknowledgement for the superseded non-zero command is recorded as obsolete and cannot restore control state or authoritative actuator state.

Only the current safe command can establish `SAFE_CONFIRMED`.

If the connection is lost and no safe command can be delivered, safe state remains `SAFE_UNCONFIRMED`.

## 15. Operator disable

Operator disable is not a trip.

On `DISABLE EXTERNAL CONTROL`:

- immediately revoke authority for non-zero demand;
- transition to `DISABLED`;
- require `0/0/0 W`;
- transmit a safe command if possible;
- track `SAFE_UNCONFIRMED` or `SAFE_CONFIRMED` independently;
- continue discovery, connection, telemetry, and evidence collection.

## 16. Latched trip behavior

Safety-relevant faults while `ENABLED` cause a latched `TRIPPED` state.

Trip conditions include at least:

- measurement not `VALID`;
- dedicated freshness limit exceeded;
- acquisition timeout;
- acquisition protocol failure;
- acquisition decode failure;
- acquisition transport failure;
- unexplained Emonio control-source cycle gap;
- actuator connection loss;
- actuator identity mismatch;
- actuator boot change;
- protocol parse or validation error;
- required capability loss;
- active actuator limit contract change;
- invalid or incompatible acknowledgement;
- qualified acknowledgement timeout.

After the fault clears, automatic reconnect and verification are permitted, but control remains `TRIPPED`.

A new explicit operator enable request is required.

## 17. Control-source cycle integrity

The load-control consumer shall detect evidence loss without changing the non-blocking `RuntimeEventBus` architecture.

For the bound Emonio, the control continuity stream uses cycle-bearing acquisition outcomes:

- a canonical `MeasurementSample` for cycle `N`;
- an explicit acquisition failure diagnostic for cycle `N`.

While `ENABLED`, consecutive acquisition outcomes shall advance by exactly one cycle ID.

Example:

- observed cycle 1820;
- next observed outcome is cycle 1822;
- no explicit acquisition failure for cycle 1821 was observed.

Result:

`TRIPPED / CONTROL_SAMPLE_SEQUENCE_GAP`

An explicit acquisition failure for cycle 1821 accounts for that cycle but itself causes a trip while control is enabled.

Cycle gaps while already `DISABLED` or `TRIPPED` are recorded but do not create a second state transition.

Measurement cycle ID and actuator command sequence are separate identities and shall never be merged.

## 18. Discovery and identity

### 18.1 Discovery

Preferred discovery is mDNS using a service concept such as:

`_ari-emonio-load._tcp.local`

DHCP-assigned IP addresses are normal.

Discovery can update network location information such as hostname, IP address, and port.

Discovery never changes persistent control binding and never enables control.

No automatic transfer to another discovered actuator is permitted.

### 18.2 Persistent actuator identity

Each actuator has a persistent logical node identity, for example:

`ARI-LOAD-001`

The persistent `node_id` is the control binding identity. IP address and hostname are not control identities.

### 18.3 Volatile actuator boot identity

Each actuator boot has a new volatile `boot_id`.

If `boot_id` changes:

- previous acknowledged actuator demand is invalidated;
- previous outstanding command state is invalidated;
- current physical applied state must be established again;
- safe state must be confirmed before enable;
- if control was `ENABLED`, transition to `TRIPPED`.

A correct persistent `node_id` does not make previous control state valid across an actuator reboot.

## 19. Viewer session identity and command sequence

Each Viewer start creates a new volatile `viewer_session_id`.

Command sequence numbers are monotonic inside one Viewer session.

The command identity includes:

- Viewer session ID;
- actuator persistent node ID;
- actuator boot ID;
- command sequence number.

Sequence numbers do not need persistence across Viewer restart because the Viewer session ID creates a new namespace.

A temporary actuator reconnect without Viewer restart does not reset the Viewer session ID or command sequence counter.

Every transmitted `COMMAND`, including safe commands, receives a sequence number.

A valid acknowledgement must match the current:

- Viewer session ID;
- actuator node ID;
- actuator boot ID;
- expected command sequence.

## 20. Transport architecture

The target real transport architecture is:

`mDNS discovery + Viewer-initiated persistent WebSocket + versioned JSON protocol`

mDNS is for discovery only.

Control traffic is unicast to the selected bound actuator.

WebSocket is preferred over custom raw TCP framing because it provides:

- persistent bidirectional communication;
- ordered delivery through TCP;
- explicit message boundaries;
- native asynchronous operation;
- connection-close detection;
- heartbeat support;
- direct JSON message carriage.

Connection alone is never sufficient for `READY`.

The session must complete protocol qualification first.

Transport heartbeat and application protocol evidence are distinct. A technically open WebSocket does not prove that the actuator application is ready.

No heartbeat, acknowledgement timeout, reconnect timeout, or control freshness numeric value is frozen in this specification. Real network activation is forbidden until those values are qualified from measured timing evidence. Mock tests inject explicit deterministic limits.

## 21. Session qualification

After connection, the session enters `VERIFYING`.

The actuator shall provide qualification data that includes at least:

- protocol version;
- persistent node ID;
- volatile boot ID;
- device class;
- capabilities;
- active-load maximum for Phase A;
- active-load maximum for Phase B;
- active-load maximum for Phase C.

The Viewer verifies:

- node ID equals persistent binding;
- protocol version is supported;
- `ACTIVE_LOAD_CONTROL` capability exists;
- all required limits are finite and valid;
- boot ID is present and valid.

A current safe physical state must then be established. The Viewer can issue a safe command after qualification and use its acknowledgement to establish `SAFE_CONFIRMED`.

Only after qualification is complete can session state become `READY`.

## 22. Protocol model

The protocol has four logical message classes:

- `HELLO`;
- `COMMAND`;
- `ACK`;
- `STATUS`.

The exact JSON key spelling and serialization schema are not frozen by this architecture document. The logical data contract and validation requirements are fixed.

### 22.1 HELLO

`HELLO` carries session qualification data:

- protocol version;
- node ID;
- boot ID;
- device class;
- capabilities;
- per-phase active-load maxima.

### 22.2 COMMAND

A `COMMAND` represents A/B/C together. Independent single-phase command messages are not used.

A normal command logically contains at least:

- protocol version;
- Viewer session ID;
- actuator node ID;
- actuator boot ID;
- command sequence;
- Emonio device ID;
- measurement cycle ID;
- measurement UTC;
- command UTC;
- control-enabled state;
- measurement quality/freshness evidence;
- measured `P_A/P_B/P_C`;
- measured `Q_A/Q_B/Q_C`;
- `P_reserve`;
- requested `P_load_A/P_load_B/P_load_C`;
- requested `Q_comp_A/Q_comp_B/Q_comp_C`.

For V1:

- measured Q is telemetry only;
- all `Q_comp_request` values are exactly `0 var`.

P and Q remain scientifically separate.

### 22.3 ACK

An `ACK` logically contains at least:

- protocol version;
- Viewer session ID;
- node ID;
- boot ID;
- acknowledged command sequence;
- acknowledgement UTC;
- applied `P_A/P_B/P_C`;
- result state.

The Viewer accepts an acknowledgement only if identity, sequence, protocol, numeric validity, limits, and result all pass strict validation.

Accepted applied values become authoritative actuator state.

### 22.4 STATUS

`STATUS` is asynchronous actuator telemetry. It can later contain:

- physical output state;
- local watchdog state;
- temperature;
- local faults;
- other actuator evidence.

`STATUS` does not grant control authority.

### 22.5 Strict parsing

Protocol handling is fail-closed for safety-relevant fields:

- unsupported required protocol version -> reject;
- missing required field -> reject;
- wrong field type -> reject;
- non-finite numeric value -> reject;
- identity mismatch -> reject;
- malformed message -> protocol fault;
- no silent safety-field defaults.

## 23. Actuator capabilities

The protocol can advertise capabilities such as:

- `ACTIVE_LOAD_CONTROL`;
- `REACTIVE_COMPENSATION`.

V1 requires only `ACTIVE_LOAD_CONTROL` for active control.

The existence of active-load control does not imply reactive-compensation capability.

Q compensation remains disabled in V1.

## 24. Evidence model

Load control has its own append-only JSON Lines evidence stream. It does not modify existing measurement CSV files.

Evidence shall keep observed facts, calculations, transmitted requests, and acknowledged applied state distinct.

Typical events include:

- `CONTROL_SERVICE_STARTED`;
- `ACTUATOR_DISCOVERED`;
- `ACTUATOR_BOUND`;
- `ACTUATOR_CONNECTED`;
- `ACTUATOR_HELLO_ACCEPTED`;
- `ACTUATOR_HELLO_REJECTED`;
- `CONTROL_ENABLE_REQUESTED`;
- `CONTROL_ENABLE_ACCEPTED`;
- `CONTROL_ENABLE_REJECTED`;
- `CONTROL_DISABLED`;
- `CONTROL_TRIPPED`;
- `CONTROL_COMMAND_CALCULATED`;
- `CONTROL_COMMAND_SENT`;
- `CONTROL_COMMAND_SUPERSEDED`;
- `CONTROL_ACK_ACCEPTED`;
- `CONTROL_ACK_REJECTED`;
- `SAFE_COMMAND_REQUESTED`;
- `SAFE_COMMAND_SENT`;
- `SAFE_STATE_CONFIRMED`;
- `SAFE_STATE_UNCONFIRMED`;
- `CONTROL_SAMPLE_SEQUENCE_GAP`;
- `CONTROL_SAMPLE_NOT_VALID`;
- `CONTROL_SAMPLE_STALE`;
- `ACTUATOR_CONNECTION_LOST`;
- `ACTUATOR_BOOT_CHANGED`;
- `PROTOCOL_ERROR`.

Command-calculation evidence contains at least:

- Viewer session ID;
- node ID;
- boot ID;
- command sequence;
- Emonio device ID;
- measurement cycle ID;
- measurement UTC;
- command UTC;
- sample quality;
- sample age;
- measured P A/B/C;
- measured Q A/B/C;
- P reserve;
- acknowledged applied load A/B/C;
- control error A/B/C;
- raw request A/B/C;
- limited request A/B/C;
- effective limit A/B/C;
- minimum/maximum saturation state.

Acknowledgement evidence contains at least:

- acknowledged sequence;
- acknowledgement UTC;
- applied P A/B/C;
- acknowledgement result.

Evidence serialization requirements:

- UTF-8;
- one JSON object per line;
- no NaN or Infinity representation;
- UTC timestamps are explicit ISO-8601 values;
- deterministic key and numeric serialization rules are testable;
- each event is append-only and is never rewritten as a different fact.

## 25. Viewer API boundary

Load-control HTTP adaptation is separate from controller logic, conceptually:

`src/emonio_viewer/server/load_control_api.py`

The server layer calls `LoadControlService`. It does not calculate actuator demand.

Read-only endpoints conceptually expose:

- load-control status;
- discovered actuators;
- recent load-control evidence.

Explicit operator command endpoints conceptually provide:

- persistent binding changes;
- safety configuration changes;
- enable;
- disable.

There is no browser API that directly sets per-phase active-load command values.

The browser can configure authority and safety settings. Only the backend supervisor can calculate actuator power commands from canonical measurement input.

All safety-critical configuration changes are permitted only while `control_mode = DISABLED`.

This includes at least:

- Emonio control-source binding;
- actuator binding;
- `P_reserve`;
- operator maximum per-phase limits;
- qualified control timing values.

API failures shall return precise service-level rejection reasons. HTTP handlers shall not invent independent safety semantics.

## 26. Viewer UI boundary

The frontend is an operator interface only.

A compact Load Control status area shall expose at least:

- control mode;
- session state;
- safe-state confirmation;
- bound Emonio;
- bound actuator;
- P reserve;
- measured P for A/B/C;
- acknowledged applied load for A/B/C;
- current requested load for A/B/C;
- per-phase limit state;
- outstanding command sequence;
- last acknowledged sequence;
- last trip reason.

The UI shall not expose direct manual actuator power command fields.

A browser reload or browser disconnect shall not define backend control state.

## 27. First implementation stage: strict hardware isolation

The first implementation is Viewer-side only and is incapable of commanding a real actuator.

The actuator session is abstracted:

```text
LoadControlSupervisor
        |
        v
ActuatorSession interface
        |
        +--> MockActuatorSession          first implementation
        |
        +--> WebSocketActuatorSession     later qualification stage
```

The first implementation selects only deterministic mock transport.

There is no fallback from mock transport to network transport.

The mock can deterministically simulate:

- node ID;
- boot ID;
- capabilities;
- per-phase limits;
- exact acknowledgement;
- applied-value offset;
- missing acknowledgement;
- wrong sequence;
- wrong identity;
- actuator reboot;
- connection loss;
- capability change.

Mock behavior is explicit. It shall not silently add randomness, delay, smoothing, noise, or plant dynamics.

Generated logical frames are inspectable through evidence and a recent-frame inspection surface.

The mock begins after canonical measurement input. It does not modify the measurement source.

## 28. Staged qualification path

The required progression is:

1. Viewer logic plus deterministic in-process mock actuator;
2. Viewer real networking plus network mock actuator;
3. ESP32 protocol implementation;
4. real low-risk actuator qualification;
5. power-stage control qualification.

Each stage requires evidence before the next stage is activated.

The first implementation shall not add active mDNS networking, real actuator WebSocket transmission, ESP32 firmware, PWM logic, or power-stage switching.

## 29. Shutdown behavior

Viewer shutdown revokes control authority before closing the actuator session.

Shutdown sequence for load control is conceptually:

1. reject new enable/configuration operations;
2. transition active control authority to non-enabled state;
3. require safe `0/0/0 W`;
4. transmit a safe command if a qualified session is available;
5. record `SAFE_CONFIRMED` if valid acknowledgement arrives before the bounded shutdown deadline;
6. otherwise record `SAFE_UNCONFIRMED`;
7. close actuator session and stop load-control tasks.

Shutdown shall not block indefinitely waiting for safe confirmation.

The numeric shutdown communication deadline is part of later timing qualification for real transport. Mock tests use an explicit deterministic limit.

## 30. Required test coverage

Implementation is test-first.

The first stage shall include deterministic tests for at least:

- correct A/B/C phase mapping;
- signed P handling;
- positive import reserve arithmetic;
- correct `450 W` result for `P=-420 W`, reserve `+30 W`, acknowledged load `0 W`;
- closed supervisory update from acknowledged state;
- per-phase independence;
- non-negative active-load commands;
- operator and actuator limits;
- maximum saturation without trip;
- startup always disabled;
- persistent binding with volatile enable;
- complete enable gate;
- precise enable rejection reasons;
- `VALID` as the only active-control quality;
- dedicated freshness trip;
- acquisition-failure trip;
- source cycle gap trip;
- one outstanding normal command;
- intermediate sample observation without delayed command replay;
- acknowledgement identity and sequence validation;
- acknowledged applied value as authoritative state;
- safe-command preemption;
- obsolete late acknowledgement rejection;
- operator disable behavior;
- trip latching;
- manual re-enable requirement;
- safe requested versus safe confirmed;
- actuator identity mismatch;
- actuator boot change;
- capability loss/change;
- connection loss;
- Viewer session ID isolation;
- monotonic command sequence;
- protocol malformed/non-finite rejection;
- Q telemetry with zero Q compensation request;
- deterministic mock scenarios;
- append-only JSONL evidence;
- separation of measured, calculated, transmitted, and acknowledged values;
- persistence boundaries;
- shutdown safe-state evidence;
- RuntimeEventBus event-loss/cycle-continuity behavior;
- no dependency from protected measurement modules into load control.

## 31. Acceptance gates for the first implementation

The first implementation is acceptable only when all of these are demonstrated:

- protected acquisition and measurement tests remain passing;
- existing read-only Modbus behavior remains unchanged;
- existing SCOPE semantics remain unchanged;
- existing CSV precision and recording tests remain unchanged;
- all new load-control unit tests pass;
- all new load-control integration tests pass with mock transport only;
- control starts disabled on every process start;
- no path can transmit to a real actuator;
- no browser endpoint can directly set phase power commands;
- all active-control decisions are traceable to canonical sample identity and acknowledged actuator state;
- every safety fault produces deterministic safe-state and evidence behavior;
- no automatic rebinding or automatic post-trip re-enable exists;
- no unqualified control constant is introduced.

## 32. Explicit non-goals

This design does not implement or qualify:

- ESP32 firmware;
- physical half-bridge control;
- PWM generation;
- duty-cycle control;
- fast electrical control loop;
- real power-stage switching;
- bidirectional active-power actuator behavior;
- reactive-power compensation;
- automatic controller tuning;
- PID control;
- unqualified gain;
- unqualified rate limit;
- unqualified deadband/hysteresis;
- final communication timeout values;
- final watchdog timeout values;
- direct browser actuator commands.

## 33. Scientific invariants

The following invariants are mandatory:

1. Canonical Emonio P and Q signs are consumed exactly as measured.
2. P and Q remain separate physical quantities.
3. A normal active load is not represented as Q compensation.
4. Control uses per-phase measured P, not inferred PF sign.
5. Total P does not redistribute phase demand.
6. A transmitted command is not an applied-state fact.
7. Only a valid acknowledgement establishes authoritative actuator state.
8. A sent safe command is not proof of safe physical state.
9. Measurement loss is not hidden by smoothing, replay, interpolation, averaging, or synthetic samples.
10. Acquisition never waits for load control.
11. Network discovery never grants control authority.
12. Viewer restart never restores enabled control.
13. Actuator reboot never preserves previous acknowledged load state.
14. A cleared fault never automatically exits `TRIPPED`.
15. No real actuator path is active in the first implementation stage.

## 34. Resulting architecture

The approved V1 supervisory architecture is:

```text
Emonio
  |
  v
Protected read-only Modbus acquisition
  |
  v
Canonical MeasurementSample
  |
  +-------------------------------> existing RuntimeStore / recording / Viewer
  |
  v
RuntimeEventBus
  |
  v
LoadControlService
  |
  v
LoadControlSupervisor
  |
  +--> deterministic controller
  +--> safety state machine
  +--> evidence logger
  |
  v
ActuatorSession abstraction
  |
  +--> deterministic MockActuatorSession     first implementation
  |
  +--> WebSocketActuatorSession              later qualified stage
          |
          v
       ESP32 local fast control loop         future stage
          |
          v
       power stage                           future stage
```

This architecture preserves the trusted Emonio measurement boundary and adds a separate, fail-safe supervisory control domain with explicit authority, identity, causality, and evidence.