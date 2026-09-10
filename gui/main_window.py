import os
import re
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget,
    QSplitter, QInputDialog, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QPushButton, QDialogButtonBox, QLabel, QTextEdit,
    QComboBox, QCheckBox, QSpinBox, QPlainTextEdit
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon, QDesktopServices

from core.project_manager import ProjectManager
from core.codegen_recorder import CodegenRecorder

from gui.tree_manager import TreeManagerWidget
from gui.routine_editor import RoutineEditorWidget
from gui.runner_widget import RunnerWidget
from gui.dataset_editor import DatasetEditorWidget
from gui.styles import DARK_THEME_QSS

class VariablesDialog(QDialog):
    """Dialog to edit project key-value variables."""
    def __init__(self, parent, project_manager: ProjectManager):
        super().__init__(parent)
        self.pm = project_manager
        self.setWindowTitle("⚙️ Projekt-Variablen verwalten")
        self.resize(450, 350)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel("Hier definierte Variablen können in Routinen über 'vars.get(\"KEY\")' verwendet werden:")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.text_edit = QTextEdit()
        vars_dict = self.pm.get_variables()
        lines = [f"{k}={v}" for k, v in vars_dict.items()]
        self.text_edit.setPlainText("\n".join(lines))
        self.text_edit.setPlaceholderText("BASE_URL=https://example.com\nUSERNAME=admin")
        layout.addWidget(self.text_edit)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self.save_vars)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def save_vars(self):
        content = self.text_edit.toPlainText()
        new_vars = {}
        for line in content.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                new_vars[k.strip()] = v.strip()
        self.pm.save_variables(new_vars)
        self.accept()


