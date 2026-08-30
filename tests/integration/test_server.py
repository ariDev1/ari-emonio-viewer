from dataclasses import replace
import asyncio
from pathlib import Path

import pytest

from aiohttp.test_utils import TestClient, TestServer

from emonio_viewer.config.model import RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.runtime.events import RuntimeEventBus
from emonio_viewer.runtime.store import RuntimeStore
from emonio_viewer.server.app import create_app
from emonio_viewer.server.keys import EVENT_BUS_KEY


class FakeRecordingManager:
    def __init__(self) -> None:
        self.calls = []
        self.active = ()
        self.errors = ()

    def start(self, device_id, interval_s, session_note=""):
        self.calls.append(("start", device_id, interval_s, session_note))
        return Path("/tmp/test-session")

    def stop(self, device_id):
        self.calls.append(("stop", device_id))

    def set_interval(self, device_id, interval_s):
        self.calls.append(("interval", device_id, interval_s))

    def active_recordings(self):
        return tuple(self.active)

    def recording_failures(self):
        return tuple(self.errors)


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


async def get_json(app, path):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.get(path)
            return response.status, await response.json()


async def post_json(app, path, body):
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(path, json=body)
            payload = await response.json() if response.content_type == "application/json" else {}
            return response.status, payload


def test_devices_endpoint_returns_backend_owned_state(tmp_path, real_sample, device_config) -> None:
    app, _ = build_app(tmp_path, real_sample, device_config)
    status, payload = asyncio.run(get_json(app, "/api/v1/devices"))
    assert status == 200
    assert payload[0]["device_id"] == "emonio-example"
    assert payload[0]["transport"] == "MODBUS_TCP"


def test_read_endpoints_are_present(tmp_path, real_sample, device_config) -> None:
    for path in (
        "/api/v1/devices/emonio-example",
        "/api/v1/diagnostics/emonio-example",
        "/api/v1/config/runtime",
    ):
        app, _ = build_app(tmp_path / path.strip("/").replace("/", "_"), real_sample, device_config)
        status, _ = asyncio.run(get_json(app, path))
        assert status == 200



def test_diagnostics_report_device_firmware_and_verified_register_map(tmp_path, real_sample, device_config) -> None:
    app, _ = build_app(tmp_path, real_sample, device_config)
    status, payload = asyncio.run(get_json(app, f"/api/v1/diagnostics/{device_config.id}"))

    assert status == 200
    assert payload["firmware_version"] == device_config.firmware_version
    assert payload["register_map_id"] == "P3-3.0.79-verified"




def test_diagnostics_report_latency_window_scope(tmp_path, real_sample, device_config) -> None:
    app, _ = build_app(tmp_path, real_sample, device_config)
    status, payload = asyncio.run(get_json(app, f"/api/v1/diagnostics/{device_config.id}"))

    assert status == 200
    assert payload["latency_statistics_scope"] == "ROLLING_VALID_CYCLES"
    assert payload["latency_window_capacity"] >= payload["latency_window_samples"] >= 1

def test_diagnostics_report_event_delivery_drops(tmp_path, real_sample, device_config) -> None:
    app, _ = build_app(tmp_path, real_sample, device_config)
    bus = app[EVENT_BUS_KEY]
    observer = bus.subscribe(maxsize=1)
    bus.publish(real_sample)
    bus.publish(real_sample)

    status, payload = asyncio.run(get_json(app, f"/api/v1/diagnostics/{device_config.id}"))

    bus.unsubscribe(observer)
    assert status == 200
    assert payload["event_deliveries_dropped"] == 1

def test_recording_command_allow_list(tmp_path, real_sample, device_config) -> None:
    app, manager = build_app(tmp_path, real_sample, device_config)
    status, _ = asyncio.run(
        post_json(
            app,
            "/api/v1/recording/start",
            {"device_id": device_config.id, "interval_s": 5.0, "session_note": "load test"},
        )
    )
    assert status == 200
    assert manager.calls[-1] == ("start", device_config.id, 5.0, "load test")


def test_recording_stop_and_interval_are_allowed(tmp_path, real_sample, device_config) -> None:
    app, manager = build_app(tmp_path / "stop", real_sample, device_config)
    status, _ = asyncio.run(post_json(app, "/api/v1/recording/stop", {"device_id": device_config.id}))
    assert status == 200
    assert manager.calls[-1] == ("stop", device_config.id)

    app, manager = build_app(tmp_path / "interval", real_sample, device_config)
    status, payload = asyncio.run(
        post_json(app, "/api/v1/recording/interval", {"device_id": device_config.id, "interval_s": 10})
    )
    assert status == 200
    assert payload["interval_s"] == 10.0
    assert manager.calls[-1] == ("interval", device_config.id, 10.0)


