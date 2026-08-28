# ARI Emonio Viewer v0.3.2 SCOPE Header Prefix Compatibility Evidence

## Baseline

- Trusted viewer baseline remains `v0.2.9`.
- `v0.3.1` is not promoted because real multi-device field testing exposed an invalid universal SCOPE header-prefix assumption.
- `v0.3.2` is a Candidate compatibility correction.

## Real-device evidence

Three Emonio P3 devices were tested with the standalone 20-capture qualification path. Each device produced 20/20 complete captures with the same structural waveform contract:

```text
channel order            0,1,2,3,4,5
samples/channel          232
frame bytes              932
capture duration         35.6 ms
derived sample rate      6488.764045 Hz
non-finite samples       0
```

The first three binary bytes differed by device but were stable across every capture on that device:

```text
device 1 prefix          e5d200
device 2 prefix          810400
device 3 prefix          e90f00
```

The original Emonio browser decoder uses byte 3 as the channel identifier and decodes Float32 samples from byte 4. It does not use bytes 0..2 as a validity gate. The v0.3.0/v0.3.1 `e5d200` equality requirement was therefore too strict.

## v0.3.2 corrected contract

Required for a published capture:

- binary frame size exactly 932 bytes;
- byte 3 channel identifier in 0..5;
- channels received exactly in order 0,1,2,3,4,5;
- exactly 232 Float32 samples per channel;
- metadata phases exactly 0,1,2;
- equal positive capture duration across phases;
- zero non-finite waveform samples.

Observational only:

- bytes 0..2 are preserved as `header_prefix_hex`;
- the API exposes the unique observed prefix values for the capture;
- the SCOPE evidence strip displays the value as `PREFIX ... · OBSERVED`;
- no physical, firmware, or hardware meaning is assigned to the prefix.

No Modbus, canonical measurement, recording, CT-evidence, persistence, or acquisition implementation is changed by this correction.
