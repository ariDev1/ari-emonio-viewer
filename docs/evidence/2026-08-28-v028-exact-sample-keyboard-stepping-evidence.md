# ARI Emonio Viewer v0.2.8 Exact-Sample Keyboard Stepping Evidence

## Release identity

- Candidate: `v0.2.8`
- Trusted field baseline: `v0.2.7`
- Qualification type: software verification only
- Field status: Candidate; real-device confirmation is still required

## Scope

v0.2.8 adds one browser-only operator feature to the trusted v0.2.7 workstation:

- click the active Measurement History plot to select the nearest real stored canonical sample;
- after selection, `ArrowLeft` selects the immediately previous real stored sample;
- after selection, `ArrowRight` selects the immediately next real stored sample;
- the first and last stored samples do not wrap;
- a missing or expired selected identity does not select a replacement sample;
- keyboard stepping uses the exact stored sample identity (`cycle_id` plus the exact received `cycle_finished_utc` string) and the existing stored sample order;
- the plot receives keyboard focus only after a valid click selection, and it is also reachable by normal keyboard focus because it has `tabindex="0"`.

The implementation does not calculate a nominal time step. Irregular acquisition intervals and reused cycle ids remain valid because the exact timestamp string is part of sample identity.

## Scientific boundaries unchanged

No change was made to:

- Modbus/TCP acquisition;
- read-only Modbus boundary;
- register map or CDAB decoding;
- canonical measurement model;
- signed P/Q values or quadrant classification;
- WebSocket measurement payload;
- 10-minute history storage and pruning semantics;
- discrete sample rendering;
- display scaling rules;
- recording backend or per-Emonio recording ownership;
- CT configuration evidence;
- remembered-device persistence;
- shutdown behavior;
- server API behavior.

Keyboard stepping does not add smoothing, averaging, interpolation, resampling, gap filling, sign correction, or value transformation.

## TDD evidence

The feature tests were written and observed failing before the production change.

Observed RED states included:

1. Exact-identity adjacent-sample test failed because `adjacentHistorySample` did not exist.
2. Keyboard frontend contract failed because the active history SVG did not have `tabindex="0"`.
3. Behavioral keyboard test failed because no `keydown` handler was registered.
4. Release identity test failed because both release locations still reported `0.2.7`.

After the minimum implementation, the targeted new tests passed `4/4`. The complete browser suite passed `69/69`.

## Software acceptance

Fresh packaged-source acceptance before packaging:

```text
Unit:                83 PASS
Integration:         40 PASS
Frontend contract:   69 PASS
Read-only gate:       3 PASS
Python compilation:   PASS
Scientific sign path: PASS

ARI Emonio Viewer Acceptance: PASS
```

The unique pytest set contains `192` tests (`83 + 40 + 69`).

## Source-isolation audit

A recursive comparison against the exact trusted v0.2.7 archive showed that these backend/scientific directories are byte-identical:

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

The only backend-source difference is:

```text
src/emonio_viewer/__init__.py
0.2.7 -> 0.2.8
```

Production feature changes are limited to:

```text
frontend/js/history.js
frontend/index.html
frontend/css/history.css
```

The CSS focus indication uses `outline`, not border or padding, so it does not intentionally allocate new layout space.

## Geometry evidence boundary

A fresh headless Chromium geometry probe was attempted in the build container. Chromium did not terminate within the probe limit. Therefore, no new browser geometry measurements are claimed for v0.2.8.

The existing deterministic layout regression tests still pass, including the fixed viewport/no-page-scroll contract, square P/Q coordinate contract, history/inspector workspace contract, and fixed overlay-drawer contract. Real fullscreen geometry remains a field-confirmation item for this Candidate.

## Field acceptance required

v0.2.7 remains the trusted baseline. v0.2.8 must remain Candidate until real-device testing confirms:

- live Emonio acquisition remains correct;
- one click selects the expected real stored history sample;
- LEFT and RIGHT move exactly one stored sample without interpolation or wrap-around;
- device switching preserves per-Emonio sample selection;
- newly arriving samples do not move an existing selected sample;
- fullscreen workstation layout remains zero-scroll;
- square P/Q geometry remains unchanged;
- Diagnostics and Recording drawers do not move the scientific workspace;
- per-Emonio recording ownership remains unchanged.
