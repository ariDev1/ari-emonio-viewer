from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
STAGE4A_CSS = ROOT / "frontend/css/load-control/p-control-observer.css"
STAGE4C_CSS = ROOT / "frontend/css/load-control/zero-export-controller.css"


def _block(source: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", source, re.DOTALL)
    assert match is not None, f"missing CSS block: {selector}"
    return match.group("body")


def test_stage4c_panel_is_dense_and_does_not_force_horizontal_status_overflow() -> None:
    source = STAGE4C_CSS.read_text(encoding="utf-8")

    section = _block(source, ".load-control-zero-export")
    assert "gap: 8px;" in section
    assert "padding: 10px 12px;" in section

    config = _block(source, ".load-control-zero-export-config")
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in config
    assert "gap: 8px;" in config

    status = _block(source, ".load-control-zero-export-status")
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in status
    assert "gap: 6px;" in status

    card = _block(source, ".load-control-zero-export-status > div")
    assert "gap: 2px;" in card
    assert "padding: 7px 9px;" in card

    actions = _block(source, ".load-control-zero-export-actions")
    assert "margin-top: 0;" in actions


def test_stage4a_panel_uses_compact_configuration_and_four_column_evidence_grid() -> None:
    source = STAGE4A_CSS.read_text(encoding="utf-8")

    section = _block(source, ".load-control-p-observer")
    assert "gap: 8px;" in section
    assert "padding: 10px 12px;" in section

    config = _block(source, ".load-control-p-observer-config")
    assert "grid-template-columns: repeat(auto-fit, minmax(125px, 1fr));" in config
    assert "gap: 7px;" in config

    status = _block(source, ".load-control-p-observer-status")
    assert "grid-template-columns: repeat(auto-fit, minmax(125px, 1fr));" in status
    assert "gap: 6px;" in status

    card = _block(source, ".load-control-p-observer-status > div")
    assert "padding: 7px 9px;" in card
    assert "border: 1px solid var(--border);" in card

    actions = _block(source, ".load-control-p-observer-actions")
    assert "margin-top: 0;" in actions
