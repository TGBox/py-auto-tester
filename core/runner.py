"""
Ausführungs-Engine — reines Python, ohne Qt.

Das ist der Kern: er weiß, wie eine Routine, Gruppe oder ein Test ausgeführt
wird, und meldet den Verlauf über einen Listener. Wer zuhört, ist ihm egal —
die GUI mappt die Ereignisse auf Qt-Signale, die CLI schreibt sie nach stdout,
Tests sammeln sie in Listen.
"""

import ast
import os
import linecache
import sys
import tempfile
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import sync_playwright, expect, Browser, BrowserContext, Page

from core.project_manager import ProjectManager
from core.report_generator import ReportGenerator
from core.diagnostics import PageDiagnostics
from core.checks import CheckRecorder, build_check_api, evaluate_checks
from core.models import RunConfig, RunResult, StepResult
from core.run_artifacts import RunArtifacts, prune_runs
from core import junit_report


class RunnerListener:
    """
    Beobachter eines Laufs. Alle Methoden sind no-ops, damit Zuhörer nur das
    überschreiben, was sie brauchen.
    """

    def on_log(self, message: str) -> None: ...
    def on_status(self, message: str) -> None: ...
    def on_progress(self, current: int, total: int) -> None: ...
    def on_step_status(self, label: str, status: str, error: str) -> None: ...
    def on_step_result(self, result: Dict[str, Any]) -> None: ...
    def on_screenshot(self, path: str) -> None: ...
    def on_finished(self, result: RunResult) -> None: ...


class CallbackListener(RunnerListener):
    """Listener aus einzelnen Callables — praktisch für Tests und kleine Adapter."""

    def __init__(self, **callbacks: Callable):
        self._cb = {k: v for k, v in callbacks.items() if callable(v)}

    def _call(self, name: str, *args):
        fn = self._cb.get(name)
        if fn:
            fn(*args)

    def on_log(self, message): self._call("on_log", message)
    def on_status(self, message): self._call("on_status", message)
    def on_progress(self, current, total): self._call("on_progress", current, total)
    def on_step_status(self, label, status, error): self._call("on_step_status", label, status, error)
    def on_step_result(self, result): self._call("on_step_result", result)
    def on_screenshot(self, path): self._call("on_screenshot", path)
    def on_finished(self, result): self._call("on_finished", result)


