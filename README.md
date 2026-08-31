# ARI Emonio Viewer

Engineering viewer for Emonio P3 electrical measurements on Linux.

Current development branch: `testing`  
Current version: `0.4.16`  
Tested device firmware: `3.0.79-release`

The Viewer keeps the canonical Modbus measurement path separate from auxiliary device evidence and SCOPE waveform acquisition.

## Measurement and acquisition paths

- Modbus/TCP is read-only.
- One runtime owner controls each Modbus/TCP client.
- Canonical measurements are acquired for Phase A, B, C, and TOTAL.
- Canonical quantities are U, I, P, Q, S, PF, frequency, and energy.
- Signed P and Q preserve four-quadrant behavior.
- Canonical samples keep the exact cycle ID and `cycle_finished_utc` timestamp.
- Auxiliary Modbus evidence reads occur only at canonical cycle boundaries.
- Reset-on-read MIN/MAX register ranges are not read.
- Read-only device evidence includes KWH IN/OUT, CONNECTED A/B/C, ERROR, and WARNING.
- CT configuration evidence is read through a separate read-only Telnet path.
- SCOPE waveform acquisition is separate from the canonical Modbus measurement path.

## Scientific invariants

The Viewer does not modify measured values to improve appearance or continuity.

- No Modbus write path.
- No smoothing.
- No averaging.
- No interpolation.
- No resampling.
- No gap filling.
- No synthetic samples.
- No sign correction.
- No waveform reconstruction.
- Invalid or non-finite SCOPE captures fail closed.
- SCOPE-derived instantaneous power does not replace canonical Modbus P.
- Browser history is not the recording authority.
- Credentials are runtime-only and are not stored.

## Negative-Condition Monitor

v0.4.16 adds a continuous per-device monitor for negative active power and negative power factor.

Supported conditions:

- `P < 0`
- `PF < 0`
- `P < 0 OR PF < 0`

Supported phases are A, B, and C. TOTAL is not part of the monitor in v0.4.16.

The threshold is exactly `0.0`. The monitor does not use epsilon, hysteresis, debounce, rounding, or inferred transitions.

For consecutive valid canonical samples:

```text
NEGATIVE_START: previous >= 0 and current < 0
NEGATIVE_END:   previous <  0 and current >= 0
```

The monitor starts one recording when the first selected negative condition becomes active. Overlapping phase or measurement conditions remain in the same recording session. The monitor stops a monitor-owned recording only when all selected conditions are clear. It then returns to `WAITING` and can start a new session for the next event without manual re-arm.

A continuity break prevents an exact crossing claim. After a gap or reconnect, the Viewer records boundary evidence such as `NEGATIVE_PRESENT_AFTER_GAP` or `NEGATIVE_PRESENT_AFTER_RECONNECT` instead of inventing `NEGATIVE_START` or `NEGATIVE_END`.

Manual recording remains authoritative. Manual STOP during an active negative condition moves the monitor to `WAITING_FOR_CLEAR` and suppresses automatic restart for the same continuous event.

## History and P-Q Density

The browser stores up to 10 minutes of exact canonical history samples for each Emonio.

Display windows:

- 30 s
- 1 min
- 2 min
- 5 min
- 10 min

The P-Q Density view uses the exact samples inside the selected display window and a deterministic 32 x 32 grid. It does not smooth, interpolate, resample, or modify the source values. Density occupancy is not quadrant authority.

The exact-sample Inspector remains tied to real stored samples. The display uses four decimal places. COPY keeps the exact stored numeric representation.

## SCOPE

SCOPE acquisition is independent from canonical Modbus measurements.

For visualization, instantaneous phase power is calculated from received SCOPE samples as:

```text
p[k] = u[k] * i[k]
```

This value is visualization evidence only. It does not replace canonical Modbus active power.

## Requirements

- Python >= 3.10
- `aiohttp==3.14.3`
- `yarl==1.24.2`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[dev]'
```

## Start

```bash
./start-emonio-viewer.sh
```

Default server binding: `127.0.0.1`.

## Verification

Run the repository acceptance gate:

```bash
./tools/ari-emonio-acceptance.sh
```

Latest v0.4.16 automated acceptance evidence:

```text
Unit tests:          250 PASS
Integration tests:    87 PASS
Frontend tests:      194 PASS
Read-only gate:        3 PASS
Python compilation:   PASS
Scientific sign path: 1 PASS

ARI Emonio Viewer Acceptance: PASS
```

The protected Modbus, measurement, acquisition, RuntimeEventBus, RuntimeStore, and SCOPE paths are also checked against the trusted pre-monitor baseline during v0.4.16 acceptance.

## Engineering references

- [SECURITY.md](SECURITY.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [ARI_EMONIO_VIEWER_TECHNICAL_OVERVIEW.md](ARI_EMONIO_VIEWER_TECHNICAL_OVERVIEW.md)

## License

Source-available software. See [LICENSE](LICENSE).
