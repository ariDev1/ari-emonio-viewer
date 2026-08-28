from dataclasses import dataclass
import ipaddress
import re


class TargetInputError(ValueError):
    """Raised when an operator target is not an IP address or hostname."""


_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(frozen=True, slots=True)
class TargetAddress:
    name: str
    host: str


def _valid_hostname(value: str) -> bool:
    if len(value) > 253:
        return False
    labels = value.rstrip(".").split(".")
    return bool(labels) and all(_HOST_LABEL.fullmatch(label) for label in labels)


def parse_target(value: str) -> TargetAddress:
    if not isinstance(value, str):
        raise TargetInputError("target must be text")
    target = value.strip()
    if not target:
        raise TargetInputError("target is required")

    try:
        ipaddress.ip_address(target)
    except ValueError:
        if not _valid_hostname(target):
            raise TargetInputError("target must be an IP address or hostname")
        explicit = target.rstrip(".")
        host = explicit if "." in explicit else f"{explicit}.local"
        name = explicit[:-6] if explicit.lower().endswith(".local") else explicit
        return TargetAddress(name=name, host=host)

    return TargetAddress(name=target, host=target)