class DiagnosticsSettingsDialog(QDialog):
    """
    Einstellungen dafür, wie mit JS-Konsolenfehlern und HTTP-Fehlern
    umgegangen wird, die während eines Laufs auftreten.
    """
    POLICIES = [
        ("Warnen (Status bleibt PASS)", "warn"),
        ("Als Fehler behandeln (Schritt wird rot)", "fail"),
        ("Nur ins Protokoll schreiben", "log"),
    ]

    def __init__(self, parent, project_manager: ProjectManager):
        super().__init__(parent)
        self.pm = project_manager
        self.setWindowTitle("🩺 Diagnose & Artefakte")
        self.resize(640, 720)
        self.setup_ui()

    ARTIFACT_MODES = [
        ("Nur bei Fehlern", "on_failure"),
        ("Immer", "always"),
        ("Aus", "off"),
    ]

    def _policy_combo(self, current: str) -> QComboBox:
        combo = QComboBox()
        for label, value in self.POLICIES:
            combo.addItem(label, value)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def _artifact_combo(self, current: str) -> QComboBox:
        combo = QComboBox()
        for label, value in self.ARTIFACT_MODES:
            combo.addItem(label, value)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def setup_ui(self):
        settings = self.pm.get_settings()
        layout = QVBoxLayout(self)

        info = QLabel(
            "Während jedes Schritts werden JS-Konsolenfehler und fehlerhafte "
            "HTTP-Antworten mitgeschnitten. Hier legst du fest, wie stark sie gewertet werden."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self.console_combo = self._policy_combo(settings.get("console_policy", "warn"))
        self.console_combo.setToolTip("Gilt für console.error und unbehandelte JS-Fehler")
        form.addRow("JS-Konsolenfehler:", self.console_combo)

        self.network_combo = self._policy_combo(settings.get("network_policy", "warn"))
        self.network_combo.setToolTip("Gilt für HTTP-Antworten mit Status 400 und höher")
        form.addRow("HTTP-Fehler (4xx/5xx):", self.network_combo)

        self.warnings_cb = QCheckBox("Auch console.warn erfassen")
        self.warnings_cb.setChecked(bool(settings.get("capture_console_warnings", False)))
        self.warnings_cb.setToolTip(
            "Warnungen sind bei vielen Web-Apps sehr häufig — erzeugt viel Rauschen"
        )
        form.addRow("", self.warnings_cb)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(500, 60000)
        self.timeout_spin.setSingleStep(500)
        self.timeout_spin.setSuffix(" ms")
        self.timeout_spin.setValue(int(settings.get("check_timeout_ms", 5000)))
        self.timeout_spin.setToolTip(
            "Wie lange eine einzelne GUI-Erwartung auf ihr Element wartet"
        )
        form.addRow("Timeout je Erwartung:", self.timeout_spin)

        layout.addLayout(form)

        # --- Artefakte pro Lauf
        layout.addWidget(QLabel("<b>Artefakte pro Lauf</b>"))
        art_form = QFormLayout()

        self.trace_combo = self._artifact_combo(settings.get("trace_mode", "on_failure"))
        self.trace_combo.setToolTip(
            "Playwright-Trace mit DOM-Snapshots, Netzwerk und Zeitleiste.\n"
            "Ansehen mit: npx playwright show-trace <datei>"
        )
        art_form.addRow("Trace aufzeichnen:", self.trace_combo)

        self.video_combo = self._artifact_combo(settings.get("video_mode", "off"))
        self.video_combo.setToolTip(
            "Eine Aufnahme pro Browser-Session (nicht pro Schritt).\n"
            "Kostet Laufzeit und Plattenplatz."
        )
        art_form.addRow("Video aufzeichnen:", self.video_combo)

        self.keep_runs_spin = QSpinBox()
        self.keep_runs_spin.setRange(0, 999)
        self.keep_runs_spin.setSpecialValueText("alle behalten")
        self.keep_runs_spin.setValue(int(settings.get("keep_runs", 20)))
        self.keep_runs_spin.setToolTip(
            "Ältere Laufverzeichnisse werden nach jedem Lauf gelöscht.\n"
            "0 = nie aufräumen (Traces und Videos summieren sich)."
        )
        art_form.addRow("Läufe aufbewahren:", self.keep_runs_spin)

        layout.addLayout(art_form)

        art_hint = QLabel(
            "Jeder Lauf bekommt ein eigenes Verzeichnis unter <code>project_data/runs/</code> "
            "mit Report, run.json, junit.xml und den Artefakten. Der Ordner ist komplett "
            "verschickbar — die Links im Report sind relativ."
        )
        art_hint.setWordWrap(True)
        art_hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(art_hint)

        layout.addWidget(QLabel(
            "<b>Konsolenmeldungen ignorieren</b> (ein regulärer Ausdruck pro Zeile):"
        ))
        self.ignore_console_edit = QPlainTextEdit("\n".join(settings.get("ignore_console", [])))
        self.ignore_console_edit.setPlaceholderText(
            "ResizeObserver loop\nDeprecationWarning\nfavicon"
        )
        self.ignore_console_edit.setMaximumHeight(110)
        layout.addWidget(self.ignore_console_edit)

        layout.addWidget(QLabel(
            "<b>URLs ignorieren</b> (ein regulärer Ausdruck pro Zeile):"
        ))
        self.ignore_urls_edit = QPlainTextEdit("\n".join(settings.get("ignore_urls", [])))
        self.ignore_urls_edit.setPlaceholderText(
            r"google-analytics\.com" "\n" r"\.woff2$" "\n" r"/telemetry/"
        )
        self.ignore_urls_edit.setMaximumHeight(110)
        layout.addWidget(self.ignore_urls_edit)

        hint = QLabel(
            "Tipp: Fange mit „Warnen“ an und schaue einen Lauf lang, wie viel dein System "
            "an Rauschen produziert. Was dauerhaft unwichtig ist, kommt in die Ignore-Listen — "
            "erst danach lohnt „Als Fehler behandeln“."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(hint)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self.save_settings)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def save_settings(self):
        def lines(widget):
            return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

        invalid = []
        for pattern in lines(self.ignore_console_edit) + lines(self.ignore_urls_edit):
            try:
                re.compile(pattern)
            except re.error as e:
                invalid.append(f"{pattern}  ({e})")

        if invalid:
            detail = "\n".join(f"• {p}" for p in invalid[:6])
            reply = QMessageBox.question(
                self, "Ungültige Ausdrücke",
                f"Diese Muster sind keine gültigen regulären Ausdrücke und würden "
                f"ignoriert:\n\n{detail}\n\nTrotzdem speichern?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.pm.save_settings({
            "console_policy": self.console_combo.currentData(),
            "network_policy": self.network_combo.currentData(),
            "capture_console_warnings": self.warnings_cb.isChecked(),
            "check_timeout_ms": self.timeout_spin.value(),
            "ignore_console": lines(self.ignore_console_edit),
            "ignore_urls": lines(self.ignore_urls_edit),
            "trace_mode": self.trace_combo.currentData(),
            "video_mode": self.video_combo.currentData(),
            "keep_runs": self.keep_runs_spin.value(),
        })
        self.accept()


