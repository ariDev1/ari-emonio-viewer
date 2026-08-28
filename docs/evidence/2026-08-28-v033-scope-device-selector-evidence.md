# ARI Emonio Viewer v0.3.3 SCOPE Device Selector Evidence

## Status

- `v0.3.3` is a Candidate operator-workflow refinement.
- It starts from the `v0.3.2` Candidate compatibility correction.
- It does not change the Emonio SCOPE transport, frame decoder, waveform samples, Modbus path, canonical measurements, recording, CT evidence, acquisition, runtime, or diagnostics implementations.

## Field basis

The corrected standalone SCOPE probe v0.1.8 qualified three real Emonio P3 devices with 20/20 complete captures each. The observed stable diagnostic prefixes were `e5d200`, `810400`, and `e90f00`. Prefix value remains observational only.

## v0.3.3 change

The SCOPE command bar contains a local Emonio selector populated from enabled runtime device configurations. The selector uses the existing application `selectDevice()` path. It does not create a second device-selection authority. The SCOPE drawer remains open while the selected Emonio changes.

Before a SCOPE-local device switch, the browser clears the username and password input values. Credentials are not copied to the next Emonio and are not stored in browser storage. Existing stale-response protection remains active during asynchronous switching.

## Scientific boundary

The change is operator navigation only. No waveform value, sample count, frame-size gate, channel mapping, sample order, capture-axis calculation, display projection, Modbus value, recording value, or canonical sign path changes.
