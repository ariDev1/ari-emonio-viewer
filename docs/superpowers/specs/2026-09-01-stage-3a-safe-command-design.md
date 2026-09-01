# ARI Emonio Viewer Stage 3A Safe Command Design

Status: DESIGN APPROVED IN CHAT — WRITTEN SPEC PENDING REVIEW

Date: 2026-09-01

Repository: `ariDev1/ari-emonio-viewer`

Branch: `testing`

Design baseline: v0.4.21 Testing, commit `253408a3bcf5d7ace83fd7f91b975611d1f49e24`

## 1. Purpose

Stage 3A qualifies the first real Viewer-to-actuator application COMMAND and the deterministic actuator ACK path.

Stage 3A is not active load control. It permits only one operator-initiated SAFE test command at a time. The command always requests zero active load on all phases and keeps `control_enabled=false`.

The design must preserve the field-qualified Stage-2 LAN discovery, WebSocket connection, HELLO qualification, heartbeat supervision, boot-instance invalidation, and explicit reconnect behavior.

## 2. Scientific and safety invariants

Stage 3A must not modify or reinterpret:

- canonical P signs;
- canonical Q signs;
- quadrant semantics;
- PF semantics;
- measurement validation;
- fixed-deadline acquisition;
- Modbus read-only behavior;
- register maps;
- measurement decoder logic;
- recording;
- CSV precision;
- SCOPE measurement semantics.

The protected scientific paths remain unchanged unless separate evidence proves that a change is necessary.

Stage 3A must not request a new Modbus cycle. It observes canonical `MeasurementSample` events that the existing acquisition path already publishes.

## 3. Stage 3A scope

Stage 3A adds only these capabilities:

1. Explicitly select one Emonio source for the current Viewer session.
2. Explicitly start one SAFE protocol test.
3. Wait for the next VALID canonical sample from that selected Emonio.
4. Build one Protocol V1 `COMMAND` frame with real sample provenance and zero requested load.
5. Send the command over the already qualified real WebSocket session.
6. Wait for one matching `ACK` for at most 2.0 s.
7. Accept or reject the exchange with deterministic evidence.

## 4. Explicit non-goals

Stage 3A must not add:

- nonzero real load requests;
- measurement-derived load requests;
- automatic command generation;
- periodic commands;
- retries;
- replay;
- automatic actuator selection;
- automatic Emonio source selection;
- persistent Stage-3A source binding;
- automatic reconnect;
- automatic requalification after actuator reboot;
- real control enable;
- PWM, GPIO, relay, MOSFET, half-bridge, or physical load output;
- Q compensation;
- changes to the Stage-1 mock supervisor calculation path.

The existing mock development controls remain isolated from the real Stage-3A path.

## 5. Existing protocol reuse

Protocol V1 already defines `COMMAND` and `ACK`. Stage 3A must reuse this protocol. It must not add placeholder measurement data and must not add a second SAFE-specific protocol frame.

The SAFE command must use one real canonical Emonio sample because the existing `COMMAND` schema requires measurement provenance.

## 6. Emonio source selection

The operator must explicitly select one Emonio source.

The selection rules are:

- no default source;
- no automatic source selection;
- no persistent Stage-3A binding;
- selection is volatile and ends when the Viewer process ends;
- the backend validates that the selected Emonio exists in the current Viewer runtime;
- Stage 3A must not reuse the persistent Stage-1 mock binding.

If the selected source becomes unavailable before command transmission, the test is rejected and no command is sent.

## 7. Operator initiation

The UI must provide one explicit action named `SEND SAFE TEST COMMAND`.

One button activation requests one SAFE test exchange.

The action must not send a command immediately. It first arms a wait for the next valid canonical sample.

The Viewer must reject a second concurrent SAFE test request while one test is active.

A later test after `PASSED` or `REJECTED` requires another explicit button activation. There is no automatic restart of a test exchange.

## 8. Canonical sample boundary

When the operator starts a SAFE test, Stage 3A records the current source cycle boundary.

The command provenance must use a later sample that satisfies all of these conditions:

- `sample.identity.device_id` equals the explicitly selected Emonio source;
- `sample.identity.cycle_id` is greater than the recorded boundary;
- `sample.quality` is `VALID`;
- the sample is the first VALID canonical sample that satisfies the above rules before the wait timeout.

