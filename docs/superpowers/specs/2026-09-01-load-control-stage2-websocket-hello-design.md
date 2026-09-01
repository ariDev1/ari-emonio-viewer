# ARI Emonio Viewer Stage 2 Design

## Real WebSocket Connection and HELLO Qualification

Date: 2026-09-01

Target branch: `testing`

Viewer baseline: ARI Emonio Viewer v0.4.19

Audited branch HEAD before this design: `4e66d549b813ac3a1bdcacf413d6c41721b2bf1e`

Status: APPROVED ARCHITECTURE. IMPLEMENTATION NOT STARTED.

## 1. Purpose

Stage 2 shall connect the Viewer to one operator-selected ARI load actuator over the real WebSocket transport and shall qualify the actuator HELLO frame.

Stage 2 shall stop after HELLO qualification.

Stage 2 shall not send a COMMAND frame.

Stage 2 shall not enable external control.

Stage 2 shall not bind the real actuator to an Emonio measurement source.

Stage 2 shall not implement physical output.

The Emonio remains the electrical measurement authority.

## 2. Verified Starting Point

The current `testing` branch already contains:

- read-only mDNS discovery;
- `ActuatorDescriptor`;
- strict protocol V1 frame decoding;
- `WebSocketActuatorSession`;
- deterministic mock actuator control;
- the Stage-1 LOAD CTRL user interface;
- the Stage-1 mock-control supervisor.

The real LAN discovery path is field-confirmed through the ESP32 advertisement and Viewer SCAN LAN operation.

The real WebSocket connection and HELLO qualification are not field-confirmed yet.

The active runtime entry point is `emonio_viewer.main_v0416:main`. It injects `server.app_v0416.create_app` into the base runtime.

## 3. Existing Responsibility Boundary

### 3.1 Discovery

`src/emonio_viewer/load_control/discovery.py`

- defines the mDNS service type;
- parses resolved mDNS advertisements;
- creates `ActuatorDescriptor` values;
- preserves `node_id`, location, device class, capabilities, and advertised `p_max`;
- provides deterministic mock discovery.

This file shall remain unchanged unless a failing Stage-2 test proves that a correction is required.

`src/emonio_viewer/load_control/discovery_zeroconf.py`

- performs Zeroconf/mDNS network discovery;
- resolves service records.

This file shall remain unchanged.

`src/emonio_viewer/load_control/lan_discovery.py`

- owns operator-triggered read-only LAN discovery;
- preserves the most recent discovery result.

This file shall remain unchanged unless a failing Stage-2 test proves that a correction is required.

### 3.2 Protocol

`src/emonio_viewer/load_control/protocol.py`

The existing decoder already performs strict HELLO schema validation.

For HELLO it requires exactly:

- `message_type`;
- `protocol_version`;
- `node_id`;
- `boot_id`;
- `device_class`;
- `capabilities`;
- `p_max`.

The existing protocol model already rejects:

- unsupported protocol versions;
- empty text identity fields;
- invalid capability container types;
- missing or extra `p_max` members;
- non-numeric `p_max` values;
- non-finite `p_max` values;
- `p_max <= 0` on any phase.

Stage 2 shall reuse this decoder. It shall not duplicate or weaken protocol parsing.

### 3.3 Real WebSocket transport

`src/emonio_viewer/load_control/session_websocket.py`

The existing transport already:

- opens the descriptor WebSocket location;
- accepts only `ws://` or `wss://` locations;
- uses explicit positive finite timeouts;
- requires the first application frame to be HELLO;
- clears retained HELLO data on disconnect;
- does not bind an actuator;
- does not authorize control;
- does not perform automatic reconnection.

Stage 2 shall reuse this transport.

A small transport change is permitted only to expose WebSocket-open and first-frame-receive as separate deterministic steps while preserving the existing `connect()` behavior for existing callers and tests.

### 3.4 Existing Stage-1 mock control

`src/emonio_viewer/load_control/service.py`

This service owns the deterministic Stage-1 mock-control path. It observes canonical measurement events and can produce mock COMMAND/ACK activity.

Stage 2 shall not convert this service into the real actuator qualification owner.

The Stage-1 mock path shall remain available for its existing tests and development functions.

## 4. Protected Scientific Boundary

The following production directories are protected from Stage-2 changes:

```text
src/emonio_viewer/acquisition/**
src/emonio_viewer/measurement/**
src/emonio_viewer/modbus/**
src/emonio_viewer/recording/**
src/emonio_viewer/scope/**
```

