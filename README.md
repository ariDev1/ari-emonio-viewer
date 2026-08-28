# ARI Emonio Viewer

ARI Emonio Viewer is a local Linux scientific measurement workstation for Emonio P3 devices. The trusted field baseline is **v0.3.3**, field-confirmed on four real Emonio devices. **v0.3.5 Candidate** is the current publication-preparation candidate. It preserves the v0.3.4 stability hardening and removes private deployment identity from the public source distribution. The SCOPE path uses the Emonio web login and WebSocket interface. It does not replace, modify, or derive the canonical Modbus measurement path.


## License and public-source model

ARI Emonio Viewer is **source-available** software. Natural persons may use it free of charge under the included `LICENSE`, including use in their own commercial activity. Use by a company or another separate commercial legal entity requires a separate commercial license. This is not an OSI-approved open-source license.

Security and contribution rules are documented in [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md). Do not commit Emonio passwords, device-number credentials, authentication cookies, local configuration, recordings, or private network information.

## Verified device contract

The current verified hardware/firmware contract is:

- Emonio P3
- firmware `3.0.79-release`
- TCP port `502`
- function `0x03` holding-register reads only
- IEEE-754 binary32 with low 16-bit word first (`CDAB`)
- register offset `6 = VAR/Q`
- register offset `8 = VA/S`
- phase bases `A=0`, `B=100`, `C=200`, `TOTAL=300`

The production acquisition module contains no register-write API.


## Current-sensor configuration evidence

The viewer can read these raw Emonio configuration keys on demand:

```text
ct_type
ct_voltage
ct_range
ct_invert
ct_didt
```

The backend uses one Telnet session on port `23` and sends only the five field-qualified read commands `conf ct_type`, `conf ct_voltage`, `conf ct_range`, `conf ct_invert`, and `conf ct_didt`. The integrated reader has no arbitrary CLI command input and no configuration-write command path.

The `Current sensor configuration` controls are collapsed under `Diagnostics -> Device Evidence` during normal operation. The operator enters the Emonio admin password only when an explicit CT configuration refresh is required. The password is sent only to the localhost backend for that read request. It is not added to TOML configuration, runtime evidence, recording files, or CT evidence responses. The backend keeps only the last successfully observed raw CT values and observation time in memory. A later Telnet read failure does not delete that successful evidence.

The viewer reports the source as `EMONIO_TELNET_CONF`, the interpretation as `RAW_DEVICE_CONFIGURATION`, and the physical orientation status as `NOT_VERIFIED`. The compact diagnostics state is `CT CONFIG: NOT READ`, `CT CONFIG: OBSERVED`, or `CT CONFIG: READ ERROR`. A read error is diagnostic only and does not affect Modbus measurements or recording. The viewer does not infer CT orientation from P or Q. It does not silently change signs. It does not map `ct_type`, `ct_voltage`, `ct_range`, or `ct_didt` to web-UI labels without qualified mapping evidence.

Field evidence from one qualified Emonio P3 device, firmware `3.0.79-release`, is:

```text
ct_type=0
ct_voltage=0
ct_range=3
ct_invert=7
ct_didt=0
```

These values match the manual Telnet results and the standalone automated v0.3.0 probe. This agreement proves device configuration reporting. It does not prove that the installed physical CT orientation is correct.

## Emonio SCOPE waveform subsystem

v0.3.5 Candidate preserves the separate read-only waveform path for the Emonio native SCOPE data and the v0.3.2 compatibility behavior. The browser still communicates only with the localhost ARI backend. The backend performs the authenticated Emonio web/SCOPE sequence and receives the waveform frames. The SCOPE subsystem does not import or call the Modbus, canonical measurement, recording, or CT-evidence implementations.

The field-qualified firmware `3.0.79-release` SCOPE contract is:

```text
operator USER + PASS
-> POST /login
-> GET /
-> GET /scope
-> WebSocket /ws
-> send literal text: scope
-> receive metadata phases 0..2 and waveform channels 0..5
```

Three real Emonio P3 devices were each exercised for 20 consecutive captures. All 60 captures agreed on the scientific structure below, while bytes 0..2 were stable per device but different between devices. The prefix is therefore observational evidence only and is not a validity gate.

