# Security Policy

ARI Emonio Viewer is technical measurement software for local Emonio P3
systems. Its security boundary is intentionally narrow.

## Read-only Modbus boundary

Modbus writes are forbidden. The production Modbus path uses holding-register
reads only. Do not add register-write functions, write-function codes, or
configuration commands to the Modbus acquisition path.

## SCOPE credentials

SCOPE username and password values are runtime-only. They must not be stored in
TOML, remembered-device JSON, recordings, logs, waveform captures,
`localStorage`, `sessionStorage`, repository files, test fixtures, screenshots,
or documentation. Authentication cookies are also runtime-only and must not be
committed or logged.

## CT Telnet credentials

The CT configuration reader uses the factory-default Emonio administrator
username `admin` and accepts the password only for the explicit localhost read
request. The password must remain runtime-only. Do not commit device-specific
passwords or device-number credentials. The integrated CT reader exposes only
the five qualified read commands. It must not expose an arbitrary Telnet CLI
or configuration-write path.

## Network boundary

The viewer HTTP server binds to `127.0.0.1`. The browser communicates with the
local ARI backend. Emonio device communication takes place from that backend on
the user's local network.

## Scientific security boundary

SCOPE and Modbus are separate scientific sources. Do not substitute, merge,
correct, average, reconstruct, or infer one source from the other. Waveform
validation must fail closed. Exact received samples must remain unchanged.

## Reporting a security issue

Do not post passwords, authentication cookies, private keys, internal network
configuration, or other secret material in a public GitHub issue. Use the
repository owner's private contact method or GitHub private vulnerability
reporting when it is enabled for the repository.
