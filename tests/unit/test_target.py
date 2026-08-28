import pytest

from emonio_viewer.acquisition.target import TargetInputError, parse_target


def test_ipv4_target_is_used_without_modification() -> None:
    target = parse_target("192.0.2.11")
    assert target.host == "192.0.2.11"
    assert target.name == "192.0.2.11"


def test_emonio_device_name_uses_mdns_local_suffix() -> None:
    target = parse_target("emonio-example")
    assert target.host == "emonio-example.local"
    assert target.name == "emonio-example"


def test_explicit_local_hostname_is_not_modified() -> None:
    target = parse_target("emonio-example.local")
    assert target.host == "emonio-example.local"
    assert target.name == "emonio-example"


@pytest.mark.parametrize("value", ["", "  ", "http://emonio-example", "192.0.2.11:502", "bad host name"])
def test_invalid_target_is_rejected(value: str) -> None:
    with pytest.raises(TargetInputError):
        parse_target(value)
