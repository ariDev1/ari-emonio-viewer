# ARI Emonio Viewer

Engineering viewer for Emonio P3 electrical measurements on Linux.

The trusted field baseline is **v0.4.14**.
The `testing` branch is **v0.4.20 Testing**. Tested device firmware: `3.0.79-release`.

## Measurement architecture

- Modbus/TCP is read-only.
- One runtime owner controls each Modbus/TCP client.
- Canonical measurements are acquired for Phase A, B, C, and TOTAL.
- Canonical quantities are U, I, P, Q, S, PF, frequency, and energy.
- Signed P and Q preserve four-quadrant behavior.
- Canonical samples keep the exact cycle ID and `cycle_finished_utc`.
- Auxiliary Modbus evidence reads occur only at canonical cycle boundaries.
- Reset-on-read MIN/MAX register ranges are not read.
- Read-only evidence includes KWH IN/OUT, CONNECTED A/B/C, ERROR, and WARNING.
- CT configuration evidence uses a separate read-only Telnet path.
- SCOPE waveform acquisition is separate from canonical Modbus measurements.

## Scientific invariants

- No Modbus write path.
- No smoothing, averaging, interpolation, resampling, or gap filling.
- No synthetic samples or sign correction.
- No waveform reconstruction.
- Invalid or non-finite SCOPE captures fail closed.
- SCOPE-derived instantaneous power does not replace canonical Modbus P.
- Browser history is not the recording authority.
- Credentials are runtime-only and are not stored.

## Negative-Condition Monitor

v0.4.17 monitors Phase A, B, and C for one condition only:

- `P < 0`

PF remains a canonical displayed measurement. It is not a separate direction trigger in the Negative-Condition Monitor. This avoids presenting P and PF as independent active-power direction tests.

TOTAL is excluded in v0.4.17. The threshold is exactly `0.0`. The monitor does not use epsilon, hysteresis, debounce, rounding, or inferred transitions.

For consecutive valid canonical samples:

```text
NEGATIVE_START: previous P >= 0 and current P < 0
NEGATIVE_END:   previous P <  0 and current P >= 0
```

The first active selected phase starts one recording. Overlapping phase conditions use the same session. A monitor-owned session stops only after all selected phases clear. The monitor then returns to `WAITING` and is ready for the next event.

A continuity break prevents an exact crossing claim. After a gap or reconnect, the Viewer records boundary evidence such as `NEGATIVE_PRESENT_AFTER_GAP` or `NEGATIVE_PRESENT_AFTER_RECONNECT`.

Manual STOP during an active negative condition moves the monitor to `WAITING_FOR_CLEAR` and suppresses automatic restart for the same continuous event.

## History and P-Q Density

The browser stores up to 10 minutes of exact canonical history per Emonio. Display windows are 30 s, 1 min, 2 min, 5 min, and 10 min.

The P-Q Density view uses exact samples from the selected window and a deterministic 32 x 32 grid. Density occupancy is not quadrant authority.

The exact-sample Inspector uses four decimal places for display. COPY keeps the exact stored numeric representation.

## SCOPE

SCOPE is independent from canonical Modbus measurements. Instantaneous phase power for visualization is:

```text
p[k] = u[k] * i[k]
```

This value is visualization evidence only.

## Requirements

- Python >= 3.10
- `aiohttp==3.14.3`
- `yarl==1.24.2`

## Install and start

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[dev]'
./start-emonio-viewer.sh
```

Default server binding: `127.0.0.1`.

## Verification

```bash
./tools/ari-emonio-acceptance.sh
```

Latest completed automated acceptance evidence before v0.4.20 changes: **v0.4.19**.

```text
Unit tests:          249 PASS
Integration tests:    87 PASS
Frontend tests:      203 PASS
Read-only gate:        3 PASS
Python compilation:   PASS
Scientific sign path: 1 PASS
ARI Emonio Viewer Acceptance: PASS
```

The testing acceptance workflow also verifies the protected Modbus, measurement, acquisition, RuntimeEventBus, RuntimeStore, and SCOPE paths against the trusted pre-monitor baseline.

## References

- [ARI_EMONIO_VIEWER_TECHNICAL_OVERVIEW.md](ARI_EMONIO_VIEWER_TECHNICAL_OVERVIEW.md)
- [SECURITY.md](SECURITY.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- Source-available software: [LICENSE](LICENSE)
