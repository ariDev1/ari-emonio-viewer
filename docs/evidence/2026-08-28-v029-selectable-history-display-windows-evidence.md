# ARI Emonio Viewer v0.2.9 Selectable History Display Windows Evidence

## Release identity

- Candidate: `v0.2.9`
- Trusted field baseline: `v0.2.8`
- Trusted baseline ZIP SHA-256: `13f10590795d86f7399f139788b1578569cae2a9dd6ca4e734f9d3f8c5fb9d95`
- Qualification type: software verification plus deterministic browser-layout comparison
- Field status: Candidate; real-device confirmation is still required

The user field-confirmed v0.2.8 as working as expected before this Candidate was started. v0.2.8 is therefore the development baseline for v0.2.9.

## Scope

v0.2.9 adds one browser-only operator feature to the trusted v0.2.8 workstation:

```text
30 s | 1 min | 2 min | 5 min | 10 min
```

The selected display window controls only which already-stored canonical history samples are rendered.

The stored browser history remains fixed at 10 minutes per Emonio.

The visible subset is selected from the exact stored timestamps relative to the newest stored sample:

```text
visible when timestampMs >= newestTimestampMs - selectedWindowMs
```

The boundary sample is included. No synthetic sample is created.

The display-window state accepts only these fixed values:

```text
30000 ms
60000 ms
120000 ms
300000 ms
600000 ms
```

The default remains 600000 ms (10 minutes).

## Scientific behavior

The display-window function does not change canonical history storage.

It does not add:

- smoothing;
- averaging;
- interpolation;
- resampling;
- gap filling;
- sign correction;
- value transformation;
- nominal sample-period assumptions.

Rendering continues to use discrete real measured sample markers only.

P/Q remain symmetric and zero-centered. U/I/S/PF/f display bounds are calculated only from the visible real measured samples. Those bounds are display coordinates only and do not change stored values.

Pointer selection maps the plot x-coordinate through the selected time window and then selects the nearest real visible stored sample. Existing LEFT/RIGHT keyboard stepping remains based on the complete stored sample array and exact sample identity. No keyboard-stepping semantic was changed.

## Storage isolation

The existing `MeasurementHistory` default remains:

```text
HISTORY_WINDOW_MS = 10 * 60 * 1000
```

A regression test changes the active display window to 30 seconds and then confirms that a sample exactly 10 minutes older than the newest sample remains stored.

The display window therefore cannot reduce the canonical 10-minute browser history retention.

## TDD evidence

Tests were added before the production feature change.

The first direct pytest command did not include the project `PYTHONPATH`; that environment-error run was discarded. The command was corrected before RED evidence was accepted.

Correct RED failures showed:

1. `HISTORY_DISPLAY_WINDOWS` did not exist.
2. `visibleHistorySamples` did not exist.
3. 30-second plot-x mapping still used the fixed 10-minute range.
4. discrete-series projection still used the fixed 10-minute range.
5. no display-window frontend controls existed.
6. the window-selector behavior test failed when its production initializer was absent.
7. the release-identity test failed because the package still reported `0.2.8`.

After the minimum implementation, the targeted tests passed and the complete browser suite passed `77/77`.

## Frontend operator contract

The existing history metric selector remains unchanged.

A second control group shares the same existing control row:

```text
DISPLAY WINDOW  30 s  1 min  2 min  5 min  10 min
```

The metadata row reports:

```text
Display
Visible / stored
Last sample
Render mode
```

`Visible / stored` makes the rendering subset explicit without changing the stored sample count.

The scientific note states that the display window is an exact timestamp subset for rendering only and that stored history remains fixed at 10 minutes.

## Deterministic Chromium geometry comparison

The trusted v0.2.8 HTML/CSS and the v0.2.9 Candidate HTML/CSS were loaded directly into the same headless Chromium instance at a `1920 x 1033` viewport. Runtime JavaScript was removed for this comparison so the measurement isolates layout geometry only.

The first v0.2.9 comparison found that a longer explanatory note wrapped to one extra line and reduced the active history plot by approximately 11.2 px. That draft was not accepted. The note was shortened without changing its scientific meaning.

The repeated comparison then produced identical baseline/Candidate geometry for the scientific workspace:

```text
Document scroll height       1033 px / 1033 px
Science workspace            1884 x 781 px / 1884 x 781 px
History panel                1417.203125 x 781 px / identical
Active history plot          1031.203125 x 600.5625 px / identical
Exact sample inspector       360 x 621.5625 px / identical
Recording strip              1884 x 40 px / identical
```

The P/Q SVG remained exactly square in both versions:

```text
v0.2.8  442.796875 x 442.796875 px  ratio 1.0
v0.2.9  442.796875 x 442.796875 px  ratio 1.0
```

This is deterministic software layout evidence. It is not a replacement for real-workstation field confirmation.

## Source-isolation audit

A recursive SHA-256 comparison against the exact trusted v0.2.8 archive confirms that these scientific/backend directories are byte-identical:

```text
src/emonio_viewer/modbus
src/emonio_viewer/acquisition
src/emonio_viewer/measurement
src/emonio_viewer/recording
src/emonio_viewer/device_evidence
src/emonio_viewer/config
src/emonio_viewer/runtime
src/emonio_viewer/server
```

The only backend-source difference is release identity:

```text
src/emonio_viewer/__init__.py
0.2.8 -> 0.2.9
```

Production feature changes are limited to:

```text
frontend/js/history.js
frontend/js/app.js
frontend/index.html
frontend/css/history.css
```

No Modbus, acquisition, canonical measurement, recording, CT evidence, persistence, runtime-event, server API, or WebSocket implementation changed.

## Software acceptance

Fresh source-tree acceptance before packaging:

```text
Unit:                83 PASS
Integration:         40 PASS
Frontend contract:   77 PASS
Read-only gate:       3 PASS
Python compilation:   PASS
Scientific sign path: PASS

ARI Emonio Viewer Acceptance: PASS
```

The unique pytest set contains `200` tests (`83 + 40 + 77`).

## Field acceptance required

v0.2.8 remains the trusted baseline. v0.2.9 must remain Candidate until real-device testing confirms:

- live Emonio acquisition remains correct;
- all five display-window controls select the expected visible interval;
- the visible sample count changes while stored history remains available;
- history points remain discrete real measured samples;
- exact-sample click selection remains correct in each window;
- LEFT/RIGHT exact-sample stepping remains unchanged;
- fullscreen workstation use remains zero-scroll;
- square P/Q geometry remains unchanged;
- Diagnostics and Recording drawers do not move the scientific workspace;
- per-Emonio recording ownership remains unchanged.
