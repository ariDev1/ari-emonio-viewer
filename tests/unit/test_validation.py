import math

from emonio_viewer.measurement.validation import Tolerances, validate_phase_values, validate_totals


def test_real_phase_b_reports_residuals_without_unqualified_warning() -> None:
    result = validate_phase_values(
        vrms=233.231094,
        irms=4.35338259,
        p=-58.4114113,
        q=-1013.66266,
        s=1015.34424,
        pf=-0.0575286783,
        tolerances=Tolerances(),
    )
    assert math.isclose(result.s_ui_delta, 1015.34424 - 233.231094 * 4.35338259, abs_tol=1e-9)
    assert math.isclose(result.pf_delta, -0.0575286783 - (-58.4114113 / 1015.34424), abs_tol=1e-12)
    assert result.warnings == ()


def test_total_check_reports_difference_without_replacing_meter_total() -> None:
    result = validate_totals(
        meter_p=-100.0,
        meter_q=-500.0,
        meter_s=550.0,
        phase_p=(10.0, -20.0, -90.0),
        phase_q=(-100.0, -200.0, -200.0),
        phase_s=(100.0, 200.0, 250.0),
        tolerances=Tolerances(),
    )
    assert result.meter_p == -100.0
    assert result.sum_p == -100.0
    assert result.delta_p == 0.0
    assert result.warnings == ()


def test_explicit_test_profile_can_raise_warning_without_repair() -> None:
    result = validate_totals(
        meter_p=110.0,
        meter_q=0.0,
        meter_s=110.0,
        phase_p=(30.0, 30.0, 30.0),
        phase_q=(0.0, 0.0, 0.0),
        phase_s=(30.0, 30.0, 30.0),
        tolerances=Tolerances(abs_power=1.0, rel_power=0.0, abs_pf=0.01, abs_va=1.0),
    )
    assert result.meter_p == 110.0
    assert result.delta_p == 20.0
    assert "TOTAL_P_CONSISTENCY_WARNING" in result.warnings


def test_real_total_residuals_match_the_captured_sample() -> None:
    result = validate_totals(
        meter_p=-127.606461,
        meter_q=-1031.63538,
        meter_s=1088.20215,
        phase_p=(0.0, -58.4114113, -69.1950531),
        phase_q=(-1.79727423, -1013.66266, -16.1754684),
        phase_s=(1.79727423, 1015.34424, 71.0605469),
        tolerances=Tolerances(),
    )
    assert math.isclose(result.delta_p, 3.4e-06, abs_tol=1e-06)
    assert math.isclose(result.delta_q, 2.263e-05, abs_tol=2e-06)
    assert math.isclose(result.delta_s, 8.887e-05, abs_tol=2e-06)
    assert result.warnings == ()


def test_low_power_factor_reference_uses_full_precision_before_presentation() -> None:
    p = 5.0
    q = -3450.0
    s = math.hypot(p, q)
    vrms = 230.0
    irms = s / vrms
    pf = p / s
    result = validate_phase_values(
        vrms=vrms,
        irms=irms,
        p=p,
        q=q,
        s=s,
        pf=pf,
        tolerances=Tolerances(),
    )
    assert math.isclose(pf, 0.0014492738, rel_tol=1e-6)
    assert result.pf_delta == 0.0
    assert f"{pf:.4f}" == "0.0014"
