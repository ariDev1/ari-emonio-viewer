from __future__ import annotations

import asyncio
from ipaddress import ip_address
import math
from typing import Any

from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

from .discovery import MdnsResolvedService


class _ServiceNameListener:
    def __init__(self) -> None:
        self.names: set[str] = set()

    def add_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.names.add(name)

    def update_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.names.add(name)

    def remove_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.names.discard(name)


def _positive_seconds(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    return seconds


def _timeout_milliseconds(seconds: float) -> int:
    return max(1, math.ceil(seconds * 1000.0))


def _first_ipv4(addresses: list[str]) -> str | None:
    for address in addresses:
        try:
            parsed = ip_address(address)
        except ValueError:
            continue
        if parsed.version == 4:
            return str(parsed)
    return None


class ZeroconfMdnsBackend:
    """Real mDNS browse/resolve backend with explicit timing inputs.

    This class discovers network locations only. It cannot bind an actuator,
    enable external control, or send a load command.
    """

    def __init__(
        self,
        *,
        aiozc_factory=AsyncZeroconf,
        browser_factory=AsyncServiceBrowser,
        sleep=asyncio.sleep,
    ) -> None:
        self._aiozc_factory = aiozc_factory
        self._browser_factory = browser_factory
        self._sleep = sleep

    async def scan(
        self,
        *,
        service_type: str,
        discovery_window_s: float,
        resolve_timeout_s: float,
    ) -> tuple[MdnsResolvedService, ...]:
        if not isinstance(service_type, str) or not service_type:
            raise ValueError("service_type must be non-empty text")
        discovery_window = _positive_seconds(discovery_window_s, "discovery_window_s")
        resolve_timeout = _positive_seconds(resolve_timeout_s, "resolve_timeout_s")
        resolve_timeout_ms = _timeout_milliseconds(resolve_timeout)

        aiozc = self._aiozc_factory()
        try:
            listener = _ServiceNameListener()
            browser = self._browser_factory(
                aiozc.zeroconf,
                service_type,
                listener=listener,
            )
            try:
                await self._sleep(discovery_window)
            finally:
                await browser.async_cancel()

            records: list[MdnsResolvedService] = []
            for name in sorted(listener.names):
                info = await aiozc.async_get_service_info(
                    service_type,
                    name,
                    resolve_timeout_ms,
                )
                if info is None:
                    continue
                address = _first_ipv4(list(info.parsed_addresses()))
                if address is None:
                    continue
                records.append(
                    MdnsResolvedService(
                        address=address,
                        port=info.port,
                        properties=info.properties,
                    )
                )
            return tuple(records)
        finally:
            await aiozc.async_close()