def test_recording_interval_rejects_non_positive_value(tmp_path, real_sample, device_config) -> None:
    app, _ = build_app(tmp_path, real_sample, device_config)
    status, _ = asyncio.run(
        post_json(app, "/api/v1/recording/interval", {"device_id": device_config.id, "interval_s": 0})
    )
    assert status == 400


@pytest.mark.parametrize(
    ("path", "interval_s"),
    (
        ("/api/v1/recording/start", "nan"),
        ("/api/v1/recording/start", "inf"),
        ("/api/v1/recording/interval", "nan"),
        ("/api/v1/recording/interval", "inf"),
    ),
)
def test_recording_commands_reject_non_finite_interval(
    tmp_path, real_sample, device_config, path, interval_s
) -> None:
    app, manager = build_app(tmp_path, real_sample, device_config)
    status, _ = asyncio.run(
        post_json(
            app,
            path,
            {"device_id": device_config.id, "interval_s": interval_s},
        )
    )

    assert status == 400
    assert manager.calls == []


def test_unknown_recording_device_is_not_forwarded(tmp_path, real_sample, device_config) -> None:
    app, manager = build_app(tmp_path, real_sample, device_config)
    status, _ = asyncio.run(
        post_json(app, "/api/v1/recording/start", {"device_id": "missing", "interval_s": 5})
    )
    assert status == 404
    assert manager.calls == []


def test_emonio_configuration_route_does_not_exist(tmp_path, real_sample, device_config) -> None:
    app, _ = build_app(tmp_path, real_sample, device_config)
    status, _ = asyncio.run(
        post_json(app, "/api/v1/modbus/write", {"register": 1, "value": 1})
    )
    assert status in {404, 405}


def test_application_factory_emits_no_aiohttp_warnings(tmp_path, real_sample, device_config) -> None:
    import warnings
    from aiohttp.web_app import NotAppKeyWarning

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        build_app(tmp_path, real_sample, device_config)

    prohibited = [
        item
        for item in caught
        if issubclass(item.category, (NotAppKeyWarning, DeprecationWarning))
    ]
    assert prohibited == []


def test_recording_commands_disabled_is_service_unavailable(tmp_path, real_sample, device_config) -> None:
    class DisabledManager(FakeRecordingManager):
        def start(self, device_id, interval_s, session_note=""):
            raise RuntimeError("recording commands disabled")

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    app = create_app(config, store, bus, DisabledManager(), frontend)
    status, _ = asyncio.run(
        post_json(app, "/api/v1/recording/start", {"device_id": device_config.id, "interval_s": 5})
    )
    assert status == 503


def test_recording_start_rejects_interval_faster_than_device_acquisition(tmp_path, real_sample, device_config) -> None:
    device = replace(device_config, poll_interval_s=2.0)
    app, manager = build_app(tmp_path, real_sample, device)
    status, _ = asyncio.run(
        post_json(
            app,
            "/api/v1/recording/start",
            {"device_id": device.id, "interval_s": 1.0, "session_note": "invalid rate"},
        )
    )
    assert status == 400
    assert manager.calls == []


def test_connect_target_route_forwards_only_target_text(tmp_path, real_sample, device_config) -> None:
    class FakeConnector:
        async def connect(self, target):
            self.target = target
            return type(
                "Result",
                (),
                {
                    "device": type(
                        "Device",
                        (),
                        {
                            "id": "emonio-new",
                            "name": "emonio-new",
                            "host": "emonio-new.local",
                            "port": 502,
                            "unit_id": 1,
                            "poll_interval_s": 2.0,
                            "timeout_s": 2.0,
                            "enabled": True,
                            "firmware_version": "unknown",
                        },
                    )(),
                    "already_connected": False,
                },
            )()

        def device_configs(self):
            return ()

        def get_device_config(self, _device_id):
            raise KeyError

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    manager = FakeRecordingManager()
    connector = FakeConnector()
    app = create_app(config, store, bus, manager, frontend, connector=connector)

    status, payload = asyncio.run(
        post_json(app, "/api/v1/devices/connect", {"target": "emonio-new"})
    )
    assert status == 200
    assert connector.target == "emonio-new"
    assert payload["device_id"] == "emonio-new"
    assert payload["host"] == "emonio-new.local"


