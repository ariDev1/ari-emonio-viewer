import inspect

from emonio_viewer.server import app_v0416


def test_stage4b_characterization_is_wired_to_existing_pwm_owner_and_event_bus() -> None:
    source = inspect.getsource(app_v0416)

    assert "from emonio_viewer.load_control.characterization_service import Stage4BCharacterizationService" in source
    assert "CHARACTERIZATION_SERVICE_KEY" in source
    assert "characterization_service: Stage4BCharacterizationService | None = None" in source
    assert "characterization_service = Stage4BCharacterizationService(" in source
    assert "bus," in source
    assert "config," in source
    assert "manual_pwm=stage3a_service" in source
    assert "app[CHARACTERIZATION_SERVICE_KEY] = characterization_service" in source


def test_stage4b_characterization_lifecycle_and_routes_are_registered() -> None:
    source = inspect.getsource(app_v0416)

    assert "await characterization_service.start()" in source
    assert "await characterization_service.close()" in source
    assert source.index("app.on_startup.append(start_stage3a)") < source.index(
        "app.on_startup.append(start_characterization)"
    )
    assert source.index("app.on_cleanup.append(stop_characterization)") < source.index(
        "app.on_cleanup.append(stop_stage3a)"
    )
    assert "register_load_control_stage4b_characterization_routes(app)" in source