Stage 2 shall not change:

- canonical P signs;
- canonical Q signs;
- quadrant semantics;
- power-factor semantics;
- measurement validation;
- fixed-deadline acquisition;
- Emonio polling;
- Modbus transport;
- Modbus read-only behavior;
- register maps;
- decoder logic;
- recording semantics;
- CSV precision;
- SCOPE measurement semantics.

Final verification shall include deterministic diff evidence that no protected production file changed.

## 5. Stage-2 Architecture

Stage 2 shall add one independent qualification owner.

Approved new production file:

```text
src/emonio_viewer/load_control/qualification.py
```

Its responsibility is only:

```text
latest LAN discovery evidence
        +
explicit operator node selection
        |
        v
real WebSocket transport
        |
        v
first application frame = HELLO
        |
        v
strict discovery-to-HELLO comparison
        |
        v
QUALIFIED or REJECTED
```

The qualification owner shall not depend on:

- `MeasurementSample`;
- the acquisition coordinator;
- Modbus;
- recording;
- SCOPE;
- the load-request controller;
- `LoadControlSupervisor`;
- COMMAND generation;
- ACK handling.

The qualification owner shall not expose a `send_command()` method.

## 6. Qualification State Model

Stage 2 shall use a dedicated connection-qualification state. It shall not reuse measurement-health states or the Stage-1 control-supervisor state.

Required states:

- `IDLE`
- `DISCOVERED`
- `CONNECTING`
- `HELLO_WAIT`
- `QUALIFIED`
- `REJECTED`
- `DISCONNECTED`

### 6.1 State definitions

`IDLE`

No LAN actuator is selected for Stage-2 qualification. No Stage-2 WebSocket is open.

`DISCOVERED`

The operator explicitly selected exactly one actuator from the most recent successful LAN discovery result. No WebSocket is open yet.

`CONNECTING`

The Viewer is opening the WebSocket location stored in the selected descriptor.

`HELLO_WAIT`

The WebSocket is open. The Viewer is waiting for the first application frame.

`QUALIFIED`

The first application frame was HELLO and all Stage-2 checks passed.

`REJECTED`

Connection or HELLO qualification failed. No qualification survives. The Stage-2 socket shall be closed.

`DISCONNECTED`

A previously opened Stage-2 WebSocket is no longer connected. No qualification survives.

The initial state shall be `IDLE`.

## 7. Operator Selection Rules

The operator shall explicitly select one actuator returned by the most recent successful LAN scan.

The browser shall submit only the selected `node_id` as selection authority.

```json
{
  "node_id": "ARI-LOAD-001"
}
```

The backend shall resolve this value against `LanActuatorDiscoveryService.last_result`.

The backend shall use the exact stored descriptor location. The browser shall not provide an IP address, port, path, or replacement WebSocket URL.

The DHCP address is a transport locator only. It is not actuator identity.

Selection shall fail if:

- the node is not in the latest successful scan result;
- more than one descriptor in that result has the selected `node_id`;
- a Stage-2 WebSocket is already open.

The operator shall disconnect before selecting another actuator.

A later LAN scan shall not replace, redirect, or requalify an already open Stage-2 WebSocket. A new advertisement becomes relevant only after the operator starts a new qualification operation.

There shall be no automatic selection of the first scan result.

## 8. Expected HELLO Schema

```json
{
  "message_type": "HELLO",
  "protocol_version": 1,
  "node_id": "ARI-LOAD-001",
  "boot_id": "BOOT-...",
  "device_class": "ARI_LOAD_ACTUATOR",
  "capabilities": [
    "ACTIVE_LOAD_CONTROL"
  ],
  "p_max": {
    "a": 1000.0,
    "b": 1000.0,
    "c": 1000.0
  }
}
```

No extra HELLO fields are expected in protocol V1.

The existing strict decoder shall continue to reject extra fields.

## 9. HELLO Qualification Rules

Protocol decoding shall occur first.

Only a successfully decoded `HelloFrame` can enter discovery comparison.

The qualification owner shall then require all of these conditions:

