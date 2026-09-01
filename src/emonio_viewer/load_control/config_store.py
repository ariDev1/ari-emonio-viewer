from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model import PersistentLoadControlConfig


SCHEMA_VERSION = 1
_CONFIG_FIELDS = (
    "bound_emonio_device_id",
    "bound_actuator_node_id",
    "p_reserve",
    "operator_limit_a",
    "operator_limit_b",
    "operator_limit_c",
)
_CONFIG_FIELD_SET = frozenset(_CONFIG_FIELDS)


class LoadControlConfigStoreError(ValueError):
    """Raised when persistent load-control configuration is invalid or cannot be replaced."""


def _config_to_json(config: PersistentLoadControlConfig) -> dict[str, Any]:
    return {name: getattr(config, name) for name in _CONFIG_FIELDS}


def _config_from_json(raw: Any) -> PersistentLoadControlConfig:
    if not isinstance(raw, dict):
        raise LoadControlConfigStoreError("load-control config must be an object")
    if set(raw) != _CONFIG_FIELD_SET:
        raise LoadControlConfigStoreError("load-control config fields do not match schema")
    try:
        return PersistentLoadControlConfig(**raw)
    except (TypeError, ValueError) as exc:
        raise LoadControlConfigStoreError("load-control config is invalid") from exc


class LoadControlConfigStore:
    """Atomic persistence for operator-qualified load-control binding and limits."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> PersistentLoadControlConfig:
        if not self.path.exists():
            return PersistentLoadControlConfig()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LoadControlConfigStoreError("invalid load-control configuration JSON") from exc

        if not isinstance(raw, dict):
            raise LoadControlConfigStoreError("load-control configuration must be an object")
        if set(raw) != {"schema_version", "config"}:
            raise LoadControlConfigStoreError("load-control configuration fields do not match schema")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise LoadControlConfigStoreError("unsupported load-control schema_version")
        return _config_from_json(raw["config"])

    def replace(self, config: PersistentLoadControlConfig) -> None:
        qualified = _config_from_json(_config_to_json(config))
        payload = {
            "schema_version": SCHEMA_VERSION,
            "config": _config_to_json(qualified),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError) as exc:
            raise LoadControlConfigStoreError("cannot replace load-control configuration") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
