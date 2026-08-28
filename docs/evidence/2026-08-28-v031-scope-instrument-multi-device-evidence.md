# ARI Emonio Viewer v0.3.1 SCOPE Instrument and Multi-Device Evidence

## Release state

- Previous trusted baseline: `v0.2.9`
- Integrated SCOPE predecessor: `v0.3.0 Candidate`
- Candidate: `v0.3.1`
- Date: `2026-08-28`

The user reported that the integrated v0.3.0 SCOPE view works well on the real Emonio workstation and supplied a screenshot of the live waveform display. The user then requested a more professional scientific instrument presentation and explicit support for users that operate more than one Emonio. This is positive single-device field evidence for the integrated SCOPE path. It is not evidence that simultaneous multi-Emonio SCOPE sessions have been field-tested.

## Scope of v0.3.1

v0.3.1 preserves the v0.3.0 read-only waveform protocol and adds only:

1. compact instrument-style SCOPE controls;
2. a compact global active-owner strip;
3. active SCOPE session count in the utility status;
4. per-Emonio phase/signal view state in volatile browser memory;
5. stale selected-device response rejection in the SCOPE frontend;
6. deterministic oscilloscope grid and axis labels;
7. compact capture evidence presentation;
8. larger waveform plot area.

No Modbus, canonical measurement, recording, CT evidence, target qualification, or measurement WebSocket implementation was changed.

## Multi-device ownership contract

`ScopeService` already stored one runtime per `device_id`. v0.3.1 exposes that proven isolation to the operator with `active_statuses()` and the compact `active_sessions` API field.

An active SCOPE owner is a device in one of these states:

```text
CONNECTING
LIVE
HOLD
```

`DISCONNECTED` and `ERROR` do not count as active owners.

The active-owner API field contains only:

```text
device_id
state
```

It does not duplicate waveform captures and it does not contain credentials.

Switching the selected Emonio changes the controlled SCOPE view only. It does not stop or replace another Emonio SCOPE runtime. The service regression suite proves independent concurrent LIVE runtimes and independent captures for two Emonios. The new ownership regression proves deterministic active-owner reporting.

## Browser multi-device contract

The SCOPE frontend stores only the selected display modes for each Emonio:

```text
phase:  A | B | C | ABC
signal: U | I | U+I
```

This view state is volatile JavaScript memory. It is not written to `localStorage`, `sessionStorage`, TOML, remembered-device configuration, or recordings.

The frontend rejects a SCOPE status response if the requested device is no longer the selected device when that response arrives. This prevents an older request for Emonio A from overwriting the visible SCOPE state after the operator switches to Emonio B.

## Visual instrument contract

The v0.3.1 drawer uses these regions:

```text
COMMAND BAR
ACTIVE SCOPE OWNERS
PHASE / SIGNAL TOOLBAR
CAPTURE EVIDENCE STRIP
OSCILLOSCOPE PLOT
SCIENTIFIC PROVENANCE LINE
```

The plot uses deterministic 10 horizontal-time divisions and 8 vertical-scale divisions. The grid affects display coordinates only. It does not alter waveform values.

Phase identity remains stable:

```text
A = cyan
B = green
C = amber
```

Signal identity remains stable:

```text
U = solid
I = dashed
```

The plot still renders the exact received 232 samples per visible channel as adjacent straight vertices only. No smoothing, averaging, interpolation, resampling, gap filling, sign correction, or synthetic waveform generation is introduced.

## 1920 x 1033 geometry comparison

Static production HTML/CSS was measured in headless Chromium at a `1920 x 1033` viewport.

### v0.3.0 SCOPE closed

```text
page                 1920 x 1033
science workspace     1884 x 781
```

### v0.3.1 SCOPE closed

```text
page                 1920 x 1033
science workspace     1884 x 781
```

The closed drawer therefore causes zero science-workspace geometry change.

### Drawer open comparison

```text
                         v0.3.0            v0.3.1
SCOPE drawer             1100 x 1017       1180 x 1017
waveform plot            1078 x 540        1158 x 649.359
page scroll              none              none
science workspace        unchanged         unchanged
```

v0.3.1 gains about 109 px of waveform plot height and 80 px of plot width while preserving the underlying workstation geometry.

## TDD evidence

The v0.3.1 behavior was introduced with failing tests first.

New regression coverage includes:

```text
ScopeService active-owner reporting
API compact active_sessions reporting
per-Emonio browser view isolation
invalid view-mode rejection
deterministic scope grid positions
active-owner frontend normalization
stale selected-device response guard
instrument-layout HTML/CSS contract
multi-device frontend contract
release identity 0.3.1
```

## Software acceptance before packaging

```text
Unit:                100 PASS
Integration:          47 PASS
Frontend contract:    91 PASS
Read-only gate:         3 PASS
Python compilation:   PASS
Scientific sign path: PASS

ARI Emonio Viewer Acceptance: PASS
```

## Field boundary

The v0.3.0 integrated SCOPE path has positive real-device/workstation evidence from the user. v0.3.1 is not yet field-confirmed. In particular, simultaneous LIVE/HOLD ownership across two or more real Emonios must be tested by the user before v0.3.1 can be promoted as the trusted integrated SCOPE baseline.
