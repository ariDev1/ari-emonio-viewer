# ARI Emonio Viewer v0.1.9 WebSocket Disconnect Evidence

## Field evidence

A real v0.1.8 Candidate run produced two `aiohttp.client_exceptions.ClientConnectionResetError` tracebacks from `src/emonio_viewer/server/websocket.py` while `ws.send_json(...)` attempted to write to a closing browser transport. The measurement and device configuration values remained correct. v0.1.8 was therefore not promoted to the trusted field baseline.

## Root cause

`websocket_measurements()` checked `ws.closed` before waiting for the next runtime event. The client transport could close after that check and before the next `send_json()` call. The next measurement then raised `ClientConnectionResetError`.

## Regression test

A deterministic integration test injects the same `ClientConnectionResetError` from the WebSocket send boundary. Before the correction, the test fails with the field exception. After the correction, the handler exits and unsubscribes the client. A second test raises an unrelated `RuntimeError` and requires that error to remain visible.

## Correction

The send boundary catches only `aiohttp.client_exceptions.ClientConnectionResetError` and breaks the per-client send loop. The existing `finally` block unsubscribes the subscriber. No acquisition, Modbus, recording, CT evidence, persistence, or shutdown transport code was modified for this correction.

## Field status

v0.1.9 is software-qualified only. v0.1.7 remains the trusted field baseline until real-device persistence, Ctrl+C shutdown, and WebSocket lifecycle behavior are confirmed.
