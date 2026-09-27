from __future__ import annotations

import re
import urllib.request

# Candidate read-only web paths that may expose the Emonio device page.
# "/" is first: the SCOPE client already proves the device serves its web
# interface there. Everything here is an unauthenticated HTTP GET, the same
# as opening the page in a browser. No login, no stored credentials.
FIRMWARE_PROBE_PATHS = ("/", "/api/device", "/status", "/info")

_DEFAULT_TIMEOUT_S = 2.0
_MAX_BODY_BYTES = 256 * 1024

# Matches the device page line "Version: 3.0.80-release" as well as JSON
# payloads such as {"version": "3.0.80-release"}.
_VERSION_PATTERNS = (
    re.compile(r"Version\s*:\s*([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?)"),
    re.compile(r'"version"\s*:\s*"([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?)"'),
)

# Strict shape for an accepted version: X.Y.Z with an optional suffix.
_STRICT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?\Z")


class FirmwareProbeError(RuntimeError):
    """Read-only firmware evidence failure with a safe operator-facing state."""

    def __init__(
        self,
        message: str,
        *,
        state: str = "READ_ERROR",
        user_message: str = "Emonio firmware version could not be read.",
    ) -> None:
        super().__init__(message)
        self.state = state
        self.user_message = user_message


def parse_firmware_version(text: str) -> str | None:
    """Return the first strictly-shaped firmware version in text, if any."""
    if not isinstance(text, str) or not text:
        return None
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        candidate = match.group(1)
        if len(candidate) <= 32 and _STRICT_VERSION.match(candidate):
            return candidate
    return None


def probe_firmware_version(
    host: str,
    *,
    port: int = 80,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    paths: tuple[str, ...] = FIRMWARE_PROBE_PATHS,
) -> str:
    """Best-effort read-only firmware discovery over plain HTTP.

    Raises FirmwareProbeError when no candidate path yields a version.
    Callers must treat this as optional evidence and never fail device
    qualification because of it.
    """
    cleaned = host.strip().rstrip("/")
    if not cleaned:
        raise FirmwareProbeError("firmware probe host must not be empty")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise FirmwareProbeError("firmware probe port must be 1..65535")
    if not paths:
        raise FirmwareProbeError("firmware probe has no candidate paths")

    last_error: str | None = None
    for path in paths:
        if not path.startswith("/"):
            continue
        url = f"http://{cleaned}:{port}{path}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ARI-Emonio-Viewer-Firmware-Probe"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                if response.status != 200:
                    last_error = f"{path}: HTTP {response.status}"
                    continue
                body = response.read(_MAX_BODY_BYTES + 1)
        except Exception as exc:
            last_error = f"{path}: {type(exc).__name__}: {exc}"
            continue
        if len(body) > _MAX_BODY_BYTES:
            last_error = f"{path}: response exceeded safety limit"
            continue
        text = body.decode("utf-8", errors="replace")
        version = parse_firmware_version(text)
        if version is not None:
            return version
        last_error = f"{path}: no version string in response"
    raise FirmwareProbeError(
        f"no Emonio firmware version found on read-only web paths ({last_error})",
        state="VERSION_NOT_FOUND",
        user_message=(
            "The Emonio web interface did not expose a firmware version "
            "without login. The measurement path is unaffected."
        ),
    )
