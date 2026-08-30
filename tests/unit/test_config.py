from pathlib import Path
import pytest

from emonio_viewer.config.loader import ConfigError, load_config


def test_loads_verified_test_device(tmp_path: Path) -> None:
    path = tmp_path / "emonio-viewer.toml"
    path.write_text(
        """
[viewer]
default_device = "emonio-example"

[recording]
default_interval_s = 10

[[devices]]
id = "emonio-example"
name = "emonio-example"
host = "192.0.2.11"
port = 502
unit_id = 1
poll_interval_s = 2.0
timeout_s = 2.0
enabled = true
firmware_version = "3.0.79-release"
""",
        encoding="utf-8",
    )
    config = load_config(path)
    device = config.devices[0]
    assert device.id == "emonio-example"
    assert device.host == "192.0.2.11"
    assert device.port == 502
    assert device.poll_interval_s == 2.0
    assert config.viewer.default_device == "emonio-example"
    assert config.recording.default_interval_s == 10.0


def test_rejects_duplicate_device_ids(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.toml"
    path.write_text(
        """
[viewer]
default_device = "meter"
[recording]
default_interval_s = 10
[[devices]]
id = "meter"
name = "A"
host = "192.0.2.1"
[[devices]]
id = "meter"
name = "B"
host = "192.0.2.2"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate device id"):
        load_config(path)


def test_rejects_non_positive_poll_interval(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        """
[viewer]
default_device = "meter"
[recording]
default_interval_s = 10
[[devices]]
id = "meter"
name = "meter"
host = "192.0.2.1"
poll_interval_s = 0
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="poll_interval_s"):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("poll_interval_s", "nan"),
        ("poll_interval_s", "inf"),
        ("timeout_s", "nan"),
        ("timeout_s", "inf"),
        ("default_interval_s", "nan"),
        ("default_interval_s", "inf"),
    ),
)
def test_rejects_non_finite_timing_configuration(tmp_path: Path, field: str, value: str) -> None:
    poll_interval = value if field == "poll_interval_s" else "2.0"
    timeout = value if field == "timeout_s" else "2.0"
    recording_interval = value if field == "default_interval_s" else "10.0"
    path = tmp_path / "non-finite.toml"
    path.write_text(
        f"""
[viewer]
default_device = "meter"
[recording]
default_interval_s = {recording_interval}
[[devices]]
id = "meter"
name = "meter"
host = "192.0.2.1"
poll_interval_s = {poll_interval}
timeout_s = {timeout}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=field):
        load_config(path)


def test_merge_runtime_devices_adds_remembered_devices_without_changing_default() -> None:
    from emonio_viewer.config.loader import merge_runtime_devices
    from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig

    fixed = DeviceConfig(id="fixed", name="fixed", host="192.0.2.11")
    remembered = DeviceConfig(id="remembered", name="remembered", host="192.0.2.12")
    config = RuntimeConfig(ViewerConfig("fixed"), RecordingConfig(10.0), (fixed,))

    merged = merge_runtime_devices(config, (remembered,))

    assert merged.viewer.default_device == "fixed"
    assert merged.devices == (fixed, remembered)


def test_merge_runtime_devices_keeps_toml_authoritative_by_id_and_host() -> None:
    from emonio_viewer.config.loader import merge_runtime_devices
    from emonio_viewer.config.model import DeviceConfig, RecordingConfig, RuntimeConfig, ViewerConfig

    fixed = DeviceConfig(id="fixed", name="fixed", host="192.0.2.11", timeout_s=3.0)
    duplicate_id = DeviceConfig(id="fixed", name="other", host="192.0.2.12", timeout_s=1.0)
    duplicate_host = DeviceConfig(id="other", name="other", host="192.0.2.11", timeout_s=1.0)
    unique = DeviceConfig(id="unique", name="unique", host="192.0.2.13")
    config = RuntimeConfig(ViewerConfig("fixed"), RecordingConfig(10.0), (fixed,))

    merged = merge_runtime_devices(config, (duplicate_id, duplicate_host, unique))

    assert merged.devices == (fixed, unique)
