from enum import Enum


class QuadrantState(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    P_AXIS_POSITIVE_Q = "P_AXIS_POSITIVE_Q"
    P_AXIS_NEGATIVE_Q = "P_AXIS_NEGATIVE_Q"
    Q_AXIS_POSITIVE_P = "Q_AXIS_POSITIVE_P"
    Q_AXIS_NEGATIVE_P = "Q_AXIS_NEGATIVE_P"
    ORIGIN = "ORIGIN"


class ActiveFlowState(str, Enum):
    POSITIVE_FLOW = "POSITIVE_FLOW"
    NEGATIVE_FLOW = "NEGATIVE_FLOW"
    ZERO_ACTIVE_POWER = "ZERO_ACTIVE_POWER"


def classify_quadrant(p: float, q: float) -> QuadrantState:
    if p > 0 and q > 0:
        return QuadrantState.Q1
    if p < 0 and q > 0:
        return QuadrantState.Q2
    if p < 0 and q < 0:
        return QuadrantState.Q3
    if p > 0 and q < 0:
        return QuadrantState.Q4
    if p == 0 and q > 0:
        return QuadrantState.P_AXIS_POSITIVE_Q
    if p == 0 and q < 0:
        return QuadrantState.P_AXIS_NEGATIVE_Q
    if p > 0 and q == 0:
        return QuadrantState.Q_AXIS_POSITIVE_P
    if p < 0 and q == 0:
        return QuadrantState.Q_AXIS_NEGATIVE_P
    return QuadrantState.ORIGIN


def classify_flow(p: float) -> ActiveFlowState:
    if p > 0:
        return ActiveFlowState.POSITIVE_FLOW
    if p < 0:
        return ActiveFlowState.NEGATIVE_FLOW
    return ActiveFlowState.ZERO_ACTIVE_POWER
