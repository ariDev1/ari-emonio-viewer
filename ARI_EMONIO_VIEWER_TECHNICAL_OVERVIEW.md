# ARI Emonio Viewer — Technical Overview

**Purpose:** Additional technical information for electrical engineers, researchers, and scientific users.

**Current trusted field baseline:** v0.4.7  
**Tested Emonio P3 firmware:** `3.0.79-release`

---

## 1. Project Purpose

ARI Emonio Viewer is a local Linux measurement viewer for Emonio P3 power measurement devices.

The project is intended for laboratory work with three-phase systems, bidirectional power flow, reactive loads, distorted waveforms, and other experiments where the sign and origin of a measurement are important.

The Viewer displays meter values without silently changing their sign or replacing them with calculated values.

Its main scientific rule is:

> **Measured data must remain identifiable as measured data. Derived data must remain identifiable as derived data.**

The Viewer therefore separates:

- canonical Modbus/TCP measurements,
- derived calculations,
- SCOPE waveform data,
- visualization,
- recording,
- device evidence, and
- diagnostics.

---

## 2. Scientific Measurement Principles

The Viewer preserves the original measurement values received from the Emonio.

If the Emonio reports negative active power, the Viewer keeps:

$$
P < 0
$$

If the Emonio reports negative reactive power, the Viewer keeps:

$$
Q < 0
$$

Negative values are not automatically classified as errors.

This is required for four-quadrant power analysis.

The measurement history also preserves discrete acquired samples. The scientific path does not use automatic:

- smoothing,
- averaging,
- interpolation,
- resampling,
- gap filling,
- synthetic samples,
- sign correction, or
- waveform reconstruction.

A line drawn between two stored samples is only a visual connection. It is not a new measurement.

If acquisition fails, the Viewer does not present an old value as a new observation.

---

## 3. Measurement Architecture

The canonical measurement path is:

```text
Emonio P3
   |
   | Modbus/TCP, read-only
   v
ReadOnlyModbusClient
   |
   v
Acquisition Worker
   |
   v
Verified register decoding
   |
   v
Canonical MeasurementSample
   |
   +--> Runtime Store
   +--> Event Bus
   +--> Recording
   +--> API / WebSocket
   |
   v
Scientific Viewer
```

Each enabled Emonio has its own acquisition worker and its own TCP client.

This keeps the measurement state of one device separate from another device.

A canonical sample contains the device identity, acquisition cycle, timing, phase measurements, TOTAL measurement, quality state, warnings, and raw register evidence.

The default configuration uses a 2.0 s polling interval and a 2.0 s Modbus timeout.

---

## 4. Read-Only Modbus Boundary

The canonical Modbus/TCP path is read-only.

There is no Modbus write path in the Viewer.

The Viewer is designed to observe the Emonio, not to configure it through Modbus.

The project also avoids reset-on-read MIN/MAX register ranges in the canonical acquisition path.

Additional Modbus evidence reads use the same runtime ownership model. They do not create an independent uncontrolled Modbus client.

This preserves one controlled owner for the primary Modbus connection of each Emonio.

---

## 5. Verified Emonio P3 Register Model

For firmware `3.0.79-release`, the verified measurement block contains 16 registers.

The block layout is:

| Register offset | Quantity |
|---:|---|
| 0 | $U_\mathrm{RMS}$ |
| 2 | $I_\mathrm{RMS}$ |
| 4 | $P$ |
| 6 | $Q$ |
| 8 | $S$ |
| 10 | Frequency |
| 12 | Energy |
| 14 | Power factor |

The block base addresses are:

| Block | Base register |
|---|---:|
| Phase A | 0 |
| Phase B | 100 |
| Phase C | 200 |
| TOTAL | 300 |

The register map identity is:

```text
P3-3.0.79-verified
```

Each quantity uses two 16-bit registers.

The Viewer uses the verified CDAB word order.

The decoder rejects a measurement block if the register count is wrong or if a required decoded value is not finite.

---

## 6. Canonical Electrical Quantities

For Phase A, Phase B, Phase C, and TOTAL, the canonical model contains:

- RMS voltage $U_\mathrm{RMS}$,
- RMS current $I_\mathrm{RMS}$,
- active power $P$,
- reactive power $Q$,
- apparent power $S$,
- frequency $f$,
- energy $E$, and
- power factor $PF$.

These are stored as meter-reported values.

The Viewer does not replace meter-reported $S$ with $\sqrt{P^2+Q^2}$.

It does not replace meter-reported $PF$ with $P/S$.

These formulas can be used as references or residual calculations, but they do not overwrite the original meter data.

---

## 7. Signed Active and Reactive Power

The sign of $P$ and $Q$ is part of the measurement evidence.

For active power:

