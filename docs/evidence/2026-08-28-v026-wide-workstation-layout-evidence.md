# ARI Emonio Viewer v0.2.6 Wide Workstation Layout Evidence

## Release identity

- Candidate: `v0.2.6`
- Derived from: `v0.2.5`
- Trusted field baseline remains: `v0.2.0`
- Qualification type: software verification only

## Field evidence that caused this change

Real-device v0.2.5 evidence proved that frontend startup and Emonio connection worked again. The same fullscreen screenshot also proved that the workstation layout did not use the available wide-screen space correctly. The collapsed Diagnostics area still reserved a large part of the P/Q row, and History remained below it with insufficient useful plot area. Therefore v0.2.5 is not promoted.

## v0.2.6 layout contract

The browser scientific grid is now:

```text
status
active target
Phase A | Phase B | Phase C | TOTAL
full-width four-quadrant P/Q
history: active plot | exact-sample inspector
```

Diagnostics and Recording are no longer scientific-grid rows. They are fixed right-side overlay drawers. When closed they consume no grid width or height. DIAG and REC state remains visible in the top status area. Opening either drawer does not change the geometry of the phase, quadrant, or history workspaces.

The P/Q SVG keeps equal geometric P/Q scaling. It is not stretched non-uniformly to fill the wide screen because that would distort vector angle and scientific geometry.

## Canonical-data boundary

The change does not modify:

- Modbus/TCP transport or register reads;
- acquisition scheduling;
- canonical measurement values;
- WebSocket measurement payload;
- history storage semantics;
- signed P/Q behavior;
- CT evidence acquisition;
- recording data semantics or per-Emonio recording ownership;
- remembered-device persistence;
- shutdown behavior.

## TDD regression evidence

New frontend contracts were written before implementation and failed against v0.2.5. They cover:

- zero scientific-grid space for closed utility drawers;
- fixed overlay drawer geometry;
- persistent DIAG and REC state in the top status area;
- full-width quadrant workspace without a reserved Diagnostics column;
- horizontal History plot and exact-sample inspector workspace;
- fixed viewport layout with no Recording grid row;
- CT evidence retained inside the Diagnostics drawer;
- per-Emonio recording ownership retained inside the Recording drawer.

After implementation the frontend contract suite passed `32/32`.

## Chromium geometry probe

A headless Chromium probe used a `1920 x 1033` viewport with representative populated phase measurement rows and the exact production CSS.

Measured geometry:

```text
viewport height         1033 px
document scroll height  1033 px
body scroll height      1033 px
viewer shell            1900 x 1033 px
phase row height         286 px
quadrant workspace       1884 x 251.27 px
history workspace        1884 x 369.73 px
history plot             1393 x 189.30 px
exact sample inspector    465 x 210.30 px
```

The geometry probe also opened the Diagnostics drawer. The viewer shell, quadrant workspace, and History workspace changed by `0 px` in x, y, width, and height. The drawer overlaid the right side at `620 px` width.

Result:

```text
GEOMETRY_PROBE: PASS
```

This is software-rendering evidence only. Real-device fullscreen acceptance is still required before v0.2.6 can become a trusted baseline.