class TestRunner:
    """
    Führt eine Routine, Gruppe oder einen Test in Playwright aus.

    Benutzung:
        runner = TestRunner(pm, RunConfig(mode="test", item_id="login_flow"))
        result = runner.run()
    """

    def __init__(
        self,
        project_manager: ProjectManager,
        config: RunConfig,
        listener: Optional[RunnerListener] = None,
    ):
        self.pm = project_manager
        self.config = config
        self.listener = listener or RunnerListener()
        self.settings = project_manager.get_settings()

        self._cancelled = False
        self._logs: List[str] = []

        # Artefakt-Verzeichnis dieses Laufs (erst in run() angelegt)
        self.artifacts: Optional[RunArtifacts] = None
        self._traced_contexts: List[Any] = []
        self._video_pages: List[Any] = []

    # ------------------------------------------------------------------ intern

    def cancel(self):
        """Bittet den Lauf, bei der nächsten Prüfstelle abzubrechen."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def _log(self, message: str):
        self._logs.append(message)
        self.listener.on_log(message)

    @staticmethod
    def _safe_url(page: Optional[Page]) -> str:
        """Aktuelle URL, oder leer wenn die Seite schon zu ist."""
        try:
            if page and not page.is_closed():
                return page.url or ""
        except Exception:
            pass
        return ""

    # ------------------------------------------------ Ausführungssequenz bauen

    def _build_sequence(self) -> tuple[List[Dict[str, Any]], bool]:
        """
        Löst mode/item_id in eine flache Liste von Routinen auf.
        Nebeneffekt: ein Test darf Browser, Gerät und Diagnose-Policy überschreiben.
        """
        cfg = self.config
        sequence: List[Dict[str, Any]] = []
        isolated_session = False

        if cfg.mode == "routine":
            sequence = [{"id": cfg.item_id, "name": cfg.item_id}]

        elif cfg.mode == "group":
            group = next((g for g in self.pm.get_groups() if g["id"] == cfg.item_id), None)
            if group:
                for rid in group.get("routine_ids", []):
                    sequence.append({"id": rid, "name": rid, "group_id": group["id"]})

        elif cfg.mode == "test":
            test = next((t for t in self.pm.get_tests() if t["id"] == cfg.item_id), None)
            if test:
                isolated_session = test.get("isolated_session", False)

                if test.get("browser_engine"):
                    cfg.browser_engine = test["browser_engine"].lower()
                if test.get("device_profile"):
                    cfg.device_profile = test["device_profile"]
                if test.get("stop_on_first_failure") is not None:
                    cfg.stop_on_first_failure = bool(test["stop_on_first_failure"])
                for key in ("console_policy", "network_policy"):
                    if test.get(key) in ("log", "warn", "fail"):
                        self.settings[key] = test[key]

                groups_dict = {g["id"]: g for g in self.pm.get_groups()}
                for item in test.get("item_ids", []):
                    if item.startswith("group:"):
                        gid = item.replace("group:", "")
                        if gid in groups_dict:
                            for rid in groups_dict[gid].get("routine_ids", []):
                                sequence.append({"id": rid, "name": rid, "group_id": gid})
                    elif item.startswith("routine:"):
                        rid = item.replace("routine:", "")
                        sequence.append({"id": rid, "name": rid})

        return sequence, isolated_session

    def _load_dataset_rows(self, variables: Dict[str, str]) -> List[Dict[str, str]]:
        if not self.config.dataset_id:
            return [variables]

        _, _, rows = self.pm.get_dataset_data(self.config.dataset_id)
        if not rows:
            self._log(
                f"[WARN] Datensatz '{self.config.dataset_id}' ist leer oder konnte nicht "
                "geladen werden. Nutze Standard-Variablen."
            )
            return [variables]
        return rows

    # -------------------------------------------------------------- Hauptlauf

    def run(self) -> RunResult:
        cfg = self.config
        self._logs = []
        result = RunResult(config=cfg)

        ds_msg = f" | Datensatz: {cfg.dataset_id}" if cfg.dataset_id else ""
        self._log(
            f"=== Starte Ausführung ({cfg.mode.upper()}: {cfg.item_id}) "
            f"| Browser: {cfg.browser_engine.upper()} | Gerät: {cfg.device_profile}{ds_msg} ==="
        )
        start_time = time.time()

        variables = self.pm.get_variables()
        dataset_rows = self._load_dataset_rows(variables)
        sequence, isolated_session = self._build_sequence()

        # Ein Test darf Browser/Gerät überschrieben haben -> erst danach auflösen
        ctx_opts = cfg.context_options()
        slow_mo_ms = cfg.slow_mo_ms

        if not sequence:
            self._log("[FEHLER] Keine gültigen Routinen zur Ausführung gefunden.")
            result.logs = list(self._logs)
            result.duration = time.time() - start_time
            self.listener.on_finished(result)
            return result

        # Ab hier wird wirklich ausgeführt -> Artefaktverzeichnis anlegen
        self.artifacts = RunArtifacts(self.pm.runs_dir, cfg.mode, cfg.item_id)
        result.artifacts_dir = self.artifacts.dir
        self._log(f"[INFO] Artefakte dieses Laufs: {self.artifacts.dir}")

        total_iterations = len(dataset_rows)
        total_steps = len(sequence) * total_iterations
        self.listener.on_progress(0, total_steps)

        console_policy = self.settings.get("console_policy", "warn")
        network_policy = self.settings.get("network_policy", "warn")
        check_timeout_ms = int(self.settings.get("check_timeout_ms", 5000))
        trace_mode = self.settings.get("trace_mode", "on_failure")
        video_mode = self.settings.get("video_mode", "off")
        self._log(
            f"[INFO] Diagnose: Konsole={console_policy.upper()}, "
            f"Netzwerk={network_policy.upper()}, Check-Timeout={check_timeout_ms}ms"
        )
        self._log(f"[INFO] Artefakte: Trace={trace_mode.upper()}, Video={video_mode.upper()}")
        if cfg.stop_on_first_failure:
            self._log("[INFO] Abbruch beim ersten Fehler ist aktiv.")

        diagnostics = PageDiagnostics(
            ignore_console=self.settings.get("ignore_console"),
            ignore_urls=self.settings.get("ignore_urls"),
            capture_console_warnings=self.settings.get("capture_console_warnings", False),
        )

        all_browsers: List[Browser] = []
        all_contexts: List[BrowserContext] = []
        current_step_counter = 0
        aborted_early = False

        with sync_playwright() as p:
            current_browser: Optional[Browser] = None
            current_context: Optional[BrowserContext] = None
            current_page: Optional[Page] = None

            engine = getattr(p, cfg.browser_engine, p.chromium)

            def create_session():
                b = engine.launch(headless=not cfg.headed, slow_mo=slow_mo_ms)

                session_opts = dict(ctx_opts)
                if video_mode != "off":
                    # Video wird beim Context konfiguriert, nicht pro Schritt —
                    # die Datei entsteht erst beim Schließen des Contexts.
                    session_opts["record_video_dir"] = self.artifacts.subdir("video")
                    viewport = ctx_opts.get("viewport")
                    if viewport:
                        session_opts["record_video_size"] = dict(viewport)

                c = b.new_context(**session_opts)

                if trace_mode != "off":
                    self._start_tracing(c)

                pg = c.new_page()
                pg.set_default_timeout(cfg.action_timeout_ms)
                diagnostics.attach_context(c)
                diagnostics.attach(pg)
                if video_mode != "off":
                    self._video_pages.append(pg)
                all_browsers.append(b)
                all_contexts.append(c)
                return b, c, pg

            try:
                if not isolated_session:
                    self._log("[INFO] Starte shared Browser Context...")
                    current_browser, current_context, current_page = create_session()

                for row_idx, row_vars in enumerate(dataset_rows, start=1):
                    if self._cancelled or aborted_early:
                        break

                    iter_vars = {**variables, **row_vars}
                    if total_iterations > 1:
                        self._log(f"--- 📊 DATENSATZ ZEILE {row_idx}/{total_iterations} ---")

                    for idx, item in enumerate(sequence, start=1):
                        if self._cancelled:
                            self._log("[ABBRUCH] Ausführung durch Benutzer gestoppt.")
                            break
                        if aborted_early:
                            break

                        current_step_counter += 1
                        rid = item["id"]
                        step_label = f"{rid} (Zeile {row_idx})" if total_iterations > 1 else rid

                        self.listener.on_status(
                            f"Führe Routine {idx}/{len(sequence)} aus: {step_label}"
                        )
                        self.listener.on_step_status(step_label, "RUNNING", "")
                        self._log(f"[{current_step_counter}/{total_steps}] Starte Routine '{rid}'...")

                        if isolated_session:
                            self._log(f"[{rid}] Starte isolierte Browser-Session...")
                            current_browser, current_context, current_page = create_session()

                        step = self._run_one_routine(
                            rid=rid,
                            step_label=step_label,
                            page=current_page,
                            context=current_context,
                            iter_vars=iter_vars,
                            diagnostics=diagnostics,
                            console_policy=console_policy,
                            network_policy=network_policy,
                            check_timeout_ms=check_timeout_ms,
                            dataset_row=row_idx,
                            trace_mode=trace_mode,
                        )
                        result.steps.append(step)
                        self.listener.on_step_result(step.to_dict())

                        if isolated_session and cfg.auto_close:
                            try:
                                if current_page and not current_page.is_closed():
                                    current_page.close()
                                if current_context:
                                    current_context.close()
                                if current_browser:
                                    current_browser.close()
                            except Exception:
                                pass

                        self.listener.on_progress(current_step_counter, total_steps)

                        if not step.passed and cfg.stop_on_first_failure:
                            self._log(
                                "[ABBRUCH] Erster Fehler aufgetreten, weitere Routinen "
                                "werden übersprungen."
                            )
                            aborted_early = True
                            break

            except Exception as e:
                result.system_error = str(e)
                self._log(f"[SYSTEM FEHLER] Unerwarteter Playwright Fehler:\n{traceback.format_exc()}")
            finally:
                # Tracing beenden, bevor die Contexts zugehen
                self._stop_tracing()

                if cfg.auto_close:
                    self._log("[INFO] Schließe alle Browserfenster...")
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

                    # Videos sind erst nach dem Schließen des Contexts fertig
                    if video_mode != "off":
                        result.videos = self._collect_videos()
                else:
                    self._log("[INFO] Browser bleibt nach Ausführung geöffnet.")
                    if video_mode != "off":
                        self._log(
                            "[WARN] Video wird erst beim Schließen des Browsers "
                            "geschrieben — mit offenem Browser gibt es keine Aufnahme."
                        )

        # Übersprungene Schritte kennzeichnen, damit die Zahlen aufgehen
        if aborted_early or self._cancelled:
            self._mark_skipped(result, sequence, dataset_rows, total_iterations)

        result.cancelled = self._cancelled
        result.duration = time.time() - start_time

        # Videos nur behalten, wenn sie gebraucht werden
        if video_mode == "on_failure" and result.videos and result.failed_count == 0:
            self._discard_videos(result)

        self._log(f"=== {result.summary} ===")
        result.logs = list(self._logs)

        result.report_path = self._write_report(result)
        if result.report_path:
            self._log(f"[REPORT] HTML-Testbericht erstellt: {result.report_path}")

        self._write_side_artifacts(result)
        result.logs = list(self._logs)

        if self.artifacts:
            self.artifacts.discard_empty_subdirs()
            self._prune_old_runs()

        self.listener.on_finished(result)
        return result

    # ------------------------------------------------------- Trace und Video

    def _start_tracing(self, context: Any):
        """Tracing für einen Context starten; pro Schritt kommen dann Chunks."""
        try:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            self._traced_contexts.append(context)
        except Exception as e:
            self._log(f"[WARN] Tracing konnte nicht gestartet werden: {e}")

    def _stop_tracing(self):
        for context in self._traced_contexts:
            try:
                context.tracing.stop()
            except Exception:
                pass
        self._traced_contexts = []

    def _collect_videos(self) -> List[str]:
        paths = []
        for page in self._video_pages:
            try:
                video = page.video
                if video is None:
                    continue
                path = video.path()
                if path and os.path.exists(path):
                    paths.append(str(path))
            except Exception as e:
                self._log(f"[WARN] Video konnte nicht ermittelt werden: {e}")
        if paths:
            self._log(f"[VIDEO] {len(paths)} Aufnahme(n) gespeichert.")
        return paths

    def _discard_videos(self, result: RunResult):
        """Bei video_mode 'on_failure' und fehlerfreiem Lauf die Aufnahmen löschen."""
        for path in result.videos:
            try:
                os.remove(path)
            except OSError:
                pass
        self._log("[VIDEO] Lauf ohne Fehler — Aufnahmen verworfen (Modus 'nur bei Fehler').")
        result.videos = []

    def _write_side_artifacts(self, result: RunResult):
        """run.json und junit.xml neben den Report legen."""
        if not self.artifacts:
            return
        try:
            self.artifacts.write_json(result.to_dict())
        except Exception as e:
            self._log(f"[WARN] run.json konnte nicht geschrieben werden: {e}")
        try:
            junit_report.write(result, self.artifacts.junit_path)
        except Exception as e:
            self._log(f"[WARN] junit.xml konnte nicht geschrieben werden: {e}")

    def _prune_old_runs(self):
        keep = int(self.settings.get("keep_runs", 20) or 0)
        if keep <= 0:
            return
        try:
            removed = prune_runs(self.pm.runs_dir, keep)
        except Exception as e:
            self._log(f"[WARN] Alte Läufe konnten nicht aufgeräumt werden: {e}")
            return
        if removed:
            self._log(f"[INFO] {len(removed)} alte(r) Lauf/Läufe entfernt (behalte {keep}).")

    def _mark_skipped(self, result, sequence, dataset_rows, total_iterations):
        """Nicht gelaufene Schritte als SKIPPED aufnehmen (nur zur Übersicht)."""
        done = {s.name for s in result.steps}
        for row_idx in range(1, total_iterations + 1):
            for item in sequence:
                rid = item["id"]
                label = f"{rid} (Zeile {row_idx})" if total_iterations > 1 else rid
                if label not in done:
                    result.steps.append(StepResult(
                        name=label, routine_id=rid, status="SKIPPED",
                        error="Nicht ausgeführt (Lauf vorher beendet)",
                        dataset_row=row_idx,
                    ))

    def _write_report(self, result: RunResult) -> str:
        cfg = self.config

        # Trace-, Screenshot- und Videopfade relativ zum Laufverzeichnis, damit
        # die Links im Report auch nach dem Verschieben/Zippen funktionieren.
        steps = result.step_dicts()
        videos = list(result.videos)
        if self.artifacts:
            for step in steps:
                for key in ("screenshot", "trace"):
                    if step.get(key):
                        step[key] = self.artifacts.relative(step[key])
            videos = [self.artifacts.relative(v) for v in videos]

        try:
            return ReportGenerator.generate(
                target_name=cfg.item_id,
                mode=cfg.mode,
                browser_engine=cfg.browser_engine,
                device_profile=cfg.device_profile,
                speed_mode=cfg.speed_mode,
                dataset_id=cfg.dataset_id,
                total_duration=result.duration,
                passed_count=result.passed_count,
                failed_count=result.failed_count,
                step_results=steps,
                logs=result.logs,
                reports_dir=self.pm.reports_dir,
                checks_passed=result.checks_passed,
                checks_failed=result.checks_failed,
                warnings_count=result.warnings_count,
                output_path=self.artifacts.report_path if self.artifacts else None,
                videos=videos,
                screenshot_base=self.artifacts.dir if self.artifacts else None,
            )
        except Exception as e:
            self._log(f"[WARN] Report konnte nicht erstellt werden: {e}")
            return ""

    # ------------------------------------------------------- ein Schritt

    def _run_one_routine(
        self,
        rid: str,
        step_label: str,
        page: Optional[Page],
        iter_vars: Dict[str, str],
        diagnostics: PageDiagnostics,
        console_policy: str,
        network_policy: str,
        check_timeout_ms: int,
        dataset_row: int,
        context: Optional[BrowserContext] = None,
        trace_mode: str = "off",
    ) -> StepResult:
        """Führt eine Routine aus, wertet Erwartungen und Diagnose aus."""
        code_content = self.pm.get_routine_code(rid)
        if not code_content:
            err_msg = f"Routine-Datei für '{rid}' existiert nicht!"
            self._log(f"[FEHLER] {err_msg}")
            self.listener.on_step_status(step_label, "FAIL", err_msg)
            return StepResult(name=step_label, routine_id=rid, status="FAIL",
                              error=err_msg, dataset_row=dataset_row)

        # Diagnose-Puffer leeren, damit Befunde diesem Schritt gehören
        diagnostics.reset()

        # Trace-Chunk für genau diesen Schritt öffnen
        tracing_chunk = self._start_trace_chunk(context, step_label, trace_mode)

        recorder = CheckRecorder(log=self._log)
        step_start = time.time()
        success, error_msg = self.execute_snippet(
            code_content, page, iter_vars, routine_id=rid, log=self._log, recorder=recorder
        )

        # Deklarative Erwartungen aus <routine>.checks.json
        declared = self.pm.get_routine_checks(rid)
        if declared and page and not page.is_closed():
            self._log(f"[CHECKS] Prüfe {len(declared)} Erwartung(en) für '{rid}'...")
            recorder.results.extend(evaluate_checks(
                declared, page,
                diagnostics_entries=list(diagnostics.entries),
                timeout_ms=check_timeout_ms,
                log=self._log,
            ))
        elif declared:
            self._log(
                f"[WARN] {len(declared)} Erwartung(en) für '{rid}' übersprungen "
                "(keine offene Seite)."
            )

        duration = time.time() - step_start

        # Diagnose-Befunde nach Policy bewerten
        diag_entries = diagnostics.take()
        diag_errors, diag_warnings = PageDiagnostics.split(diag_entries)
        console_errors = [e for e in diag_errors if e.kind in ("console", "pageerror")]
        network_errors = [e for e in diag_errors if e.kind == "network"]

        policy_failures: List[str] = []
        warn_entries: List[Any] = list(diag_warnings)

        for group, policy, label in (
            (console_errors, console_policy, "JS-Konsolenfehler"),
            (network_errors, network_policy, "HTTP-Fehler"),
        ):
            if not group:
                continue
            detail = "; ".join(e.short() for e in group[:3])
            if len(group) > 3:
                detail += f" ... (+{len(group) - 3} weitere)"
            if policy == "fail":
                policy_failures.append(f"{len(group)}x {label}: {detail}")
            elif policy == "warn":
                warn_entries.extend(group)
                self._log(f"  [WARN] {len(group)}x {label}: {detail}")
            else:
                for e in group:
                    self._log(f"  [{e.kind.upper()}] {e.short()}")

        check_failures = recorder.failure_summary()
        step_ok = success and not check_failures and not policy_failures

        combined_error = "\n\n".join([p for p in (
            error_msg if not success else "",
            check_failures,
            "\n".join(policy_failures),
        ) if p])

        shot_path = ""
        if step_ok:
            check_note = f" | {recorder.passed_count} Erwartung(en) erfüllt" if recorder.results else ""
            warn_note = f" | ⚠ {len(warn_entries)}" if warn_entries else ""
            self._log(f"[PASS] Routine '{rid}' erfolgreich ({duration:.2f}s){check_note}{warn_note}.")
            self.listener.on_step_status(step_label, "PASS", "")
        else:
            self._log(f"[FAIL] Routine '{rid}' fehlgeschlagen ({duration:.2f}s): {combined_error}")
            self.listener.on_step_status(step_label, "FAIL", combined_error)
            shot_path = self._capture_screenshot(page, step_label)

        # Trace-Chunk schließen: behalten oder verwerfen
        trace_path = self._finish_trace_chunk(tracing_chunk, step_label, step_ok, trace_mode)

        return StepResult(
            name=step_label,
            routine_id=rid,
            status="PASS" if step_ok else "FAIL",
            duration=duration,
            error=combined_error,
            screenshot=shot_path,
            trace=trace_path,
            url=self._safe_url(page),
            dataset_row=dataset_row,
            checks=[r.to_dict() for r in recorder.results],
            warnings=[e.to_dict() for e in warn_entries],
        )

    # --------------------------------------------------------- Trace-Chunks

    def _start_trace_chunk(self, context: Optional[BrowserContext],
                           step_label: str, trace_mode: str):
        """
        Öffnet einen Trace-Abschnitt für einen Schritt. Auch bei 'on_failure'
        wird aufgezeichnet — beim Schließen entscheidet sich, ob der Abschnitt
        gespeichert oder verworfen wird.
        """
        if trace_mode == "off" or context is None or context not in self._traced_contexts:
            return None
        try:
            context.tracing.start_chunk(title=step_label)
            return context
        except Exception as e:
            self._log(f"[WARN] Trace-Abschnitt konnte nicht gestartet werden: {e}")
            return None

    def _finish_trace_chunk(self, context, step_label: str,
                            step_ok: bool, trace_mode: str) -> str:
        if context is None:
            return ""

        keep = trace_mode == "always" or (trace_mode == "on_failure" and not step_ok)
        if not keep:
            try:
                context.tracing.stop_chunk()  # ohne Pfad = verwerfen
            except Exception:
                pass
            return ""

        try:
            path = self.artifacts.unique_path("trace", step_label, ".zip")
            context.tracing.stop_chunk(path=path)
            if os.path.exists(path):
                self._log(
                    f"[TRACE] Aufzeichnung gespeichert: {path}\n"
                    f"         Ansehen mit: npx playwright show-trace \"{path}\""
                )
                return path
            return ""
        except Exception as e:
            self._log(f"[WARN] Trace konnte nicht gespeichert werden: {e}")
            return ""

    def _capture_screenshot(self, page: Optional[Page], step_label: str) -> str:
        if not page or page.is_closed():
            return ""
        try:
            if self.artifacts:
                shot_path = self.artifacts.unique_path("shots", step_label, ".png")
            else:  # Fallback, falls kein Laufverzeichnis existiert
                shot_dir = os.path.join(tempfile.gettempdir(), "py_auto_tester_screenshots")
                os.makedirs(shot_dir, exist_ok=True)
                shot_path = os.path.join(shot_dir, f"error_{int(time.time())}.png")
            page.screenshot(path=shot_path, full_page=True)
            self.listener.on_screenshot(shot_path)
            self._log(f"[SCREENSHOT] Gespeichert unter: {shot_path}")
            return shot_path
        except Exception as se:
            self._log(f"[WARN] Screenshot konnte nicht erstellt werden: {se}")
            return ""

    # ------------------------------------------------- Routine-Code ausführen

    @staticmethod
    def _has_effective_top_level_code(code: str) -> bool:
        """
        True if the routine performs actual work at module level (legacy style,
        i.e. Playwright calls without an execute() wrapper).
        Imports, defs, classes, docstrings and 'pass' do not count as work.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef, ast.Pass)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                continue
            return True
        return False

    @staticmethod
    def _format_syntax_error(exc: SyntaxError, filename: str) -> str:
        loc = f"{filename}, Zeile {exc.lineno}"
        if exc.offset:
            loc += f", Spalte {exc.offset}"
        parts = [f"SyntaxError: {exc.msg}", f"  [{loc}]"]
        if exc.text:
            parts.append(f"    -> {exc.text.rstrip()}")
        return "\n".join(parts)

    @staticmethod
    def _format_exception(filename: str) -> str:
        """
        Formats the active exception, pointing at the failing line *inside the
        routine* instead of at the engine internals.
        """
        exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_type is None:
            return "Unbekannter Fehler"

        head = f"{exc_type.__name__}: {exc_value}".strip()

        routine_frames = [fr for fr in traceback.extract_tb(exc_tb) if fr.filename == filename]
        if not routine_frames:
            return head

        last = routine_frames[-1]
        loc = f"{filename}, Zeile {last.lineno}"
        if last.name and last.name != "<module>":
            loc += f" in {last.name}()"

        parts = [head, f"  [{loc}]"]
        if last.line:
            parts.append(f"    -> {last.line.strip()}")
        if len(routine_frames) > 1:
            chain = " -> ".join(
                f"Zeile {fr.lineno}" + (f" ({fr.name})" if fr.name != "<module>" else "")
                for fr in routine_frames
            )
            parts.append(f"  Aufrufkette: {chain}")
        return "\n".join(parts)

    def execute_snippet(
        self,
        code: str,
        page: Optional[Page],
        vars_dict: Dict[str, str],
        routine_id: str = "routine",
        log: Optional[Callable[[str], None]] = None,
        recorder: Optional[CheckRecorder] = None,
    ) -> tuple[bool, str]:
        """
        Executes a routine snippet, passing 'page' and 'vars' into its namespace.

        A single namespace dict is used for globals AND locals, so helper
        functions defined by the routine can call each other. The code is
        compiled under the routine's filename and registered in linecache, so
        tracebacks report real routine line numbers and source lines.
        """
        def _log(msg: str):
            if log:
                log(msg)

        filename = f"{routine_id}.py"
        linecache.cache[filename] = (len(code), None, code.splitlines(True), filename)

        if recorder is None:
            recorder = CheckRecorder(log=log)

        namespace: Dict[str, Any] = {
            "__name__": "__routine__",
            "__file__": filename,
            "page": page,
            "vars": vars_dict,
            "expect": expect,
            "log": _log,
            "re": __import__("re"),
        }
        namespace.update(build_check_api(recorder, log=log))

        try:
            compiled = compile(code, filename, "exec")
        except SyntaxError as e:
            return False, self._format_syntax_error(e, filename)

        had_top_level_code = self._has_effective_top_level_code(code)

        # --- Phase 1: Modulebene ausführen (definiert execute(), Legacy-Code läuft)
        try:
            exec(compiled, namespace)
        except Exception:
            return False, self._format_exception(filename)

        # --- Phase 2: execute(page, vars) aufrufen
        execute_fn = namespace.get("execute")

        if execute_fn is None:
            if had_top_level_code:
                _log(
                    f"[WARN] Routine '{routine_id}' hat keine Funktion 'execute(page, vars)' "
                    "und wurde im Legacy-Modus auf Modulebene ausgeführt. "
                    "Bitte in 'def execute(page, vars):' umbauen."
                )
                return True, ""
            return False, (
                f"Keine Funktion 'execute(page, vars)' in {filename} gefunden und kein "
                "ausführbarer Code auf Modulebene. Die Routine hat nichts getan.\n"
                "  Erwartet wird:\n"
                "    def execute(page, vars):\n"
                "        page.goto(vars.get('BASE_URL'))"
            )

        if not callable(execute_fn):
            return False, (
                f"'execute' in {filename} ist keine Funktion, sondern "
                f"{type(execute_fn).__name__}."
            )

        try:
            execute_fn(page, vars_dict)
        except Exception:
            return False, self._format_exception(filename)

        return True, ""