1. `hello.protocol_version == 1`.
2. `hello.node_id == selected_descriptor.node_id`.
3. `hello.boot_id` is non-empty.
4. `hello.device_class == "ARI_LOAD_ACTUATOR"`.
5. `"ACTIVE_LOAD_CONTROL"` is present in `hello.capabilities`.
6. `hello.p_max.a` is finite and greater than zero.
7. `hello.p_max.b` is finite and greater than zero.
8. `hello.p_max.c` is finite and greater than zero.
9. `hello.p_max.a == selected_descriptor.p_max.a`.
10. `hello.p_max.b == selected_descriptor.p_max.b`.
11. `hello.p_max.c == selected_descriptor.p_max.c`.

`p_max` comparison shall use exact numeric equality after both representations pass finite-number validation.

Stage 2 shall not use a tolerance.

Stage 2 shall not clamp, repair, replace, or default invalid HELLO data.

Stage 2 shall not copy discovery identity into a mismatched HELLO.

Any mismatch shall cause `REJECTED` and shall close the Stage-2 WebSocket.

## 10. Qualified Identity

The qualified active connection instance is:

```text
node_id + current boot_id
```

The qualified record shall preserve:

- selected discovery descriptor;
- HELLO `node_id`;
- HELLO `boot_id`;
- HELLO protocol version;
- HELLO device class;
- HELLO capabilities;
- HELLO `p_max`.

The IP address shall not be part of identity.

The WebSocket URL may be shown as connection evidence, but it remains a locator only.

## 11. ESP32 Reboot Rule

The same `node_id` after ESP32 reboot is expected.

A changed `boot_id` defines a new actuator boot instance.

Qualification for an old boot instance shall never be reused for a new boot instance.

After reconnect, the Viewer shall receive and qualify a new HELLO before it can display `QUALIFIED` again.

## 12. Disconnect Detection and Invalidation

Any WebSocket disconnect shall invalidate Stage-2 qualification.

After successful HELLO qualification, the qualification owner shall keep one read-only transport watcher active for that WebSocket. Its only Stage-2 purpose is to observe remote close or transport error.

The watcher shall not send any frame.

If later application frames arrive after HELLO, Stage 2 shall not treat them as control evidence and shall not use them to grant additional authority. The watcher may consume and ignore them while it continues to observe the connection. Stage 2 shall not implement ACK or STATUS semantics.

On remote close, local disconnect, transport error, or application cleanup, the qualification owner shall clear:

- retained HELLO;
- retained qualified boot instance;
- any pending HELLO task;
- the transport watcher;
- any transient state that could imply current qualification.

The state shall become `DISCONNECTED` if a Stage-2 WebSocket was previously opened.

External control shall remain `DISABLED`.

Stage 2 shall have no command replay queue and no outstanding control command.

No previous nonzero request shall be restored or recreated.

## 13. Reconnection Rule

Stage 2 shall not automatically reconnect.

The operator shall initiate every new connection qualification.

Every new connection shall require a new first-frame HELLO.

No cached HELLO shall satisfy a later connection.

No reconnect action shall send COMMAND.

## 14. WebSocket Transport State Exposure

The current `WebSocketActuatorSession.connect()` combines socket opening and first-frame HELLO reception.

Stage 2 requires explicit `CONNECTING` and `HELLO_WAIT` evidence.

The minimal approved transport change is:

- preserve existing `connect()` behavior for compatibility;
- add a small two-step interface that opens the WebSocket first and receives the first application frame second;
- keep timeout validation and cleanup in `session_websocket.py`;
- keep the no-auto-reconnect rule.

Required Stage-2 transition order:

```text
IDLE
  -> DISCOVERED
  -> CONNECTING
  -> HELLO_WAIT
  -> QUALIFIED
```

Any failure after selection shall transition to `REJECTED` and close the Stage-2 socket.

A later transport loss from `QUALIFIED` shall transition to `DISCONNECTED`.

## 15. Timeouts

The qualification owner shall use explicit finite positive timeouts.

Production defaults:

- WebSocket connect timeout: `3.0 s`;
- first HELLO receive timeout: `2.0 s`.

These values apply only to external actuator qualification. They shall not modify any Emonio acquisition timeout.

Tests may inject smaller deterministic values.

A timeout shall reject the qualification. It shall not start an automatic retry.

## 16. API Design

Stage 2 shall add:

```text
POST /api/v1/load-control/lan-qualification/connect
GET  /api/v1/load-control/lan-qualification/status
POST /api/v1/load-control/lan-qualification/disconnect
```

### 16.1 Connect

Request:

```json
{
  "node_id": "ARI-LOAD-001"
}
```

Required operation order:

