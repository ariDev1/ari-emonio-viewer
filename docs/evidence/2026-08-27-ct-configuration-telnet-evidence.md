# Emonio CT Configuration Telnet Evidence

Date: 2026-08-27

## Scope

This record qualifies the read-only programmatic path for Emonio current-sensor configuration evidence. It does not qualify physical CT orientation.

## Device

- Hardware: Emonio-P3 (gaua)
- Device identity: field-qualified Emonio P3 (public identifier removed)
- Firmware: `3.0.79-release` (ger)
- Development network locator: removed from public evidence
- Telnet service: enabled

## Manual evidence

The following commands were executed manually on the real device:

```text
conf ct_type
conf ct_voltage
conf ct_range
conf ct_invert
conf ct_didt
```

Observed values:

```text
ct_type=0
ct_voltage=0
ct_range=3
ct_invert=7
ct_didt=0
```

## Automated evidence

The fixed-command probe `emonio_ct_invert_telnet_probe_v0_2_0.py` returned exactly `7` for `conf ct_invert` on the real device.

The fixed-whitelist probe `emonio_ct_config_telnet_probe_v0_3_0.py` then returned exactly:

```text
ct_type=0
ct_voltage=0
ct_range=3
ct_invert=7
ct_didt=0
```

This matches the manual evidence for all five keys.

## Proven transport behavior

The earlier automated reader failed because it treated a repeated shell prompt as command completion. The Emonio terminal can redraw the prompt while a command is still being entered. The field-qualified reader therefore does not use the shell prompt as the completion marker for `conf ct_*` reads. It waits for a complete standalone integer result line.

The qualified transport uses:

- Telnet port `23`
- admin login
- CRLF line ending
- no character pacing
- minimal Telnet option rejection with `DONT` and `WONT`
- one authenticated session for the five fixed reads

## Viewer integration boundary

v0.1.7 Candidate preserves the v0.1.6 transport boundary and keeps the paths separate:

```text
Emonio Modbus/TCP 502 -> measurement acquisition -> canonical measurement model
Emonio Telnet 23      -> CT configuration evidence -> device evidence service
```

The browser talks only to the localhost viewer backend. The CT password is not stored in viewer configuration, recording files, or CT evidence objects.

## Scientific limits

The viewer reports raw device configuration only.

`ct_invert=7` is device configuration evidence. It does not prove that the physical CT orientation, conductor direction, or phase assignment is correct.

The mapping between raw `ct_type`, `ct_voltage`, `ct_range`, and `ct_didt` values and the Emonio web-UI labels is not qualified here. The viewer must not invent that mapping.


## v0.1.7 presentation and failure isolation

v0.1.7 Candidate does not change the field-qualified Telnet reader or the Modbus measurement path. It moves CT configuration controls into a collapsed `Device Evidence` section inside Diagnostics.

The normal measurement viewer does not depend on a successful CT Telnet read. CT evidence states are compact: `NOT READ`, `OBSERVED`, or `READ ERROR`. A later read failure preserves the last successful evidence for the same device. When the selected device changes, CT evidence is cleared before the new device state is loaded so evidence cannot cross device boundaries.
