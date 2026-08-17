import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget,
    QSplitter, QInputDialog, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QPushButton, QDialogButtonBox, QLabel, QTextEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

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

    def show_about_dialog(self):
        QMessageBox.about(
            self, "Über Playwright Auto-Tester Studio",
            "<h3>⚡ Playwright Auto-Tester Studio</h3>"
            "<p>Eine praktische grafische Oberfläche zur Aufnahme, Strukturierung "
            "und Ausführung von modularen Playwright-Testsuiten.</p>"
            "<p><b>Features:</b> Routinen, Gruppen, End-to-End Tests, Shared Context & Live Runner.</p>"
        )
