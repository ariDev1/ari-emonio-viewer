# ARI Emonio Viewer — Technical Overview

**Document purpose:** Additional technical information for electrical engineers, researchers, and scientific users who want to understand the measurement architecture and scientific boundaries of the ARI Emonio Viewer.

**Current trusted field baseline:** v0.4.7  
**Tested Emonio P3 firmware:** `3.0.79-release`

---

## 1. Project Purpose

ARI Emonio Viewer is a local Linux measurement viewer for Emonio P3 power measurement devices.

The project is intended for laboratory work where the user needs direct access to electrical measurements without losing the original sign, phase assignment, timing information, or device identity.

The Viewer is designed for work with three-phase systems and bidirectional power flow. It can display positive and negative active power \(P\), positive and negative reactive power \(Q\), apparent power \(S\), voltage, current, power factor, frequency, energy, waveform data, and related device evidence.

The project is not designed as a generic consumer dashboard. It is designed as a scientific measurement interface.

The central rule is simple:

> **Measured data must remain identifiable as measured data. Derived data must remain identifiable as derived data. Display transformations must not change the scientific meaning of the measurement.**

The Viewer therefore separates acquisition, validation, derivation, visualization, diagnostics, and recording.

---

## 2. Scientific Design Principles

The ARI Emonio Viewer follows several rules that are important for scientific work.

### 2.1 Preserve the original sign

The Viewer does not convert negative active power into positive active power.

It does not convert negative reactive power into positive reactive power.

If the Emonio reports:

\[
P < 0
\]

the Viewer keeps \(P < 0\).

If the Emonio reports:

\[
Q < 0
\]

the Viewer keeps \(Q < 0\).

This is necessary for four-quadrant analysis.

### 2.2 Preserve discrete observations

The measurement history uses stored samples.

The Viewer does not create artificial samples between measured points.

The scientific measurement path does not use:

- smoothing,
- averaging,
- interpolation,
- resampling,
- gap filling,
- synthetic samples,
- automatic sign correction, or
- waveform reconstruction.

A line that is drawn between points is a display aid. It does not create a new measurement.

### 2.3 Do not hide unavailable data

If acquisition fails, the Viewer must not replace the missing observation with a previous value and present it as a new measurement.

Failure states are kept visible through diagnostics and quality information.

### 2.4 Separate data sources

The canonical Modbus/TCP measurements and the SCOPE waveform data are separate measurement sources.

A SCOPE-derived value does not replace a canonical Modbus value.

This separation is especially important for active power.

The Emonio Modbus value \(P\) remains the canonical meter-reported active power.

Waveform-derived instantaneous power is an additional visualization and analysis path.

### 2.5 Separate observation from interpretation

The Viewer shows signs, magnitudes, vectors, residuals, timing, and device state.

It does not automatically claim a physical cause for an observed result.

For example, a negative measured \(P\) is preserved as a negative measured \(P\). The physical interpretation still depends on the wiring, CT direction, voltage reference, instrument convention, experimental topology, and test conditions.

---

## 3. Measurement Architecture

The normal measurement path is:

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
   |
   +--> Event Bus
   |
   +--> Recording
   |
   +--> API / WebSocket
   |
   v
