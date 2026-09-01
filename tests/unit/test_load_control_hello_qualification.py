from dataclasses import replace

import pytest

from emonio_viewer.load_control.model import ActuatorDescriptor, ThreePhasePower
from emonio_viewer.load_control.protocol import HelloFrame
from emonio_viewer.load_control.qualification import (
    LoadControlQualificationError,
    qualify_hello,
)


def _descriptor() -> ActuatorDescriptor:
    return ActuatorDescriptor(
        node_id="ARI-LOAD-001",
        location="ws://192.168.1.141:8080/load-control",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def _hello() -> HelloFrame:
    return HelloFrame(
        protocol_version=1,
        node_id="ARI-LOAD-001",
        boot_id="BOOT-001",
        device_class="ARI_LOAD_ACTUATOR",
        capabilities=("ACTIVE_LOAD_CONTROL",),
        p_max=ThreePhasePower(1000.0, 1000.0, 1000.0),
    )


def test_hello_qualification_accepts_exact_discovery_match() -> None:
    descriptor = _descriptor()
    hello = _hello()

    assert qualify_hello(descriptor, hello) is None
    assert descriptor == _descriptor()
    assert hello == _hello()


@pytest.mark.parametrize(
    ("hello", "expected"),
    [
        (replace(_hello(), node_id="ARI-LOAD-OTHER"), "node_id"),
        (replace(_hello(), device_class="OTHER_CLASS"), "device_class"),
        (replace(_hello(), capabilities=("OTHER_CAPABILITY",)), "ACTIVE_LOAD_CONTROL"),
        (replace(_hello(), p_max=ThreePhasePower(999.0, 1000.0, 1000.0)), "p_max.a"),
        (replace(_hello(), p_max=ThreePhasePower(1000.0, 999.0, 1000.0)), "p_max.b"),
        (replace(_hello(), p_max=ThreePhasePower(1000.0, 1000.0, 999.0)), "p_max.c"),
    ],
)
def test_hello_qualification_rejects_discovery_mismatch(hello, expected) -> None:
    with pytest.raises(LoadControlQualificationError, match=expected):
        qualify_hello(_descriptor(), hello)
