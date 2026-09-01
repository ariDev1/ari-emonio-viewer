import json

import pytest

from emonio_viewer.load_control.evidence import ControlEvidenceWriter, EvidenceWriteError


def test_evidence_writer_appends_one_deterministic_json_object_per_line(tmp_path):
    path = tmp_path / "load-control-evidence.jsonl"
    writer = ControlEvidenceWriter(path)
    writer.append({"event": "CONTROL_SERVICE_STARTED", "z": 2, "a": 1})
    writer.append({"event": "CONTROL_ENABLE_REJECTED", "reason": "NO_SAMPLE"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0] == '{"a":1,"event":"CONTROL_SERVICE_STARTED","z":2}'
    assert json.loads(lines[1])["reason"] == "NO_SAMPLE"
    assert writer.healthy is True


def test_recent_returns_decoded_tail_without_rewriting_file(tmp_path):
    path = tmp_path / "load-control-evidence.jsonl"
    writer = ControlEvidenceWriter(path)
    for index in range(5):
        writer.append({"event": "TEST", "index": index})
    before = path.read_bytes()
    assert tuple(item["index"] for item in writer.recent(2)) == (3, 4)
    assert path.read_bytes() == before


def test_write_failure_marks_writer_unhealthy(tmp_path, monkeypatch):
    path = tmp_path / "load-control-evidence.jsonl"
    writer = ControlEvidenceWriter(path)

    def fail_open(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(path.__class__, "open", fail_open)
    with pytest.raises(EvidenceWriteError):
        writer.append({"event": "CONTROL_COMMAND_SENT"})
    assert writer.healthy is False
    assert "disk full" in writer.last_error