Scientific Viewer
```

The architecture gives each enabled Emonio its own acquisition worker and its own TCP client.

This prevents one device from becoming the acquisition owner of another device.

The software keeps device identity in the canonical sample. A sample contains information such as:

- device ID,
- device name,
- device IP,
- firmware version,
- transport,
- cycle ID,
- acquisition timing,
- measurement values,
- quality state,
- warnings, and
- raw Modbus block evidence.

The current runtime design uses one independent acquisition worker per enabled device.

The default configuration uses a 2.0 s polling interval and a 2.0 s Modbus timeout.

---

## 4. Read-Only Modbus Boundary

The canonical measurement path uses Modbus/TCP in read-only mode.

There is no Modbus write path in the Viewer.

This is a deliberate architectural boundary.

The Viewer is intended to observe the Emonio. It is not intended to change the electrical configuration of the device through Modbus.

The project also avoids reset-on-read MIN/MAX register ranges in the canonical acquisition path.

Auxiliary Modbus evidence reads are controlled through the same runtime ownership model. They do not create a second uncontrolled Modbus client that competes with canonical measurement acquisition.

This single-owner rule reduces timing ambiguity and prevents auxiliary reads from weakening the primary measurement path.

---

## 5. Verified Emonio P3 Register Model

For firmware `3.0.79-release`, the current verified measurement block contains 16 Modbus registers per phase or total block.

The block layout is:

| Register offset | Quantity |
|---:|---|
| 0 | \(U_\mathrm{RMS}\) |
| 2 | \(I_\mathrm{RMS}\) |
| 4 | \(P\) |
| 6 | \(Q\) |
| 8 | \(S\) |
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

The register map identity used by the software is:

```text
P3-3.0.79-verified
```

Each floating-point quantity occupies two 16-bit Modbus registers.

The Viewer uses the verified CDAB word order for decoding.

The decoder rejects a measurement block if:

- the register count is not correct, or
- a required decoded value is not finite.

A non-finite required value is therefore not accepted as a normal scientific measurement.

---

## 6. Canonical Electrical Quantities

For Phase A, Phase B, Phase C, and TOTAL, the canonical model contains:

\[
U_\mathrm{RMS}
\]

\[
I_\mathrm{RMS}
\]

\[
P
\]

\[
Q
\]

\[
S
\]

\[
f
\]

\[
E
\]

\[
PF
\]

These quantities are stored as the values reported through the verified Emonio Modbus register map.

The Viewer does not replace meter-reported \(S\) with a value calculated from \(P\) and \(Q\).

It also does not replace meter-reported \(PF\) with a calculated value.

Instead, calculations can be used as validation residuals while the original meter values remain available.

This is an important distinction between **measurement** and **consistency analysis**.

---

## 7. Signed Active and Reactive Power

The Viewer treats the sign of \(P\) and \(Q\) as scientific information.

For active power:

- \(P > 0\) is classified as positive active flow.
- \(P < 0\) is classified as negative active flow.
- \(P = 0\) is classified as zero active power.

The software does not rename negative power as an error.

The software also does not assume that negative power must be corrected.

The sign is retained for inspection.

For reactive power, the sign is also retained without automatic correction.

This allows the Viewer to represent all four sign combinations of \(P\) and \(Q\).

---

## 8. Four-Quadrant Representation

The four-quadrant engine uses the measured signs of \(P\) and \(Q\).

The software classification is:

| Quadrant | Condition |
|---|---|
| Q1 | \(P > 0,\ Q > 0\) |
| Q2 | \(P < 0,\ Q > 0\) |
| Q3 | \(P < 0,\ Q < 0\) |
| Q4 | \(P > 0,\ Q < 0\) |

Axis states and the origin are also treated explicitly.

This means the software does not force a sample on an axis into one of the four open quadrants.

The Viewer can display the power vector in the \(P\)-\(Q\) plane.

The basic geometric quantities are:

\[
S_\mathrm{geom} = \sqrt{P^2 + Q^2}
\]

and

\[
\varphi = \operatorname{atan2}(Q,P)
\]

when these values are used for vector geometry.

However, the geometric magnitude must not be confused with the meter-reported apparent power value \(S\).

The Viewer keeps the meter-reported \(S\) as its own quantity.

This distinction is useful because real instruments can report values that do not satisfy idealized identities exactly.

---

## 9. Per-Phase and TOTAL Analysis

The Viewer provides separate analysis for:

- Phase A,
- Phase B,
- Phase C, and
- TOTAL.

This is important in an unbalanced three-phase system.

A total value can hide different behavior on the individual phases.

For example:

```text
Phase A: P > 0
Phase B: P < 0
Phase C: P > 0
```

can still produce a positive or negative total depending on the magnitudes.

The Viewer therefore keeps the individual phase values visible.

The four-quadrant vector view can be inspected per phase and for TOTAL.

This allows the user to study the electrical state of each phase instead of reducing the complete system to one total number.

---

## 10. Meter TOTAL Versus Sum of Phases

The Emonio provides a meter-reported TOTAL block.

The Viewer preserves this TOTAL block.

It does not silently replace the device TOTAL with:

\[
P_A + P_B + P_C
\]

The same rule applies to \(Q\) and \(S\).

For analysis, the software calculates:

\[
P_\Sigma = P_A + P_B + P_C
\]

\[
Q_\Sigma = Q_A + Q_B + Q_C
\]

\[
S_\Sigma = S_A + S_B + S_C
\]

It then calculates residuals:

\[
\Delta P = P_\mathrm{TOTAL} - P_\Sigma
\]

\[
\Delta Q = Q_\mathrm{TOTAL} - Q_\Sigma
\]

\[
\Delta S = S_\mathrm{TOTAL} - S_\Sigma
\]

These are derived values.

They do not overwrite the meter data.

This architecture is useful because it allows the user to see both:

1. what the meter reports as TOTAL, and
2. how that value compares with the sum of the phase blocks.

---

## 11. Observational Consistency Checks

The Viewer contains a validation layer.

For a phase, it can calculate the difference between meter-reported apparent power and the product of RMS voltage and current:

\[
\Delta S_{UI} = S - U_\mathrm{RMS} I_\mathrm{RMS}
\]

It can also compare the meter-reported power factor with:

\[
PF_\mathrm{ref} = \frac{P}{S}
\]

when \(S \neq 0\).

The software can also observe whether:

\[
|P| > S
\]

or:

\[
|Q| > S
\]

under a qualified tolerance model.

The important point is that the default V1 behavior is **observational residual reporting**.

Scientific warning thresholds are not assumed to be universally valid.

The default tolerance fields are not qualified.

Therefore, the software does not automatically turn every deviation from an ideal formula into a scientific fault.

This is important for real power measurement because waveform distortion, instrument algorithms, phase relationships, bandwidth, sampling methods, and device-specific definitions can affect the relationship between displayed quantities.

---

## 12. Measurement Quality and Timing

The canonical sample model contains explicit quality states:

```text
VALID
DEGRADED
STALE
INVALID
```

The sample also contains timing information for each acquisition cycle.

This includes:

- cycle start time,
- cycle finish time,
- monotonic start time,
- monotonic finish time,
- cycle span, and
- schedule lag.

The purpose is to keep time as part of the measurement evidence.

A sample is not only a group of numbers. It is a group of numbers associated with a defined device and acquisition cycle.

---

## 13. Measurement History

The Viewer keeps a rolling history for the canonical quantities.

The available display windows are:

- 30 s,
- 1 min,
- 2 min,
- 5 min, and
- 10 min.

The stored measurement history remains based on real acquired samples.

Changing the display window changes which stored samples are rendered.

It does not create new samples.

The Viewer supports exact-sample inspection.

This allows the user to inspect a stored observation instead of estimating a value from the visual position of a line.

This is especially useful when a sign transition or short event must be inspected.

---

## 14. SCOPE Waveform Path

The SCOPE subsystem is separate from canonical Modbus acquisition.

Its source identity is:

```text
EMONIO_WEBSOCKET_SCOPE
```

A SCOPE capture can contain waveform channels, phase metadata, acquisition timing, sample count, and source evidence.

Waveform frames include information such as:

- channel number,
- channel name,
- received frame size,
- header evidence,
- payload SHA-256,
- sample count,
- sample values, and
- non-finite sample count.

Per-phase SCOPE metadata can include:

- phase,
- connection state,
- \(U_\mathrm{RMS}\),
- \(I_\mathrm{RMS}\),
- frequency,
- power factor, and
- capture duration.

The SCOPE axis model contains:

- sample interval, and
- sample rate.

The sample rate is derived from the received capture axis and sample count.

The Viewer identifies this basis explicitly rather than presenting the rate as an independent meter register.

---

## 15. Instantaneous Waveform Power

When corresponding voltage and current waveform samples are available for a phase, the Viewer can calculate instantaneous power for visualization:

\[
p[k] = u[k] \cdot i[k]
\]

for each sample index \(k\).

This is a derived waveform quantity.

It is not the canonical Modbus active power value.

The distinction must remain visible:

```text
Canonical P:
    Emonio Modbus/TCP meter measurement