A cached sample from before the button activation must never be used.

Stage 3A must observe the existing `RuntimeEventBus`. It must not request, trigger, reschedule, or delay acquisition.

## 9. Sample wait timeout

The sample wait timeout is derived from the selected Emonio configuration:

`sample_wait_timeout_s = 2 * poll_interval_s`

The selected `poll_interval_s` must be finite and greater than zero.

With the normal 2.0 s polling interval, the Stage-3A wait limit is 4.0 s.

If no qualifying sample arrives before the deadline:

- state becomes `REJECTED`;
- reason is `NO_NEW_VALID_SAMPLE`;
- no COMMAND is sent;
- there is no automatic retry.

If the selected source emits an acquisition failure before a qualifying sample is accepted, Stage 3A rejects the active test with `SOURCE_ACQUISITION_FAILURE`. It does not send a command.

## 10. SAFE COMMAND construction

The command must be a normal Protocol V1 `CommandFrame`.

The following fields are fixed for Stage 3A:

- `protocol_version = 1`;
- `control_enabled = false`;
- `p_reserve = 0.0`;
- `p_load_request = {a: 0.0, b: 0.0, c: 0.0}`;
- `q_comp_request = {a: 0.0, b: 0.0, c: 0.0}`.

The following fields must come from real current evidence:

- `node_id` from the qualified Stage-2 HELLO;
- `boot_id` from the qualified Stage-2 HELLO;
- `emonio_device_id` from the explicit Stage-3A source selection;
- `measurement_cycle_id` from the accepted canonical sample;
- `measurement_utc` from that sample's canonical cycle-finished UTC timestamp;
- `measured_p` from canonical phase A/B/C P values in that sample;
- `measured_q` from canonical phase A/B/C Q values in that sample.

`command_utc` is generated by the Viewer at command creation time.

Stage 3A must not modify, clamp, repair, average, smooth, or sign-correct the copied P or Q evidence.

## 11. Viewer session identity and command sequence

Stage 3A owns one volatile non-empty `viewer_session_id` for the Viewer process.

The command sequence starts at 1 for that Stage-3A Viewer session.

A sequence number is allocated immediately before one command send attempt. Once allocated, that sequence number is consumed permanently, whether the send succeeds or fails. It is never reused in the same Viewer session.

Each later operator-initiated SAFE test that reaches the send boundary receives the next sequence number.

The first Stage-3A field qualification therefore uses sequence 1.

## 12. Single-owner WebSocket receive architecture

The current Stage-2 implementation has a disconnect watcher that owns `websocket.receive()`. The existing `receive_ack()` method also calls the receive path. Two concurrent readers on one WebSocket are not permitted.

Stage 3A must establish one receive owner for the real actuator WebSocket.

The design is:

1. HELLO remains the first application frame and is received during connection qualification.
2. After HELLO qualification, exactly one receive loop owns all later WebSocket receives.
3. The receive loop classifies inbound application frames.
4. `ACK` frames are delivered to the one active Stage-3A ACK waiter.
5. `STATUS` frames are allowed. They can be logged but cannot satisfy an ACK waiter and cannot qualify a SAFE command.
6. A second `HELLO`, an actuator-originated `COMMAND`, malformed protocol JSON, or another unexpected application frame is a protocol fault.
7. A protocol fault invalidates the real actuator session and rejects an active Stage-3A exchange.
8. WebSocket CLOSE, CLOSED, ERROR, heartbeat loss, or transport failure invalidates the real session.
9. No other task may call `websocket.receive()` directly while the receive owner is active.

This refactor must preserve all Stage-2 disconnect and heartbeat behavior.

## 13. ACK timeout

The ACK timeout is fixed at 2.0 s for Stage 3A.

The monotonic ACK timer starts only after the command send operation completes successfully.

If no valid ACK is accepted within 2.0 s:

- state becomes `REJECTED`;
- reason is `ACK_TIMEOUT`;
- no command is retried;
- no second command is generated automatically;
- a late ACK cannot change the terminal result.

A late ACK received after the exchange is terminal is logged as unexpected evidence. It does not change the state and does not cause an automatic command.

## 14. Strict SAFE ACK acceptance

A Stage-3A ACK passes only when all required fields match exactly.

Required exact matches are:

