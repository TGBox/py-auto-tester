import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QProgressBar, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QMessageBox
)
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtCore import Qt, Signal

from core.project_manager import ProjectManager
from core.execution_engine import ExecutionEngineWorker

class RunnerWidget(QWidget):
    """
    Live Test Runner View widget displaying execution logs, progress, and screenshots.
    """
    execution_finished_signal = Signal()

    def __init__(self, project_manager: ProjectManager):
        super().__init__()
        self.pm = project_manager
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Control Panel Header
        ctrl_card = QFrame()
        ctrl_card.setObjectName("cardPanel")
        c_layout = QHBoxLayout(ctrl_card)

        self.target_label = QLabel("🎯 Ziel: Kein Element ausgewählt")
        self.target_label.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 13px;")
        c_layout.addWidget(self.target_label)

        c_layout.addStretch()

        # Browser Selection Dropdown
        browser_label = QLabel("🌐 Browser:")
        browser_label.setStyleSheet("font-weight: bold;")
        c_layout.addWidget(browser_label)

        self.browser_combo = QComboBox()
        self.browser_combo.addItem("🌐 Chromium (Chrome/Edge)", "chromium")
        self.browser_combo.addItem("🦊 Firefox", "firefox")
        self.browser_combo.addItem("🧩 WebKit (Safari)", "webkit")
        self.browser_combo.setCurrentIndex(0)
        self.browser_combo.setToolTip("Wähle die Browser-Engine")
        c_layout.addWidget(self.browser_combo)

        # Device / Emulation Dropdown
        device_label = QLabel("📱 Gerät:")
        device_label.setStyleSheet("font-weight: bold;")
        c_layout.addWidget(device_label)

        self.device_combo = QComboBox()
        self.device_combo.addItem("🖥️ Desktop 1080p (1920x1080)", "desktop_1080p")
        self.device_combo.addItem("🖥️ Desktop 768p (1366x768)", "desktop_768p")
        self.device_combo.addItem("📱 iPhone 14 (Mobile Touch)", "iphone_14")
        self.device_combo.addItem("📱 Pixel 7 (Mobile Touch)", "pixel_7")
        self.device_combo.addItem("📱 iPad Air (Tablet)", "ipad_air")
        self.device_combo.setCurrentIndex(0)
        self.device_combo.setToolTip("Wähle das Geräte- und Viewport-Profil für die Emulation")
        c_layout.addWidget(self.device_combo)

        # Speed Dropdown
        speed_label = QLabel("⏱️ Tempo:")
        speed_label.setStyleSheet("font-weight: bold;")
        c_layout.addWidget(speed_label)

        self.speed_combo = QComboBox()
        self.speed_combo.addItem("⚡ So schnell wie möglich", "fastest")
        self.speed_combo.addItem("🚗 Normal (300ms)", "normal")
        self.speed_combo.addItem("🐢 Langsam (1000ms)", "slow")
        self.speed_combo.addItem("🐾 Schritt für Schritt (2500ms)", "step")
        self.speed_combo.setCurrentIndex(1) # Default to Normal
        self.speed_combo.setToolTip("Bestimmt die Verzögerung zwischen einzelnen Playwright-Aktionen (slow_mo)")
        c_layout.addWidget(self.speed_combo)

        self.headed_cb = QCheckBox("Browser sichtbar (Headed)")
        self.headed_cb.setChecked(True)
        c_layout.addWidget(self.headed_cb)

        self.auto_close_cb = QCheckBox("Browser am Ende schließen")
        self.auto_close_cb.setChecked(True)
        self.auto_close_cb.setToolTip("Schließt das Browserfenster automatisch nach Abschluss des Tests")
        c_layout.addWidget(self.auto_close_cb)

        self.run_btn = QPushButton("▶ Ausführen")
        self.run_btn.setObjectName("runButton")
        self.run_btn.clicked.connect(self.start_execution)
        c_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("⏹ Stopp")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_execution)
        c_layout.addWidget(self.stop_btn)

        layout.addWidget(ctrl_card)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Splitter: Table (Top/Left) & Console/Screenshot (Bottom/Right)
        splitter = QSplitter(Qt.Vertical)

        # Step Status Table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Routine / Schritt", "Status", "Fehlerdetails"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        splitter.addWidget(self.table)

        # Console & Screenshot area
        bottom_widget = QWidget()
        b_layout = QHBoxLayout(bottom_widget)
        b_layout.setContentsMargins(0, 0, 0, 0)

        # Console Output
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setPlaceholderText("Live-Konsolenausgabe...")
        b_layout.addWidget(self.log_console, stretch=3)

        # Screenshot Preview Box
        shot_frame = QFrame()
        shot_frame.setObjectName("cardPanel")
        shot_layout = QVBoxLayout(shot_frame)

        shot_title = QLabel("🖼 Screenshot bei Fehler")
        shot_title.setStyleSheet("font-weight: bold; color: #F8FAFC;")
        shot_layout.addWidget(shot_title)

        self.shot_label = QLabel("Kein Fehler")
        self.shot_label.setAlignment(Qt.AlignCenter)
        self.shot_label.setMinimumSize(220, 140)
        self.shot_label.setStyleSheet("border: 1px dashed #475569; border-radius: 6px; background-color: #0F172A;")
        shot_layout.addWidget(self.shot_label)

        b_layout.addWidget(shot_frame, stretch=1)

        splitter.addWidget(bottom_widget)
        layout.addWidget(splitter)

        self.current_mode = None
        self.current_item_id = None

    def set_target(self, mode: str, item_id: str):
        self.current_mode = mode
        self.current_item_id = item_id
        self.target_label.setText(f"🎯 Ausführungsziel: {mode.upper()} -> '{item_id}'")

    def start_execution(self):
        if not self.current_mode or not self.current_item_id:
            QMessageBox.warning(self, "Warnung", "Bitte wähle zuerst eine Routine, Gruppe oder einen Test im Explorer aus.")
            return

        # Reset UI state
        self.progress_bar.setValue(0)
        self.table.setRowCount(0)
        self.log_console.clear()
        self.shot_label.setText("Warte auf Fehler...")
        self.shot_label.setPixmap(QPixmap())

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # Start QThread Worker
        headed = self.headed_cb.isChecked()
        auto_close = self.auto_close_cb.isChecked()
        speed_mode = self.speed_combo.currentData() or "normal"
        browser_engine = self.browser_combo.currentData() or "chromium"
        device_profile = self.device_combo.currentData() or "desktop_1080p"

        self.worker = ExecutionEngineWorker(
            self.pm, self.current_mode, self.current_item_id,
            headed=headed, speed_mode=speed_mode, auto_close=auto_close,
            browser_engine=browser_engine, device_profile=device_profile
        )
        self.worker.log_signal.connect(self.append_log)
        self.worker.step_progress_signal.connect(self.update_progress)
        self.worker.step_status_signal.connect(self.update_step_status)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.screenshot_signal.connect(self.show_screenshot)
        self.worker.start()

    def stop_execution(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.append_log("[USER] Stopp-Signal gesendet. Warten auf Thread...")
            self.stop_btn.setEnabled(False)

    def append_log(self, text: str):
        self.log_console.append(text)

    def update_progress(self, current: int, total: int):
        if total > 0:
            val = int((current / total) * 100)
            self.progress_bar.setValue(val)

    def update_step_status(self, item_id: str, status: str, error_msg: str):
        # Check if item exists in table
        row_found = -1
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == item_id:
                row_found = row
                break

        if row_found == -1:
            row_found = self.table.rowCount()
            self.table.insertRow(row_found)
            self.table.setItem(row_found, 0, QTableWidgetItem(item_id))

        status_item = QTableWidgetItem(status)
        if status == "PASS":
            status_item.setForeground(QColor("#10B981"))
            status_item.setText("✅ PASS")
        elif status == "FAIL":
            status_item.setForeground(QColor("#EF4444"))
            status_item.setText("❌ FAIL")
        else:
            status_item.setForeground(QColor("#F59E0B"))
            status_item.setText("⏳ RUNNING")

        self.table.setItem(row_found, 1, status_item)
        self.table.setItem(row_found, 2, QTableWidgetItem(error_msg))

    def show_screenshot(self, filepath: str):
        if os.path.exists(filepath):
            pixmap = QPixmap(filepath)
            scaled = pixmap.scaled(self.shot_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.shot_label.setPixmap(scaled)

    def on_finished(self, success: bool, summary: str):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.execution_finished_signal.emit()