- $P > 0$: positive active flow,
- $P < 0$: negative active flow,
- $P = 0$: zero active power.

For reactive power, the sign is also preserved.

The Viewer does not assume that a negative sign must be corrected.

The physical interpretation depends on the experiment, wiring, CT orientation, voltage reference, instrument convention, and system topology.

The software records the observation first.

---

## 8. Four-Quadrant Power Representation

The four-quadrant engine uses the measured signs of $P$ and $Q$.

| Quadrant | Condition |
|---|---|
| Q1 | $P > 0,\ Q > 0$ |
| Q2 | $P < 0,\ Q > 0$ |
| Q3 | $P < 0,\ Q < 0$ |
| Q4 | $P > 0,\ Q < 0$ |

Axis states and the origin are also treated explicitly.

For vector geometry, the Viewer can use:

$$
S_\mathrm{geom} = \sqrt{P^2 + Q^2}
$$

and:

$$
\varphi = \arg(P + jQ)
$$

The geometric magnitude $S_\mathrm{geom}$ is not the same data object as the meter-reported apparent power $S$.

The Viewer keeps both concepts separate.

This is important because real instruments can report quantities that do not satisfy ideal equations exactly.

---

## 9. Phase A, B, C, and TOTAL

The Viewer keeps Phase A, Phase B, Phase C, and TOTAL separate.

This is important in unbalanced three-phase systems.

For example:

```text
Phase A: P > 0
Phase B: P < 0
Phase C: P > 0
```

The total active power depends on the magnitudes of the individual phase values.

A total-only display could hide this behavior.

The Viewer therefore supports per-phase inspection and a separate TOTAL view.

The four-quadrant vector display can also be inspected for A, B, C, and TOTAL.

---

## 10. Meter TOTAL and Phase Sums

The Emonio supplies a meter-reported TOTAL block.

The Viewer preserves this block.

It does not replace the meter TOTAL with a calculated sum of the phase values.

For analysis, the Viewer can calculate:

$$
P_\Sigma = P_A + P_B + P_C
$$

$$
Q_\Sigma = Q_A + Q_B + Q_C
$$

$$
S_\Sigma = S_A + S_B + S_C
$$

It can then calculate residuals:

$$
\Delta P = P_\mathrm{TOTAL} - P_\Sigma
$$

$$
\Delta Q = Q_\mathrm{TOTAL} - Q_\Sigma
$$

$$
\Delta S = S_\mathrm{TOTAL} - S_\Sigma
$$

These are derived values.

They do not overwrite the Emonio TOTAL measurement.

This allows the operator to compare the meter TOTAL with the sum of the phase blocks without losing either data source.

---

## 11. Consistency Analysis

The Viewer contains an observational validation layer.

For a phase, it can calculate:

$$
\Delta S_{UI} = S - U_\mathrm{RMS} I_\mathrm{RMS}
$$

It can also compare the meter power factor with:

$$
PF_\mathrm{ref} = \frac{P}{S}
$$

when $S \neq 0$.

The validation layer can also observe conditions such as $|P| > S$ or $|Q| > S$ when qualified tolerances are available.

The default design does not assume universal scientific warning thresholds.

This is important because real measurements can include waveform distortion, harmonics, different instrument algorithms, bandwidth effects, and device-specific definitions.

The Viewer reports residuals without forcing the measured values into an idealized model.

---

## 12. Measurement Quality and Timing

The canonical sample model includes explicit quality states:

```text
VALID
DEGRADED
STALE
INVALID
```

The sample also contains acquisition timing information, including:

- cycle start time,
- cycle finish time,
- monotonic start and finish time,
- cycle span, and
- schedule lag.

A measurement is therefore linked to a specific device and acquisition cycle.

This improves traceability when several devices or long recordings are used.

---

## 13. Measurement History

The Viewer keeps rolling history for the canonical quantities.

Available display windows are:

- 30 s,
- 1 min,
- 2 min,
- 5 min, and
- 10 min.

Changing the display window changes only which stored samples are shown.

It does not change the stored values.

The Viewer also supports exact-sample inspection.

This is useful when the user must inspect a sign change, short event, or specific measurement cycle.

---

## 14. SCOPE Waveform Path

The SCOPE subsystem is separate from canonical Modbus acquisition.

Its source identity is:

```text
EMONIO_WEBSOCKET_SCOPE
```

A SCOPE capture can contain:

- waveform channels,
- phase metadata,
- acquisition timing,
- sample count,
- sample interval,
- sample rate,
- frame evidence, and
- payload SHA-256 information.

Per-phase SCOPE metadata can include RMS voltage, RMS current, frequency, power factor, connection state, and capture duration.

The sample rate is derived from the received capture axis and sample count.

The Viewer identifies this as a derived timing value.