- `protocol_version == 1`;
- `viewer_session_id == current Stage-3A viewer_session_id`;
- `node_id == qualified HELLO node_id`;
- `boot_id == qualified HELLO boot_id`;
- `sequence == outstanding command sequence`;
- `result == "APPLIED"`;
- `applied_p.a == 0.0`;
- `applied_p.b == 0.0`;
- `applied_p.c == 0.0`.

There is no tolerance for `applied_p` in Stage 3A because the present actuator is a software-only protocol test device with no physical power output.

The validator must not clamp, repair, default, or reinterpret any ACK field.

Any mismatch rejects the test. The diagnostic reason must identify the mismatch category without changing the received evidence.

An ACK received while no Stage-3A command is outstanding is logged as `SAFE_ACK_UNEXPECTED`. It cannot change `PASSED`, `REJECTED`, or any Stage-2 qualification state.

## 15. Actuator reboot and disconnect behavior

Stage-2 identity remains `(node_id, boot_id)`.

If the actuator disconnects before the command is sent:

- the active Stage-3A test is rejected;
- no command is sent.

If the actuator disconnects while the Viewer waits for ACK:

- the active Stage-3A test is rejected;
- no retry is made.

If the actuator reboots:

- Stage-2 qualification is invalidated;
- the old boot ID cannot be used for a new Stage-3A command;
- the operator must explicitly scan/connect/qualify the new boot instance before another SAFE test can become READY.

There is no automatic reconnect or automatic requalification.

## 16. Stage-3A state model

The Stage-3A service uses these states:

- `IDLE`
- `SOURCE_SELECTED`
- `READY`
- `WAITING_FOR_SAMPLE`
- `COMMAND_SENT`
- `WAITING_FOR_ACK`
- `PASSED`
- `REJECTED`

State meaning:

`IDLE`: no Stage-3A source is selected.

`SOURCE_SELECTED`: an Emonio source is selected, but the real actuator is not currently HELLO-qualified.

`READY`: source is selected and the Stage-2 actuator instance is HELLO-qualified.

`WAITING_FOR_SAMPLE`: operator started a SAFE test and the service is waiting for the next qualifying canonical sample.

`COMMAND_SENT`: the one SAFE command was serialized and its WebSocket send completed successfully.

`WAITING_FOR_ACK`: the command is outstanding and the 2.0 s ACK deadline is active.

`PASSED`: the strict matching SAFE ACK was accepted.

`REJECTED`: the active SAFE test failed deterministically.

`PASSED` and `REJECTED` are terminal for that one test exchange. They do not clear the selected Emonio source and they do not trigger another exchange.

When the operator later presses `SEND SAFE TEST COMMAND`, the backend re-evaluates the complete admissibility gate. If the gate passes, a new exchange starts at `WAITING_FOR_SAMPLE` and uses a new source cycle boundary. If the gate fails, no command is sent.

If Stage-2 qualification is lost, the effective Stage-3A readiness becomes `SOURCE_SELECTED` until a new explicit Stage-2 qualification succeeds.

## 17. Stage-3A admissibility gate

`SEND SAFE TEST COMMAND` is admissible only when all of these conditions hold:

- one Emonio source is explicitly selected;
- selected Emonio exists in current runtime;
- selected Emonio acquisition is available for new canonical samples;
- one real actuator WebSocket session is connected;
- HELLO is qualified;
- current actuator node ID and boot ID are available;
- no other Stage-3A exchange is active;
- no ACK is outstanding.

If any gate fails, the request is rejected before transmission.

## 18. Backend service boundary

Stage 3A must use a dedicated real-protocol qualification service. It must not connect the existing Stage-1 `LoadControlService` mock supervisor directly to the real actuator.

The dedicated Stage-3A service owns:

- volatile Emonio source selection;
- active SAFE test state;
- source cycle boundary;
- sample wait deadline;
- Stage-3A viewer session ID;
- real command sequence allocation;
- outstanding SAFE command identity;
- ACK deadline;
- strict Stage-3A ACK validation;
- Stage-3A diagnostic events.

It depends on existing components through narrow interfaces:

- Stage-2 qualification service for current qualified actuator identity and real WebSocket session;
- `RuntimeEventBus` for canonical samples and acquisition diagnostics;
- current device configuration for selected source `poll_interval_s`.

It must not own or modify acquisition.

## 19. API design

Stage 3A adds these exact API operations:

