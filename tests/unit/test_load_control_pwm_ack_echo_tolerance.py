from emonio_viewer.load_control.manual_pwm import Stage3BManualPwmCommandService
from emonio_viewer.load_control.pwm_protocol import PwmAckFrame, PwmCommandFrame


def _command() -> PwmCommandFrame:
    return PwmCommandFrame(
        protocol_version=1,
        viewer_session_id="VIEWER-PWM-FIELD-001",
        node_id="ARI-LOAD-001",
        boot_id="BOOT-PWM-FIELD-001",
        sequence=19,
        duty_percent=74.609375,
    )


def _ack(command: PwmCommandFrame, requested_duty_percent: float) -> PwmAckFrame:
    return PwmAckFrame(
        protocol_version=1,
        viewer_session_id=command.viewer_session_id,
        node_id=command.node_id,
        boot_id=command.boot_id,
        sequence=command.sequence,
        result="APPLIED",
        requested_duty_percent=requested_duty_percent,
        actual_duty_percent=74.57886676875957,
        compare_ticks=487,
        period_ticks=653,
    )


def test_pwm_ack_accepts_field_observed_requested_duty_serialization_rounding() -> None:
    command = _command()
    ack = _ack(command, 74.60938)

    assert Stage3BManualPwmCommandService._pwm_ack_mismatch(command, ack) is None


def test_pwm_ack_rejects_requested_duty_difference_beyond_serialization_tolerance() -> None:
    command = _command()
    ack = _ack(command, 74.60935)

    assert (
        Stage3BManualPwmCommandService._pwm_ack_mismatch(command, ack)
        == "PWM_ACK_REQUESTED_DUTY_MISMATCH"
    )