SCOPE data do not replace Modbus data.

---

## 15. Instantaneous Waveform Power

When corresponding voltage and current waveform samples are available, the Viewer can calculate:

$$
p[k] = u[k]\,i[k]
$$

for each sample index $k$.

This is instantaneous waveform power derived from the received SCOPE samples.

It is not the same quantity as the canonical Modbus active power $P$.

The distinction is:

```text
Canonical P
    Meter-reported Modbus/TCP active power

p[k]
    Sample-by-sample product of SCOPE voltage and current
```

The Viewer does not use $p[k]$ to replace canonical meter $P$.

It also does not reconstruct missing waveform samples.

Invalid or non-finite SCOPE captures fail closed.

---

## 16. Why Instantaneous Power Is Useful

For voltage and current waveforms:

$$
p(t)=u(t)i(t)
$$

The sign of $p(t)$ can change during one electrical cycle.

This can occur in systems with reactive energy exchange.

For an ideal sinusoidal case:

$$
u(t)=\hat{U}\sin(\omega t)
$$

$$
i(t)=\hat{I}\sin(\omega t-\varphi)
$$

The instantaneous power is:

$$
p(t)=\frac{\hat{U}\hat{I}}{2}
\left[
\cos(\varphi)-\cos(2\omega t-\varphi)
\right]
$$

The first term is related to the average active-power component.

The second term oscillates at twice the fundamental frequency.

Waveform inspection is therefore useful for reactive loads, distorted waveforms, switching circuits, transformers, resonant networks, and other systems where RMS quantities alone do not show the full time-domain behavior.

For non-sinusoidal systems, a single phase-angle model can be insufficient.

---

## 17. Modbus and SCOPE Are Separate Evidence Paths

The Viewer keeps two distinct paths:

```text
Path A:
EMONIO -> Modbus/TCP -> canonical U/I/P/Q/S/PF/f/E

Path B:
EMONIO -> SCOPE WebSocket -> waveform samples and SCOPE metadata
```

Both paths can describe the same experiment, but they are not the same evidence source.

This separation is intentional.

A disagreement between the two paths must remain visible.

Possible causes can include different measurement windows, timing, waveform distortion, channel mapping, scaling, phase reference, or different internal algorithms.

The Viewer does not silently force both paths to agree.

---

## 18. Device Evidence

The Viewer can also read additional Emonio evidence such as:

- KWH IN,
- KWH OUT,
- CONNECTED A,
- CONNECTED B,
- CONNECTED C,
- ERROR, and
- WARNING.

These values are read-only device evidence.

They do not rewrite the canonical measurement sample.

The Viewer also supports read-only CT configuration evidence through Telnet.

Telnet is a separate evidence path.

Credentials are runtime-only and are not stored by the Viewer.

---

## 19. Multi-Device Operation

The Viewer can operate with multiple Emonio devices.

Each device has independent runtime ownership for:

- configuration,
- acquisition worker,
- Modbus client,
- current sample,
- diagnostics,
- history,
- SCOPE state, and
- recording state.

Switching the selected device in the frontend does not change the identity of stored samples.

This is important in laboratory systems where several Emonios measure different locations at the same time.

---

## 20. Recording and Diagnostics

Session recording is per Emonio.

Recorded measurements come from the canonical measurement stream.

Recording does not create a second measurement algorithm.

Acquisition failures are published as explicit diagnostic events.

A diagnostic event can contain device identity, cycle identity, time, affected block, failure type, and detail.

The central rule is:

> **A missing measurement must remain distinguishable from a valid measurement.**

The Viewer does not manufacture continuity when acquisition evidence is missing.

---

## 21. What the Viewer Calculates

The Viewer calculates secondary quantities for analysis.

Examples include:

### Phase sums

$$
P_\Sigma=P_A+P_B+P_C
$$

$$
Q_\Sigma=Q_A+Q_B+Q_C
$$

$$
S_\Sigma=S_A+S_B+S_C
$$

### TOTAL residuals

$$
\Delta P=P_\mathrm{TOTAL}-P_\Sigma
$$

$$
\Delta Q=Q_\mathrm{TOTAL}-Q_\Sigma
$$

$$
\Delta S=S_\mathrm{TOTAL}-S_\Sigma
$$

### RMS consistency residual

$$
\Delta S_{UI}=S-U_\mathrm{RMS}I_\mathrm{RMS}
$$

### Power-factor consistency residual

$$
\Delta PF=PF-\frac{P}{S}
$$

when $S\neq0$.

### Instantaneous waveform power

$$
p[k]=u[k]i[k]
$$

These quantities are calculations based on observed data.

They are not independent measurements.

---

## 22. What the Viewer Does Not Replace

The Viewer does not automatically replace:

