# ARI Emonio Viewer v0.2.3 Operator Layout Compaction Evidence

## Release identity

- Candidate: `ARI_Emonio_Viewer_v0.2.3_Candidate`
- Derived from: `ARI_Emonio_Viewer_v0.2.2_Candidate`
- Qualification type: software verification only
- Trusted field baseline remains: `v0.2.0`

## Change scope

v0.2.3 changes only the operator-facing browser layout and interaction model for low-frequency panels and history visualization.

Implemented scope:

- Diagnostics panel folded by default with live state / valid-cycle / error summary in the header.
- Session recording panel folded by default with live recording summary in the header.
- Single active rolling-history plot with selector buttons for `P(t)`, `Q(t)`, `U(t)`, `I(t)`, `S(t)`, `PF(t)`, and `f(t)`.
- Exact-sample inspection retained and compacted into a phase-card strip.
- Fullscreen workstation shell tuned to avoid page scrolling on normal desktop operation.
- Four-quadrant vector remains visible above rolling history.

Not changed:

- Modbus acquisition, polling cadence, device qualification, WebSocket payload, diagnostics source data, CT evidence path, recording backend, persistence, or shutdown behavior.
- Canonical history semantics: no smoothing, no filtering, no interpolation, no averaging, no sign correction, no gap filling, and no resampling.

## Verification summary

Software verification executed on the packaged source tree:

- Browser contract + history math: PASS
- Full pytest suite: PASS (`171 passed`)

## Qualification note

This is software evidence only. Real-device workstation validation is still required before v0.2.3 can become a trusted baseline.
