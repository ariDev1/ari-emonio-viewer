import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.recording.trigger import (
    TriggerBlock,
    TriggerMeasurement,
    TriggerMode,
    TriggerOperator,
)
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app


class FakeRecordingManager:
    def __init__(self):
        self.calls = []
        self.active = ()
        self.errors = ()
        self.triggers = ()
        self.disabled = False
        self.configured = False

    def active_recordings(self):
        return tuple(self.active)

    def recording_failures(self):
        return tuple(self.errors)

    def trigger_statuses(self):
        return tuple(self.triggers)

    def configure_trigger(self, config):
        if self.disabled:
            raise RuntimeError("recording commands disabled")
        self.calls.append(("configure", config))
        self.configured = True
        status = {
            "device_id": config.device_id,
            "state": "DISARMED",
            "config": {
                "block": config.block.value,
                "measurement": config.measurement.value,
                "operator": config.operator.value,
                "threshold": config.threshold,
                "mode": config.mode.value,
                "recording_interval_s": config.recording_interval_s,
            },
            "armed_utc": None,
            "last_fired_cycle_id": None,
            "last_fired_utc": None,
            "last_fired_value": None,
        }
        self.triggers = (status,)
        return status

    def arm_trigger(self, device_id):
        if self.disabled:
            raise RuntimeError("recording commands disabled")
        if self.active:
            raise RuntimeError("recording already active")
        if not self.configured:
            raise RuntimeError("trigger not configured")
        self.calls.append(("arm", device_id))
        status = dict(self.triggers[0])
        status["state"] = "ARMED"
        status["armed_utc"] = "2026-08-31T06:00:00+00:00"
        self.triggers = (status,)
        return status

    def disarm_trigger(self, device_id):
        if self.disabled:
            raise RuntimeError("recording commands disabled")
        if not self.configured:
            raise RuntimeError("trigger not configured")
        self.calls.append(("disarm", device_id))
        status = dict(self.triggers[0])
        status["state"] = "DISARMED"
        status["armed_utc"] = None
        self.triggers = (status,)
        return status


def build_app(tmp_path, real_sample, device_config):
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(
        ViewerConfig(device_config.id),
        RecordingConfig(10.0),
        (device_config,),
    )
    manager = FakeRecordingManager()
    return create_app(config, store, bus, manager, frontend), manager


async def request(app, method, path, body=None):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.request(method, path, json=body)
            payload = await response.json() if response.content_type == "application/json" else None
            return response.status, payload


def valid_body(device_config):
    return {
        "device_id": device_config.id,
        "block": "A",
        "measurement": "P",
        "operator": "GT",
        "threshold": 1000.25,
        "mode": "CROSSING",
        "recording_interval_s": device_config.poll_interval_s,
    }


def test_configure_trigger_parses_exact_contract(tmp_path, real_sample, device_config):
    app, manager = build_app(tmp_path, real_sample, device_config)
    status, payload = asyncio.run(
        request(app, "POST", "/api/v1/recording/trigger/configure", valid_body(device_config))
    )
    assert status == 200
    assert payload["state"] == "DISARMED"
    config = manager.calls[-1][1]
    assert config.block is TriggerBlock.A
    assert config.measurement is TriggerMeasurement.P
    assert config.operator is TriggerOperator.GT
    assert config.threshold == 1000.25
    assert config.mode is TriggerMode.CROSSING
    assert config.recording_interval_s == device_config.poll_interval_s


def test_recording_status_includes_trigger_collection(tmp_path, real_sample, device_config):
    app, manager = build_app(tmp_path, real_sample, device_config)
    manager.configure_trigger(
        __import__("emonio_viewer.recording.trigger", fromlist=["TriggerConfig"]).TriggerConfig(
            device_id=device_config.id,
            block=TriggerBlock.A,
            measurement=TriggerMeasurement.P,
            operator=TriggerOperator.GT,
            threshold=1.23456789,
            mode=TriggerMode.LEVEL,
            recording_interval_s=device_config.poll_interval_s,
        )
    )
    status, payload = asyncio.run(request(app, "GET", "/api/v1/recording/status"))
    assert status == 200
    assert set(payload) == {"active", "errors", "triggers"}
    assert payload["triggers"][0]["config"]["threshold"] == 1.23456789