- measured $P$ with $UI\cos\varphi$,
- measured $Q$ with $UI\sin\varphi$,
- measured $S$ with $\sqrt{P^2+Q^2}$,
- measured $PF$ with $P/S$,
- meter TOTAL with the phase sums, or
- measured Modbus $P$ with SCOPE-derived power.

For an ideal sinusoidal single-frequency system:

$$
P=UI\cos\varphi
$$

$$
Q=UI\sin\varphi
$$

$$
S=UI
$$

and:

$$
S^2=P^2+Q^2
$$

These are useful reference relationships.

They are not universal replacement rules for all measured waveforms.

The Viewer therefore preserves the instrument values and uses derived equations for analysis.

---

## 23. Negative Active Power and Reactive Exchange

Negative active power is an allowed measurement state.

The Viewer does not reject $P<0$ because of its sign.

A negative value can occur in systems with bidirectional power flow, regeneration, reversed measurement orientation, source behavior, energy return, or unusual phase relationships.

The software preserves the sign. The experimental setup determines the physical interpretation.

Reactive systems also exchange energy between electric and magnetic fields.

For a capacitor:

$$
W_C=\frac{1}{2}CV^2
$$

For an inductor:

$$
W_L=\frac{1}{2}LI^2
$$

In AC systems, this stored energy can move between the source and reactive elements during the cycle.

This can produce intervals of negative instantaneous power even when average active power is positive.

The SCOPE power view shows this behavior in the time domain.

The four-quadrant $P$-$Q$ view shows the power state in the power plane.

These are complementary views.

---

## 24. Scientific Scope

The Viewer can provide evidence such as:

- meter-reported electrical quantities,
- signed active and reactive power,
- waveform samples,
- device metadata,
- acquisition timing,
- four-quadrant state,
- derived residuals,
- instantaneous waveform power, and
- recorded measurement data.

The Viewer can show what the instrument reported and how different observed quantities relate to each other.

The Viewer alone does not prove the complete physical interpretation of an experiment.

A scientific conclusion can also depend on:

- sensor calibration,
- CT orientation,
- voltage reference,
- wiring topology,
- bandwidth,
- grounding,
- synchronization,
- instrument uncertainty,
- external instruments, and
- experimental repeatability.

The software therefore preserves evidence before interpretation.

---

## 25. Acceptance and Current Baseline

The repository includes:

```bash
./tools/ari-emonio-acceptance.sh
```

The acceptance process includes:

- unit tests,
- integration tests,
- frontend tests,
- read-only checks,
- Python compilation, and
- scientific sign-path checks.

The read-only gate helps prevent accidental introduction of a Modbus write path.

The scientific sign-path gate helps prevent future software changes from removing or inverting valid negative $P$ or $Q$ values.

Real-device testing is also part of project qualification.

The current trusted field baseline is:

```text
ARI Emonio Viewer v0.4.7
```

The tested Emonio P3 firmware is:

```text
3.0.79-release
```

---

## 26. Project Structure

Important source areas include:

```text
src/emonio_viewer/modbus/
    Register map, decoder, protocol, transport

src/emonio_viewer/acquisition/
    Acquisition workers and device ownership

src/emonio_viewer/measurement/
    Canonical model, quadrant logic, validation

src/emonio_viewer/scope/
    SCOPE client, protocol, capture model, service

src/emonio_viewer/device_evidence/
    Read-only device evidence

src/emonio_viewer/recording/
    Per-device recording

src/emonio_viewer/diagnostics/
    Runtime diagnostics

src/emonio_viewer/runtime/
    Runtime state and event distribution

src/emonio_viewer/server/
    Local API and WebSocket service

frontend/js/
    Viewer behavior and scientific visualization

frontend/css/
    Structured presentation rules

tests/
    Unit, integration, frontend, and regression tests
```

The separation is intentional.

Acquisition does not depend on presentation logic.

The frontend is not the scientific authority for canonical measurements.

SCOPE data do not replace Modbus data.

Recording does not redefine measurements.

---

## 27. Summary

ARI Emonio Viewer is a local scientific measurement viewer for Emonio P3 devices.

The architecture preserves:

- device identity,
- phase identity,
- measurement sign,
- canonical meter values,
- acquisition timing,
- raw Modbus evidence,
- separate SCOPE waveform evidence,
- exact stored history samples,
- per-device recording, and
- explicit failure states.

The Viewer adds deterministic analysis where useful.

It can calculate phase sums, residuals, quadrant states, vector geometry, and instantaneous waveform power.

These derived values remain separate from the original measurement values.

This makes the Viewer suitable for experiments where unusual power flow, reactive exchange, waveform distortion, phase relationships, or negative active power are important observations.

The project principle is:

> **Preserve the evidence first. Analyze it second.**
