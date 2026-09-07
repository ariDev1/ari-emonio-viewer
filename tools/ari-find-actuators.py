#!/usr/bin/env python3
"""Find ARI load actuators by their protocol HELLO identity.

The tool scans one local IPv4 network for the actuator WebSocket endpoint,
reads only the first HELLO frame, validates the ARI actuator identity, and
closes the connection. It does not send actuator control commands.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
from typing import Awaitable, Callable

from aiohttp import ClientSession, WSMsgType


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from emonio_viewer.load_control.protocol import HelloFrame, ProtocolError, decode_frame
from emonio_viewer.load_control.qualification import (
    REQUIRED_CAPABILITY,
    REQUIRED_DEVICE_CLASS,
)


DEFAULT_WEBSOCKET_PORT = 8080
DEFAULT_WEBSOCKET_PATH = "/load-control"
DEFAULT_BENCH_PORT = 2323
DEFAULT_CONNECT_TIMEOUT_S = 0.6
DEFAULT_HELLO_TIMEOUT_S = 1.0
DEFAULT_CONCURRENCY = 64
MAX_NETWORK_ADDRESSES = 4096


@dataclass(frozen=True, slots=True)
class FoundActuator:
    ip: str
    node_id: str
    boot_id: str
    capabilities: tuple[str, ...]


def qualify_hello_text(text: str) -> HelloFrame | None:
    """Return a qualified HELLO or None for any non-ARI endpoint."""

    try:
        frame = decode_frame(text)
    except (ProtocolError, TypeError, ValueError):
        return None
    if not isinstance(frame, HelloFrame):
        return None
    if frame.device_class != REQUIRED_DEVICE_CLASS:
        return None
    if REQUIRED_CAPABILITY not in frame.capabilities:
        return None
    return frame


async def scan_network(
    network: ipaddress.IPv4Network,
    probe: Callable[[str], Awaitable[FoundActuator | None]],
    *,
    concurrency: int,
) -> list[FoundActuator]:
    """Probe all usable addresses and return qualified results in IP order."""

    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("network must be an IPv4Network")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("concurrency must be an integer >= 1")

    semaphore = asyncio.Semaphore(concurrency)

    async def limited(address: str) -> FoundActuator | None:
        async with semaphore:
            return await probe(address)

    addresses = [str(address) for address in network.hosts()]
    results = await asyncio.gather(*(limited(address) for address in addresses))
    found = [item for item in results if item is not None]
    return sorted(found, key=lambda item: ipaddress.ip_address(item.ip))


async def _probe_address(
    client: ClientSession,
    address: str,
    *,
    websocket_port: int,
    websocket_path: str,
    connect_timeout_s: float,
    hello_timeout_s: float,
) -> FoundActuator | None:
    location = f"ws://{address}:{websocket_port}{websocket_path}"
    websocket = None
    try:
        websocket = await asyncio.wait_for(
            client.ws_connect(location, autoping=True, heartbeat=None),
            timeout=connect_timeout_s,
        )
        message = await asyncio.wait_for(websocket.receive(), timeout=hello_timeout_s)
        if message.type is not WSMsgType.TEXT or not isinstance(message.data, str):
            return None
        hello = qualify_hello_text(message.data)
        if hello is None:
            return None
        return FoundActuator(
            ip=address,
            node_id=hello.node_id,
            boot_id=hello.boot_id,
            capabilities=hello.capabilities,
        )
    except (asyncio.TimeoutError, OSError, ValueError):
        return None
    except Exception:
        # HTTP endpoints, failed WebSocket upgrades, and malformed peers are
        # non-actuator scan results. Discovery must continue deterministically.
        return None
    finally:
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                pass


async def discover_network(
    network: ipaddress.IPv4Network,
    *,
    websocket_port: int,
    websocket_path: str,
    connect_timeout_s: float,
    hello_timeout_s: float,
    concurrency: int,
) -> list[FoundActuator]:
    async with ClientSession() as client:
        async def probe(address: str) -> FoundActuator | None:
            return await _probe_address(
                client,
                address,
                websocket_port=websocket_port,
                websocket_path=websocket_path,
                connect_timeout_s=connect_timeout_s,
                hello_timeout_s=hello_timeout_s,
            )

        return await scan_network(network, probe, concurrency=concurrency)


def _run_ip_json(arguments: list[str]) -> object:
    completed = subprocess.run(
        ["ip", "-j", "-4", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def detect_local_network() -> tuple[ipaddress.IPv4Network, str]:
    """Return the network and interface used by the IPv4 default route."""

    routes = _run_ip_json(["route", "show", "default"])
    if not isinstance(routes, list):
        raise RuntimeError("cannot read the IPv4 default route")
    candidates = [
        route
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("dev"), str)
    ]
    if not candidates:
        raise RuntimeError("no IPv4 default-route interface was found")
    candidates.sort(key=lambda route: int(route.get("metric", 0)))
    interface = candidates[0]["dev"]

    addresses = _run_ip_json(["addr", "show", "dev", interface])
    if not isinstance(addresses, list) or not addresses:
        raise RuntimeError(f"no IPv4 address data was found for {interface}")

    address_info = addresses[0].get("addr_info", []) if isinstance(addresses[0], dict) else []
    global_ipv4 = [
        item
        for item in address_info
        if isinstance(item, dict)
        and item.get("family") == "inet"
        and item.get("scope") == "global"
        and isinstance(item.get("local"), str)
        and isinstance(item.get("prefixlen"), int)
    ]
    if not global_ipv4:
        raise RuntimeError(f"no global IPv4 address was found for {interface}")

    selected = global_ipv4[0]
    network = ipaddress.ip_network(
        f"{selected['local']}/{selected['prefixlen']}",
        strict=False,
    )
    if not isinstance(network, ipaddress.IPv4Network):
        raise RuntimeError("detected network is not IPv4")
    return network, interface


def format_report(
    found: list[FoundActuator],
    *,
    network: ipaddress.IPv4Network,
    interface: str,
    websocket_port: int,
    websocket_path: str,
    bench_port: int,
) -> str:
    lines = [
        "ARI actuator discovery",
        f"Network: {network} ({interface})",
        "Discovery method: protocol-qualified WebSocket HELLO",
        "No control commands were sent.",
        "",
    ]
    if not found:
        lines.append("No protocol-qualified ARI load actuator was found.")
        return "\n".join(lines)

    for item in found:
        capabilities = ",".join(item.capabilities)
        lines.extend(
            [
                f"{item.node_id}  {item.ip}",
                f"  Boot ID: {item.boot_id}",
                f"  Capabilities: {capabilities}",
                f"  WebSocket: ws://{item.ip}:{websocket_port}{websocket_path}",
                f"  Bench: nc {item.ip} {bench_port}",
            ]
        )
    return "\n".join(lines)


def _positive_float(text: str) -> float:
    value = float(text)
    if value <= 0.0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return value


def _port(text: str) -> int:
    value = int(text)
    if value < 1 or value > 65535:
        raise argparse.ArgumentTypeError("port must be in 1..65535")
    return value


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find ARI load actuators without relying on mDNS.",
    )
    parser.add_argument(
        "--network",
        help="IPv4 CIDR to scan. Default: network of the IPv4 default route.",
    )
    parser.add_argument("--port", type=_port, default=DEFAULT_WEBSOCKET_PORT)
    parser.add_argument("--path", default=DEFAULT_WEBSOCKET_PATH)
    parser.add_argument("--bench-port", type=_port, default=DEFAULT_BENCH_PORT)
    parser.add_argument(
        "--connect-timeout",
        type=_positive_float,
        default=DEFAULT_CONNECT_TIMEOUT_S,
    )
    parser.add_argument(
        "--hello-timeout",
        type=_positive_float,
        default=DEFAULT_HELLO_TIMEOUT_S,
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=DEFAULT_CONCURRENCY,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        if args.network:
            parsed = ipaddress.ip_network(args.network, strict=False)
            if not isinstance(parsed, ipaddress.IPv4Network):
                raise ValueError("--network must be IPv4")
            network = parsed
            interface = "operator-specified"
        else:
            network, interface = detect_local_network()

        if network.num_addresses > MAX_NETWORK_ADDRESSES:
            raise ValueError(
                f"network {network} contains {network.num_addresses} addresses; "
                f"use --network with a subnet of at most {MAX_NETWORK_ADDRESSES} addresses"
            )
        if not isinstance(args.path, str) or not args.path.startswith("/"):
            raise ValueError("--path must start with /")

        print(
            f"Scanning {network} for ws://<host>:{args.port}{args.path} ...",
            flush=True,
        )
        found = asyncio.run(
            discover_network(
                network,
                websocket_port=args.port,
                websocket_path=args.path,
                connect_timeout_s=args.connect_timeout,
                hello_timeout_s=args.hello_timeout,
                concurrency=args.concurrency,
            )
        )
        print(
            format_report(
                found,
                network=network,
                interface=interface,
                websocket_port=args.port,
                websocket_path=args.path,
                bench_port=args.bench_port,
            )
        )
        return 0 if found else 1
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ARI actuator discovery ERROR: {exc}", file=sys.stderr)
        print("No control commands were sent.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
