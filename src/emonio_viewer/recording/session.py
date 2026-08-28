from datetime import datetime, timezone
import re
from pathlib import Path

from emonio_viewer.config.model import DeviceConfig
from emonio_viewer.modbus.register_map import REGISTER_MAP_ID


def _safe_device_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    if not safe:
        raise ValueError("device id cannot produce an empty recording name")
    return safe


def create_session_directory(root: Path, device_id: str, started_utc: datetime) -> tuple[str, Path]:
    stamp = started_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    session_id = f"{stamp}_{_safe_device_id(device_id)}"
    path = root / session_id
    path.mkdir(parents=True, exist_ok=False)
    return session_id, path


def initial_session_metadata(
    *,
    session_id: str,
    started_utc: datetime,
    device: DeviceConfig,
    application_version: str,
    recording_interval_s: float,
) -> dict:
    return {
        "schema_version": 1,
        "application_version": application_version,
        "session_id": session_id,
        "started_utc": started_utc.astimezone(timezone.utc).isoformat(),
        "device": {
            "id": device.id,
            "name": device.name,
            "host": device.host,
            "port": device.port,
            "unit_id": device.unit_id,
            "firmware": device.firmware_version,
        },
        "transport": {
            "type": "MODBUS_TCP",
            "register_map": REGISTER_MAP_ID,
            "float_format": "CDAB",
            "write_capability": False,
        },
        "acquisition": {
            "interval_s": device.poll_interval_s,
            "timeout_s": device.timeout_s,
        },
        "recording": {"interval_s": recording_interval_s},
    }


def discover_resumable_session(root: Path):
    """V1 deliberately never auto-resumes a previous recording session."""
    _ = root
    return None