```text
channels                 0,1,2,3,4,5
samples per channel      232
frame bytes              932
capture axis             35.6 ms
derived sample rate      6488.764045 Hz
non-finite samples       0
observed prefix device 1 e5d200
observed prefix device 2 810400
observed prefix device 3 e90f00
```

The field-qualified channel map is:

```text
CH0  Phase A current
CH1  Phase A voltage
CH2  Phase B current
CH3  Phase B voltage
CH4  Phase C current
CH5  Phase C voltage
```

Bytes 0..2 of every binary frame are preserved and exposed as `PREFIX ... · OBSERVED`. Their meaning is not inferred. Byte 3 remains the channel identifier.

The derived sample rate is calculated from the Emonio-reported capture duration and the 232 received sample positions. It is display/evidence metadata. It is not an independently measured ADC clock.

Open the `SCOPE` overlay drawer for the selected Emonio. Enter both the Emonio web username and password and select `START LIVE`. The password field is hidden. The operator can use `HOLD`, `LIVE`, and `STOP`, select `A`, `B`, `C`, or `ABC`, and select `U`, `I`, or `U+I`. The drawer shows the selected Emonio state and a compact list of all Emonios that currently own a CONNECTING, LIVE, or HOLD SCOPE session. Phase/signal view selections are kept separately for each Emonio in browser memory only. Switching the selected Emonio never stops another Emonio SCOPE session and never mixes captures between devices. Voltage and current use separate symmetric zero-centered display scales when they are shown together. The oscilloscope-style grid is display-only. The plot connects adjacent received measured vertices with straight segments only. It does not smooth, average, interpolate, resample, clamp, sign-correct, or synthesize waveform samples.

Scope credentials are runtime-only. They are not written to TOML, `remembered-devices.json`, recordings, measurement logs, scope captures, browser `localStorage`, or browser `sessionStorage`. They are not returned by the local API. The backend does not retain the username or password after it establishes the authenticated remote SCOPE connection.

Each Emonio has independent SCOPE session state. `LIVE` requests one complete capture at a time and uses a minimum 1.009 s interval between request starts. `HOLD` stops new requests while keeping the last complete volatile capture visible. `STOP` closes the remote SCOPE session. An incomplete, structurally invalid, or non-finite capture fails closed and stops further LIVE requests for that session.

The SCOPE values and canonical Modbus values are separate scientific sources:

```text
EMONIO_WEBSOCKET_SCOPE     instantaneous waveform captures
Modbus/TCP canonical path  U/I/P/Q/S/PF/f/energy measurements
```

The viewer does not silently substitute one source for the other. SCOPE captures are not added to the normal measurement recording files.