def test_arm_and_disarm_trigger_endpoints(tmp_path, real_sample, device_config):
    app, manager = build_app(tmp_path, real_sample, device_config)
    asyncio.run(request(app, "POST", "/api/v1/recording/trigger/configure", valid_body(device_config)))
    status, payload = asyncio.run(
        request(app, "POST", "/api/v1/recording/trigger/arm", {"device_id": device_config.id})
    )
    assert status == 200
    assert payload["state"] == "ARMED"
    status, payload = asyncio.run(
        request(app, "POST", "/api/v1/recording/trigger/disarm", {"device_id": device_config.id})
    )
    assert status == 200
    assert payload["state"] == "DISARMED"


def test_arm_without_configuration_returns_conflict(tmp_path, real_sample, device_config):
    app, _ = build_app(tmp_path, real_sample, device_config)
    status, _ = asyncio.run(
        request(app, "POST", "/api/v1/recording/trigger/arm", {"device_id": device_config.id})
    )
    assert status == 409


def test_arm_while_recording_returns_conflict(tmp_path, real_sample, device_config):
    app, manager = build_app(tmp_path, real_sample, device_config)
    asyncio.run(request(app, "POST", "/api/v1/recording/trigger/configure", valid_body(device_config)))
    manager.active = ({"device_id": device_config.id},)
    status, _ = asyncio.run(
        request(app, "POST", "/api/v1/recording/trigger/arm", {"device_id": device_config.id})
    )
    assert status == 409
    assert manager.active == ({"device_id": device_config.id},)


def test_trigger_commands_disabled_return_service_unavailable(tmp_path, real_sample, device_config):
    app, manager = build_app(tmp_path, real_sample, device_config)
    manager.disabled = True
    for path, body in (
        ("/api/v1/recording/trigger/configure", valid_body(device_config)),
        ("/api/v1/recording/trigger/arm", {"device_id": device_config.id}),
        ("/api/v1/recording/trigger/disarm", {"device_id": device_config.id}),
    ):
        status, _ = asyncio.run(request(app, "POST", path, body))
        assert status == 503


def test_trigger_configure_rejects_unknown_device(tmp_path, real_sample, device_config):
    app, _ = build_app(tmp_path, real_sample, device_config)
    body = valid_body(device_config)
    body["device_id"] = "missing"
    status, _ = asyncio.run(request(app, "POST", "/api/v1/recording/trigger/configure", body))
    assert status == 404


@__import__("pytest").mark.parametrize(
    ("field", "value"),
    [
        ("block", "D"),
        ("measurement", "ENERGY"),
        ("operator", "EQ"),
        ("mode", "REPEAT"),
        ("threshold", "not-a-number"),
        ("threshold", float("nan")),
        ("threshold", float("inf")),
        ("recording_interval_s", 0),
        ("recording_interval_s", float("nan")),
        ("recording_interval_s", float("inf")),
    ],
)
def test_trigger_configure_rejects_invalid_input(
    tmp_path, real_sample, device_config, field, value
):
    app, _ = build_app(tmp_path, real_sample, device_config)
    body = valid_body(device_config)
    body[field] = value
    status, _ = asyncio.run(request(app, "POST", "/api/v1/recording/trigger/configure", body))
    assert status == 400


def test_trigger_configure_rejects_interval_below_acquisition(tmp_path, real_sample, device_config):
    app, _ = build_app(tmp_path, real_sample, device_config)
    body = valid_body(device_config)
    body["recording_interval_s"] = device_config.poll_interval_s / 2
    status, _ = asyncio.run(request(app, "POST", "/api/v1/recording/trigger/configure", body))
    assert status == 400
