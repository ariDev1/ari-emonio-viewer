# Contributing to ARI Emonio Viewer

ARI Emonio Viewer is scientific measurement software. Changes must preserve
measurement evidence and the read-only device boundary.

## Engineering rules

- Keep Modbus read-only. Modbus writes are forbidden.
- Keep SCOPE scientifically separate from canonical Modbus measurements.
- Preserve signed P and Q values and four-quadrant semantics.
- Preserve exact discrete history samples.
- Preserve exact received SCOPE waveform samples.
- Do not add smoothing, averaging, interpolation, resampling, gap filling,
  synthetic samples, sign correction, or waveform reconstruction.
- Do not weaken fail-closed validation to make a test pass.
- Keep credentials and authentication cookies out of Git.
- Keep CSS structured by responsibility.
- Avoid unrelated refactors.

## Test-first changes

Use test-driven development for behavioral changes. Add a failing regression
test first, confirm the expected failure, implement the smallest repair, and
then run the complete acceptance suite:

```bash
./tools/ari-emonio-acceptance.sh
```

Do not remove or weaken an acceptance gate.

## Evidence classes

Software-only acceptance is not real-device qualification. State clearly
whether evidence comes from deterministic software tests, a controlled local
network test, or a real Emonio device. Do not claim 24/7 field reliability from
software stress tests.

## Publication hygiene

Do not commit runtime recordings, local configuration, remembered-device files,
logs, waveform captures unless explicitly approved as scientific fixtures,
credentials, cookies, private keys, editor state, virtual environments, build
output, or package archives.
