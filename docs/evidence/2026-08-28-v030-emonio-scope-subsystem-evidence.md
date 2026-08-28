# ARI Emonio Viewer v0.3.0 Emonio SCOPE Subsystem Evidence

## Release identity

- Candidate: `v0.3.0`
- Trusted field baseline: `v0.2.9`
- Trusted v0.2.9 ZIP SHA-256: `55dc84254d319e73019625a1a69c6e3205ebd3cf7cabfff5dcfe410376428b53`
- Qualification type: field-qualified SCOPE protocol evidence plus software integration verification
- Integrated field status: Candidate; real-device viewer confirmation is still required

The user field-confirmed v0.2.9 as working as expected before this Candidate was started. v0.2.9 therefore remains the trusted development baseline until the integrated v0.3.0 viewer is field-confirmed.

## Purpose

v0.3.0 adds an isolated read-only Emonio SCOPE subsystem. It displays real instantaneous Phase A/B/C voltage and current waveform captures from the Emonio web/WebSocket SCOPE interface.

The SCOPE subsystem does not replace, modify, or derive the canonical Modbus measurement model. It is a second scientific source with an explicit source identity:

```text
EMONIO_WEBSOCKET_SCOPE
```

## Real-device SCOPE protocol qualification

Before integration, standalone diagnostic probe `emonio_scope_ws_probe_v0_1_7.py` was run against a real Emonio P3 with firmware `3.0.79-release`.

The authenticated path was field-confirmed as:

```text
operator username + password
-> POST /login with multipart fields USER and PASS
-> HTTP 302 Location: /
-> GET /
-> HTTP 200
-> GET /scope
-> HTTP 200
-> WebSocket ws://<emonio>/ws
-> send literal text "scope"
-> receive only
```

The device returned `LOGIN_SESSION_KEY` during the successful authenticated run.

Twenty consecutive captures were complete. Every capture reported:

```text
channel order             0,1,2,3,4,5
metadata phases           0,1,2
samples per channel       232
frame bytes               932
header prefix             e5d200
capture duration          35.6 ms
axis-derived sample rate  6488.764045 Hz
non-finite samples        0
```

Qualification result:

```text
Captures complete:       20/20
Channel IDs 0..5:        PASS
Channel order stable:    PASS
232 samples/channel:     PASS
932 bytes/frame:         PASS
Header prefix e5d200:    PASS
Non-finite samples zero: PASS
Capture duration stable: PASS
Axis sample rate stable: PASS
Overall:                 QUALIFIED
```

The field-qualified channel map is:

```text
CH0 = Phase A current
CH1 = Phase A voltage
CH2 = Phase B current
CH3 = Phase B voltage
CH4 = Phase C current
CH5 = Phase C voltage
```

Each 932-byte binary frame is interpreted as:

```text
bytes 0..2    e5 d2 00
byte 3        channel id
bytes 4..931  232 little-endian IEEE-754 Float32 samples
```

The sample rate is derived from the Emonio-reported 35.6 ms capture axis and 232 sample positions:

```text
sample interval = 35.6 ms / 231
sample rate     = 231 / 0.0356 s
                = 6488.764045 Hz
```

This is an axis-derived rate. It is not claimed as an independently measured ADC clock.

## Integrated architecture

The trusted Modbus path remains:

```text
Emonio P3
-> WLAN
-> Modbus/TCP port 502
-> read-only acquisition
-> canonical measurement model
-> browser viewer / recorder
```

The new SCOPE path is separate:

```text
Emonio P3
-> authenticated HTTP web prerequisite
-> WebSocket /ws
-> fixed text request "scope"
-> strict waveform/metadata decoder
-> per-Emonio ScopeService
-> localhost scope API
-> browser SCOPE overlay drawer
```

The browser does not connect directly to the Emonio. Remote SCOPE communication is owned by the backend.

## Read-only and credential boundary

The SCOPE transport has one remote HTTP POST path:

```text
/login
```

The only remote WebSocket application payload is:

```text
scope
```

The operator must provide both username and password for each new SCOPE connection. The password input is hidden.

Credentials are not stored in:

- TOML;
- `remembered-devices.json`;
- recordings;
- measurement logs;
- scope captures;
- browser `localStorage`;
- browser `sessionStorage`.

Credentials are not part of SCOPE models or API responses. The backend client object has no username or password field after connection setup.

No Modbus write path was added. The SCOPE package does not import Modbus, canonical measurement, recording, or CT-evidence modules.

## Strict capture contract

The integrated decoder requires:

```text
6 binary channels exactly:       0,1,2,3,4,5
3 metadata phases exactly:       0,1,2
binary frame bytes exactly:      932
header prefix exactly:           e5d200
samples per channel exactly:     232
capture duration equal by phase: required
non-finite waveform samples:     rejected
```

The binary decoder preserves the received Float32 values and separately reports any non-finite count. A complete published capture rejects non-finite samples fail-closed. No value is replaced, clamped, or corrected.

If a LIVE capture is incomplete or invalid, the per-device SCOPE session enters `ERROR`, closes the remote client, and sends no further SCOPE request until the operator explicitly starts a new session.

## Per-device lifecycle

Scope state is isolated by Emonio device id:

```text
DISCONNECTED
CONNECTING
LIVE
HOLD
ERROR
```

`LIVE` sends one fixed `scope` request and waits for the full capture before another request can start. Request starts are separated by at least 1.009 s.

`HOLD` prevents new requests and keeps the last complete capture in volatile memory.

