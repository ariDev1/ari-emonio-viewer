# ARI Emonio Viewer v0.2.0 Canonical Measurement History Evidence

## Baseline

v0.2.0 Candidate is built from the field-confirmed v0.1.9 viewer baseline.

## Scope

This build adds browser-session measurement history only. The source measurement path remains:

Emonio P3 -> read-only Modbus/TCP -> canonical measurement model -> runtime event bus -> WebSocket -> browser

No Modbus read schedule, register map, decoder, measurement model, validation rule, recorder, CT evidence service, persistent device registry, or shutdown transport code was changed for this feature.

## History contract

- Fixed rolling window: 10 minutes.
- Time basis: canonical `cycle_finished_utc` from the existing WebSocket payload.
- Values: canonical signed `P` and `Q` for Phase A, Phase B, Phase C, and TOTAL.
- Buffer scope: browser session only.
- Isolation: separate history for each device id.
- Duplicate handling: one point per cycle id per device.
- Rendering: discrete SVG sample markers only.
- No connecting line or path is generated.
- No smoothing.
- No averaging.
- No interpolation.
- No sign correction.
- No gap filling.
- No resampling.
- Full JavaScript numeric values are stored before presentation formatting.
- The vertical display scale is symmetric around zero and derived from the largest observed absolute value in the visible device history.

## TDD evidence

The first focused run failed because `frontend/js/history.js`, the history UI, and `frontend/css/history.css` did not exist. This was the intended RED state.

After implementation, the focused browser/history suite passed 24 checks. The history mathematics tests prove:

- signed full-precision P/Q values are retained;
- exact ten-minute timestamp pruning;
- device isolation;
- cycle-id de-duplication;
- timestamp projection uses elapsed time rather than sample index;
- positive and negative values retain their sign direction around zero;
- chart data contains discrete points only and no path or segment representation.

## Software acceptance

Before release identity was frozen, the complete modified tree passed:

- Unit: 80 PASS
- Integration: 38 PASS
- Frontend contract: 29 PASS
- Read-only gate: 3 PASS
- Python compilation: PASS
- Scientific sign path: PASS

Field qualification of the new visual history remains required before v0.2.0 is promoted above the trusted v0.1.9 baseline.
