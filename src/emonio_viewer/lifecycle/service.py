from __future__ import annotations

import asyncio

from .model import DeviceLifecycleCommandError, DeviceLifecycleResult, LifecycleFailureStage


class DeviceLifecycleService:
    """Coordinate one device shutdown without changing subsystem science."""

    def __init__(self, coordinator, recording, scope_service, store) -> None:
        self._coordinator = coordinator
        self._recording = recording
        self._scope = scope_service
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, device_id: str) -> asyncio.Lock:
        lock = self._locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[device_id] = lock
        return lock

    def _recording_is_active(self, device_id: str) -> bool:
        checker = getattr(self._recording, "is_active", None)
        if callable(checker):
            return bool(checker(device_id))
        return any(
            item.get("device_id") == device_id
            for item in self._recording.active_recordings()
        )

    def status(
        self,
        device_id: str,
        *,
        failed_stage: LifecycleFailureStage | None = None,
        detail: str | None = None,
        recording_state: str | None = None,
    ) -> DeviceLifecycleResult:
        acquisition = self._coordinator.acquisition_status(device_id)
        measurement = self._store.get_device(device_id)
        scope = self._scope.status(device_id)
        if recording_state is None:
            recording_state = "RECORDING" if self._recording_is_active(device_id) else "STOPPED"
        return DeviceLifecycleResult(
            device_id=device_id,
            acquisition_state=acquisition.state.value,
            measurement_state=measurement.state.value,
            recording_state=recording_state,
            scope_state=scope.state.value,
            failed_stage=failed_stage,
            detail=detail,
        )

    async def disconnect(self, device_id: str) -> DeviceLifecycleResult:
        async with self._lock_for(device_id):
            if self._recording_is_active(device_id):
                try:
                    self._recording.stop(device_id)
                except Exception as exc:
                    result = self.status(
                        device_id,
                        failed_stage=LifecycleFailureStage.RECORDING,
                        detail=str(exc) or type(exc).__name__,
                        recording_state="ERROR",
                    )
                    raise DeviceLifecycleCommandError(result) from exc

            try:
                await self._scope.stop(device_id)
            except Exception as exc:
                result = self.status(
                    device_id,
                    failed_stage=LifecycleFailureStage.SCOPE,
                    detail=str(exc) or type(exc).__name__,
                )
                raise DeviceLifecycleCommandError(result) from exc

            try:
                await asyncio.to_thread(self._coordinator.disconnect_device, device_id)
            except Exception as exc:
                result = self.status(
                    device_id,
                    failed_stage=LifecycleFailureStage.ACQUISITION,
                    detail=str(exc) or type(exc).__name__,
                )
                raise DeviceLifecycleCommandError(result) from exc

            return self.status(device_id)

    async def reconnect(self, device_id: str) -> DeviceLifecycleResult:
        async with self._lock_for(device_id):
            try:
                await asyncio.to_thread(self._coordinator.reconnect_device, device_id)
            except Exception as exc:
                result = self.status(
                    device_id,
                    failed_stage=LifecycleFailureStage.ACQUISITION,
                    detail=str(exc) or type(exc).__name__,
                )
                raise DeviceLifecycleCommandError(result) from exc
            return self.status(device_id)