p[k]:
    sample-by-sample product of received SCOPE voltage and current waveforms
```

The waveform product is useful because it shows when instantaneous power is positive or negative during the electrical cycle.

It can reveal waveform structure that one RMS or averaged power value cannot show.

However, the Viewer does not use SCOPE-derived \(p[k]\) to replace canonical meter \(P\).

It also does not reconstruct missing waveform samples.

Invalid or non-finite SCOPE captures fail closed.

---

## 16. Why Instantaneous Power Is Useful

For periodic voltage and current:

\[
p(t) = u(t)i(t)
\]

The sign of \(p(t)\) can change during a cycle even when average active power has one stable sign.

This is normal in systems with reactive energy exchange.

For an ideal sinusoidal system:

\[
u(t) = \hat{U}\sin(\omega t)
\]

and:

\[
i(t) = \hat{I}\sin(\omega t-\varphi)
\]

The instantaneous power is:

\[
p(t)=\frac{\hat{U}\hat{I}}{2}
\left[
\cos(\varphi)-\cos(2\omega t-\varphi)
\right]
\]

The first term is associated with the average active-power component.

The second term oscillates at twice the fundamental frequency.

This is one reason that waveform inspection is useful in experiments with reactive elements, distorted waveforms, phase shifts, switching circuits, transformers, resonant networks, and other non-trivial loads.

For non-sinusoidal systems, the received waveform data are even more important because a single phase-angle model may not fully describe the electrical behavior.

---

## 17. Modbus Measurement and SCOPE Measurement Must Not Be Mixed

The Viewer intentionally keeps two paths:

```text
Path A:
EMONIO -> Modbus/TCP -> canonical U/I/P/Q/S/PF/f/E

