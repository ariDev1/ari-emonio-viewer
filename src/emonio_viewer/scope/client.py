from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid

import aiohttp
from yarl import URL

from .model import ScopeCapture, ScopeMetadata, ScopeWaveformFrame
from .protocol import SCOPE_COMMAND, build_capture, decode_binary_frame, decode_metadata

import re

# Local firmware-version shapes for the device web pages this transport
# already reads. Kept inside scope on purpose: the scope package must not
# import device_evidence (see test_scope_read_only_contract). Agreement with
# device_evidence.firmware.parse_firmware_version is pinned by unit test.
_FIRMWARE_VERSION_PATTERNS = (
    re.compile(r"Version\s*:\s*([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?)"),
    re.compile(r'"version"\s*:\s*"([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?)"'),
)
_STRICT_FIRMWARE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?\Z")


def extract_firmware_version(text: str) -> str | None:
    """Return the first strictly-shaped firmware version in text, if any."""
    if not isinstance(text, str) or not text:
        return None
    for pattern in _FIRMWARE_VERSION_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        candidate = match.group(1)
        if len(candidate) <= 32 and _STRICT_FIRMWARE_VERSION.match(candidate):
            return candidate
    return None


class ScopeClientError(RuntimeError):
    """Raised when the read-only Emonio scope transport cannot produce a valid capture."""


# Read-only web paths that may expose the Emonio device page. "/" is first:
# login already proves the device serves its web interface there.
_FIRMWARE_PROBE_PATHS = ("/", "/api/device", "/status", "/info")


def _base_url(host: str) -> str:
    value = host.strip()
    if not value:
        raise ValueError("scope host must not be empty")
    if "://" in value:
        parsed = URL(value)
        if parsed.scheme != "http" or not parsed.host:
            raise ValueError("scope host must use plain HTTP")
        if parsed.path not in {"", "/"} or parsed.query_string or parsed.fragment:
            raise ValueError("scope host must contain only host and optional port")
        return str(parsed.with_path("" )).rstrip("/")
    return f"http://{value.rstrip('/')}"


def _multipart_login_body(username: str, password: str, boundary: str) -> bytes:
    chunks: list[bytes] = []
    for name, value in (("USER", username), ("PASS", password)):
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n'.encode("ascii"),
                b"\r\n",
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


