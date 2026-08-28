# Contributing

Keep changes small, measurable, and reversible.

## Rules

- Keep Modbus read-only.
- Keep SCOPE separate from canonical Modbus measurements.
- Preserve signed P/Q and four-quadrant semantics.
- Preserve exact history and SCOPE samples.
- Do not add smoothing, averaging, interpolation, resampling, gap filling,
  synthetic samples, sign correction, or waveform reconstruction.
- Do not weaken fail-closed validation to make tests pass.
- Keep credentials, cookies, local configuration, recordings, and build output
  out of Git.
- Avoid unrelated refactors and keep CSS structured by responsibility.

## Changes

Use TDD for behavioral changes: write the failing regression test first,
implement the smallest repair, then run the complete acceptance suite:

```bash
./tools/ari-emonio-acceptance.sh
```

Do not remove or weaken an acceptance gate. Software-only acceptance must not
be described as real-device or 24/7 field qualification.
