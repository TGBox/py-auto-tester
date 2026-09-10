"""
Qt-Adapter für die Ausführungs-Engine.

Enthält keine Ausführungslogik — er startet den TestRunner in einem QThread und
übersetzt dessen Listener-Ereignisse in Qt-Signale.
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

from core.project_manager import ProjectManager
from core.models import RunConfig, RunResult, get_context_options, get_slow_mo_ms
from core.runner import TestRunner, RunnerListener


class _SignalListener(RunnerListener):
    """Leitet Runner-Ereignisse an die Signale des Workers weiter."""

    def __init__(self, worker: "ExecutionEngineWorker"):
        self._w = worker

    def on_log(self, message): self._w.log_signal.emit(message)
    def on_status(self, message): self._w.status_signal.emit(message)
    def on_progress(self, current, total): self._w.step_progress_signal.emit(current, total)
    def on_step_status(self, label, status, error): self._w.step_status_signal.emit(label, status, error)
    def on_step_result(self, result): self._w.step_result_signal.emit(result)
    def on_screenshot(self, path): self._w.screenshot_signal.emit(path)

    def on_finished(self, result: RunResult):
        self._w.finished_signal.emit(result.success, result.summary, result.report_path)


class ExecutionEngineWorker(QThread):
    """
    QThread worker to execute routines/groups/tests asynchronously in Playwright.

    Die eigentliche Arbeit macht core.runner.TestRunner; dieser Wrapper existiert
    nur, damit die GUI nicht blockiert und Ergebnisse als Signale ankommen.
    """
    status_signal = Signal(str)
    log_signal = Signal(str)
    step_progress_signal = Signal(int, int)          # current, total
    step_status_signal = Signal(str, str, str)       # label, status, error
    step_result_signal = Signal(dict)                # full step result
    finished_signal = Signal(bool, str, str)         # success, summary, report_path
    screenshot_signal = Signal(str)                  # screenshot path on failure

    def __init__(
        self,
        project_manager: ProjectManager,
        mode: str,
        item_id: str,
        headed: bool = True,
        speed_mode: str = "fastest",
        auto_close: bool = True,
        browser_engine: str = "chromium",
        device_profile: str = "desktop_1080p",
        dataset_id: Optional[str] = None,
        stop_on_first_failure: bool = False,
    ):
        super().__init__()
        self.pm = project_manager
        self.config = RunConfig(
            mode=mode,
            item_id=item_id,
            headed=headed,
            speed_mode=speed_mode,
            auto_close=auto_close,
            browser_engine=browser_engine,
            device_profile=device_profile,
            dataset_id=dataset_id,
            stop_on_first_failure=stop_on_first_failure,
        )
        self.runner = TestRunner(project_manager, self.config, listener=_SignalListener(self))
        self.result: Optional[RunResult] = None

    # --- Bequemer Zugriff auf die Konfiguration (die GUI liest diese Felder) --

    @property
    def mode(self) -> str: return self.config.mode

    @property
    def item_id(self) -> str: return self.config.item_id

    @property
    def dataset_id(self) -> Optional[str]: return self.config.dataset_id

    @property
    def browser_engine(self) -> str: return self.config.browser_engine

    @property
    def device_profile(self) -> str: return self.config.device_profile

    @property
    def speed_mode(self) -> str: return self.config.speed_mode

    @property
    def settings(self) -> Dict[str, Any]: return self.runner.settings

    def get_slow_mo_ms(self) -> int:
        return get_slow_mo_ms(self.config.speed_mode)

    @staticmethod
    def get_context_options(profile: str) -> dict:
        return get_context_options(profile)

    # --- Steuerung ----------------------------------------------------------

    def cancel(self):
        self.runner.cancel()

    def run(self):
        self.result = self.runner.run()
