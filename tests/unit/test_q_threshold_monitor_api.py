from types import SimpleNamespace

import pytest
from aiohttp import web

from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig
from emonio_viewer.server.api_v0416 import _monitor_config
from emonio_viewer.server.keys import RUNTIME_CONFIG_KEY


def request_with_device():
    device = DeviceConfig("emonio-a", "EMONIO A", "192.0.2.1")
    runtime = RuntimeConfig(
        ViewerConfig(device.id),
        RecordingConfig(10.0),
        (device,),
    )
    return SimpleNamespace(app={RUNTIME_CONFIG_KEY: runtime})


def q_body(**updates):
    body = {
        "device_id": "emonio-a",
        "condition": "Q_THRESHOLD",
        "phases": ["A", "C"],
        "recording_interval_s": 2.0,
        "threshold_var": 123.5,
        "q_direction": "BOTH",
    }
    body.update(updates)
    return body


def test_monitor_api_parses_q_threshold_magnitude_and_direction():
    config = _monitor_config(request_with_device(), q_body())
    assert config.condition.value == "Q_THRESHOLD"
    assert [phase.value for phase in config.phases] == ["A", "C"]
    assert config.recording_interval_s == 2.0
    assert config.threshold_var == 123.5
    assert config.q_direction.value == "BOTH"


@pytest.mark.parametrize(
    "threshold",
    (-1.0, "nan", "inf", "-inf", "not-a-number", None),
)
def test_monitor_api_rejects_invalid_q_threshold_magnitude(threshold):
    with pytest.raises(web.HTTPBadRequest):
        _monitor_config(request_with_device(), q_body(threshold_var=threshold))


@pytest.mark.parametrize("direction", (None, "", "INVALID"))
def test_monitor_api_rejects_invalid_q_direction(direction):
    with pytest.raises(web.HTTPBadRequest):
        _monitor_config(request_with_device(), q_body(q_direction=direction))


def test_existing_p_negative_api_does_not_require_q_parameters():
    config = _monitor_config(
        request_with_device(),
        {
            "device_id": "emonio-a",
            "condition": "P_NEGATIVE",
            "phases": ["B"],
            "recording_interval_s": 2.0,
        },
    )
    assert config.condition.value == "P_NEGATIVE"
    assert config.threshold_var is None
    assert config.q_direction is None