`STOP` closes the remote client and changes state to `DISCONNECTED`. The last complete capture can remain visible in volatile memory for inspection.

Viewer shutdown closes all active SCOPE sessions before the existing acquisition shutdown completes.

## Frontend scientific rendering

The SCOPE drawer is a fixed overlay. It does not consume scientific grid space.

Controls are:

```text
START LIVE | LIVE | HOLD | STOP
A | B | C | ABC
U | I | U+I
```

The SVG uses the exact received sample arrays. Sample x coordinates use sample index across the Emonio-reported capture duration.

Visible voltage traces share one symmetric zero-centered voltage scale. Visible current traces share one symmetric zero-centered current scale. In `U+I`, voltage and current remain on separate scales because the units differ.

Rendering connects adjacent measured vertices with straight polyline segments only. It does not smooth, average, interpolate, resample, fill gaps, sign-correct, or synthesize samples.

The drawer reports:

- SCOPE state;
- controlled Emonio;
- source;
- capture sequence;
- received UTC;
- capture duration;
- samples per channel;
- axis-derived sample rate.

SCOPE data is not written into normal measurement recording files in v0.3.0.

## TDD evidence

Every production subsystem was started from failing tests.

RED -> GREEN sequence:

1. Protocol/model tests failed because `emonio_viewer.scope` did not exist. The strict field-qualified model and decoder made them pass.
2. Client tests failed because no authenticated SCOPE client existed. The exact login, prerequisite GET, WebSocket, and fixed `scope` request made them pass.
3. Service tests failed because per-device LIVE/HOLD/STOP ownership did not exist. The isolated `ScopeService` made them pass.
4. API tests failed because the local application did not accept a SCOPE service or expose SCOPE routes. Minimal server integration made them pass.
5. Frontend tests failed because `scope.js`, `scope.css`, controls, and rendering did not exist. The overlay implementation made them pass.
6. Release identity test failed while the package still reported `0.2.9`. The synchronized `0.3.0` identity made it pass.
7. Pre-package scientific review added a failing test for a non-finite waveform inside an otherwise structurally complete capture. `build_capture()` now rejects that capture fail-closed while the raw frame decoder still preserves and reports the received values.

## Deterministic workstation geometry comparison

The trusted v0.2.9 HTML/CSS and the v0.3.0 Candidate HTML/CSS were loaded at a `1920 x 1033` Chromium viewport.

With the SCOPE drawer closed, baseline and Candidate geometry were identical:

```text
document/body viewport           1920 x 1033
status row                       1884 x 48
active target row                1884 x 42
phase row                        1884 x 86
science workspace                1884 x 781
P/Q SVG                          442.796875 x 442.796875
P/Q aspect ratio                 1.0
history panel                    1417.203125 x 781
active history plot              1031.203125 x 600.5625
exact sample inspector           360 x 621.5625
recording strip                  1884 x 40
page scroll                      none
```

With the SCOPE drawer open, the scientific workspace, P/Q plot, history panel, and active history plot retained the same coordinates and dimensions. The SCOPE drawer itself measured approximately `1100 x 1017 px`, and its waveform plot measured approximately `1076 x 538 px`.

This is deterministic software geometry evidence. Integrated real-workstation confirmation is still required.

## Source-isolation audit

A recursive SHA-256 source-tree comparison against trusted v0.2.9 confirms that these existing scientific directories are byte-identical after cache artifacts are excluded:

```text
src/emonio_viewer/modbus             IDENTICAL
src/emonio_viewer/acquisition        IDENTICAL
src/emonio_viewer/measurement        IDENTICAL
src/emonio_viewer/recording          IDENTICAL
src/emonio_viewer/device_evidence    IDENTICAL
src/emonio_viewer/config             IDENTICAL
src/emonio_viewer/runtime            IDENTICAL
src/emonio_viewer/diagnostics        IDENTICAL
```

Existing backend changes are limited to release identity, main shutdown/service construction, and local server SCOPE route injection. All remote SCOPE acquisition and parsing logic lives in the new `src/emonio_viewer/scope/` package.

## Software acceptance

Fresh source-tree acceptance after the final non-finite fail-closed change and documentation update is:

```text
Unit:                99 PASS
Integration:         46 PASS
Frontend contract:   84 PASS
Read-only gate:       3 PASS
Python compilation:   PASS
Scientific sign path: PASS

ARI Emonio Viewer Acceptance: PASS
```

The exact packaged ZIP must reproduce this same acceptance from a fresh extraction before delivery. No integrated field-acceptance claim is made by this document before the user tests v0.3.0 on the real Emonio workstation.

## Integrated field acceptance required

v0.2.9 remains the trusted baseline until v0.3.0 is field-confirmed.

The integrated field test should confirm:

- normal Modbus measurements remain correct;
- recording ownership remains per Emonio;
- selectable history windows and exact sample stepping remain correct;
- opening SCOPE does not move or resize the scientific workspace;
- operator must enter both Emonio username and password;
- `START LIVE` reaches `LIVE` and shows real waveforms;
- `A/B/C/ABC` selection is correct;
- `U/I/U+I` selection is correct;
- capture evidence reports 232 samples/channel and 35.6 ms on the qualified device;
- HOLD stops new captures while keeping the last complete capture visible;
- LIVE resumes new captures;
- STOP closes the SCOPE session;
- device switching preserves per-device SCOPE ownership and state;
- failed/incomplete SCOPE acquisition does not affect Modbus acquisition or recording;
- fullscreen workstation use remains zero-scroll;
- P/Q remains exactly square.
