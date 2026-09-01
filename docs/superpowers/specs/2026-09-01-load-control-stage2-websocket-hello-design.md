# ARI Emonio Viewer Stage 2 Design

## Real WebSocket Connection and HELLO Qualification

Date: 2026-09-01

Target branch: `testing`

Viewer baseline: ARI Emonio Viewer v0.4.19

Audit branch HEAD before this design document: `4e66d549b813ac3a1bdcacf413d6c41721b2bf1e`

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

The current testing branch already contains these independent parts:

- read-only mDNS discovery;
- an `ActuatorDescriptor` model;
- strict protocol V1 frame decoding;
- a `WebSocketActuatorSession` transport;
- deterministic mock actuator control;
- the Stage-1 LOAD CTRL user interface;
- the Stage-1 mock-control supervisor.

The real LAN discovery path is field-confirmed through the ESP32 advertisement and Viewer SCAN LAN operation.

The real WebSocket connection and HELLO qualification are not field-confirmed yet.

The current active runtime entry point is `emonio_viewer.main_v0416:main`. This runtime injects `server.app_v0416.create_app` into the base runtime.

## 3. Existing Files and Responsibilities

### 3.1 Discovery

`src/emonio_viewer/load_control/discovery.py`

Responsibilities:

- define the mDNS service type;
- parse resolved mDNS advertisements;
- create `ActuatorDescriptor` objects;
- preserve `node_id`, location, device class, capabilities, and advertised `p_max` values;
- provide the deterministic mock discovery source.

This file shall remain unchanged unless a failing test proves that Stage 2 requires a correction.

`src/emonio_viewer/load_control/discovery_zeroconf.py`

Responsibilities:

- perform the Zeroconf/mDNS network scan;
- resolve service records.

This file shall remain unchanged.

`src/emonio_viewer/load_control/lan_discovery.py`

Responsibilities:

- own the operator-triggered read-only LAN discovery operation;
- preserve the most recent discovery result.

This file shall remain unchanged unless a failing test proves that Stage 2 requires a correction.

### 3.2 Protocol

`src/emonio_viewer/load_control/protocol.py`

The current decoder already performs strict HELLO schema validation.

For HELLO it already requires the exact field set:

- `message_type`;
- `protocol_version`;
- `node_id`;
- `boot_id`;
- `device_class`;
- `capabilities`;
- `p_max`.

The current protocol model already rejects:

- unsupported protocol versions;
- empty text identity fields;
- invalid capability container types;
- missing or extra `p_max` members;
- non-numeric `p_max` values;
- non-finite `p_max` values;
- `p_max <= 0` on any phase.

Stage 2 shall reuse this decoder. Stage 2 shall not duplicate or weaken protocol parsing.

### 3.3 Real WebSocket transport

`src/emonio_viewer/load_control/session_websocket.py`

The transport already:

- opens the descriptor WebSocket location;
- accepts only `ws://` or `wss://` locations;
- uses explicit positive finite timeouts;
- requires the first application frame to be HELLO;
- clears the retained HELLO on disconnect;
- does not bind an actuator;
- does not authorize control;
- does not perform automatic reconnection.

Stage 2 shall reuse this transport.

A small transport change is permitted only to expose the state transition between TCP/WebSocket connection completion and HELLO reception. The existing public behavior shall remain compatible with existing tests.

### 3.4 Existing Stage-1 mock control

`src/emonio_viewer/load_control/service.py`

This service owns the Stage-1 deterministic mock-control path. It also observes canonical measurement events and can produce mock COMMAND/ACK control activity.

Stage 2 shall not convert this service into the real actuator owner.

The existing mock path shall remain available for its existing tests and development functions.

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

The final implementation verification shall include a source-diff gate that confirms that no protected production file changed.

## 5. Stage-2 Architecture

Stage 2 shall add one independent qualification owner.

Recommended production file:

```text
src/emonio_viewer/load_control/qualification.py
```

The qualification owner shall have one purpose:

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
strict HELLO comparison
        |
        v