- `GET /api/v1/load-control/lan-safe-test/status`
- `GET /api/v1/load-control/lan-safe-test/sources`
- `POST /api/v1/load-control/lan-safe-test/source`
- `POST /api/v1/load-control/lan-safe-test/send`

`POST /api/v1/load-control/lan-safe-test/source` accepts exactly one field:

```json
{"emonio_device_id":"<selected-current-device-id>"}
```

`POST /api/v1/load-control/lan-safe-test/send` accepts only an empty JSON object:

```json
{}
```

Unknown or additional request fields are rejected.

The browser must never be able to supply:

- `control_enabled=true`;
- a nonzero P request;
- Q compensation;
- sequence number;
- node ID override;
- boot ID override;
- measured P/Q values;
- measurement cycle ID;
- measurement timestamp.

These values remain backend-owned.

## 20. UI design

The primary real-actuator area changes from Stage 2 network qualification to Stage 3A SAFE protocol qualification.

The UI must continue to show:

- LAN discovery;
- explicit actuator selection;
- WebSocket state;
- HELLO state;
- node ID and boot ID;
- protocol/class/capability;
- advertised test limits;
- diagnostic log;
- explicit disconnect.

Stage 3A adds one small section named `SAFE command qualification` with:

- explicit Emonio source selector;
- current Stage-3A state;
- selected source;
- accepted sample cycle when available;
- outstanding or last sequence;
- ACK result;
- `SEND SAFE TEST COMMAND` button.

The UI must state clearly:

- `NONZERO REAL CONTROL DISABLED`;
- the command request is fixed at `0 / 0 / 0 W`;
- one button activation sends at most one command after a new valid sample is acquired;
- there is no automatic retry.

The Stage-1 mock controls remain inside `DEVELOPMENT / MOCK CONTROL`.

## 21. Diagnostic evidence

The existing bounded backend diagnostic log remains the primary field evidence for the real LAN actuator path.

Stage 3A must add these stable events:

- `SAFE_SOURCE_SELECTED`
- `SAFE_TEST_REQUESTED`
- `SAFE_SAMPLE_WAIT_STARTED`
- `SAFE_SAMPLE_ACCEPTED`
- `SAFE_COMMAND_SENT`
- `SAFE_ACK_RECEIVED`
- `SAFE_ACK_QUALIFIED`
- `SAFE_ACK_UNEXPECTED`
- `SAFE_TEST_PASSED`
- `SAFE_TEST_REJECTED`

The log must include the fields needed to reconstruct protocol qualification, as applicable:

- Emonio device ID;
- measurement cycle ID;
- measurement UTC;
- canonical measured P A/B/C;
- canonical measured Q A/B/C;
- viewer session ID;
- actuator node ID;
- actuator boot ID;
- command sequence;
- requested P A/B/C;
- ACK applied P A/B/C;
- rejection reason.

No credentials or secrets are logged.

## 22. Deterministic rejection categories

Stage 3A must distinguish these failures:

- `SOURCE_NOT_SELECTED`
- `SOURCE_NOT_AVAILABLE`
- `SOURCE_ACQUISITION_FAILURE`
- `NO_NEW_VALID_SAMPLE`
- `ACTUATOR_NOT_QUALIFIED`
- `ACTUATOR_DISCONNECTED`
- `COMMAND_SEND_FAILED`
- `ACK_TIMEOUT`
- `ACK_PROTOCOL_MISMATCH`
- `ACK_SESSION_MISMATCH`
- `ACK_NODE_MISMATCH`
- `ACK_BOOT_MISMATCH`
- `ACK_SEQUENCE_MISMATCH`
- `ACK_RESULT_MISMATCH`
- `ACK_APPLIED_P_MISMATCH`
- `UNEXPECTED_ACTUATOR_FRAME`

A malformed post-HELLO protocol frame is `UNEXPECTED_ACTUATOR_FRAME` unless an active ACK exchange can classify it more specifically as `ACK_PROTOCOL_MISMATCH`.

A failure must never trigger an automatic command.

## 23. Concurrency rules

Stage 3A must use one serialized operation boundary for source changes and SAFE test initiation.

Only one SAFE exchange can be active at a time.

The WebSocket has one receive owner.

The RuntimeEventBus remains read-only from the Stage-3A service perspective. Stage 3A subscribes to evidence but does not publish synthetic measurement samples.