## Linux setup

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
```

The public default configuration contains one disabled documentation device at `192.0.2.10`, which is an IANA TEST-NET address. It does not connect to a real device. For normal operation, enter the real Emonio IP address or hostname in the `EMONIO TARGET` field, or supply a local configuration with `--config`. Keep local configuration out of Git.

Enable the Modbus/TCP server on the Emonio before starting the viewer. The normal operator workflow does not require editing the TOML file. Enter the Emonio IP address or device name directly in the `EMONIO TARGET` field and select `CONNECT`. A plain device name such as `emonio-example` is resolved as the local mDNS name `emonio-example.local`. Runtime-added targets use the fixed read-only Modbus/TCP port `502` and a 2 s acquisition interval.

## Remembered devices

After a runtime target completes one full valid read-only A/B/C/TOTAL Modbus qualification cycle and is registered for live acquisition, v0.1.8 stores that device configuration in `config/remembered-devices.json`. On the next start, the viewer loads the fixed TOML configuration first and then adds remembered devices that do not duplicate a TOML device id or host. TOML devices remain authoritative.

The remembered-device file contains only the device id, name, host, Modbus port, unit id, poll interval, timeout, enabled state, and firmware-version field. It does not contain the Emonio Telnet password, CT configuration evidence, measurement values, recording data, or session notes. A failed target qualification does not create or modify a remembered-device entry. Registry writes use a temporary file, `fsync`, and atomic `os.replace`.

Deleting `config/remembered-devices.json` removes only the remembered runtime-device list. It does not modify `config/emonio-viewer.toml`, recordings, or measurement data.


## Development status

The trusted field baseline is **v0.3.3**. It is field-confirmed on four real Emonio devices, including independent per-device SCOPE operation. v0.3.4 remains the verified stability-hardening package from which **v0.3.5 Candidate** is derived. v0.3.5 changes publication identity, public examples, documentation, dependency declaration, and repository/release tooling only. It does not change canonical Modbus measurement science, SCOPE scientific interpretation, recording science, or structured CSS.

## Software acceptance

```bash
./tools/ari-emonio-acceptance.sh
```

The final software acceptance line is:

```text
ARI Emonio Viewer Acceptance: PASS
```

### Dependency security note

v0.3.5 changes the direct `aiohttp` requirement from `3.12.15` to `3.14.3` and declares the directly imported `yarl` package explicitly. The former aiohttp release has upstream security advisories fixed in later 3.14.x releases. This is a dependency-only publication hardening change. Exact clean-environment qualification of the `aiohttp==3.14.3` installation remains a required publication gate; do not treat a test run with another aiohttp version as proof of that exact dependency set.

### Deterministic release package

Create the qualified ARI release ZIP only with:

```bash
python3 tools/build-release.py
```

The tool writes the versioned ZIP and matching SHA-256 file below `dist/`. It uses a sorted file order, normalized ZIP timestamps, explicit executable modes, and a fixed exclusion policy for runtime and development debris. GitHub-generated source archives are convenience downloads and are not the qualified ARI release artifact.

Before the first public commit, stage the complete intended repository tree and run:

```bash
./tools/ari-emonio-publication-gate.sh
```

That gate scans the exact staged Git blobs. A passing gate does not replace the complete software acceptance suite or real-device qualification.

## Start the viewer

For normal Linux use, start the viewer from the extracted project directory with:

```bash
./start-emonio-viewer.sh
```

On the first start, the launcher creates a local `.venv` and installs the runtime dependencies. Later starts reuse that environment unless `pyproject.toml` changed. When `xdg-open` is available, the launcher opens the viewer after the local server responds. Stop the viewer with `Ctrl+C`.

To start without opening a browser:

```bash
./start-emonio-viewer.sh --no-browser
```

The direct command remains available after setup:

```bash
. .venv/bin/activate
emonio-viewer --config config/emonio-viewer.toml
```

Viewer address:

```text
http://127.0.0.1:8787
```

The server binds to localhost only. The browser does not connect to the Emonio directly. A target is accepted only after the backend completes one full read-only A/B/C/TOTAL acquisition cycle. A failed target does not replace the currently selected valid device.

## Measurement rules

- Signed P, Q, PF, and energy values are preserved.
- IRMS remains an unsigned RMS magnitude.
- Four-quadrant state is derived from the signed P/Q pair in the backend.
- No smoothing, interpolation, sign correction, gap filling, or automatic transport fallback is used.
- A failed acquisition never replaces the last valid sample with zeroes.
- Recording cadence is independent from acquisition cadence, but recording cannot be faster than acquisition.

## Canonical measurement history

v0.2.9 retains the canonical browser-session history fields `U(t)`, `I(t)`, `P(t)`, `Q(t)`, `S(t)`, `PF(t)`, and `f(t)` from the trusted v0.2.8 baseline. The browser still stores a fixed rolling 10-minute history per Emonio. The display window can show 30 s, 1 min, 2 min, 5 min, or 10 min of those exact stored samples. On wide workstations, the square four-quadrant P/Q plot and Measurement History share one primary science row. The active history plot and exact-sample inspector remain side by side. Diagnostics is a fixed overlay drawer that consumes zero scientific grid space while closed. Recording has an always-visible compact operator strip with selected Emonio, state, interval, RECORD, STOP, and MORE controls; detailed recording information and the optional session note remain in the Recording drawer. No additional Modbus read, measurement API, acquisition worker, recording data path, or history storage path was introduced.

The history window is exactly 10 minutes relative to the newest received canonical sample for each device. History is isolated by device id. A device switch shows only that device's browser-session history. Each exact browser sample identity, defined by the received `cycle_id` and exact `cycle_finished_utc` string, is stored once. A later acquisition process can reuse a cycle id after restart without causing a different timestamped cycle to be discarded. Samples older than the ten-minute window are removed from the browser buffer. History is not persisted to disk and starts again when the browser page is restarted.

The charts render discrete sample markers only for Phase A, Phase B, Phase C, and TOTAL. Marker x-coordinates use the parsed time coordinate derived from `cycle_finished_utc`. The browser also retains the exact received `cycle_finished_utc` string so sub-millisecond text precision is not lost by JavaScript date parsing. The browser history retains the canonical `vrms`, `irms`, `p`, `q`, `s`, `pf`, and `frequency` numeric values before presentation formatting. There are no connecting lines because the viewer must not imply values between acquisition cycles. There is no smoothing, averaging, interpolation, sign correction, gap filling, or measurement resampling.

`P(t)` and `Q(t)` keep the field-qualified symmetric zero-centered display scale derived from the largest observed absolute canonical value in the current device history. `U(t)`, `I(t)`, `S(t)`, `PF(t)`, and `f(t)` use the exact observed minimum and maximum across A/B/C/TOTAL in the current device history for display coordinates. Zero is not forced into these observed ranges. If all observed values are equal, the points are displayed at the vertical center while the axis reports that same value. These rules change display coordinates only and never clamp, correct, or alter stored measurement values. Axis and sample-time labels use UTC.

The Sample inspector is browser-only. The operator can click inside the active history plot. The viewer maps the pointer through the SVG screen transformation, converts only the horizontal plot coordinate to a target time, and selects the nearest real stored sample. Equal-distance ties select the earlier measured sample. After a real sample is selected, LEFT and RIGHT move only to the previous or next real stored sample in the existing device history. Stepping uses exact sample identity (`cycle_id` plus the exact received `cycle_finished_utc` string) and stored sample order. It does not calculate a time increment, interpolate, resample, average, synthesize, or wrap at the first or last sample. The same selected sample produces one vertical inspection cursor on the active metric plot. The readout shows the exact stored A/B/C/TOTAL canonical values with JavaScript round-trip number formatting instead of forcing four-decimal presentation rounding. It also shows device id, cycle id, quality, and the exact received `cycle_finished_utc` string. Selection state remains isolated by device.

## Recording

Sessions are written below `recordings/`. Each session has:

```text
session.json
measurements.csv
events.csv
```

Measurement rows are append-only while the session is active. Missing recording points are written as events, not as fabricated measurement rows.

Operator-facing measurement values use four decimal places in the browser and CSV output. All scientific calculations and validation use the full decoded IEEE-754 value before presentation rounding. For example, `P=5 W` and `Q=-3450 var` gives a non-zero low power factor near `0.0014`; P or Q is never rounded before PF consistency calculations.

## Real-device qualification

Software acceptance is not the final field gate. Before a build is treated as trusted, run it against a real Emonio P3 and collect at least 30 complete cycles. Require zero structural acquisition failures and zero reconnects. Compare at least one browser snapshot with the Emonio native Meter page for U, I, P, Q, S, PF, and frequency. Do not change validation limits to force agreement.

## Shutdown hardening

v0.1.8 changes shutdown ownership only. The acquisition coordinator now sets the shared stop event, shuts down and closes all owned Modbus sockets, and then joins acquisition workers. `ReadOnlyModbusClient.close()` uses `shutdown(SHUT_RDWR)` before `close()` so a worker blocked in a socket receive is interrupted instead of waiting for the configured read timeout. The client keeps a local socket reference for an in-progress Modbus response so concurrent shutdown cannot expose an internal socket-state assertion. Modbus read timeouts, register access, decoding, signed values, recording, and CT evidence behavior are unchanged.

The deterministic software regression uses a real local TCP socket that withholds the Modbus response. The v0.1.7 ordering exceeded a 0.75 s join bound and reported a live worker. The v0.1.8 shutdown path passes the same controlled test without reducing the configured 5 s Modbus timeout. Real-device Ctrl+C timing remains a field-acceptance item for this Candidate.

## WebSocket disconnect handling

v0.1.9 treats `aiohttp.client_exceptions.ClientConnectionResetError` raised by `WebSocketResponse.send_json()` as a normal browser-client disconnect. The handler stops sending to that client and unsubscribes it from the runtime event bus. The exception boundary is limited to this proven disconnect exception; unrelated send failures are not hidden. Measurement acquisition, Modbus transport, recording, CT evidence, and the v0.1.8 shutdown changes are unchanged by this correction.
