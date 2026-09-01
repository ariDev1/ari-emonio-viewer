import json
import math

import pytest

from emonio_viewer.load_control.model import ThreePhasePower
from emonio_viewer.load_control.protocol import (
    LOAD_CONTROL_PROTOCOL_VERSION,
    AckFrame,
    CommandFrame,
    HelloFrame,
    ProtocolError,
    StatusFrame,
    decode_frame,
    encode_frame,
)


def _command(**overrides):
    values = dict(
        protocol_version=LOAD_CONTROL_PROTOCOL_VERSION,
        viewer_session_id="VIEWER-TEST-001",
        node_id="ARI-LOAD-MOCK-001",
        boot_id="MOCK-BOOT-001",
        sequence=7,
        emonio_device_id="emonio-example",
        measurement_cycle_id=42,
        measurement_utc="2026-09-01T11:00:00+00:00",
        command_utc="2026-09-01T11:00:00.050000+00:00",
        control_enabled=True,
        p_reserve=30.0,
        measured_p=ThreePhasePower(-420.0, 10.0, 20.0),
        measured_q=ThreePhasePower(12.0, -5.0, 0.0),
        p_load_request=ThreePhasePower(450.0, 20.0, 10.0),
        q_comp_request=ThreePhasePower(0.0, 0.0, 0.0),
    )
    values.update(overrides)
    return CommandFrame(**values)


def _hello_payload():
    return {
        "message_type": "HELLO",
        "protocol_version": 1,
        "node_id": "ARI-LOAD-001",
        "boot_id": "BOOT-001",
        "device_class": "ARI_LOAD_ACTUATOR",
        "capabilities": ["ACTIVE_LOAD_CONTROL"],
        "p_max": {"a": 1000.0, "b": 1000.0, "c": 1000.0},
    }


def test_command_round_trip_is_deterministic_and_preserves_phase_values():
    frame = _command()
    text = encode_frame(frame)
    assert text == encode_frame(frame)
    assert "NaN" not in text
    assert decode_frame(text) == frame
    raw = json.loads(text)
    assert raw["message_type"] == "COMMAND"
    assert raw["p_load_request"] == {"a": 450.0, "b": 20.0, "c": 10.0}
    assert raw["q_comp_request"] == {"a": 0.0, "b": 0.0, "c": 0.0}


def test_command_rejects_non_zero_q_compensation_in_stage1():
    with pytest.raises(ValueError):
        _command(q_comp_request=ThreePhasePower(0.0, 1.0, 0.0))


def test_ack_requires_non_negative_finite_applied_power():
    with pytest.raises(ValueError):
        AckFrame(
            protocol_version=1,
            viewer_session_id="VIEWER-TEST-001",
            node_id="ARI-LOAD-MOCK-001",
            boot_id="MOCK-BOOT-001",
            sequence=7,
            ack_utc="2026-09-01T11:00:00.060000+00:00",
            applied_p=ThreePhasePower(-1.0, 0.0, 0.0),
            result="APPLIED",
        )
    with pytest.raises(ValueError):
        AckFrame(
            protocol_version=1,
            viewer_session_id="VIEWER-TEST-001",
            node_id="ARI-LOAD-MOCK-001",
            boot_id="MOCK-BOOT-001",
            sequence=7,
            ack_utc="2026-09-01T11:00:00.060000+00:00",
            applied_p=ThreePhasePower(math.nan, 0.0, 0.0),
            result="APPLIED",
        )


def test_hello_and_status_round_trip():
    hello = HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-MOCK-001",
        boot_id="MOCK-BOOT-001",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(600.0, 700.0, 800.0),
    )
    status = StatusFrame(
        protocol_version=1,
        node_id="ARI-LOAD-MOCK-001",
        boot_id="MOCK-BOOT-001",
        status_utc="2026-09-01T11:00:00+00:00",
        applied_p=ThreePhasePower(0.0, 0.0, 0.0),
        state="READY",
        faults=(),
    )
    assert decode_frame(encode_frame(hello)) == hello
    assert decode_frame(encode_frame(status)) == status


def test_decoder_rejects_unknown_fields_and_unknown_message_type():
    with pytest.raises(ProtocolError):
        decode_frame('{"message_type":"BOGUS","protocol_version":1}')
    text = encode_frame(_command())
    raw = json.loads(text)
    raw["unexpected"] = 1
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(raw))


def test_hello_decoder_rejects_wrong_protocol_version():
    payload = _hello_payload()
    payload["protocol_version"] = 2
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


def test_hello_decoder_rejects_empty_boot_id():
    payload = _hello_payload()
    payload["boot_id"] = ""
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


def test_hello_decoder_rejects_missing_p_max():
    payload = _hello_payload()
    payload.pop("p_max")
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


def test_hello_decoder_rejects_missing_p_max_phase():
    payload = _hello_payload()
    payload["p_max"].pop("c")
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


def test_hello_decoder_rejects_extra_p_max_phase():
    payload = _hello_payload()
    payload["p_max"]["d"] = 1000.0
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


@pytest.mark.parametrize(
    ("phase", "value"),
    [
        ("a", math.nan),
        ("b", math.inf),
        ("c", 0.0),
        ("a", -1.0),
    ],
)
def test_hello_decoder_rejects_invalid_p_max_value(phase, value):
    payload = _hello_payload()
    payload["p_max"][phase] = value
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))


def test_hello_decoder_rejects_extra_top_level_field():
    payload = _hello_payload()
    payload["unexpected"] = 1
    with pytest.raises(ProtocolError):
        decode_frame(json.dumps(payload))