A source change is rejected while a SAFE exchange is active.

A real actuator disconnect cancels any active sample or ACK wait and produces one deterministic terminal rejection for that exchange.

## 24. Test strategy

Implementation must be test-first.

### 24.1 Unit tests

Unit tests must prove:

- no command can be built without qualified actuator identity;
- no command can be built without explicit Emonio selection;
- cached pre-request samples are ignored;
- next valid post-request sample is accepted;
- invalid samples do not become command provenance;
- sample wait timeout equals `2 * poll_interval_s`;
- sample timeout sends no command;
- acquisition failure before sample acceptance sends no command;
- SAFE command is exactly zero P and zero Q request with `control_enabled=false`;
- canonical measured P/Q are copied without transformation;
- sequence allocation is monotonic and never reused, including after send failure;
- ACK deadline is 2.0 s after successful send;
- ACK timeout produces no retry;
- every strict ACK identity mismatch is rejected;
- nonzero `applied_p` is rejected;
- exact zero matching ACK passes;
- late ACK cannot turn REJECTED into PASSED;
- concurrent SAFE tests are rejected;
- source change during active exchange is rejected;
- actuator disconnect invalidates active exchange;
- actuator boot change requires new Stage-2 qualification;
- a new explicit test after PASS or REJECTED gets a new sample boundary and next sequence;
- malformed and unexpected post-HELLO frames fail closed.

### 24.2 WebSocket ownership tests

Tests must prove:

- only one task owns post-HELLO receives;
- ACK delivery does not create a second `receive()` caller;
- Stage-2 heartbeat remote-disconnect detection still works;
- STATUS does not satisfy an ACK waiter;
- a second HELLO fails closed;
- an actuator-originated COMMAND fails closed;
- malformed post-HELLO protocol JSON fails closed;
- WebSocket error closes and invalidates the qualification path;
- no automatic reconnect occurs.

### 24.3 API tests

Tests must prove:

- source selection accepts exactly `emonio_device_id`;
- SAFE send accepts exactly `{}`;
- additional fields are rejected;
- the browser cannot submit nonzero power, sequence, measured data, node override, or boot override.

### 24.4 Frontend contract tests

Tests must prove:

- no source auto-selection;
- button disabled when Stage 3A is not admissible;
- button shows fixed zero-output purpose;
- one click produces one backend SAFE-test request;
- UI cannot set nonzero power;
- mock controls remain isolated.

### 24.5 Protected-path acceptance

The existing complete acceptance suite and protected scientific path gate must pass before field testing.

## 25. Field acceptance sequence

Stage 3A is not field-qualified by automated tests alone.

The first real field test must use the software-only ARI Load Test Actuator with no physical output.

Required sequence:

1. Start the Viewer candidate on `testing`.
2. Confirm normal Emonio acquisition.
3. Scan LAN.
4. Explicitly select `ARI-LOAD-001`.
5. Connect and qualify HELLO.
6. Explicitly select one Emonio source.
7. Press `SEND SAFE TEST COMMAND` once.
8. Confirm the accepted provenance sample has a cycle ID later than the button-request boundary.
9. Confirm exactly one COMMAND is logged as sent.
10. Confirm the command has `control_enabled=false` and `p_load_request=0/0/0 W`.
11. Confirm the actuator returns one matching ACK within 2.0 s.
12. Confirm ACK `result=APPLIED` and `applied_p=0/0/0 W` exactly.
13. Confirm Stage 3A reports PASS.
14. Confirm no second command is sent automatically.
15. Use actuator-side serial evidence to independently confirm the received COMMAND and emitted ACK.

Field acceptance must also include negative tests for at least ACK timeout, identity mismatch, and actuator reboot/disconnect before later stages are permitted.

## 26. Promotion boundary

Stage 3A implementation remains on `testing` until automated acceptance and real actuator field evidence pass.

Stage 3A PASS does not authorize nonzero load commands.

A later stage is required before any nonzero request, measurement-derived control request, continuous control loop, or physical load hardware can be enabled.

## 27. Reversibility

The Stage-3A implementation must be removable without changing canonical acquisition or measurement code.

The architecture must preserve the Stage-2 qualification service boundaries so that the software can return to HELLO-only qualification if Stage 3A evidence fails.

No Stage-3A configuration is required for normal Viewer measurement operation.
