import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CALCULATOR = ROOT / "src/emonio_viewer/load_control/zero_export.py"
SERVICE = ROOT / "src/emonio_viewer/load_control/zero_export_service.py"
API = ROOT / "src/emonio_viewer/server/load_control_stage4c_api.py"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"
FRONTEND_API = ROOT / "frontend/js/load-control-stage4c-api.js"
FRONTEND_UI = ROOT / "frontend/js/load-control-stage4c-ui.js"
PYPROJECT = ROOT / "pyproject.toml"

PROTECTED_SCIENTIFIC_PATHS = (
    "src/emonio_viewer/acquisition",
    "src/emonio_viewer/measurement",
    "src/emonio_viewer/modbus",
    "src/emonio_viewer/recording",
    "src/emonio_viewer/scope",
    "src/emonio_viewer/runtime/events.py",
    "src/emonio_viewer/runtime/store.py",
)


def _function(tree: ast.AST, name: str):
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _source_segment(source: str, tree: ast.AST, name: str) -> str:
    return ast.get_source_segment(source, _function(tree, name)) or ""


def test_stage4c_calculator_is_p_only_with_fixed_qualified_duty_bounds() -> None:
    source = CALCULATOR.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calculator = _function(tree, "calculate_zero_export_step")
    names = [arg.arg for arg in calculator.args.kwonlyargs]
    assert names == [
        "measured_p_w",
        "p_deadband_w",
        "confirmed_duty_percent",
        "lower_bracket_duty_percent",
        "upper_bracket_duty_percent",
    ]
    assert "p_target" not in names
    assert "duty_step" not in names
    assert "q" not in names
    assert "pf" not in names
    assert "SAFE_OFF_DUTY_PERCENT = 0.0" in source
    assert "ACTIVE_DUTY_MIN_PERCENT = 25.0" in source
    assert "ACTIVE_DUTY_MAX_PERCENT = 75.0" in source
    assert "from emonio_viewer" not in source


def test_stage4c_service_observes_canonical_events_without_scientific_read_authority() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "RuntimeEventBus" in source
    assert "MeasurementSample" in source
    assert "SampleQuality" in source
    for forbidden in (
        "emonio_viewer.modbus",
        "emonio_viewer.acquisition",
        "RuntimeStore",
        "read_holding",
        "read_input",
        "read_register",
    ):
        assert forbidden not in source


def test_stage4c_physical_authority_is_only_the_reserved_manual_pwm_interface() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
            and owner.attr == "_manual_pwm"
        ):
            calls.add(node.func.attr)
    assert calls == {
        "manual_pwm_status",
        "reserve_pwm_owner",
        "release_pwm_owner",
        "run_reserved_pwm",
    }
    assert 'ZERO_EXPORT_PWM_OWNER = "STAGE4C_ZERO_EXPORT"' in source
    for forbidden in (
        "QualifiedActuatorChannel",
        "PwmCommandFrame",
        "send_pwm",
        "run_manual_pwm",
        "_next_sequence",
        "allocate_sequence",
        "LanActuatorDiscoveryService",
        "reconnect",
        "zeroconf",
    ):
        assert forbidden not in source


def test_stage4c_serializes_event_actuation_stale_safety_and_operator_actions() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    consume = _source_segment(source, tree, "_consume_events")
    enable = _source_segment(source, tree, "enable")
    disable = _source_segment(source, tree, "disable")
    assert consume.count("async with self._operation_lock") == 2
    assert "async with self._operation_lock" in enable
    assert "async with self._operation_lock" in disable
    assert "await self._handle_event(item)" in consume
    assert "reason=\"SAMPLE_STALE\"" in consume


def test_stage4c_requires_post_ack_causal_and_settling_boundaries_before_control() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    arm = _source_segment(source, tree, "_arm_after_ack")
    handle = _source_segment(source, tree, "_handle_event")
    assert "self._causal_after_ns = now" in arm
    assert "self._settling_pending = True" in arm
    assert "self._freshness_deadline_ns = now + self._freshness_ns()" in arm
    assert "sample.timing.cycle_finished_monotonic_ns <= causal_after" in handle
    assert handle.index("if self._settling_pending:") < handle.index("decision = calculate_zero_export_step(")