1. validate explicit `node_id` input;
2. resolve exactly one descriptor from the latest LAN discovery result;
3. set `DISCOVERED`;
4. set `CONNECTING`;
5. open the descriptor WebSocket;
6. set `HELLO_WAIT`;
7. receive the first application frame;
8. decode and qualify HELLO;
9. set `QUALIFIED` or `REJECTED`;
10. return Stage-2 status.

This endpoint shall not call the existing binding API.

This endpoint shall not call the existing enable API.

This endpoint shall not send COMMAND.

### 16.2 Status

Before selection, status shall report:

```json
{
  "state": "IDLE",
  "connected": false,
  "hello_qualified": false
}
```

A qualified status shall expose at least:

```json
{
  "state": "QUALIFIED",
  "connected": true,
  "hello_qualified": true,
  "node_id": "ARI-LOAD-001",
  "boot_id": "BOOT-...",
  "protocol_version": 1,
  "device_class": "ARI_LOAD_ACTUATOR",
  "capabilities": ["ACTIVE_LOAD_CONTROL"],
  "p_max": {
    "a": 1000.0,
    "b": 1000.0,
    "c": 1000.0
  },
  "location": "ws://192.168.1.141:8080/load-control",
  "last_error": null
}
```

`location` is connection evidence only. It is not identity.

For non-qualified states, unqualified HELLO identity fields shall be `null`. Invalid HELLO values shall not be presented as qualified values.

The selected discovery descriptor may be reported separately from qualified HELLO identity.

### 16.3 Disconnect

The endpoint shall close the Stage-2 WebSocket and clear qualification.

It shall not send a safe COMMAND because Stage 2 never obtains command authority.

## 17. Application Wiring

The active v0.4.19 runtime uses `server/app_v0416.py` for LOAD CTRL integration.

Stage 2 shall wire the qualification owner through this compatibility application layer.

Expected changes:

- add one dedicated AppKey in `src/emonio_viewer/server/keys.py`;
- construct the qualification owner in `server/app_v0416.py` from the existing LAN discovery service;
- close it during application cleanup;
- expose it through `server/load_control_api.py`.

`src/emonio_viewer/main.py` shall not change.

`src/emonio_viewer/main_v0416.py` shall not change unless a failing implementation test proves that wiring cannot be completed through `app_v0416.py` alone. Any such scope expansion requires explicit review before modification.

## 18. UI Design

The LOAD CTRL panel shall identify Stage 2 accurately.

Approved wording:

```text
STAGE 2 · REAL WEBSOCKET HELLO QUALIFICATION · CONTROL DISABLED
```

The existing read-only LAN scan shall remain.

Each discovered actuator card shall provide an explicit action such as:

```text
SELECT / QUALIFY
```

There shall be no default selection.

The selected LAN actuator shall not populate or modify the existing mock binding automatically.

The Stage-2 view shall show:

- connection state;
- `CONNECTED` only while the Stage-2 WebSocket is open;
- `HELLO QUALIFIED` only after every qualification check passes;
- `node_id`;
- `boot_id`;
- protocol version;
- device class;
- required capability;
- advertised test limits;
- WebSocket locator as connection evidence;
- last qualification error when present.

External control shall still show `DISABLED`.

The Stage-2 selection and qualification action shall not invoke:

- save binding;
- enable external control;
- a control-demand calculation;
- COMMAND transmission.

## 19. Scientific Wording Correction

Current text:

```text
Physical max: A 1000.0 W · B 1000.0 W · C 1000.0 W
```

Approved replacement:

```text
Advertised test limit: A 1000.0 W · B 1000.0 W · C 1000.0 W
```

The Viewer shall not describe these values as physical ratings, measured power, or applied electrical power.

They are advertised protocol test limits.

## 20. COMMAND Prohibition

Stage 2 shall not send a COMMAND frame under any condition.

This applies to:

- successful qualification;
- rejected qualification;
- disconnect;
- reconnect;
- timeout;
- ESP32 reboot;
- repeated LAN scans;
- UI refresh;
- transport watcher activity;
- application shutdown.

Automated tests shall assert that the fake WebSocket sent-frame list remains empty for successful qualification, rejected qualification, disconnect, and connection-loss scenarios.

## 21. Error Handling

Stage 2 shall fail closed.

These conditions shall reject qualification:

