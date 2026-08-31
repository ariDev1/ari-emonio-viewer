from pathlib import Path


def test_negative_monitor_ui_exposes_only_p_negative_condition() -> None:
    source = Path("frontend/js/recording-monitor-ui.js").read_text(encoding="utf-8")
    assert 'const CONDITIONS = new Set(["P_NEGATIVE"]);' in source
    assert "PF_NEGATIVE" not in source
    assert "P_OR_PF_NEGATIVE" not in source
    assert "PF &lt; 0" not in source
    assert "P &lt; 0 OR PF &lt; 0" not in source
    assert '<option value="P_NEGATIVE">P &lt; 0</option>' in source
