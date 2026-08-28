from dataclasses import dataclass
import math

from .model import DerivedTotals, PhaseMeasurement, SampleQuality


@dataclass(frozen=True, slots=True)
class Tolerances:
    """Optional qualified warning limits.

    A value of None means that the related scientific warning gate is disabled.
    V1 defaults to observational residual reporting only.
    """

    abs_power: float | None = None
    rel_power: float | None = None
    abs_pf: float | None = None
    abs_va: float | None = None

    @property
    def qualified(self) -> bool:
        return None not in (self.abs_power, self.rel_power, self.abs_pf, self.abs_va)


@dataclass(frozen=True, slots=True)
class PhaseValidation:
    s_ui_delta: float
    pf_delta: float | None
    p_excess_over_s: float
    q_excess_over_s: float
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TotalValidation:
    meter_p: float
    meter_q: float
    meter_s: float
    sum_p: float
    sum_q: float
    sum_s: float
    delta_p: float
    delta_q: float
    delta_s: float
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    quality: SampleQuality
    warnings: tuple[str, ...]
    derived: DerivedTotals
    phase_a: PhaseValidation
    phase_b: PhaseValidation
    phase_c: PhaseValidation


def _close(a: float, b: float, abs_tol: float, rel_tol: float) -> bool:
    return math.isclose(a, b, abs_tol=abs_tol, rel_tol=rel_tol)


def validate_phase_values(
    *,
    vrms: float,
    irms: float,
    p: float,
    q: float,
    s: float,
    pf: float,
    tolerances: Tolerances,
) -> PhaseValidation:
    ui = vrms * irms
    pf_reference = None if s == 0.0 else p / s
    warnings: list[str] = []

    if tolerances.qualified:
        assert tolerances.abs_power is not None
        assert tolerances.rel_power is not None
        assert tolerances.abs_pf is not None
        assert tolerances.abs_va is not None

        if not _close(s, ui, tolerances.abs_va, tolerances.rel_power):
            warnings.append("PHASE_S_UI_CONSISTENCY_WARNING")
        if pf_reference is not None and not _close(
            pf,
            pf_reference,
            tolerances.abs_pf,
            tolerances.rel_power,
        ):
            warnings.append("PHASE_PF_CONSISTENCY_WARNING")
        if abs(p) > s + tolerances.abs_power:
            warnings.append("PHASE_ABS_P_GT_S_WARNING")
        if abs(q) > s + tolerances.abs_power:
            warnings.append("PHASE_ABS_Q_GT_S_WARNING")

    return PhaseValidation(
        s_ui_delta=s - ui,
        pf_delta=None if pf_reference is None else pf - pf_reference,
        p_excess_over_s=max(0.0, abs(p) - s),
        q_excess_over_s=max(0.0, abs(q) - s),
        warnings=tuple(warnings),
    )


def validate_totals(
    *,
    meter_p: float,
    meter_q: float,
    meter_s: float,
    phase_p: tuple[float, float, float],
    phase_q: tuple[float, float, float],
    phase_s: tuple[float, float, float],
    tolerances: Tolerances,
) -> TotalValidation:
    sum_p = sum(phase_p)
    sum_q = sum(phase_q)
    sum_s = sum(phase_s)
    delta_p = meter_p - sum_p
    delta_q = meter_q - sum_q
    delta_s = meter_s - sum_s
    warnings: list[str] = []

    if tolerances.qualified:
        assert tolerances.abs_power is not None
        assert tolerances.rel_power is not None
        if not _close(meter_p, sum_p, tolerances.abs_power, tolerances.rel_power):
            warnings.append("TOTAL_P_CONSISTENCY_WARNING")
        if not _close(meter_q, sum_q, tolerances.abs_power, tolerances.rel_power):
            warnings.append("TOTAL_Q_CONSISTENCY_WARNING")
        if not _close(meter_s, sum_s, tolerances.abs_power, tolerances.rel_power):
            warnings.append("TOTAL_S_CONSISTENCY_WARNING")

    return TotalValidation(
        meter_p=meter_p,
        meter_q=meter_q,
        meter_s=meter_s,
        sum_p=sum_p,
        sum_q=sum_q,
        sum_s=sum_s,
        delta_p=delta_p,
        delta_q=delta_q,
        delta_s=delta_s,
        warnings=tuple(warnings),
    )


def validate_complete_measurement(
    *,
    phase_a: PhaseMeasurement,
    phase_b: PhaseMeasurement,
    phase_c: PhaseMeasurement,
    total: PhaseMeasurement,
    tolerances: Tolerances,
) -> ValidationResult:
    a = validate_phase_values(
        vrms=phase_a.vrms,
        irms=phase_a.irms,
        p=phase_a.p,
        q=phase_a.q,
        s=phase_a.s,
        pf=phase_a.pf,
        tolerances=tolerances,
    )
    b = validate_phase_values(
        vrms=phase_b.vrms,
        irms=phase_b.irms,
        p=phase_b.p,
        q=phase_b.q,
        s=phase_b.s,
        pf=phase_b.pf,
        tolerances=tolerances,
    )
    c = validate_phase_values(
        vrms=phase_c.vrms,
        irms=phase_c.irms,
        p=phase_c.p,
        q=phase_c.q,
        s=phase_c.s,
        pf=phase_c.pf,
        tolerances=tolerances,
    )
    totals = validate_totals(
        meter_p=total.p,
        meter_q=total.q,
        meter_s=total.s,
        phase_p=(phase_a.p, phase_b.p, phase_c.p),
        phase_q=(phase_a.q, phase_b.q, phase_c.q),
        phase_s=(phase_a.s, phase_b.s, phase_c.s),
        tolerances=tolerances,
    )
    warnings = a.warnings + b.warnings + c.warnings + totals.warnings
    return ValidationResult(
        quality=SampleQuality.DEGRADED if warnings else SampleQuality.VALID,
        warnings=warnings,
        derived=DerivedTotals(
            sum_p=totals.sum_p,
            sum_q=totals.sum_q,
            sum_s=totals.sum_s,
            delta_p=totals.delta_p,
            delta_q=totals.delta_q,
            delta_s=totals.delta_s,
        ),
        phase_a=a,
        phase_b=b,
        phase_c=c,
    )