def test_ct_configuration_evidence_is_separate_read_only_device_route(tmp_path, real_sample, device_config) -> None:
    from datetime import datetime, timezone
    from emonio_viewer.device_evidence.model import CtConfigurationEvidence, CtConfigurationValues

    class FakeCtService:
        def __init__(self) -> None:
            self.evidence = None
            self.calls = []

        def get(self, device_id):
            assert device_id == device_config.id
            return self.evidence

        async def read(self, device_id, host, password):
            self.calls.append((device_id, host, password))
            self.evidence = CtConfigurationEvidence(
                device_id=device_id,
                observed_utc=datetime(2026, 8, 27, 20, 2, tzinfo=timezone.utc),
                values=CtConfigurationValues(0, 0, 3, 7, 0),
            )
            return self.evidence

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    service = FakeCtService()
    app = create_app(config, store, bus, FakeRecordingManager(), frontend, ct_configuration=service)

    async def exercise():
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                response = await client.get(f"/api/v1/devices/{device_config.id}/ct-config")
                first_status = response.status
                first_payload = await response.json()
                response = await client.post(
                    f"/api/v1/devices/{device_config.id}/ct-config/read",
                    json={"password": "top-secret"},
                )
                second_status = response.status
                second_payload = await response.json()
                return first_status, first_payload, second_status, second_payload

    first_status, first_payload, status, payload = asyncio.run(exercise())
    assert first_status == 200
    assert first_payload == {"device_id": device_config.id, "status": "NOT_READ", "evidence": None}
    assert status == 200
    assert service.calls == [(device_config.id, device_config.host, "top-secret")]
    assert payload["status"] == "OBSERVED"
    assert payload["evidence"]["source"] == "EMONIO_TELNET_CONF"
    assert payload["evidence"]["physical_orientation_status"] == "NOT_VERIFIED"
    assert payload["evidence"]["values"] == {
        "ct_type": 0,
        "ct_voltage": 0,
        "ct_range": 3,
        "ct_invert": 7,
        "ct_didt": 0,
    }
    assert "password" not in str(payload).lower()
    assert "top-secret" not in str(payload)


def test_ct_configuration_read_requires_password_and_known_device(tmp_path, real_sample, device_config) -> None:
    class FakeCtService:
        def get(self, _device_id):
            return None

        async def read(self, *_args):
            raise AssertionError("read must not be called")

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    app = create_app(config, store, bus, FakeRecordingManager(), frontend, ct_configuration=FakeCtService())

    async def exercise():
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                missing_password = await client.post(
                    f"/api/v1/devices/{device_config.id}/ct-config/read",
                    json={},
                )
                unknown_device = await client.post(
                    "/api/v1/devices/missing/ct-config/read",
                    json={"password": "secret"},
                )
                return missing_password.status, unknown_device.status

    missing_password_status, unknown_device_status = asyncio.run(exercise())
    assert missing_password_status == 400
    assert unknown_device_status == 404


def _ct_failure_app(tmp_path, real_sample, device_config, error):
    class FailedCtService:
        def get(self, _device_id):
            return None

        async def read(self, *_args):
            raise error

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    return create_app(config, store, bus, FakeRecordingManager(), frontend, ct_configuration=FailedCtService())


def test_ct_configuration_telnet_unavailable_is_explicit_service_state(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer.device_evidence.telnet import CtConfigurationReadError

    error = CtConfigurationReadError(
        "connection refused",
        state="TELNET_UNAVAILABLE",
        stage="CONNECT",
        user_message="Telnet is unavailable. Enable Telnet on the Emonio before reading CT configuration.",
    )
    app = _ct_failure_app(tmp_path, real_sample, device_config, error)
    status, payload = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/ct-config/read", {"password": "secret"})
    )
    assert status == 503
    assert payload == {
        "status": "TELNET_UNAVAILABLE",
        "stage": "CONNECT",
        "message": "Telnet is unavailable. Enable Telnet on the Emonio before reading CT configuration.",
    }
    assert "secret" not in str(payload)


def test_ct_configuration_auth_failure_is_distinct_from_telnet_unavailable(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer.device_evidence.telnet import CtConfigurationReadError

    error = CtConfigurationReadError(
        "login rejected",
        state="AUTH_FAILED",
        stage="AUTH",
        user_message="Telnet authentication failed for user admin. Check the Emonio admin password.",
    )
    app = _ct_failure_app(tmp_path, real_sample, device_config, error)
    status, payload = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/ct-config/read", {"password": "secret"})
    )
    assert status == 401
    assert payload["status"] == "AUTH_FAILED"
    assert payload["stage"] == "AUTH"
    assert "secret" not in str(payload)


def test_ct_configuration_other_read_error_is_reported_as_bad_gateway(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer.device_evidence.telnet import CtConfigurationReadError

    error = CtConfigurationReadError(
        "simulated transport failure",
        state="READ_ERROR",
        stage="CT_RANGE",
        user_message="CT configuration read failed during CT_RANGE.",
    )
    app = _ct_failure_app(tmp_path, real_sample, device_config, error)
    status, payload = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/ct-config/read", {"password": "secret"})
    )
    assert status == 502
    assert payload["status"] == "READ_ERROR"
    assert payload["stage"] == "CT_RANGE"


