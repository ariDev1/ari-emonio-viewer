import pytest

from emonio_viewer.measurement.quadrant import (
    ActiveFlowState,
    QuadrantState,
    classify_flow,
    classify_quadrant,
)


@pytest.mark.parametrize(
    ("p", "q", "expected"),
    [
        (1.0, 1.0, QuadrantState.Q1),
        (-1.0, 1.0, QuadrantState.Q2),
        (-1.0, -1.0, QuadrantState.Q3),
        (1.0, -1.0, QuadrantState.Q4),
        (0.0, 1.0, QuadrantState.P_AXIS_POSITIVE_Q),
        (0.0, -1.0, QuadrantState.P_AXIS_NEGATIVE_Q),
        (1.0, 0.0, QuadrantState.Q_AXIS_POSITIVE_P),
        (-1.0, 0.0, QuadrantState.Q_AXIS_NEGATIVE_P),
        (0.0, 0.0, QuadrantState.ORIGIN),
    ],
)
def test_exact_quadrant_contract(p: float, q: float, expected: QuadrantState) -> None:
    assert classify_quadrant(p, q) is expected


def test_flow_preserves_active_power_sign() -> None:
    assert classify_flow(1.0) is ActiveFlowState.POSITIVE_FLOW
    assert classify_flow(-1.0) is ActiveFlowState.NEGATIVE_FLOW
    assert classify_flow(0.0) is ActiveFlowState.ZERO_ACTIVE_POWER
