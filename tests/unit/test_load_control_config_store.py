import json
import os

import pytest

from emonio_viewer.load_control.config_store import (
    LoadControlConfigStore,
    LoadControlConfigStoreError,
)
from emonio_viewer.load_control.model import PersistentLoadControlConfig


def test_missing_store_loads_empty_configuration(tmp_path):
    store = LoadControlConfigStore(tmp_path / "load-control.json")
    assert store.load() == PersistentLoadControlConfig()


def test_store_round_trips_only_persistent_fields(tmp_path):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    config = PersistentLoadControlConfig(
        bound_emonio_device_id="emonio-example",
        bound_actuator_node_id="ARI-LOAD-MOCK-001",
        p_reserve=30.0,
        operator_limit_a=600.0,
        operator_limit_b=700.0,
        operator_limit_c=800.0,
    )
    store.replace(config)
    assert store.load() == config
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert set(payload) == {"schema_version", "config"}
    assert "enabled" not in path.read_text(encoding="utf-8")
    assert "boot_id" not in path.read_text(encoding="utf-8")
    assert "sequence" not in path.read_text(encoding="utf-8")
    assert "ack_timeout_s" not in path.read_text(encoding="utf-8")


def test_store_rejects_unknown_schema_fields(tmp_path):
    path = tmp_path / "load-control.json"
    path.write_text(
        '{"schema_version":1,"config":{},"unexpected":true}\n',
        encoding="utf-8",
    )
    with pytest.raises(LoadControlConfigStoreError):
        LoadControlConfigStore(path).load()


def test_store_rejects_invalid_json(tmp_path):
    path = tmp_path / "load-control.json"
    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(LoadControlConfigStoreError):
        LoadControlConfigStore(path).load()


def test_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "load-control.json"
    store = LoadControlConfigStore(path)
    original = PersistentLoadControlConfig(p_reserve=30.0)
    store.replace(original)

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(LoadControlConfigStoreError):
        store.replace(PersistentLoadControlConfig(p_reserve=40.0))

    assert LoadControlConfigStore(path).load() == original
    assert not path.with_name(path.name + ".tmp").exists()
