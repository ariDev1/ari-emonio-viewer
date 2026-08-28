# ARI Emonio Viewer v0.2.1 Expanded Canonical Measurement History Evidence

## Baseline

v0.2.1 Candidate is built from the field-confirmed v0.2.0 viewer baseline.

The v0.2.0 Modbus acquisition, canonical measurement model, recording, CT evidence, remembered-device registry, WebSocket backend, and shutdown behavior are not changed by this feature.

## Change scope

The browser-session history now retains and displays these canonical fields for Phase A, Phase B, Phase C, and TOTAL:

- `vrms` -> `U(t)` in V
- `irms` -> `I(t)` in A
- `p` -> `P(t)` in W
- `q` -> `Q(t)` in var
- `s` -> `S(t)` in VA
- `pf` -> `PF(t)` dimensionless
- `frequency` -> `f(t)` in Hz

The four-quadrant vector and Diagnostics row is above the complete rolling-history section.

## Scientific display contract

The history window remains exactly 10 minutes. The x-coordinate uses the canonical `cycle_finished_utc` timestamp. Each accepted cycle id is stored once per device. Device histories remain isolated.

The renderer uses discrete sample markers only. It does not draw a path, polyline, or polygon between samples. It does not smooth, average, interpolate, resample, fill gaps, or correct signs.

`P` and `Q` keep a symmetric zero-centered display scale. `U`, `I`, `S`, `PF`, and frequency use the exact observed minimum and maximum in the current device history. Zero is not forced into those ranges. If minimum equals maximum, the sample is placed at the vertical center. Scaling changes display coordinates only. It does not alter canonical values.

## TDD evidence

The new RED tests failed because:

- the history buffer retained only `p` and `q`;
- the requested `U/I/S/PF/f` chart contract did not exist;
- observed-range projection functions did not exist;
- the rolling-history section was above the four-quadrant row;
- the additional SVG plots did not exist.

After the minimal frontend implementation, the focused history/layout gate passed 33 tests.

## Software acceptance

Before release packaging:

- Unit: 80 PASS
- Integration: 38 PASS
- Frontend contract: 38 PASS
- Read-only source gate: PASS
- Python compilation: PASS
- Scientific sign path: PASS

Real-device visual qualification is still required before v0.2.1 is promoted above the trusted v0.2.0 baseline.
