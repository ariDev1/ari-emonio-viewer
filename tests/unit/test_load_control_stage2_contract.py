from pathlib import Path

from emonio_viewer.load_control.qualification import LoadControlQualificationService


def test_stage2_qualification_has_no_measurement_or_command_authority() -> None:
    source = Path("src/emonio_viewer/load_control/qualification.py").read_text(encoding="utf-8")
    for forbidden in (
        "emonio_viewer.measurement",
        "emonio_viewer.modbus",
        "emonio_viewer.recording",
        "emonio_viewer.scope",
        "LoadControlSupervisor",
        "MeasurementSample",
        "CommandFrame",
        "AckFrame",
        "send_command(",
    ):
        assert forbidden not in source


def test_stage2_service_exposes_no_control_method() -> None:
    assert not hasattr(LoadControlQualificationService, "send_command")
    assert not hasattr(LoadControlQualificationService, "enable")
    assert not hasattr(LoadControlQualificationService, "configure_binding")
