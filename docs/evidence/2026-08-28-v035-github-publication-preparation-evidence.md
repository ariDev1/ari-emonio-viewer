# ARI Emonio Viewer v0.3.5 GitHub Publication Preparation Evidence

## Evidence class

Software-only publication-preparation evidence.

This document is not real-device qualification and is not 24/7 field-stability evidence.

## Baseline

v0.3.5 was prepared from the exact v0.3.4 Candidate ZIP with SHA-256:

```text
dab980f897e81c51161ffcfbacc91d3c596cfa078c2872a2a87f290b6d8edf15
```

The v0.3.4 package passed its unchanged acceptance suite before publication preparation:

```text
112 unit PASS
50 integration PASS
104 frontend PASS
3 read-only PASS
Python compilation PASS
scientific sign path PASS
```

## Publication-preparation scope

The public Candidate changes only repository/publication material and dependency declarations:

- release identity moves to v0.3.5 Candidate;
- the shipped field-device configuration is replaced with one disabled TEST-NET example;
- private field hostname and private network locators are removed from public examples and non-scientific test identities;
- obsolete internal Superpowers planning/specification documents are excluded from the public tree;
- source-available licensing terms are added;
- `SECURITY.md` and `CONTRIBUTING.md` are added;
- `.gitignore` is strengthened for generated, runtime, editor, and local configuration files;
- deterministic release tooling is added;
- staged-tree publication scanning is added;
- directly imported `yarl` is declared explicitly;
- the aiohttp dependency target moves from 3.12.15 to 3.14.3 because upstream security advisories affect the former release.

The production Modbus, canonical measurement, SCOPE scientific model, acquisition, recording science, CT read commands, runtime, diagnostics, and structured CSS are not intentionally changed.

## CT credential boundary

New Emonio devices use the factory administrator username `admin`. The integrated CT reader keeps that username constant. The device-specific password is accepted only at runtime for an explicit CT read and is not stored in repository files, configuration, recordings, evidence objects, or browser storage.

No device-specific password or device-number credential is included in this public Candidate.

## Scientific preservation

The following contracts remain mandatory:

- Modbus writes are forbidden;
- signed P and Q values are preserved;
- four-quadrant semantics are preserved;
- canonical history keeps exact discrete samples;
- SCOPE and Modbus remain separate scientific sources;
- SCOPE uses exact received Float32 samples;
- no smoothing, averaging, interpolation, resampling, gap filling, synthetic samples, sign correction, or waveform reconstruction is added;
- malformed or non-finite SCOPE captures fail closed.

## Publication tests

New tests cover:

- sanitized public default configuration;
- sanitized frontend target examples;
- exclusion of internal planning documents;
- required license/security/contribution files;
- Git ignore safety;
- direct dependency declarations;
- deterministic byte-identical ZIP generation;
- release SHA-256 generation;
- executable mode preservation;
- release exclusion rules;
- publication-gate secret and debris detection;
- publication-gate false-positive resistance for negative regression assertions.

## Current software acceptance

After the publication-preparation changes and the release-output exclusion regression repair, the complete acceptance suite passes in the audit sandbox:

```text
124 unit PASS
50 integration PASS
104 frontend PASS
3 read-only PASS
Python compilation PASS
scientific sign path PASS
```

The audit sandbox used Python 3.13.5 and had aiohttp 3.13.3 installed. Therefore this run does not prove the exact new `aiohttp==3.14.3` dependency target.

## Workstation dependency qualification

The declared dependency target was then installed and tested on the development workstation in a clean Python virtual environment. This is workstation software-acceptance evidence. It is not real-device qualification.

Qualified environment:

```text
Python 3.12
aiohttp 3.14.3
yarl 1.24.2
pytest 8.4.1
```

The complete unchanged acceptance entry point then passed:

```text
123 unit PASS
50 integration PASS
104 frontend PASS
3 read-only PASS
Python compilation PASS
scientific sign path PASS
ARI Emonio Viewer Acceptance: PASS
```

This closes the exact declared `aiohttp==3.14.3` and `yarl==1.24.2` dependency-qualification gate for v0.3.5 source. No real Emonio hardware result is inferred from this software-only run.