QUALIFIED or REJECTED
```

The qualification owner shall not depend on:

- `MeasurementSample`;
- the Emonio acquisition coordinator;
- the Modbus package;
- the recording package;
- SCOPE;
- the load-request controller;
- `LoadControlSupervisor`;
- COMMAND generation;
- ACK handling.

This separation prevents Stage 2 from obtaining control authority.

## 6. Qualification State Model

Stage 2 shall use a dedicated connection-qualification state. It shall not reuse measurement-health states and shall not reuse the Stage-1 control supervisor state as the qualification authority.

Required states:

- `DISCOVERED`
- `CONNECTING`
- `HELLO_WAIT`
- `QUALIFIED`
- `REJECTED`
- `DISCONNECTED`

### 6.1 State meaning

`DISCOVERED`

The operator selected one actuator from the latest LAN discovery result. No WebSocket connection is qualified.

`CONNECTING`

The Viewer is opening the WebSocket location from the selected descriptor.

`HELLO_WAIT`

The WebSocket transport is open. The Viewer is waiting for the first application frame.

`QUALIFIED`

The first application frame was a valid HELLO and all Stage-2 discovery-to-HELLO checks passed.

`REJECTED`

A connection or HELLO qualification requirement failed. No qualification survives.

`DISCONNECTED`

A previously open or qualified WebSocket is no longer connected. No qualification survives.

### 6.2 Initial state

Before an operator selects a LAN actuator, there is no Stage-2 selected actuator and no qualified connection.

The UI shall not imply that the first discovery result is selected.

## 7. Operator Selection Rules

The operator shall explicitly select one actuator returned by the most recent successful LAN scan.

The browser shall submit only the selected `node_id` as selection authority.

Example request:

```json
{
  "node_id": "ARI-LOAD-001"
}
```

The backend shall resolve this `node_id` against `LanActuatorDiscoveryService.last_result`.

The backend shall use the exact stored descriptor location. The browser shall not provide an IP address, port, path, or replacement WebSocket URL.

The DHCP address is a transport locator only. It is not actuator identity.

If the selected `node_id` is not in the latest discovery result, the connection request shall fail.

If the latest discovery result contains more than one descriptor with the selected `node_id`, the connection request shall fail as ambiguous. Stage 2 shall not choose one automatically.

If a Stage-2 connection is already open, another selection request shall fail. The operator shall disconnect first. Stage 2 shall not replace a connection automatically.

A new LAN scan shall not replace or redirect an already open qualified WebSocket. A changed advertisement becomes relevant only after the operator performs a new connection qualification.

## 8. HELLO Schema

The expected ESP32 HELLO application frame is:

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

Only a successfully decoded `HelloFrame` can enter Stage-2 discovery comparison.

The Stage-2 qualification function shall then require all of these conditions:

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

The `p_max` comparison shall use exact numeric equality after both representations have passed finite-number validation.

Stage 2 shall not use a tolerance.

Stage 2 shall not clamp a value.

Stage 2 shall not repair a value.

Stage 2 shall not substitute a default.

Stage 2 shall not copy discovery identity into a mismatched HELLO.

Any mismatch shall cause `REJECTED`.

## 10. Qualified Identity

The qualified active connection instance is identified by:

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
- HELLO `p_max` values.

The IP address shall not be part of actuator identity.

The WebSocket URL may be shown as connection evidence, but it shall remain a locator only.

## 11. ESP32 Reboot Rule

The same `node_id` after ESP32 reboot is expected.

A changed `boot_id` defines a new actuator boot instance.

Qualification for an old boot instance shall never be reused for a new boot instance.

After reconnect, the Viewer shall receive and qualify a new HELLO before it can display `QUALIFIED` again.

## 12. Disconnect Rule

Any WebSocket disconnect shall invalidate Stage-2 qualification immediately.

On disconnect, the qualification owner shall clear:

- retained HELLO;
- retained qualified boot instance;
- any pending HELLO-wait task;
- any Stage-2 transient connection state that could imply qualification.

The resulting state shall be `DISCONNECTED` for a connection that was opened previously.

External control shall remain `DISABLED`.

Stage 2 has no COMMAND authority, so it shall have no command replay queue and no outstanding control command.

No previous nonzero control request shall be restored or recreated by Stage 2.

## 13. Reconnection Rule

Stage 2 shall not automatically reconnect.

The operator shall initiate a new connection qualification.

Every new connection shall require a new first-frame HELLO qualification.

No cached HELLO shall satisfy a later connection.

No reconnect action shall send a COMMAND.

## 14. WebSocket Transport State Exposure

The current `WebSocketActuatorSession.connect()` method combines WebSocket opening and first-frame HELLO reception.

Stage 2 requires explicit `CONNECTING` and `HELLO_WAIT` evidence.

The preferred minimal transport change is:

- preserve the existing `connect()` method and its existing behavior for compatibility;
- add a small internal or additional two-step transport interface that can open the WebSocket first and receive the first application frame second;
- keep all timeout validation and cleanup rules in `session_websocket.py`;
- keep the existing no-auto-reconnect rule.

Existing `connect()` tests shall remain valid.

The Stage-2 qualification owner shall use the two-step path so that it can publish `HELLO_WAIT` only after the WebSocket is open.

## 15. Timeouts

The qualification owner shall use explicit finite positive connection and HELLO receive timeouts.

The production defaults shall be:

- WebSocket connect timeout: `3.0 s`;
- first HELLO receive timeout: `2.0 s`.

These values apply only to the external actuator qualification path. They shall not modify any Emonio acquisition timeout.

Tests may inject smaller deterministic timeout values.

A timeout shall cause qualification failure. It shall not cause automatic retry.

## 16. API Design

Stage 2 shall add these endpoints to the existing LOAD CTRL API surface:

```text
POST /api/v1/load-control/lan-qualification/connect
GET  /api/v1/load-control/lan-qualification/status
POST /api/v1/load-control/lan-qualification/disconnect
```

### 16.1 Connect

Request body:

```json
{
  "node_id": "ARI-LOAD-001"
}
```

The endpoint shall:

1. verify explicit `node_id` input;
2. resolve exactly one descriptor from the latest LAN discovery result;
3. transition to `DISCOVERED`;
4. open the descriptor WebSocket;
5. transition to `CONNECTING` and then `HELLO_WAIT`;
6. receive the first application frame;
7. perform strict HELLO qualification;
8. return the resulting Stage-2 status.

The endpoint shall not call the existing binding API.

The endpoint shall not call the existing enable API.

The endpoint shall not send COMMAND.

### 16.2 Status

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

For non-qualified states, identity fields that have not been qualified shall be `null` rather than copied from invalid HELLO data.

The selected discovery descriptor may be reported separately from qualified HELLO identity.

### 16.3 Disconnect

The endpoint shall close the Stage-2 WebSocket and clear qualification.

It shall not send a safe COMMAND because Stage 2 never obtains command authority.

## 17. Application Wiring

The active v0.4.19 runtime uses `server/app_v0416.py` for LOAD CTRL integration.

Stage 2 shall wire the new qualification owner through this compatibility application layer.

Expected small wiring changes:

- add a dedicated AppKey in `src/emonio_viewer/server/keys.py`;
- construct the qualification owner in `server/app_v0416.py` from the existing LAN discovery service;
- close it during application cleanup;
- expose it through `server/load_control_api.py`.

`src/emonio_viewer/main.py` shall not change.

`src/emonio_viewer/main_v0416.py` shall not change unless an implementation test proves that wiring cannot be completed through `app_v0416.py` alone.

## 18. UI Design

The LOAD CTRL panel shall change its stage description from Stage 1 to a Stage-2 description that remains scientifically precise.

Recommended header:

```text
STAGE 2 · REAL WEBSOCKET HELLO QUALIFICATION · CONTROL DISABLED
```

The LAN discovery section shall continue to use the existing read-only scan.

Each discovered LAN actuator card shall provide an explicit operator action such as:

```text
SELECT / QUALIFY
```

There shall be no default selection.

The selected actuator shall not populate or modify the existing mock binding automatically.

The Stage-2 qualification view shall show:

- connection state;
- `CONNECTED` only while the WebSocket is open;
- `HELLO QUALIFIED` only after all qualification checks pass;
- `node_id`;
- `boot_id`;
- protocol version;
- device class;
- required capability;
- advertised test limits;
- current WebSocket locator as connection evidence;
- last qualification error if present.

The Viewer shall continue to show external control as `DISABLED`.

The Stage-2 UI shall not invoke:

- save binding;
- enable external control;
- set a control demand;
- send COMMAND.

## 19. Scientific Wording Correction

The current UI text:

```text
Physical max: A 1000.0 W · B 1000.0 W · C 1000.0 W
```

is incorrect for the protocol test actuator.

It shall be replaced with:

```text
Advertised test limit: A 1000.0 W · B 1000.0 W · C 1000.0 W
```

The Viewer shall not describe these values as:

- physical ratings;
- measured power;
- applied electrical power.

They are advertised protocol test limits.

## 20. COMMAND Prohibition

Stage 2 shall not send a COMMAND frame under any condition.

This rule applies to:

- successful qualification;
- failed qualification;
- disconnect;
- reconnect;
- timeout;
- ESP32 reboot;
- repeated LAN scans;
- UI refresh;
- application shutdown.

The Stage-2 qualification owner shall not expose a `send_command()` method.

The automated test suite shall verify that the fake WebSocket sent-frame list remains empty after successful and rejected Stage-2 qualification scenarios.

## 21. Error Handling

Stage 2 shall fail closed.

Examples:

- selected node missing from latest discovery: reject;
- duplicate selected node IDs in latest discovery: reject;
- WebSocket open failure: reject;
- WebSocket timeout: reject;
- binary first application frame: reject;
- malformed JSON: reject;
- first frame not HELLO: reject;
- protocol mismatch: reject;
- node mismatch: reject;
- empty boot ID: reject;
- device-class mismatch: reject;
- capability missing: reject;
- invalid `p_max`: reject;
- discovery/HELLO `p_max` mismatch: reject.

The service shall retain a concise `last_error` suitable for operator evidence.

Invalid HELLO values shall not be presented as qualified values.

A rejection shall not modify Emonio measurement state.

## 22. Test-First Requirements

Tests shall be added before production behavior changes.

Required unit and integration coverage:

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
14. reconnect requires a new HELLO;
15. changed `boot_id` creates a new actuator boot instance;
16. no automatic actuator selection;
17. duplicate discovered `node_id` selection rejects as ambiguous;
18. no automatic binding;
19. no automatic external-control enable;
20. no COMMAND is sent during successful qualification;
21. no COMMAND is sent during rejected qualification;
22. no COMMAND is sent during disconnect;
23. Emonio measurement production files remain unchanged.

Existing Stage-1 tests shall remain in the complete test run.

The complete repository regression suite shall pass before a Stage-2 candidate is given to the operator for field testing.

## 23. Expected Test File Boundary

Expected new or updated tests:

```text
tests/unit/test_load_control_hello_qualification.py
tests/unit/test_load_control_websocket_session.py
tests/unit/test_load_control_stage2_service.py
tests/integration/test_load_control_stage2_api.py
tests/browser/test_load_control_contract.py
```

A protected-file contract test shall verify the agreed scientific production boundary by source diff or equivalent deterministic evidence.

## 24. Expected Production Change Boundary

Expected new production file:

```text
src/emonio_viewer/load_control/qualification.py
```

Expected small production changes:

```text
src/emonio_viewer/load_control/session_websocket.py
src/emonio_viewer/server/keys.py
src/emonio_viewer/server/load_control_api.py
src/emonio_viewer/server/app_v0416.py
frontend/js/load-control-api.js
frontend/js/load-control-ui.js
frontend/css/load-control/load-control.css
```

No other production file is part of the approved Stage-2 scope unless a failing test provides evidence that the boundary is insufficient.

Any required expansion of the production change boundary shall stop implementation and require explicit review before the additional file is changed.

## 25. Stage-2 Field Acceptance Target

The automated suite can qualify software behavior, but it cannot provide real ESP32 field evidence.

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

That work shall require a separate architecture review and approval.
