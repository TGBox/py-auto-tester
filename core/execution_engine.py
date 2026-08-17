import os
import sys
import time
import traceback
import tempfile
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QThread, Signal
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

from core.project_manager import ProjectManager
from core.report_generator import ReportGenerator

class ExecutionEngineWorker(QThread):
    """
    QThread worker to execute routines/groups/tests asynchronously in Playwright.
    """
    status_signal = Signal(str)
    log_signal = Signal(str)
    step_progress_signal = Signal(int, int) # current, total
    step_status_signal = Signal(str, str, str) # item_id, status ('RUNNING'/'PASS'/'FAIL'), error_msg
    finished_signal = Signal(bool, str, str) # success, summary, report_path
    screenshot_signal = Signal(str) # screenshot path on failure

    def __init__(self, project_manager: ProjectManager, mode: str, item_id: str, headed: bool = True, speed_mode: str = "fastest", auto_close: bool = True, browser_engine: str = "chromium", device_profile: str = "desktop_1080p", dataset_id: Optional[str] = None):
        super().__init__()
        self.pm = project_manager
        self.mode = mode # 'routine', 'group', or 'test'
        self.item_id = item_id
        self.headed = headed
        self.speed_mode = speed_mode # 'fastest', 'normal', 'slow', 'step'
        self.auto_close = auto_close
        self.browser_engine = browser_engine.lower() # 'chromium', 'firefox', 'webkit'
        self.device_profile = device_profile # 'desktop_1080p', 'iphone_14', etc.
        self.dataset_id = dataset_id
        self._is_cancelled = False

    def get_slow_mo_ms(self) -> int:
        mapping = {
            "fastest": 0,
            "normal": 300,
            "slow": 1000,
            "step": 2500
        }
        return mapping.get(self.speed_mode, 0)

    @staticmethod
    def get_context_options(profile: str) -> dict:
        profiles = {
            "desktop_1080p": {"viewport": {"width": 1920, "height": 1080}},
            "desktop_768p": {"viewport": {"width": 1366, "height": 768}},
            "iphone_14": {
                "viewport": {"width": 390, "height": 844},
                "is_mobile": True,
                "has_touch": True,
                "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
            },
            "pixel_7": {
                "viewport": {"width": 412, "height": 915},
                "is_mobile": True,
                "has_touch": True,
                "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
            },
            "ipad_air": {
                "viewport": {"width": 820, "height": 1180},
                "is_mobile": True,
                "has_touch": True
            }
        }
        return profiles.get(profile, {"viewport": {"width": 1280, "height": 720}})

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        slow_mo_ms = self.get_slow_mo_ms()
        ctx_opts = self.get_context_options(self.device_profile)
        ds_msg = f" | Datensatz: {self.dataset_id}" if self.dataset_id else ""
        self.log_signal.emit(f"=== Starte Ausführung ({self.mode.upper()}: {self.item_id}) | Browser: {self.browser_engine.upper()} | Gerät: {self.device_profile}{ds_msg} ===")
        start_time = time.time()
        
        # Load variables
        variables = self.pm.get_variables()

        # Load dataset rows if specified
        dataset_rows = []
        if self.dataset_id:
            _, _, dataset_rows = self.pm.get_dataset_data(self.dataset_id)
            if not dataset_rows:
                self.log_signal.emit(f"[WARN] Datensatz '{self.dataset_id}' ist leer oder konnte nicht geladen werden. Nutze Standard-Variablen.")
                dataset_rows = [variables]
        else:
            dataset_rows = [variables]
        
        # Build execution sequence of routine IDs
        routine_sequence: List[Dict[str, Any]] = []
        isolated_session = False

        if self.mode == "routine":
            routine_sequence = [{"id": self.item_id, "name": self.item_id}]
        elif self.mode == "group":
            groups = self.pm.get_groups()
            group = next((g for g in groups if g["id"] == self.item_id), None)
            if group:
                for rid in group.get("routine_ids", []):
                    routine_sequence.append({"id": rid, "name": rid, "group_id": group["id"]})
        elif self.mode == "test":
            tests = self.pm.get_tests()
            test = next((t for t in tests if t["id"] == self.item_id), None)
            if test:
                isolated_session = test.get("isolated_session", False)
                # Test overrides if present
                if test.get("browser_engine"):
                    self.browser_engine = test["browser_engine"].lower()
                if test.get("device_profile"):
                    self.device_profile = test["device_profile"]
                    ctx_opts = self.get_context_options(self.device_profile)

                groups_dict = {g["id"]: g for g in self.pm.get_groups()}
                
                for item in test.get("item_ids", []):
                    if item.startswith("group:"):
                        gid = item.replace("group:", "")
                        if gid in groups_dict:
                            for rid in groups_dict[gid].get("routine_ids", []):
                                routine_sequence.append({"id": rid, "name": rid, "group_id": gid})
                    elif item.startswith("routine:"):
                        rid = item.replace("routine:", "")
                        routine_sequence.append({"id": rid, "name": rid})

        if not routine_sequence:
            self.log_signal.emit("[FEHLER] Keine gültigen Routinen zur Ausführung gefunden.")
            self.finished_signal.emit(False, "Keine Routinen in der Ausführungssequenz.")
            return

        total_iterations = len(dataset_rows)
        total_steps = len(routine_sequence) * total_iterations
        self.step_progress_signal.emit(0, total_steps)

        passed_count = 0
        failed_count = 0
        current_step_counter = 0

        collected_logs: List[str] = []
        collected_step_results: List[Dict[str, Any]] = []

        def log_and_emit(msg: str):
            collected_logs.append(msg)
            self.log_signal.emit(msg)

        all_browsers: List[Browser] = []
        all_contexts: List[BrowserContext] = []

        with sync_playwright() as p:
            current_browser: Optional[Browser] = None
            current_context: Optional[BrowserContext] = None
            current_page: Optional[Page] = None

            # Select Playwright engine
            engine = getattr(p, self.browser_engine, p.chromium)

            def create_session():
                b = engine.launch(headless=not self.headed, slow_mo=slow_mo_ms)
                c = b.new_context(**ctx_opts)
                pg = c.new_page()
                pg.set_default_timeout(15000) # 15 second action timeout
                all_browsers.append(b)
                all_contexts.append(c)
                return b, c, pg

            try:
                if not isolated_session:
                    log_and_emit("[INFO] Starte shared Browser Context...")
                    current_browser, current_context, current_page = create_session()

                for row_idx, row_vars in enumerate(dataset_rows, start=1):
                    if self._is_cancelled:
                        break

                    # Merge base variables with row variables
                    iter_vars = {**variables, **row_vars}
                    if len(dataset_rows) > 1:
                        log_and_emit(f"--- 📊 DATENSATZ ZEILE {row_idx}/{total_iterations} ---")

                    for idx, item in enumerate(routine_sequence, start=1):
                        if self._is_cancelled:
                            log_and_emit("[ABBRUCH] Ausführung durch Benutzer gestoppt.")
                            break

                        current_step_counter += 1
                        rid = item["id"]
                        step_label = f"{rid} (Zeile {row_idx})" if len(dataset_rows) > 1 else rid
                        
                        self.status_signal.emit(f"Führe Routine {idx}/{len(routine_sequence)} aus: {step_label}")
                        self.step_status_signal.emit(step_label, "RUNNING", "")
                        log_and_emit(f"[{current_step_counter}/{total_steps}] Starte Routine '{rid}'...")

                        if isolated_session:
                            log_and_emit(f"[{rid}] Starte isolierte Browser-Session...")
                            current_browser, current_context, current_page = create_session()

                        # Load routine code
                        code_content = self.pm.get_routine_code(rid)
                        if not code_content:
                            err_msg = f"Routine-Datei für '{rid}' existiert nicht!"
                            log_and_emit(f"[FEHLER] {err_msg}")
                            self.step_status_signal.emit(step_label, "FAIL", err_msg)
                            failed_count += 1
                            collected_step_results.append({
                                "name": step_label, "status": "FAIL", "duration": 0.0, "error": err_msg, "screenshot": ""
                            })
                            continue

                        # Execute python snippet
                        step_start = time.time()
                        success, error_msg = self._execute_snippet(code_content, current_page, iter_vars)
                        duration = time.time() - step_start

                        shot_path = ""
                        if success:
                            passed_count += 1
                            log_and_emit(f"[PASS] Routine '{rid}' erfolgreich ({duration:.2f}s).")
                            self.step_status_signal.emit(step_label, "PASS", "")
                        else:
                            failed_count += 1
                            log_and_emit(f"[FAIL] Routine '{rid}' fehlgeschlagen ({duration:.2f}s): {error_msg}")
                            self.step_status_signal.emit(step_label, "FAIL", error_msg)

                            # Take error screenshot
                            if current_page and not current_page.is_closed():
                                try:
                                    screenshot_dir = os.path.join(tempfile.gettempdir(), "py_auto_tester_screenshots")
                                    os.makedirs(screenshot_dir, exist_ok=True)
                                    shot_path = os.path.join(screenshot_dir, f"error_{rid}_{int(time.time())}.png")
                                    current_page.screenshot(path=shot_path, full_page=True)
                                    self.screenshot_signal.emit(shot_path)
                                    log_and_emit(f"[SCREENSHOT] Gespeichert unter: {shot_path}")
                                except Exception as se:
                                    log_and_emit(f"[WARN] Screenshot konnte nicht erstellt werden: {str(se)}")

                        collected_step_results.append({
                            "name": step_label,
                            "status": "PASS" if success else "FAIL",
                            "duration": duration,
                            "error": error_msg,
                            "screenshot": shot_path
                        })

                        if isolated_session and self.auto_close:
                            try:
                                if current_page and not current_page.is_closed(): current_page.close()
                                if current_context: current_context.close()
                                if current_browser: current_browser.close()
                            except Exception:
                                pass

                        self.step_progress_signal.emit(current_step_counter, total_steps)

            except Exception as e:
                tb = traceback.format_exc()
                log_and_emit(f"[SYSTEM FEHLER] Unerwarteter Playwright Fehler:\n{tb}")
                report_p = ReportGenerator.generate(
                    self.item_id, self.mode, self.browser_engine, self.device_profile,
                    self.speed_mode, self.dataset_id, time.time() - start_time,
                    passed_count, failed_count, collected_step_results, collected_logs, self.pm.reports_dir
                )
                self.finished_signal.emit(False, f"Systemfehler: {str(e)}", report_p)
                return
            finally:
                if self.auto_close:
                    log_and_emit("[INFO] Schließe alle Browserfenster...")
                    for ctx in all_contexts:
                        try:
                            for pg in ctx.pages:
                                if not pg.is_closed():
                                    pg.close()
                            ctx.close()
                        except Exception:
                            pass
                    for b in all_browsers:
                        try:
                            b.close()
                        except Exception:
                            pass
                else:
                    log_and_emit("[INFO] Browser bleibt nach Ausführung geöffnet.")

        elapsed = time.time() - start_time
        summary = f"Ausführung beendet in {elapsed:.2f}s | Erfolgreich: {passed_count} | Fehlgeschlagen: {failed_count}"
        log_and_emit(f"=== {summary} ===")

        # Generate HTML Report
        report_path = ReportGenerator.generate(
            target_name=self.item_id,
            mode=self.mode,
            browser_engine=self.browser_engine,
            device_profile=self.device_profile,
            speed_mode=self.speed_mode,
            dataset_id=self.dataset_id,
            total_duration=elapsed,
            passed_count=passed_count,
            failed_count=failed_count,
            step_results=collected_step_results,
            logs=collected_logs,
            reports_dir=self.pm.reports_dir
        )
        log_and_emit(f"[REPORT] HTML-Testbericht erstellt: {report_path}")

        overall_success = (failed_count == 0 and not self._is_cancelled)
        self.finished_signal.emit(overall_success, summary, report_path)

    def _execute_snippet(self, code: str, page: Page, vars_dict: Dict[str, str]) -> tuple[bool, str]:
        """
        Executes routine python snippet dynamically passing page and vars_dict.
        """
        local_scope = {}
        global_scope = {
            "page": page,
            "vars": vars_dict,
            "Playwright": None,
            "re": __import__("re")
        }
        
        try:
            exec(code, global_scope, local_scope)
            
            # Check if execute(page, vars) function exists
            execute_fn = local_scope.get("execute") or global_scope.get("execute")
            if callable(execute_fn):
                execute_fn(page, vars_dict)
                return True, ""
            else:
                # If no function wrapper, exec ran top-level code directly
                return True, ""
                
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)}"
            return False, err_msg
