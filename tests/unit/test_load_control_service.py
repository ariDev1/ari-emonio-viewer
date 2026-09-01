from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import time

from emonio_viewer.load_control.evidence import EvidenceWriteError
from emonio_viewer.load_control.model import ControlMode, SafeState
from emonio_viewer.load_control.service import LoadControlService, MOCK_ACTUATOR
from emonio_viewer.runtime.events import RuntimeEventBus


def _sample(real_sample, *, cycle_id: int, p_a: float, p_b: float, p_c: float):
    now_utc = datetime.now(timezone.utc)
    now_ns = time.monotonic_ns()

    def phase(block, p):
        return replace(block, measurement=replace(block.measurement, p=p))

    return replace(
        real_sample,
        identity=replace(real_sample.identity, cycle_id=cycle_id),
        timing=replace(
            real_sample.timing,
            cycle_started_utc=now_utc,
            cycle_finished_utc=now_utc,
            cycle_started_monotonic_ns=now_ns,
            cycle_finished_monotonic_ns=now_ns,
            cycle_span_ms=0.0,
        ),
        phase_a=phase(real_sample.phase_a, p_a),
        phase_b=phase(real_sample.phase_b, p_b),
        phase_c=phase(real_sample.phase_c, p_c),
    )


async def _configured_service(tmp_path, real_sample):
    service = LoadControlService(
        RuntimeEventBus(),
        config_path=tmp_path / "load-control.json",
        evidence_path=tmp_path / "load-control.jsonl",
        viewer_session_id="VIEWER-TEST-001",
    )
    await service.configure_binding(
        emonio_device_id=real_sample.identity.device_id,
        actuator_node_id=MOCK_ACTUATOR.node_id,
    )
    await service.configure_limits(
        p_reserve=30.0,
        operator_limit_a=600.0,
        operator_limit_b=600.0,
        operator_limit_c=600.0,
    )
    await service.configure_timing(
        control_sample_max_age_s=5.0,
        ack_timeout_s=1.0,
    )
    return service


def test_service_closes_loop_with_mock_ack_and_operator_disable(tmp_path, real_sample):
    async def scenario():
        service = await _configured_service(tmp_path, real_sample)

        first = _sample(real_sample, cycle_id=1, p_a=30.0, p_b=30.0, p_c=30.0)
        await service._handle_runtime_event(first)
        status = service.status()
        assert status["control_mode"] == ControlMode.DISABLED.value
        assert status["safe_state"] == SafeState.SAFE_CONFIRMED.value
        assert status["acknowledged_p"] == {"a": 0.0, "b": 0.0, "c": 0.0}

        await service.enable()
        assert service.status()["control_mode"] == ControlMode.ENABLED.value

        second = _sample(real_sample, cycle_id=2, p_a=-420.0, p_b=30.0, p_c=30.0)
        await service._handle_runtime_event(second)
        status = service.status()
        assert status["last_requested_p"] == {"a": 450.0, "b": 0.0, "c": 0.0}
        assert status["acknowledged_p"] == {"a": 450.0, "b": 0.0, "c": 0.0}
        assert status["last_calculation"]["a"]["raw_request"] == 450.0

        await service.disable()
        status = service.status()
        assert status["control_mode"] == ControlMode.DISABLED.value
        assert status["safe_state"] == SafeState.SAFE_CONFIRMED.value
        assert status["last_requested_p"] == {"a": 0.0, "b": 0.0, "c": 0.0}

    asyncio.run(scenario())


def test_required_evidence_failure_trips_and_preempts_with_zero(tmp_path, real_sample, monkeypatch):
    async def scenario():
        service = await _configured_service(tmp_path, real_sample)
        first = _sample(real_sample, cycle_id=1, p_a=30.0, p_b=30.0, p_c=30.0)
        await service._handle_runtime_event(first)
        await service.enable()

        original_append = service.evidence_writer.append

        def fail_control_calculation(event):
            if event.get("event") == "CONTROL_COMMAND_CALCULATED":
                raise EvidenceWriteError("injected evidence failure")
            original_append(event)

        monkeypatch.setattr(service.evidence_writer, "append", fail_control_calculation)

        second = _sample(real_sample, cycle_id=2, p_a=-420.0, p_b=30.0, p_c=30.0)
        await service._handle_runtime_event(second)
        status = service.status()
        assert status["control_mode"] == ControlMode.TRIPPED.value
        assert status["trip_reason"] == "EVIDENCE_WRITE_FAILED"
        assert status["last_requested_p"] == {"a": 0.0, "b": 0.0, "c": 0.0}

    asyncio.run(scenario())


def test_timing_is_volatile_and_not_written_to_persistent_config(tmp_path, real_sample):
    async def scenario():
        config_path = tmp_path / "load-control.json"
        service = LoadControlService(
            RuntimeEventBus(),
            config_path=config_path,
            evidence_path=tmp_path / "load-control.jsonl",
            viewer_session_id="VIEWER-TEST-002",
        )
        await service.configure_binding(
            emonio_device_id=real_sample.identity.device_id,
            actuator_node_id=MOCK_ACTUATOR.node_id,
        )
        await service.configure_limits(
            p_reserve=30.0,
            operator_limit_a=600.0,
            operator_limit_b=600.0,
            operator_limit_c=600.0,
        )
        await service.configure_timing(
            control_sample_max_age_s=4.0,
            ack_timeout_s=0.8,
        )
        text = config_path.read_text(encoding="utf-8")
        assert "control_sample_max_age_s" not in text
        assert "ack_timeout_s" not in text

    asyncio.run(scenario())
