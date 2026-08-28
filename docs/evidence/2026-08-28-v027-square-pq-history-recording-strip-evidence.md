# ARI Emonio Viewer v0.2.7 Square P/Q + History Workstation Evidence

## Release identity

- Candidate: `v0.2.7`
- Derived from: `v0.2.6`
- Qualification type: software verification and deterministic browser geometry only
- Trusted field baseline remains: `v0.2.0`

## Real-device evidence that motivated the correction

Real-device v0.2.6 evidence confirmed that device connection and live measurement display worked. The user-provided 1920-class fullscreen screenshot also showed that the full-width P/Q row still contained excessive empty space, Measurement History was below it, and Recording was not visible as a normal operator control. Therefore v0.2.6 is not promoted.

## v0.2.7 workstation contract

On a wide workstation:

- Phase A/B/C/TOTAL remain in one full-width row.
- The four-quadrant P/Q plot and Measurement History share one primary science row.
- The P/Q SVG uses a square `430 x 430` coordinate space and `preserveAspectRatio="xMidYMid meet"`.
- P and Q use the same geometric scale; vector angles are not distorted.
- Measurement History keeps the selector-driven active metric plot and exact stored-sample inspector.
- Recording is always visible as a compact bottom strip.
- The Recording strip shows selected Emonio, selected recording state, interval, RECORD, STOP, and MORE.
- The detailed Recording drawer retains active-recording ownership information and the optional session note.
- Diagnostics remains an overlay drawer and consumes zero science-grid space while closed.

## Scientific boundaries unchanged

No change was made to:

- Modbus/TCP acquisition or read-only boundary
- canonical measurement model
- signed P/Q values or quadrant classification
- WebSocket measurement payload
- 10-minute history storage semantics
- no-filter / no-average / no-interpolation / no-resampling rules
- per-Emonio recording ownership
- CSV recording backend semantics
- CT configuration evidence path
- remembered-device persistence
- shutdown behavior

## TDD evidence

The v0.2.7 layout and recording-strip contracts were written first and failed against v0.2.6. After the minimum implementation, the targeted frontend/quadrant/recording-state set passed `40/40`.

The complete browser suite then passed `65/65`, and the full pytest suite passed `187/187` before release identity was applied.

## Chromium geometry evidence

A deterministic Chromium probe used `/usr/bin/chromium` at `1920 x 1033` with representative populated phase rows.

Measured geometry:

```text
viewport                 1920 x 1033
document                 1920 x 1033
page scroll              none
science workspace        1884 x 581 px
P/Q card                 460.8 x 497.8 px
P/Q SVG                  442.8 x 442.8 px
History                   1417.2 x 581 px
active history plot       1031.2 x 400.6 px
exact sample inspector      360 x 421.6 px
Recording strip             1884 x 40 px
```

Opening the Diagnostics drawer caused `0 px` movement of the science workspace, P/Q card, History, and Recording strip.

This is software-rendering evidence only. Real-device fullscreen acceptance is still required before v0.2.7 can become a trusted baseline.