class MainWindow(QMainWindow):
    """Main Application Window for Py-Auto-Tester."""
    def __init__(self, root_dir: str = "project_data"):
        super().__init__()
        self.pm = ProjectManager(root_dir)
        self.setWindowTitle("⚡ Playwright Auto-Tester Studio")
        self.resize(1280, 800)

        # Apply Global QSS Theme
        self.setStyleSheet(DARK_THEME_QSS)

        self.setup_ui()

    def setup_ui(self):
        # Central Widget & Splitter Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # Sidebar (Tree Manager)
        self.tree_manager = TreeManagerWidget(self.pm)
        self.tree_manager.item_selected_signal.connect(self.on_tree_item_selected)
        self.tree_manager.run_requested_signal.connect(self.on_run_requested)
        self.tree_manager.record_requested_signal.connect(self.start_recording_flow)
        
        self.tree_manager.setMinimumWidth(280)
        splitter.addWidget(self.tree_manager)

        # Right Content Area (Tabbed Interface)
        self.tabs = QTabWidget()

        # Tab 1: Routine Code Editor
        self.editor_widget = RoutineEditorWidget(self.pm)
        self.editor_widget.routine_saved_signal.connect(lambda: self.tree_manager.refresh_tree())
        self.tabs.addTab(self.editor_widget, "📝 Routine Editor")

        # Tab 2: Live Test Runner
        self.runner_widget = RunnerWidget(self.pm)
        self.tabs.addTab(self.runner_widget, "▶ Test Runner")

        # Tab 3: Dataset Editor
        self.dataset_widget = DatasetEditorWidget(self.pm)
        self.dataset_widget.datasets_updated_signal.connect(self.runner_widget.refresh_datasets)
        self.tabs.addTab(self.dataset_widget, "📊 Datensätze")

        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter)

        # Create Menu Bar
        self.create_menu_bar()

    def create_menu_bar(self):
        mb = self.menuBar()

        # Menu: Datei
        file_menu = mb.addMenu("Datei")

        rec_act = file_menu.addAction("🔴 Neue Routine Aufnehmen")
        rec_act.triggered.connect(self.start_recording_flow)

        vars_act = file_menu.addAction("⚙️ Variablen Verwalten")
        vars_act.triggered.connect(self.open_variables_dialog)

        diag_act = file_menu.addAction("🩺 Diagnose & Artefakte")
        diag_act.triggered.connect(self.open_diagnostics_dialog)

        rep_act = file_menu.addAction("📂 Läufe-Ordner öffnen")
        rep_act.setToolTip("Öffnet project_data/runs mit Reports, Traces und Videos")
        rep_act.triggered.connect(self.open_reports_folder)

        file_menu.addSeparator()
        exit_act = file_menu.addAction("Beenden")
        exit_act.triggered.connect(self.close)

        # Menu: Ansicht
        view_menu = mb.addMenu("Ansicht")
        v_refresh = view_menu.addAction("🔄 Explorer Aktualisieren")
        v_refresh.triggered.connect(lambda: self.tree_manager.refresh_tree())

        # Menu: Hilfe
        help_menu = mb.addMenu("Hilfe")
        h_info = help_menu.addAction("Über Py-Auto-Tester")
        h_info.triggered.connect(self.show_about_dialog)

    def start_recording_flow(self):
        """Flow to start Playwright Codegen recording for a routine."""
        # 1. Ask URL
        default_url = self.pm.get_variables().get("BASE_URL", "https://google.com")
        url, ok = QInputDialog.getText(
            self, "🔴 Routine Aufnehmen (Playwright Codegen)",
            "Start-URL für die Aufnahme eingeben:",
            QLineEdit.Normal, default_url
        )
        if not ok or not url.strip():
            return

        # 2. Ask Routine Name
        routine_name, ok_name = QInputDialog.getText(
            self, "Routine benennen",
            "Name für die neue Routine (z.B. Login, Patient Suchen):"
        )
        if not ok_name or not routine_name.strip():
            return

        routine_id = routine_name.lower().replace(" ", "_")

        QMessageBox.information(
            self, "Codegen starten",
            "Das Playwright Codegen Fenster öffnet sich gleich.\n\n"
            "1. Führe deine Interaktionen im Browser aus.\n"
            "2. Schließe das Browserfenster, sobald du fertig bist.\n"
            "3. Der Code wird automatisch bereinigt & als Routine gespeichert."
        )

        # 3. Launch Codegen using selected browser and device profile
        browser = self.runner_widget.browser_combo.currentData() or "chromium"
        device = self.runner_widget.device_combo.currentData() or "desktop_1080p"

        snippet, err_msg = CodegenRecorder.launch_codegen(url.strip(), browser=browser, device=device)
        if err_msg:
            QMessageBox.warning(self, "Aufnahme Fehler/Abbruch", err_msg)
            return

        if snippet:
            self.pm.save_routine(routine_id, routine_name, f"Aufgenommen von {url}", snippet)
            self.tree_manager.refresh_tree()
            self.tabs.setCurrentIndex(0)
            self.editor_widget.load_routine(routine_id)
            QMessageBox.information(self, "Erfolg", f"Routine '{routine_name}' erfolgreich aufgenommen und gespeichert!")

    def on_tree_item_selected(self, item_type: str, item_id: str):
        if item_type == "routine":
            self.tabs.setCurrentIndex(0) # Editor tab
            self.editor_widget.load_routine(item_id)
            self.runner_widget.set_target("routine", item_id)
        elif item_type in ["group", "test"]:
            self.tabs.setCurrentIndex(1) # Runner tab
            self.runner_widget.set_target(item_type, item_id)

    def on_run_requested(self, item_type: str, item_id: str):
        self.tabs.setCurrentIndex(1) # Runner tab
        self.runner_widget.set_target(item_type, item_id)
        self.runner_widget.start_execution()

    def open_variables_dialog(self):
        dlg = VariablesDialog(self, self.pm)
        dlg.exec_()

    def open_diagnostics_dialog(self):
        dlg = DiagnosticsSettingsDialog(self, self.pm)
        dlg.exec_()

    def open_reports_folder(self):
        target = self.pm.runs_dir if os.path.exists(self.pm.runs_dir) else self.pm.reports_dir
        if not os.path.exists(target):
            QMessageBox.information(self, "Hinweis", "Es gibt noch keine Läufe.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def show_about_dialog(self):
        QMessageBox.about(
            self, "Über Playwright Auto-Tester Studio",
            "<h3>⚡ Playwright Auto-Tester Studio</h3>"
            "<p>Eine praktische grafische Oberfläche zur Aufnahme, Strukturierung "
            "und Ausführung von modularen Playwright-Testsuiten.</p>"
            "<p><b>Features:</b> Routinen, Gruppen, End-to-End Tests, Shared Context & Live Runner.</p>"
        )
