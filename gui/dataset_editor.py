import os
import csv
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QFileDialog,
    QInputDialog, QMessageBox, QFrame, QHeaderView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from core.project_manager import ProjectManager

class DatasetEditorWidget(QWidget):
    """
    GUI Widget to view, edit, import, and manage CSV/JSON test datasets.
    """
    datasets_updated_signal = Signal()

    def __init__(self, project_manager: ProjectManager):
        super().__init__()
        self.pm = project_manager
        self.current_dataset_id = None
        self.setup_ui()
        self.refresh_dataset_list()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header Control Panel
        card = QFrame()
        card.setObjectName("cardPanel")
        c_layout = QHBoxLayout(card)

        title = QLabel("📊 Datensatz-Verwaltung")
        title.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 14px;")
        c_layout.addWidget(title)

        c_layout.addStretch()

        dataset_label = QLabel("Datensatz wählen:")
        dataset_label.setStyleSheet("font-weight: bold;")
        c_layout.addWidget(dataset_label)

        self.dataset_combo = QComboBox()
        self.dataset_combo.setMinimumWidth(200)
        self.dataset_combo.currentIndexChanged.connect(self.on_dataset_selected)
        c_layout.addWidget(self.dataset_combo)

        new_btn = QPushButton("➕ Neu")
        new_btn.clicked.connect(self.create_new_dataset)
        c_layout.addWidget(new_btn)

        import_btn = QPushButton("📂 CSV Importieren")
        import_btn.clicked.connect(self.import_csv_file)
        c_layout.addWidget(import_btn)

        del_btn = QPushButton("🗑️ Löschen")
        del_btn.clicked.connect(self.delete_dataset)
        c_layout.addWidget(del_btn)

        layout.addWidget(card)

        # Table Control Toolbar (Row/Column Actions)
        t_card = QFrame()
        t_card.setObjectName("cardPanel")
        t_layout = QHBoxLayout(t_card)

        self.info_label = QLabel("Kein Datensatz ausgewählt")
        self.info_label.setStyleSheet("font-weight: bold; color: #CBD5E1;")
        t_layout.addWidget(self.info_label)

        t_layout.addStretch()

        add_col_btn = QPushButton("➕ Spalte Hinzufügen")
        add_col_btn.clicked.connect(self.add_column)
        t_layout.addWidget(add_col_btn)

        add_row_btn = QPushButton("➕ Zeile Hinzufügen")
        add_row_btn.clicked.connect(self.add_row)
        t_layout.addWidget(add_row_btn)

        del_row_btn = QPushButton("➖ Zeile Löschen")
        del_row_btn.clicked.connect(self.delete_row)
        t_layout.addWidget(del_row_btn)

        self.save_btn = QPushButton("💾 Speichern")
        self.save_btn.setObjectName("accentButton")
        self.save_btn.clicked.connect(self.save_current_dataset)
        t_layout.addWidget(self.save_btn)

        layout.addWidget(t_card)

        # Table Widget
        self.table = QTableWidget(0, 0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

    def refresh_dataset_list(self):
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()

        datasets = self.pm.get_datasets()
        if not datasets:
            self.dataset_combo.addItem("Keine Datensätze vorhanden", None)
            self.current_dataset_id = None
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.info_label.setText("Erstelle oder importiere einen Datensatz")
        else:
            for d in datasets:
                self.dataset_combo.addItem(f"📊 {d['name']} ({d['id']}.csv)", d["id"])
            
            # Select first or current
            idx = 0
            if self.current_dataset_id:
                for i in range(self.dataset_combo.count()):
                    if self.dataset_combo.itemData(i) == self.current_dataset_id:
                        idx = i
                        break

            self.dataset_combo.setCurrentIndex(idx)
            self.current_dataset_id = self.dataset_combo.itemData(idx)
            self.load_dataset(self.current_dataset_id)

        self.dataset_combo.blockSignals(False)

    def on_dataset_selected(self, index: int):
        dataset_id = self.dataset_combo.itemData(index)
        if dataset_id:
            self.current_dataset_id = dataset_id
            self.load_dataset(dataset_id)

    def load_dataset(self, dataset_id: str):
        if not dataset_id:
            return

        headers, rows, _ = self.pm.get_dataset_data(dataset_id)
        self.info_label.setText(f"📝 Bearbeite Datensatz: {dataset_id}.csv ({len(rows)} Zeilen)")

        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))

        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(val)
                self.table.setItem(r_idx, c_idx, item)

    def create_new_dataset(self):
        name, ok = QInputDialog.getText(self, "Neuer Datensatz", "Name des Datensatzes (z.B. patienten_daten):")
        if not ok or not name.strip():
            return

        dataset_id = name.lower().replace(" ", "_")
        headers = ["USERNAME", "PASSWORD"]
        rows = [["user1@demo.de", "pass123"], ["user2@demo.de", "pass456"]]

        self.pm.save_dataset(dataset_id, headers, rows)
        self.current_dataset_id = dataset_id
        self.refresh_dataset_list()
        self.datasets_updated_signal.emit()

    def import_csv_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "CSV / JSON Datei importieren", "", "Daten Dateien (*.csv *.json)")
        if not file_path:
            return

        filename = os.path.basename(file_path)
        base_name = os.path.splitext(filename)[0]
        dataset_id = base_name.lower().replace(" ", "_")

        headers = []
        rows = []

        try:
            if file_path.endswith(".json"):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    headers = list(data[0].keys())
                    for item in data:
                        rows.append([str(item.get(h, "")) for h in headers])
            else:
                with open(file_path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    lines = list(reader)
                    if lines:
                        headers = [h.strip() for h in lines[0]]
                        for r in lines[1:]:
                            rows.append([cell.strip() for cell in r])

            if not headers:
                QMessageBox.warning(self, "Import Fehler", "Datei konnte nicht gelesen werden oder enthält keine Spaltenüberschriften.")
                return

            self.pm.save_dataset(dataset_id, headers, rows)
            self.current_dataset_id = dataset_id
            self.refresh_dataset_list()
            self.datasets_updated_signal.emit()
            QMessageBox.information(self, "Erfolg", f"Datensatz '{dataset_id}' erfolgreich importiert ({len(rows)} Zeilen).")

        except Exception as e:
            QMessageBox.critical(self, "Import Fehler", f"Fehler beim Importieren: {str(e)}")

    def add_column(self):
        col_name, ok = QInputDialog.getText(self, "Neue Spalte", "Name der Variablen-Spalte (z.B. PATIENT_NAME):")
        if not ok or not col_name.strip():
            return

        col_name = col_name.strip().upper().replace(" ", "_")
        col_count = self.table.columnCount()
        self.table.insertColumn(col_count)
        self.table.setHorizontalHeaderItem(col_count, QTableWidgetItem(col_name))

    def add_row(self):
        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        for c in range(self.table.columnCount()):
            self.table.setItem(row_count, c, QTableWidgetItem(""))

    def delete_row(self):
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
        elif self.table.rowCount() > 0:
            self.table.removeRow(self.table.rowCount() - 1)

    def save_current_dataset(self):
        if not self.current_dataset_id:
            return

        headers = []
        for c in range(self.table.columnCount()):
            header_item = self.table.horizontalHeaderItem(c)
            h_text = header_item.text() if header_item else f"COL_{c}"
            headers.append(h_text)

        rows = []
        for r in range(self.table.rowCount()):
            row_data = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                val = item.text() if item else ""
                row_data.append(val)
            rows.append(row_data)

        self.pm.save_dataset(self.current_dataset_id, headers, rows)
        QMessageBox.information(self, "Gespeichert", f"Datensatz '{self.current_dataset_id}' wurde erfolgreich gespeichert ({len(rows)} Zeilen).")
        self.datasets_updated_signal.emit()

    def delete_dataset(self):
        if not self.current_dataset_id:
            return

        reply = QMessageBox.question(
            self, "Datensatz löschen",
            f"Möchtest du den Datensatz '{self.current_dataset_id}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.pm.delete_dataset(self.current_dataset_id)
            self.current_dataset_id = None
            self.refresh_dataset_list()
            self.datasets_updated_signal.emit()
