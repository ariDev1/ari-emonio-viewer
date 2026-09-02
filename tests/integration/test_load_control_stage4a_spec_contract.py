import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "src/emonio_viewer/load_control/automatic_observation.py"
STAGE4A_API = ROOT / "src/emonio_viewer/server/load_control_stage4a_api.py"
APP = ROOT / "src/emonio_viewer/server/app_v0416.py"
FRONTEND_API = ROOT / "frontend/js/load-control-stage4a-api.js"
FRONTEND_UI = ROOT / "frontend/js/load-control-stage4a-ui.js"
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


def test_stage4a_observer_has_no_actuator_transport_authority() -> None:
    source = OBSERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "QualifiedActuatorChannel" not in source
    assert "PwmCommandFrame" not in source
    forbidden_calls = {"send", "send_pwm", "receive", "receive_nowait", "bind", "clear"}
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called_attributes.isdisjoint(forbidden_calls)


def test_stage4a_observer_does_not_allocate_actuator_command_sequences() -> None:
    source = OBSERVER.read_text(encoding="utf-8")
    for forbidden in (
        "_next_sequence",
        "next_sequence(",
        "allocate_sequence",
        "command_sequence +=",
        "command_sequence = command_sequence +",
    ):
        assert forbidden not in source


def test_stage4a_app_wiring_does_not_give_observer_the_qualified_channel() -> None:
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    observer_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "PControlObserverService")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "PControlObserverService")
        )
    ]
    assert observer_calls
    for call in observer_calls:
        keyword_names = {item.arg for item in call.keywords}
        assert "qualified_channel" not in keyword_names
        assert "channel" not in keyword_names
        argument_text = ast.get_source_segment(source, call) or ""
        assert "qualified_channel" not in argument_text


def test_stage4a_http_and_frontend_have_no_pwm_output_route_or_command() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (STAGE4A_API, FRONTEND_API, FRONTEND_UI)
    )
    for forbidden in (
        "PWM_COMMAND",
        "/lan-pwm/apply",
        "/lan-pwm/off",
        "applyManualPwmDuty",
        "turnManualPwmOff",
        "PwmCommandFrame",
    ):
        assert forbidden not in sources


def test_stage4a_keeps_active_launcher_and_version() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert 'version = "0.4.23"' in pyproject
    assert 'emonio-viewer = "emonio_viewer.main_v0416:main"' in pyproject


def test_stage4a_protected_path_contract_is_explicit() -> None:
    assert PROTECTED_SCIENTIFIC_PATHS == (
        "src/emonio_viewer/acquisition",
        "src/emonio_viewer/measurement",
        "src/emonio_viewer/modbus",
        "src/emonio_viewer/recording",
        "src/emonio_viewer/scope",
        "src/emonio_viewer/runtime/events.py",
        "src/emonio_viewer/runtime/store.py",
    )


def test_stage4a_calculator_signature_has_no_q_or_pf_control_input() -> None:
    source = OBSERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calculator = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "calculate_p_control_proposal"
    )
    names = [arg.arg for arg in calculator.args.kwonlyargs]
    assert names == [
        "measured_p_w",
        "p_target_w",
        "p_deadband_w",
        "confirmed_duty_percent",
        "duty_step_percent",
    ]
    assert "q" not in names
    assert "pf" not in names


def test_stage4a_observer_uses_runtime_event_bus_not_modbus_or_runtime_store() -> None:
    source = OBSERVER.read_text(encoding="utf-8")
    assert "RuntimeEventBus" in source
    assert "emonio_viewer.modbus" not in source
    assert "RuntimeStore" not in source
    assert "read_holding" not in source
    assert "read_input" not in source


def test_stage4a_ui_has_no_apply_proposed_action() -> None:
    source = FRONTEND_UI.read_text(encoding="utf-8")
    assert "APPLY PROPOSED" not in source
    assert "Apply a proposal manually" in source
    assert "No automatic PWM command is sent" in source
