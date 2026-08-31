from emonio_viewer import main as base_main
from emonio_viewer.recording.continuous_monitor import NegativeMonitorRecordingManager
from emonio_viewer.server.app_v0416 import create_app


def main(argv: list[str] | None = None) -> int:
    base_main.RecordingManager = NegativeMonitorRecordingManager
    base_main.create_app = create_app
    return base_main.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