Path B:
EMONIO -> SCOPE WebSocket -> waveform samples and SCOPE metadata
```

These paths can support the same experiment, but they are not the same evidence source.

This prevents a derived waveform result from being presented as if it came from a meter register.

It also allows disagreement between the paths to remain observable.

A disagreement can be scientifically useful.

It can indicate:

- different measurement windows,
- different algorithms,
- different timing,
- waveform distortion,
- channel mapping issues,
- scaling issues,
- phase-reference differences, or
- another condition that requires investigation.

The software should expose such evidence. It should not silently force the two paths to agree.

---

## 18. Device Evidence

The Viewer includes additional read-only device evidence.

The current project can expose:

- KWH IN,
- KWH OUT,
- CONNECTED A,
- CONNECTED B,
- CONNECTED C,
- ERROR, and
- WARNING.

These values are treated as device evidence.

They are not used to rewrite the canonical measurement sample.

The project also includes read-only CT configuration evidence through Telnet.

Telnet is treated as a separate evidence path.

Credentials are runtime-only and are not stored by the Viewer.

The UI distinguishes evidence states instead of pretending that an unavailable Telnet result is an observed configuration.

---

## 19. Multi-Device Operation

The Viewer can work with multiple Emonio devices.

Each device has independent runtime ownership.

The architecture keeps separate:

- configuration,
- acquisition worker,
- Modbus/TCP client,
- current sample,
- diagnostics,
- history,
- SCOPE state, and
- recording ownership.

This separation is important in a laboratory where several meters observe different parts of one experiment.

Switching the selected device in the frontend must not change the scientific identity of stored data.

The selected display target and the data acquisition owner are separate concepts.

---

## 20. Recording

Session recording is per Emonio.

Recorded data originate from the canonical measurement stream.

Recording is not a second measurement algorithm.

The recording path receives the measurement sample after canonical acquisition and decoding.

This keeps the recorded values aligned with the values that the runtime publishes.

The project is designed so that recording state belongs to a device.

A recording operation on one Emonio must not become the recording state of another Emonio.

---

## 21. Diagnostics and Failure Visibility

The Viewer treats acquisition failures as explicit runtime events.

A failure can contain:

- device identity,
- cycle identity,
- time,
- affected block,
- failure type, and
- detail.

Failures are published as diagnostic events.

This supports a central scientific rule:

> **A missing measurement must remain distinguishable from a valid measurement.**

The Viewer must not manufacture continuity when the acquisition path did not provide evidence.

This rule also applies to SCOPE capture failures.

---

## 22. Local Operation and Network Boundary

ARI Emonio Viewer is a local application.

The default web server binding is:

```text
127.0.0.1
```

This means the normal server interface is local to the workstation unless the operator intentionally changes the deployment.

The application communicates with Emonio devices through the local network.

The Viewer is designed for Linux systems and uses a local Python runtime with a browser-based scientific interface.

---

## 23. User Interface Philosophy

The interface is designed to behave like a technical instrument.

Important values have explicit units and signs.

The interface keeps Phase A, Phase B, Phase C, and TOTAL identifiable.

The visual design is intended to support measurement reading rather than decorative presentation.

The current interface includes areas for:

- live phase measurements,
- TOTAL measurements,
- measurement history,
- exact-sample inspection,
- four-quadrant vector analysis,
- SCOPE waveform inspection,
- session recording,
- Modbus device evidence,
- CT evidence, and
- diagnostics.

The project uses separated CSS files for major interface functions.

This keeps visual behavior structured and reduces the risk that an unrelated style change modifies an important scientific panel.

---

## 24. What the Viewer Calculates

The Viewer contains derived quantities.

Examples include:

### 24.1 Phase sums

\[
P_\Sigma=P_A+P_B+P_C
\]

\[
Q_\Sigma=Q_A+Q_B+Q_C
\]

\[
S_\Sigma=S_A+S_B+S_C
\]

### 24.2 TOTAL residuals

\[
\Delta P=P_\mathrm{TOTAL}-P_\Sigma
\]

\[
\Delta Q=Q_\mathrm{TOTAL}-Q_\Sigma
\]

\[
\Delta S=S_\mathrm{TOTAL}-S_\Sigma
\]

### 24.3 RMS consistency residual

\[
\Delta S_{UI}=S-U_\mathrm{RMS}I_\mathrm{RMS}
\]

### 24.4 Power-factor consistency residual

\[
\Delta PF=PF-\frac{P}{S}
\]

when \(S\neq0\).

### 24.5 Waveform instantaneous power

\[
p[k]=u[k]i[k]
\]

These quantities are calculations based on observed data.

They must not be confused with independent measurements.

---

## 25. What the Viewer Does Not Calculate as a Replacement

The Viewer does not automatically replace:

- measured \(P\) with \(UI\cos\varphi\),
- measured \(Q\) with \(UI\sin\varphi\),
- measured \(S\) with \(\sqrt{P^2+Q^2}\),
- measured \(PF\) with \(P/S\),
- measured TOTAL with the sum of the phase blocks, or
- measured Modbus \(P\) with averaged SCOPE \(p[k]\).

These formulas can be useful for analysis.

They are not used to rewrite the original meter evidence.

---

## 26. Scientific Interpretation of \(P\), \(Q\), \(S\), and PF

For an ideal sinusoidal single-frequency case, the familiar relationships are:

\[
P = UI\cos\varphi
\]

\[
Q = UI\sin\varphi
\]

\[
S = UI
\]

and:

\[
S^2=P^2+Q^2
\]

These equations are useful references.

They are not universal replacement rules for every real measured waveform.

In systems with harmonic distortion or non-sinusoidal current, different definitions of apparent power and power factor can be relevant.

For this reason, the Viewer preserves the instrument values and exposes residuals instead of forcing all data into one idealized model.

This is a deliberate scientific design decision.

---

## 27. Negative Active Power

Negative active power is an allowed measurement state in the Viewer.

The software does not treat:

\[
P < 0
\]

as invalid simply because it is negative.

A negative value can be relevant in systems with bidirectional power flow, regeneration, reversed measurement orientation, source behavior, energy return, or experimental phase relationships.

The software records the sign.

The experimental setup determines the physical interpretation.

This distinction prevents software assumptions from hiding a potentially important observation.

---

## 28. Reactive Energy Exchange

Reactive systems exchange energy between electric and magnetic fields.

Capacitors can store energy in an electric field:

\[
W_C = \frac{1}{2}CV^2
\]

Inductors can store energy in a magnetic field:

\[
W_L = \frac{1}{2}LI^2
\]

In AC systems, this stored energy can move between the source, the electric field, and the magnetic field during different parts of a cycle.

This can produce intervals with negative instantaneous power even when the average active power is positive.

The SCOPE power visualization can help make this exchange visible in the time domain.

The four-quadrant \(P\)-\(Q\) view gives a complementary view in the power plane.

These two visualizations answer different questions and should not be treated as equivalent measurements.

---

## 29. Use in Three-Phase Experiments

The Viewer is especially useful when each phase behaves differently.

Examples include:

- unbalanced loads,
- capacitive branches,
- inductive branches,
- mixed RLC networks,
- transformers,
- power-electronic loads,
- regenerative systems,
- resonant circuits,
- switching systems,
- experimental magnetic structures, and
- systems with unusual phase relationships.

The per-phase design allows the user to inspect a condition that would be hidden by a total-only display.

The TOTAL block remains useful for system-level power flow.

The phase blocks remain necessary for understanding how that total is formed.

---

## 30. Evidence Before Interpretation

The project architecture supports a measurement workflow such as:

```text
1. Acquire
2. Decode
3. Validate structure
4. Preserve raw and canonical evidence
5. Publish
6. Record
7. Visualize
8. Derive secondary quantities
9. Compare
10. Interpret
```

Interpretation comes after the measurement evidence is preserved.

This is important for unusual experiments.

If software changes the data before the operator can inspect it, the software can hide the phenomenon that the experiment was designed to study.

---

## 31. Acceptance and Regression Testing

The repository contains an acceptance script:

```bash
./tools/ari-emonio-acceptance.sh
```

The acceptance process includes gates for:

- unit tests,
- integration tests,
- frontend tests,
- read-only behavior,
- Python compilation, and
- the scientific sign path.

The read-only gate is important because a future code change must not accidentally introduce a Modbus write path.

The scientific sign-path gate is important because a future code change must not remove or invert valid negative \(P\) or \(Q\) data.

Field testing on real Emonio P3 devices is also part of the project qualification process.

Software tests and real-device evidence serve different purposes. Both are required for confidence in the complete measurement path.

---

## 32. Scope of Scientific Claims

The ARI Emonio Viewer is measurement and analysis software.

It can provide evidence such as:

- meter-reported electrical quantities,
- waveform samples,
- device metadata,
- timing,
- four-quadrant state,
- derived residuals,
- instantaneous waveform power, and
- recording data.

The Viewer can show that a device reported a value.

It can show how that value relates to other observed values.

It can show a waveform and deterministic calculations derived from that waveform.

The Viewer alone cannot prove the complete physical interpretation of an experiment.

A scientific conclusion can also depend on:

- sensor calibration,
- CT orientation,
- voltage reference,
- wiring topology,
- measurement bandwidth,
- grounding,
- synchronization,
- instrument uncertainty,
- environmental conditions,
- external instruments, and
- experimental repeatability.

The project therefore tries to preserve evidence instead of embedding conclusions into the measurement path.

---

## 33. Intended Users

The technical design is intended for users who need more than a simplified power dashboard.

Typical users include:

- electrical engineers,
- electronics engineers,
- power engineers,
- research laboratories,
- scientific experimenters,
- metrology-oriented developers,
- three-phase system developers, and
- researchers studying bidirectional or reactive power flow.

A basic user can use the live measurement panels.

A scientific user can inspect phase-specific data, history, exact samples, residuals, raw acquisition evidence, SCOPE waveforms, and four-quadrant states.

---

## 34. Current Technical Baseline

At the time of this document, the trusted field baseline is:

```text
ARI Emonio Viewer v0.4.7
```

The tested Emonio firmware is:

```text
3.0.79-release
```

The current repository states the following main scientific boundaries:

- Modbus/TCP canonical measurement is read-only.
- A/B/C/TOTAL are kept as canonical measurement blocks.
- Signed \(P\) and \(Q\) are preserved.
- History uses exact stored samples.
- Multi-device runtime state is isolated.
- Recording is per device.
- Modbus device evidence is read-only.
- CT evidence is read-only.
- SCOPE is a separate waveform source.
- SCOPE instantaneous power is derived for visualization.
- Canonical Modbus \(P\) is not replaced by SCOPE-derived power.
- Non-finite SCOPE data fail closed.
- Credentials are runtime-only.
- No smoothing, interpolation, resampling, gap filling, synthetic samples, or automatic sign correction is permitted in the scientific path.

---

## 35. Relevant Source Areas

The project keeps major functions separated in the repository.

Important locations include:

```text
src/emonio_viewer/modbus/
    Verified register map, decoder, protocol, transport

