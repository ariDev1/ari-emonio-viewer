# ARI Emonio Viewer v0.2.4 Layout and Recording Ownership Evidence

## Status

- Candidate: `v0.2.4`
- Derived from: rejected `v0.2.3`
- Trusted field baseline remains: `v0.2.0`
- v0.2.4 field acceptance: not yet confirmed

## Real-device defect evidence from v0.2.3 / v0.2.2 testing

The operator reported two defects during real-device use:

1. The collapsed Diagnostics panel stretched to the full height of the P/Q row. The history workspace was not usable as intended in fullscreen operation.
2. A recording started on one Emonio remained backend-owned by that device, but the frontend used one global recording flag. After the operator selected another Emonio, STOP and interval commands targeted the newly selected device and could return `404 Recording not active`. The recording panel did not clearly identify the recording owner.

## Root causes

- The analysis grid used `align-items: stretch`, which forced the collapsed Diagnostics card to match the quadrant-card height.
- The active history plot used a fixed/clamped height instead of consuming only the remaining history-workspace height.
- The browser represented recording activity as one global Boolean instead of device-keyed state.
- The server had no read-only endpoint to report active recording ownership after a browser reload.

## v0.2.4 changes

### Operator layout

- The analysis grid uses intrinsic-height alignment for the folded Diagnostics panel.
- Diagnostics and Recording use separator treatment instead of full large box borders.
- The history card allocates the active plot with `minmax(0, 1fr)` so the plot uses the remaining workstation height.
- The exact-sample inspector is denser while preserving the full canonical values.
- Major scientific panels remain visually separated; decorative nested borders are reduced.

### Recording ownership

- Recording state is represented per `device_id` in the browser.
- A read-only `GET /api/v1/recording/status` endpoint reports active recording owners, intervals, session directories, and start timestamps.
- Recording status is recovered from the backend after browser load and device selection.
- The Recording panel shows the selected Emonio, whether that Emonio is recording, and all active recording owners.
- STOP and interval controls are enabled only when the selected Emonio owns an active recording.
- Switching the selected Emonio does not stop, transfer, or reassign an existing recording.

## Scientific boundary

Not changed:

- Modbus register access or read-only policy
- acquisition cadence or worker logic
- canonical signed measurement model
- WebSocket measurement payload
- CT evidence path
- CSV measurement values or recording sampling semantics
- remembered-device persistence
- deterministic shutdown behavior
- history filtering / averaging / interpolation / resampling / sign handling

## Software verification

Before release identity update:

- Full pytest suite: `180 passed`
- Unit: `81 passed`
- Integration: `39 passed`
- Frontend contract: `60 passed`
- Read-only gate: `3 passed`
- Python compilation: PASS
- Scientific sign path: PASS

A headless Chromium geometry probe was attempted but Chromium did not terminate even for a trivial data URL in the build container. No browser geometry evidence is claimed from that failed probe. Real fullscreen visual qualification remains a field-test requirement.