class EmonioScopeClient:
    __slots__ = ("_session", "_ws", "_base", "_closed")

    def __init__(
        self,
        session: aiohttp.ClientSession,
        ws: aiohttp.ClientWebSocketResponse,
        base: str,
    ) -> None:
        self._session = session
        self._ws = ws
        self._base = base
        self._closed = False

    @classmethod
    async def connect(
        cls,
        host: str,
        username: str,
        password: str,
        *,
        timeout_s: float = 8.0,
    ) -> "EmonioScopeClient":
        if not isinstance(username, str) or not username:
            raise ValueError("username must not be empty")
        if not isinstance(password, str) or not password:
            raise ValueError("password must not be empty")
        base = _base_url(host)
        connector = aiohttp.TCPConnector(force_close=True)
        session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            timeout=aiohttp.ClientTimeout(total=timeout_s),
            connector=connector,
            headers={"User-Agent": "ARI-Emonio-Viewer-Scope"},
        )
        try:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
            body = _multipart_login_body(username, password, boundary)
            login_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Cache-Control": "max-age=0",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "Origin": base,
                "Referer": f"{base}/login",
                "Upgrade-Insecure-Requests": "1",
            }
            async with session.post(
                f"{base}/login",
                data=body,
                headers=login_headers,
                allow_redirects=False,
            ) as response:
                await response.read()
                if response.status != 302 or response.headers.get("Location") != "/":
                    raise ScopeClientError(
                        f"scope login rejected: HTTP {response.status}; "
                        f"Location={response.headers.get('Location', '')!r}"
                    )

            for path in ("/", "/scope"):
                async with session.get(f"{base}{path}", allow_redirects=False) as response:
                    await response.read()
                    if response.status != 200:
                        raise ScopeClientError(f"scope prerequisite {path} returned HTTP {response.status}")

            ws_url = URL(base).with_scheme("ws").with_path("/ws")
            ws = await session.ws_connect(
                ws_url,
                origin=base,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                autoping=True,
                autoclose=True,
                compress=15,
                max_msg_size=4 * 1024 * 1024,
            )
            return cls(session, ws, base)
        except BaseException:
            await session.close()
            raise
        finally:
            username = ""
            password = ""
            body = b"" if "body" in locals() else b""

    async def capture_once(self, *, sequence: int, listen_s: float = 2.0) -> ScopeCapture:
        if self._closed or self._ws.closed:
            raise ScopeClientError("scope WebSocket is closed")
        if listen_s <= 0:
            raise ValueError("listen_s must be greater than zero")

        await self._ws.send_str(SCOPE_COMMAND)
        deadline = asyncio.get_running_loop().time() + listen_s
        channels: dict[int, ScopeWaveformFrame] = {}
        metadata: dict[int, ScopeMetadata] = {}
        channel_order: list[int] = []
        metadata_order: list[int] = []

        while len(channels) < 6 or len(metadata) < 3:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                message = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            if message.type is aiohttp.WSMsgType.BINARY:
                try:
                    frame = decode_binary_frame(bytes(message.data))
                except ValueError as exc:
                    raise ScopeClientError(f"invalid scope binary frame: {exc}") from exc
                if frame.channel in channels:
                    raise ScopeClientError(f"duplicate scope channel {frame.channel} in one capture")
                channels[frame.channel] = frame
                channel_order.append(frame.channel)
                continue

            if message.type is aiohttp.WSMsgType.TEXT:
                try:
                    item = decode_metadata(str(message.data))
                except ValueError as exc:
                    raise ScopeClientError(f"invalid scope metadata: {exc}") from exc
                if item is None:
                    continue
                if item.phase in metadata:
                    raise ScopeClientError(f"duplicate scope metadata phase {item.phase} in one capture")
                metadata[item.phase] = item
                metadata_order.append(item.phase)
                continue

            if message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            }:
                break
            if message.type is aiohttp.WSMsgType.ERROR:
                raise ScopeClientError(f"scope WebSocket receive error: {self._ws.exception()}")

        if len(channels) != 6 or len(metadata) != 3:
            raise ScopeClientError(
                f"incomplete scope capture: channels={sorted(channels)} metadata={sorted(metadata)}"
            )
        try:
            return build_capture(
                sequence=sequence,
                received_utc=datetime.now(timezone.utc).isoformat(),
                channels=channels,
                metadata=metadata,
                channel_order=tuple(channel_order),
                metadata_order=tuple(metadata_order),
            )
        except ValueError as exc:
            raise ScopeClientError(f"invalid complete scope capture: {exc}") from exc

    async def fetch_firmware(self) -> str:
        """Best-effort firmware discovery over the authenticated web session.

        Raises ScopeClientError when no page yields a version. Callers must
        treat this as optional evidence and never fail a scope session
        because of it.
        """
        if self._closed or self._ws.closed:
            raise ScopeClientError("scope WebSocket is closed")
        last_error = "no candidate path attempted"
        for path in _FIRMWARE_PROBE_PATHS:
            try:
                async with self._session.get(
                    f"{self._base}{path}", allow_redirects=False
                ) as response:
                    if response.status != 200:
                        last_error = f"{path}: HTTP {response.status}"
                        continue
                    body = await response.read()
            except Exception as exc:
                last_error = f"{path}: {type(exc).__name__}"
                continue
            if len(body) > 256 * 1024:
                last_error = f"{path}: response exceeded safety limit"
                continue
            version = extract_firmware_version(body.decode("utf-8", errors="replace"))
            if version is not None:
                return version
            last_error = f"{path}: no version string in response"
        raise ScopeClientError(f"no Emonio firmware version found ({last_error})")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if not self._ws.closed:
                await self._ws.close()
        finally:
            await self._session.close()
