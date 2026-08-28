# Security

ARI Emonio Viewer is local technical measurement software.

## Device access

- Modbus writes are forbidden. Production Modbus access is read-only.
- The integrated CT reader exposes only qualified read commands.
- The viewer HTTP service binds to `127.0.0.1`.

## Credentials

SCOPE credentials, CT passwords, and authentication cookies are runtime-only.
Do not store or commit them in configuration, recordings, logs, captures,
tests, screenshots, browser storage, or repository files.

The CT reader uses the Emonio factory-default administrator username `admin`.
The device-specific password must remain runtime-only.

## Scientific boundary

Modbus and SCOPE are separate measurement sources. Do not merge, substitute,
correct, average, reconstruct, or infer one from the other. Invalid waveform
captures must fail closed and exact received samples must remain unchanged.

## Reporting

Do not post passwords, cookies, private keys, or private network details in a
public issue. Use GitHub private vulnerability reporting when enabled.