def test_stage4c_fail_closed_reasons_and_unconfirmed_safe_state_are_explicit() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    for required in (
        "SAMPLE_STALE",
        "SAMPLE_INVALID",
        "SAMPLE_SEQUENCE_GAP",
        "ACQUISITION_FAILURE",
        "ACTUATOR_DISCONNECTED",
        "ACTUATOR_NODE_CHANGED",
        "ACTUATOR_BOOT_CHANGED",
        "PWM_COMMAND_NOT_CONFIRMED",
        "SAFE_OFF_UNCONFIRMED",
        "SAFE_UNCONFIRMED",
    ):
        assert required in source
    assert "await self._finish_safe(" in source


def test_stage4c_app_wiring_reuses_stage3a_manual_pwm_and_closes_stage4c_first() -> None:
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "Stage4CZeroExportControllerService")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "Stage4CZeroExportControllerService")
        )
    ]
    assert len(calls) == 1
    call_text = ast.get_source_segment(source, calls[0]) or ""
    assert "manual_pwm=stage3a_service" in call_text
    assert "qualified_channel" not in call_text

    assert source.index("app.on_startup.append(start_characterization)") < source.index(
        "app.on_startup.append(start_zero_export_controller)"
    )
    assert source.index("app.on_cleanup.append(stop_zero_export_controller)") < source.index(
        "app.on_cleanup.append(stop_characterization)"
    )
    assert source.index("app.on_cleanup.append(stop_zero_export_controller)") < source.index(
        "app.on_cleanup.append(stop_stage3a)"
    )


def test_stage4c_http_surface_is_exact_and_has_no_direct_pwm_route() -> None:
    source = API.read_text(encoding="utf-8")
    routes = set(re.findall(r'app\.router\.add_(?:get|post)\("([^"]+)"', source))
    assert routes == {
        "/api/v1/load-control/zero-export/status",
        "/api/v1/load-control/zero-export/configure",
        "/api/v1/load-control/zero-export/enable",
        "/api/v1/load-control/zero-export/disable",
    }
    assert '_CONFIG_FIELDS = {"source_id", "phase", "p_deadband_w"}' in source
    for forbidden in (
        "/lan-pwm/",
        "run_reserved_pwm",
        "run_manual_pwm",
        "PwmCommandFrame",
        "duty_step",
        "p_target",
    ):
        assert forbidden not in source


def test_stage4c_frontend_has_no_manual_pwm_hook_or_operator_duty_increment() -> None:
    api_source = FRONTEND_API.read_text(encoding="utf-8")
    ui_source = FRONTEND_UI.read_text(encoding="utf-8")
    combined = api_source + "\n" + ui_source
    for forbidden in (
        "/lan-pwm/apply",
        "/lan-pwm/off",
        "applyManualPwmDuty",
        "turnManualPwmOff",
        "runManualPwm",
        "duty_step",
        "lc-zec-step",
        "p_target",
    ):
        assert forbidden not in combined
    for required in (
        "Canonical signed P is the only feedback input.",
        "Target is fixed at 0 W.",
        "No watts-to-duty calibration is used.",
        "No operator-selected duty increment is used.",
        "No Q or PF control is used.",
        "No PID is active.",
        "No automatic reconnect is used.",
    ):
        assert required in ui_source


def test_stage4c_keeps_release_identity_and_protected_scientific_contract() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert 'version = "0.4.23"' in pyproject
    assert 'emonio-viewer = "emonio_viewer.main_v0416:main"' in pyproject
    assert PROTECTED_SCIENTIFIC_PATHS == (
        "src/emonio_viewer/acquisition",
        "src/emonio_viewer/measurement",
        "src/emonio_viewer/modbus",
        "src/emonio_viewer/recording",
        "src/emonio_viewer/scope",
        "src/emonio_viewer/runtime/events.py",
        "src/emonio_viewer/runtime/store.py",
    )
