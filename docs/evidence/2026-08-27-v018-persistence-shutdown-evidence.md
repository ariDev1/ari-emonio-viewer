# ARI Emonio Viewer v0.1.8 Persistence and Shutdown Evidence

## Baseline

v0.1.8 Candidate is derived from the field-confirmed v0.1.7 viewer baseline.

Before modification, the extracted v0.1.7 package passed:

- Unit: 71 PASS
- Integration: 31 PASS
- Frontend contract: 20 PASS
- Read-only source gate: 3 PASS
- Python compilation: PASS
- Scientific sign path: PASS

## Remembered-device evidence

The new registry is `config/remembered-devices.json`.

The registry schema contains only:

- `id`
- `name`
- `host`
- `port`
- `unit_id`
- `poll_interval_s`
- `timeout_s`
- `enabled`
- `firmware_version`

It does not serialize passwords, CT evidence, measurements, session notes, or recording data.

Tests prove:

- missing registry -> empty remembered-device set;
- atomic write and round-trip;
- duplicate id rejection;
- duplicate host rejection;
- malformed/unsupported schema rejection;
- successful target persistence occurs after recorder and coordinator registration;
- failed Modbus qualification does not persist a device;
- a persisted qualified target reappears in a fresh runtime configuration load;
- TOML device id/host entries remain authoritative during merge.

## Shutdown root-cause evidence

A controlled integration server accepts one real TCP Modbus request and intentionally withholds the response. The test device retains a 5 s Modbus timeout.

With the v0.1.7 shutdown order, `AcquisitionCoordinator.stop(join_timeout_s=0.75)` sets the stop event and joins the worker before closing the client. The test reproducibly failed after the join bound with:

`RuntimeError: workers did not stop: ['blocking-meter']`

Changing only the coordinator order to close the client before joining was not sufficient on the test platform. A plain cross-thread `socket.close()` did not interrupt the blocked `recv()`.

The additional transport evidence showed that `shutdown(socket.SHUT_RDWR)` before `close()` is required to interrupt the blocked receive. This change made the controlled blocking test pass without reducing the 5 s configured Modbus timeout.

A second deterministic regression exposed a concurrent-close race between the Modbus header and body reads. v0.1.8 keeps a local socket reference for one in-progress response, so shutdown produces an `OSError` transport interruption instead of an internal `AssertionError`.

## Scientific boundary

The shutdown change does not alter:

- Modbus function selection;
- register addresses;
- read-only policy;
- Modbus timeout values;
- CDAB decoding;
- signed P/Q/PF/energy values;
- measurement validation;
- four-quadrant classification;
- recording format;
- Telnet CT evidence commands or interpretation.

## Pre-package software acceptance

After the persistence and shutdown changes, before final packaging:

- Unit: 80 PASS
- Integration: 36 PASS
- Frontend contract: 20 PASS
- Read-only source gate: 3 PASS
- Python compilation: PASS
- Scientific sign path: PASS

Final packaged-ZIP acceptance and SHA-256 are recorded after clean extraction verification.

## Package verification boundary

The final archive is tested only after it is created and extracted into a clean directory. The archive SHA-256 and exact extracted-package acceptance result are stored in an external release verification sidecar next to the ZIP. The ZIP does not contain a self-referential hash claim.
