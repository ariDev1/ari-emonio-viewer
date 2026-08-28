# ARI Emonio Viewer v0.2.2 Exact Sample Inspection Evidence

Date: 2026-08-28

## Status

v0.2.2 is a software-qualified development Candidate. It is not field-confirmed.

Trusted field baseline: v0.2.0.

v0.2.1 remains a previous software-qualified Candidate and is not promoted by this change.

## Source basis

v0.2.2 was developed from the supplied v0.2.1 Candidate archive with SHA-256:

```text
c90fe75045769f81c9d074714394979e92b0c010b1a25b43c218bfd76116a09f
```

No Modbus register map, Modbus transport, acquisition worker, canonical measurement model, recording path, CT evidence path, WebSocket backend, device persistence, or shutdown implementation was changed except application release identity files.

## Corrected visual hierarchy

The v0.2.1 HTML source order placed the four-quadrant and Diagnostics row before the rolling history. However, `frontend/css/layout.css` assigned the CSS grid rows in this order:

```text
phases
history
analysis
recording
```

Because the elements have explicit CSS grid areas, this made the effective browser order place rolling history above the analysis row.

v0.2.2 changes only the grid row order to:

```text
phases
analysis
history
recording
```

A regression test now checks the effective CSS grid order in addition to the existing HTML order test.

## Exact stored-sample inspection

The new Sample inspector is implemented in the browser history path only.

It preserves these rules:

- canonical WebSocket samples remain the only history input;
- history remains isolated by device id;
- the rolling window remains exactly 10 minutes;
- P and Q remain signed and unchanged;
- no smoothing is used;
- no averaging is used;
- no interpolation is used;
- no resampling is used;
- no gap filling is used;
- no sign correction is used;
- no plausibility clamping is used;
- plots remain discrete measured sample markers.

Each stored browser sample now retains both:

```text
cycleFinishedUtc = exact received cycle_finished_utc string
timestampMs      = parsed JavaScript time coordinate for plotting only
```

This prevents sub-millisecond text precision from being discarded when the operator inspects a sample. Plot positioning still uses the parsed time coordinate.

## Sample identity after process restart

v0.2.1 rejected any later browser sample that reused an existing `cycle_id`. Acquisition cycle ids can restart after a process restart.

v0.2.2 defines the browser duplicate identity as the pair:

```text
(cycle_id, exact cycle_finished_utc string)
```

An exact duplicate pair is rejected. The same cycle id with a different canonical timestamp is retained as a different measured cycle.

This is a browser-history correction only. No acquisition cycle identity or backend schema was changed.

## Selection rule

A click inside a history plot is transformed from screen coordinates into native SVG coordinates with the SVG screen transformation matrix. This avoids coordinate error when the browser scales or letterboxes the SVG.

The horizontal plot coordinate is converted to a target timestamp. The viewer then selects the nearest real stored sample.

If two real samples are exactly the same temporal distance from the target timestamp, the earlier measured sample is selected. No interpolated sample is created.

The selected real sample produces one synchronized vertical inspection cursor in each history plot.

## Inspector readout

The inspector reports:

```text
Device id
Cycle id
Exact Finished UTC string
Quality

Phase A: U I P Q S PF f
Phase B: U I P Q S PF f
Phase C: U I P Q S PF f
TOTAL:   U I P Q S PF f
```

The inspector uses JavaScript round-trip number formatting (`String(number)`) instead of the normal four-decimal presentation format. This does not increase the underlying IEEE-754 precision. It prevents the inspector from deliberately rounding the stored browser number to four decimal places.

## TDD evidence

The hierarchy and inspection work was implemented test-first.

The initial targeted RED run proved these missing or incorrect behaviors:

- effective CSS grid order placed history before analysis;
- inspector structure did not exist;
- exact canonical `cycle_finished_utc` text was not retained;
- a reused cycle id with a different timestamp was incorrectly rejected;
- nearest-real-sample selection did not exist;
- plot-x to timestamp selection mapping did not exist;
- non-forced-rounding inspector formatting did not exist.

The exact-duplicate rejection property already existed through the older cycle-id-only duplicate rule, so that specific preservation test was already green before the identity correction.

A later review identified that linear `clientX / element width` mapping would be incorrect for a scaled or letterboxed SVG. A new regression test was added first. It failed against the linear mapping. The implementation was then changed to `getScreenCTM()` plus `createSVGPoint()` coordinate transformation, after which the test passed.

## Software qualification before final packaging

The complete acceptance command was:

```bash
./tools/ari-emonio-acceptance.sh
```

Observed result:

```text
Unit:                80 PASS
Integration:         38 PASS
Frontend contract:   48 PASS
Read-only gate:       3 PASS
Python compilation:   PASS
Scientific sign path: PASS

ARI Emonio Viewer Acceptance: PASS
```

This is software evidence only. Real-device visual and measurement qualification is still required before v0.2.2 can become a trusted baseline.
