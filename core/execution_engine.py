import os
import sys
import time
import traceback
import tempfile
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QThread, Signal
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

from core.project_manager import ProjectManager

class ExecutionEngineWorker(QThread):
    """
    QThread worker to execute routines/groups/tests asynchronously in Playwright.
    """
    status_signal = Signal(str)
    log_signal = Signal(str)
    step_progress_signal = Signal(int, int) # current, total
    step_status_signal = Signal(str, str, str) # item_id, status ('RUNNING'/'PASS'/'FAIL'), error_msg
    finished_signal = Signal(bool, str) # success, summary
    screenshot_signal = Signal(str) # screenshot path on failure

    def __init__(self, project_manager: ProjectManager, mode: str, item_id: str, headed: bool = True, speed_mode: str = "fastest", auto_close: bool = True):
        super().__init__()
        self.pm = project_manager
        self.mode = mode # 'routine', 'group', or 'test'
        self.item_id = item_id
        self.headed = headed
        self.speed_mode = speed_mode # 'fastest', 'normal', 'slow', 'step'
        self.auto_close = auto_close
        self._is_cancelled = False

    def get_slow_mo_ms(self) -> int:
        mapping = {
            "fastest": 0,
            "normal": 300,
            "slow": 1000,
            "step": 2500
        }
        return mapping.get(self.speed_mode, 0)

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        slow_mo_ms = self.get_slow_mo_ms()
        self.log_signal.emit(f"=== Starte Ausführung ({self.mode.upper()}: {self.item_id}) | Tempo: {self.speed_mode} ({slow_mo_ms}ms) | Auto-Close: {self.auto_close} ===")
        start_time = time.time()
        
        # Load variables
        variables = self.pm.get_variables()
        
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

        total_steps = len(routine_sequence)
        self.step_progress_signal.emit(0, total_steps)

        passed_count = 0
        failed_count = 0

        all_browsers: List[Browser] = []
        all_contexts: List[BrowserContext] = []

        with sync_playwright() as p:
            current_browser: Optional[Browser] = None
            current_context: Optional[BrowserContext] = None
            current_page: Optional[Page] = None

            def create_session():
                b = p.chromium.launch(headless=not self.headed, slow_mo=slow_mo_ms)
                c = b.new_context()
                pg = c.new_page()
                pg.set_default_timeout(15000) # 15 second action timeout
                all_browsers.append(b)
                all_contexts.append(c)
                return b, c, pg

            try:
                if not isolated_session:
                    self.log_signal.emit("[INFO] Starte shared Browser Context...")
                    current_browser, current_context, current_page = create_session()

                for idx, item in enumerate(routine_sequence, start=1):
                    if self._is_cancelled:
                        self.log_signal.emit("[ABBRUCH] Ausführung durch Benutzer gestoppt.")
                        break

                    rid = item["id"]
                    self.status_signal.emit(f"Führe Routine {idx}/{total_steps} aus: {rid}")
                    self.step_status_signal.emit(rid, "RUNNING", "")
                    self.log_signal.emit(f"[{idx}/{total_steps}] Starte Routine '{rid}'...")

                    if isolated_session:
                        self.log_signal.emit(f"[{rid}] Starte isolierte Browser-Session...")
                        current_browser, current_context, current_page = create_session()

                    # Load routine code
                    code_content = self.pm.get_routine_code(rid)
                    if not code_content:
                        err_msg = f"Routine-Datei für '{rid}' existiert nicht!"
                        self.log_signal.emit(f"[FEHLER] {err_msg}")
                        self.step_status_signal.emit(rid, "FAIL", err_msg)
                        failed_count += 1
                        continue

                    # Execute python snippet
                    step_start = time.time()
                    success, error_msg = self._execute_snippet(code_content, current_page, variables)
                    duration = time.time() - step_start

                    if success:
                        passed_count += 1
                        self.log_signal.emit(f"[PASS] Routine '{rid}' erfolgreich ({duration:.2f}s).")
                        self.step_status_signal.emit(rid, "PASS", "")
                    else:
                        failed_count += 1
                        self.log_signal.emit(f"[FAIL] Routine '{rid}' fehlgeschlagen ({duration:.2f}s): {error_msg}")
                        self.step_status_signal.emit(rid, "FAIL", error_msg)

                        # Take error screenshot
                        if current_page and not current_page.is_closed():
                            try:
                                screenshot_dir = os.path.join(tempfile.gettempdir(), "py_auto_tester_screenshots")
                                os.makedirs(screenshot_dir, exist_ok=True)
                                shot_path = os.path.join(screenshot_dir, f"error_{rid}_{int(time.time())}.png")
                                current_page.screenshot(path=shot_path, full_page=True)
                                self.screenshot_signal.emit(shot_path)
                                self.log_signal.emit(f"[SCREENSHOT] Gespeichert unter: {shot_path}")
                            except Exception as se:
                                self.log_signal.emit(f"[WARN] Screenshot konnte nicht erstellt werden: {str(se)}")

                    if isolated_session and self.auto_close:
                        try:
                            if current_page and not current_page.is_closed(): current_page.close()
                            if current_context: current_context.close()
                            if current_browser: current_browser.close()
                        except Exception:
                            pass

                    self.step_progress_signal.emit(idx, total_steps)

            except Exception as e:
                tb = traceback.format_exc()
                self.log_signal.emit(f"[SYSTEM FEHLER] Unerwarteter Playwright Fehler:\n{tb}")
                self.finished_signal.emit(False, f"Systemfehler: {str(e)}")
                return
            finally:
                if self.auto_close:
                    self.log_signal.emit("[INFO] Schließe alle Browserfenster...")
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
                    self.log_signal.emit("[INFO] Browser bleibt nach Ausführung geöffnet.")

        elapsed = time.time() - start_time
        summary = f"Ausführung beendet in {elapsed:.2f}s | Erfolgreich: {passed_count} | Fehlgeschlagen: {failed_count}"
        self.log_signal.emit(f"=== {summary} ===")
        overall_success = (failed_count == 0 and not self._is_cancelled)
        self.finished_signal.emit(overall_success, summary)

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
