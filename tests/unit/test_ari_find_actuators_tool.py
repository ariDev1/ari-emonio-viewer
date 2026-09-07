from __future__ import annotations

import asyncio
import importlib.util
import ipaddress
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "ari-find-actuators.py"


def _load_tool():
    assert TOOL_PATH.exists(), "tools/ari-find-actuators.py is required"
    spec = importlib.util.spec_from_file_location("ari_find_actuators", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _hello(*, node_id: str = "ARI-LOAD-002", device_class: str = "ARI_LOAD_ACTUATOR", capabilities=None) -> str:
    if capabilities is None:
        capabilities = ["ACTIVE_LOAD_CONTROL", "PWM_DUTY_CONTROL"]
    return json.dumps(
        {
            "message_type": "HELLO",
            "protocol_version": 1,
            "node_id": node_id,
            "boot_id": "BOOT-TEST-002",
            "device_class": device_class,
            "capabilities": capabilities,
            "p_max": {"a": 1000.0, "b": 1000.0, "c": 1000.0},
        }
    )


def test_protocol_qualification_accepts_only_ari_load_actuator_hello() -> None:
    tool = _load_tool()

    hello = tool.qualify_hello_text(_hello())
    assert hello is not None
    assert hello.node_id == "ARI-LOAD-002"
    assert hello.boot_id == "BOOT-TEST-002"

    assert tool.qualify_hello_text(_hello(device_class="OTHER_DEVICE")) is None
    assert tool.qualify_hello_text(_hello(capabilities=["PWM_DUTY_CONTROL"])) is None
    assert tool.qualify_hello_text("not-json") is None


def test_scan_network_returns_only_qualified_hosts_in_ip_order() -> None:
    tool = _load_tool()
    network = ipaddress.ip_network("192.0.2.0/29")
    calls: list[str] = []

    async def fake_probe(address: str):
        calls.append(address)
        if address == "192.0.2.5":
            return tool.FoundActuator(
                ip=address,
                node_id="ARI-LOAD-005",
                boot_id="BOOT-5",
                capabilities=("ACTIVE_LOAD_CONTROL",),
            )
        if address == "192.0.2.2":
            return tool.FoundActuator(
                ip=address,
                node_id="ARI-LOAD-002",
                boot_id="BOOT-2",
                capabilities=("ACTIVE_LOAD_CONTROL", "PWM_DUTY_CONTROL"),
            )
        return None

    found = asyncio.run(tool.scan_network(network, fake_probe, concurrency=3))

    assert calls == [str(item) for item in network.hosts()]
    assert [item.ip for item in found] == ["192.0.2.2", "192.0.2.5"]
    assert [item.node_id for item in found] == ["ARI-LOAD-002", "ARI-LOAD-005"]


def test_report_contains_websocket_and_bench_commands() -> None:
    tool = _load_tool()
    found = [
        tool.FoundActuator(
            ip="192.168.2.147",
            node_id="ARI-LOAD-002",
            boot_id="BOOT-ABC",
            capabilities=("ACTIVE_LOAD_CONTROL", "PWM_DUTY_CONTROL"),
        )
    ]

    report = tool.format_report(
        found,
        network=ipaddress.ip_network("192.168.2.0/24"),
        interface="enp6s0",
        websocket_port=8080,
        websocket_path="/load-control",
        bench_port=2323,
    )

    assert "ARI-LOAD-002" in report
    assert "192.168.2.147" in report
    assert "BOOT-ABC" in report
    assert "ws://192.168.2.147:8080/load-control" in report
    assert "nc 192.168.2.147 2323" in report
    assert "No control commands were sent." in report
