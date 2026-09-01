from pathlib import Path


def test_recording_monitor_ui_exposes_p_and_q_threshold_conditions() -> None:
    source = Path("frontend/js/recording-monitor-ui.js").read_text(encoding="utf-8")
    assert 'const CONDITIONS = new Set(["P_NEGATIVE", "Q_THRESHOLD"]);' in source
    assert '<option value="P_NEGATIVE">P &lt; 0</option>' in source
    assert '<option value="Q_THRESHOLD">Q THRESHOLD</option>' in source
    assert "RECORDING CONDITION MONITOR" in source
    assert 'id="recording-monitor-q-threshold"' in source
    assert 'id="recording-monitor-q-direction"' in source
    assert '<option value="POSITIVE">POSITIVE</option>' in source
    assert '<option value="NEGATIVE">NEGATIVE</option>' in source
    assert '<option value="BOTH">BOTH</option>' in source
    assert "PF_NEGATIVE" not in source
    assert "P_OR_PF_NEGATIVE" not in source
    assert "PF &lt; 0" not in source
    assert "P &lt; 0 OR PF &lt; 0" not in source