def test_ct_configuration_programming_error_is_not_mislabeled_as_transport_failure(tmp_path, real_sample, device_config) -> None:
    class BuggyCtService:
        def get(self, _device_id):
            return None

        async def read(self, *_args):
            raise ValueError("simulated programming defect")

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    app = create_app(config, store, bus, FakeRecordingManager(), frontend, ct_configuration=BuggyCtService())

    status, _ = asyncio.run(
        post_json(app, f"/api/v1/devices/{device_config.id}/ct-config/read", {"password": "secret"})
    )
    assert status == 500



def test_recording_status_endpoint_is_read_only_and_reports_device_owners(tmp_path, real_sample, device_config) -> None:
    app, manager = build_app(tmp_path, real_sample, device_config)
    manager.active = (
        {
            "device_id": device_config.id,
            "device_name": device_config.name,
            "interval_s": 10.0,
            "session_dir": "/tmp/session-a",
            "started_utc": "2026-08-28T05:00:00+00:00",
        },
    )
    manager.errors = (
        {
            "device_id": "emonio-failed",
            "device_name": "Failed meter",
            "state": "ERROR",
            "interval_s": 5.0,
            "session_dir": "/tmp/session-failed",
            "started_utc": "2026-08-28T04:00:00+00:00",
            "failed_utc": "2026-08-28T04:00:05+00:00",
            "error_type": "OSError",
            "error_detail": "disk full",
        },
    )
    status, payload = asyncio.run(get_json(app, "/api/v1/recording/status"))
    assert status == 200
    assert payload == {"active": list(manager.active), "errors": list(manager.errors)}
    assert manager.calls == []


def test_frontend_index_uses_release_versioned_static_namespace_and_no_store_cache(tmp_path, real_sample, device_config) -> None:
    from emonio_viewer import __version__

    frontend = tmp_path / "frontend"
    (frontend / "js").mkdir(parents=True)
    (frontend / "css").mkdir(parents=True)
    (frontend / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="/static/css/base.css"></head>'
        '<body><script type="module" src="/static/js/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (frontend / "js" / "app.js").write_text('import "./api.js";\n', encoding="utf-8")
    (frontend / "js" / "api.js").write_text('export const ok = true;\n', encoding="utf-8")
    (frontend / "css" / "base.css").write_text('body {}\n', encoding="utf-8")

    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,))
    app = create_app(config, store, bus, FakeRecordingManager(), frontend)

    async def exercise():
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                index = await client.get("/")
                html = await index.text()
                app_js = await client.get(f"/static/{__version__}/js/app.js")
                api_js = await client.get(f"/static/{__version__}/js/api.js")
                legacy = await client.get("/static/js/api.js")
                return (
                    index.status,
                    index.headers.get("Cache-Control"),
                    html,
                    app_js.status,
                    await app_js.text(),
                    api_js.status,
                    await api_js.text(),
                    legacy.status,
                )

    status, cache_control, html, app_status, app_source, api_status, api_source, legacy_status = asyncio.run(exercise())
    assert status == 200
    assert cache_control == "no-store"
    assert f'href="/static/{__version__}/css/base.css"' in html
    assert f'src="/static/{__version__}/js/app.js"' in html
    assert app_status == 200
    assert 'import "./api.js";' in app_source
    assert api_status == 200
    assert "export const ok = true;" in api_source
    assert legacy_status == 404


def test_failed_target_route_returns_stable_operator_state_and_keeps_diagnostic_detail(
    tmp_path, real_sample, device_config
) -> None:
    from emonio_viewer.acquisition.connector import TargetConnectionError

    class FailingConnector:
        async def connect(self, _target):
            raise TargetConnectionError(
                "A: TRANSPORT: [Errno -2] Name or service not known"
            )

        def device_configs(self):
            return ()

        def get_device_config(self, _device_id):
            raise KeyError

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    store = RuntimeStore()
    store.register_device(device_config)
    store.publish_sample(real_sample, connections_opened=1)
    bus = RuntimeEventBus()
    config = RuntimeConfig(
        ViewerConfig(device_config.id), RecordingConfig(10.0), (device_config,)
    )
    manager = FakeRecordingManager()
    app = create_app(
        config,
        store,
        bus,
        manager,
        frontend,
        connector=FailingConnector(),
    )

    status, payload = asyncio.run(
        post_json(app, "/api/v1/devices/connect", {"target": "emonio-missing"})
    )

    assert status == 502
    assert payload["state"] == "TARGET_UNAVAILABLE"
    assert payload["message"] == "Target could not be qualified."
    assert payload["detail"] == "A: TRANSPORT: [Errno -2] Name or service not known"
    assert store.get_device(device_config.id).last_sample == real_sample