- selected node missing from the latest successful discovery result;
- duplicate selected node IDs in that result;
- another Stage-2 connection already open;
- WebSocket open failure;
- WebSocket connect timeout;
- HELLO receive timeout;
- binary first application frame;
- malformed JSON;
- first frame not HELLO;
- protocol mismatch;
- node mismatch;
- empty boot ID;
- device-class mismatch;
- missing required capability;
- invalid `p_max`;
- discovery/HELLO `p_max` mismatch.

The qualification owner shall retain one concise `last_error` for operator evidence.

A rejection shall not modify Emonio measurement state.

## 22. Test-First Requirements

Tests shall be added before production behavior changes.

Required coverage:

1. valid HELLO qualifies;
2. HELLO must be the first application frame;
3. wrong `message_type` rejects;
4. wrong `protocol_version` rejects;
5. wrong `node_id` rejects;
6. empty `boot_id` rejects;
7. wrong `device_class` rejects;
8. missing `ACTIVE_LOAD_CONTROL` capability rejects;
9. missing `p_max` rejects;
10. non-finite `p_max` rejects;
11. `p_max <= 0` rejects;
12. discovery/HELLO `p_max` mismatch rejects;
13. WebSocket disconnect invalidates qualification;
14. remote close invalidates qualification;
15. reconnect requires a new HELLO;
16. changed `boot_id` creates a new actuator boot instance;
17. initial state is `IDLE`;
18. no automatic actuator selection;
19. duplicate discovered `node_id` selection rejects as ambiguous;
20. no automatic binding;
21. no automatic external-control enable;
22. no COMMAND is sent during successful qualification;
23. no COMMAND is sent during rejected qualification;
24. no COMMAND is sent during disconnect or connection loss;
25. later application frames do not grant Stage-2 control authority;
26. Emonio protected production files remain unchanged.

Existing Stage-1 tests shall remain in the complete test run.

The complete repository regression suite shall pass before a Stage-2 candidate is given to the operator for field testing.

## 23. Expected Test Boundary

Expected new or updated tests:

```text
tests/unit/test_load_control_hello_qualification.py
tests/unit/test_load_control_websocket_session.py
tests/unit/test_load_control_stage2_service.py
tests/integration/test_load_control_stage2_api.py
tests/browser/test_load_control_contract.py
```

Final verification shall also compare the candidate diff against the approved protected scientific boundary.

## 24. Expected Production Change Boundary

New production file:

```text
src/emonio_viewer/load_control/qualification.py
```

Expected small changes:

```text
src/emonio_viewer/load_control/session_websocket.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/load_control_api.py
src/emonio_viewer/server/app_v0416.py
frontend/js/load-control-api.js
frontend/js/load-control-ui.js
frontend/css/load-control/load-control.css
```

No other production file is in the approved Stage-2 scope.

If a failing test proves that another production file must change, implementation shall stop before that file is modified and the boundary shall be reviewed explicitly.

## 25. Stage-2 Field Acceptance Target

Automated tests cannot provide real ESP32 field evidence.

Field PASS shall not be claimed until the operator tests the candidate with the real ESP32.

Expected ESP32 serial evidence:

```text
[WS] Viewer connected
[WS] HELLO sent
```

Expected Viewer evidence:

```text
ARI-LOAD-001
CONNECTED
HELLO QUALIFIED
boot_id = BOOT-...
protocol = 1
device class = ARI_LOAD_ACTUATOR
capability = ACTIVE_LOAD_CONTROL
advertised test limits = 1000 / 1000 / 1000 W
```

External control shall still show:

```text
DISABLED
```

There shall be no ESP32 serial evidence of a received COMMAND during Stage 2.

## 26. Out of Scope

Stage 2 shall not implement:

- explicit real actuator binding to an Emonio source;
- control enable for the real actuator;
- COMMAND transmission;
- ACK reception;
- ACK sequence qualification;
- duplicate sequence qualification;
- out-of-order sequence qualification;
- command retry;
- command replay;
- automatic reconnect;
- MQTT;
- GPIO;
- PWM;
- relay control;
- MOSFET control;
- half-bridge control;
- physical load control;
- measured actuator power.

These items belong to later stages.

## 27. Stage-3 Gate

Stage 3 shall not start until Stage 2 is field-confirmed with the real ESP32.

Stage 3 may then design:

```text
explicit binding
-> controlled COMMAND
-> deterministic ACK
-> sequence / duplicate / out-of-order qualification
```

Stage 3 shall require a separate architecture review and explicit approval.