src/emonio_viewer/acquisition/
    Device acquisition workers and ownership

src/emonio_viewer/measurement/
    Canonical measurement model, quadrant logic, validation

src/emonio_viewer/scope/
    SCOPE client, protocol, capture model, service

src/emonio_viewer/device_evidence/
    Read-only Emonio device evidence

src/emonio_viewer/recording/
    Per-device recording

src/emonio_viewer/diagnostics/
    Runtime diagnostic evidence

src/emonio_viewer/runtime/
    Runtime state and event distribution

src/emonio_viewer/server/
    Local API and WebSocket service

frontend/js/
    Viewer behavior and scientific visualizations

frontend/css/
    Structured presentation rules for individual viewer areas

tests/
    Unit, integration, frontend, read-only, and regression evidence

tools/ari-emonio-acceptance.sh
    Project acceptance gate
```

This structure is intentional.

The acquisition code should not contain presentation logic.

The frontend should not become the scientific authority for canonical measurements.

The SCOPE path should not become a hidden replacement for the Modbus path.

The recording path should not redefine measurements.

Each layer has a limited responsibility.

---

## 36. Summary

ARI Emonio Viewer is a local scientific measurement viewer for Emonio P3 devices.

Its main purpose is not to make electrical measurements look simple.

Its purpose is to make the measurement evidence clear.

The architecture preserves:

- device identity,
- phase identity,
- measurement sign,
- canonical meter values,
- timing,
- raw Modbus evidence,
- separate waveform evidence,
- exact stored history samples,
- per-device recording, and
- explicit failure states.

The Viewer adds deterministic analysis where useful.

It can calculate phase sums, residuals, quadrant states, vector geometry, and instantaneous waveform power.

These derived values remain separate from the original measurement values.

This separation makes the Viewer suitable for experiments where unusual power flow, reactive exchange, waveform distortion, phase relationships, or negative active power are part of the observation rather than conditions that software should automatically remove.

---

## 37. Project Principle

The project can be summarized by one rule:

> **Do not modify the evidence to make the result easier to explain. Preserve the evidence first. Analyze it second.**
