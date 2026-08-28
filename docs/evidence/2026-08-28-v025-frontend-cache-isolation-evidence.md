# ARI Emonio Viewer v0.2.5 Frontend Cache Isolation Evidence

## Release status

- Candidate: `v0.2.5`
- Derived from: rejected `v0.2.4`
- Trusted field baseline remains: `v0.2.0`
- Field acceptance: not yet confirmed

## Real-device failure evidence from v0.2.4

The real-device workstation screenshot showed that frontend JavaScript did not execute:

- phase measurement rows were absent;
- the active-device selector was empty;
- the header remained at static `No device`, `STARTING`, and `CONNECTING` values;
- Recording remained at its static `STATUS UNKNOWN` state;
- the operator could not connect to any Emonio from the browser.

Source tracing found a release-skew failure mode. v0.2.4 `app.js` imports `getRecordingStatus` from `api.js`, while v0.2.3 `api.js` does not export that symbol. All previous releases used the same `/static/js/...` URLs. The server supplied ETag and Last-Modified headers but no release-specific asset namespace. A browser could therefore combine modules from different releases and fail module linking before `main()` executed.

## v0.2.5 correction

v0.2.5 makes the frontend asset namespace release-specific at the server boundary:

```text
/static/<application-version>/css/...
/static/<application-version>/js/...
```

The served index is generated from the unchanged source HTML links and rewrites `/static/...` references to the current application-version namespace. The index response is `Cache-Control: no-store`.

The launcher also opens the document with a release-qualified query:

```text
http://127.0.0.1:8787/?v=<application-version>
```

Relative ES-module imports remain relative, so when `app.js` is loaded from the release-specific namespace its `./api.js`, `./history.js`, and other dependencies stay inside that same release namespace.

The unversioned `/static/js/...` route is not registered by v0.2.5.

## Scientific display correction

Before JavaScript has supplied diagnostics evidence, the static Diagnostics summary now reports:

```text
NO DATA
— VALID
— ERRORS
```

It no longer claims `ONLINE` before observed runtime evidence exists.

## Scope boundary

No change was made to:

- Modbus transport or register map;
- acquisition workers or polling;
- canonical measurements or sign handling;
- WebSocket measurement payload;
- CT evidence acquisition;
- per-Emonio recording semantics introduced in v0.2.4;
- device persistence;
- shutdown behavior.

This is software evidence only. Real-device browser qualification is required before promotion.
