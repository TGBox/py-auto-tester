import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QMessageBox, QFrame, QSplitter,
    QTableWidget, QTableWidgetItem, QComboBox, QHeaderView, QAbstractItemView
)
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import QRegularExpression, Signal, Qt

from py_auto_tester.core.project_manager import ProjectManager
from py_auto_tester.core.checks import CHECK_TYPES, new_check


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Simple, clean Python syntax highlighter for PySide6 QPlainTextEdit."""
    def __init__(self, document):
        super().__init__(document)

        self.highlighting_rules = []

        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#F472B6")) # Pink/Magenta
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "def", "class", "import", "from", "return", "if", "else", "elif",
            "for", "while", "in", "as", "with", "try", "except", "pass", "and", "or", "not",
            "assert", "raise", "None", "True", "False"
        ]
        for word in keywords:
            pattern = QRegularExpression(rf"\b{word}\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # Playwright & Page calls
        page_format = QTextCharFormat()
        page_format.setForeground(QColor("#38BDF8")) # Cyan
        page_format.setFontWeight(QFont.Bold)
        pattern = QRegularExpression(
            r"\b(page|vars|execute|get_by_role|get_by_text|get_by_label|locator|"
            r"click|fill|press|goto|dblclick|wait_for_url|wait_for_selector)\b"
        )
        self.highlighting_rules.append((pattern, page_format))

        # Assertion helpers available in the routine namespace
        assert_format = QTextCharFormat()
        assert_format.setForeground(QColor("#FBBF24")) # Amber
        assert_format.setFontWeight(QFont.Bold)
        pattern = QRegularExpression(r"\b(expect|check|require|step|log)\b")
        self.highlighting_rules.append((pattern, assert_format))

        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#34D399")) # Mint Green
        pattern = QRegularExpression(r'".*?"|\'.*?\'')
        self.highlighting_rules.append((pattern, string_format))

        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#64748B")) # Muted Gray
        pattern = QRegularExpression(r"#.*")
        self.highlighting_rules.append((pattern, comment_format))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class ChecksEditorWidget(QWidget):
    """
    Tabellen-Editor für die deklarativen Erwartungen einer Routine.

    Jede Zeile ist eine Erwartung: aktiv? / Typ / Selektor / Wert.
    Welche Felder eine Zeile braucht, kommt aus CHECK_TYPES — Felder, die der
    gewählte Typ nicht kennt, werden gesperrt und ausgegraut.
    """
    changed_signal = Signal()

    COL_ENABLED = 0
    COL_TYPE = 1
    COL_TARGET = 2
    COL_VALUE = 3

    def __init__(self):
        super().__init__()
        self._loading = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Toolbar
        bar = QFrame()
        bar.setObjectName("cardPanel")
        b_layout = QHBoxLayout(bar)

        title = QLabel("🎯 Erwartungen")
        title.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 13px;")
        b_layout.addWidget(title)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #94A3B8;")
        b_layout.addWidget(self.count_label)

        b_layout.addStretch()

        add_btn = QPushButton("➕ Erwartung")
        add_btn.setToolTip("Fügt eine neue Erwartung hinzu, die nach der Routine geprüft wird")
        add_btn.clicked.connect(self.add_check)
        b_layout.addWidget(add_btn)

        del_btn = QPushButton("➖ Entfernen")
        del_btn.setToolTip("Entfernt die markierte Erwartung")
        del_btn.clicked.connect(self.remove_selected)
        b_layout.addWidget(del_btn)

        layout.addWidget(bar)

        # Tabelle
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Aktiv", "Erwartung", "Selektor", "Wert"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_ENABLED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TARGET, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_VALUE, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._update_hint)
        layout.addWidget(self.table)

        # Hinweiszeile für den gewählten Typ
        self.hint_label = QLabel(
            "Erwartungen werden nach dem Routine-Code geprüft. "
            "Ohne Erwartung gilt eine Routine nur als erfolgreich, wenn sie nicht abstürzt."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.hint_label)

    # -- Laden / Speichern ------------------------------------------------

    def load_checks(self, checks):
        self._loading = True
        self.table.setRowCount(0)
        for check in checks or []:
            self._append_row(check)
        self._loading = False
        self._update_count()
        self._update_hint()

    def get_checks(self):
        """Liest die Tabelle zurück in die Datenstruktur."""
        checks = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, self.COL_TYPE)
            if combo is None:
                continue
            ctype = combo.currentData()
            spec = CHECK_TYPES.get(ctype, {})

            enabled_item = self.table.item(row, self.COL_ENABLED)
            enabled = enabled_item.checkState() == Qt.Checked if enabled_item else True

            target = ""
            if spec.get("target"):
                item = self.table.item(row, self.COL_TARGET)
                target = item.text().strip() if item else ""

            value = ""
            if spec.get("value"):
                item = self.table.item(row, self.COL_VALUE)
                value = item.text().strip() if item else ""

            checks.append({
                "type": ctype,
                "target": target,
                "value": value,
                "enabled": enabled,
            })
        return checks

    def validation_problems(self):
        """Liste unvollständiger Erwartungen, für die Warnung beim Speichern."""
        problems = []
        for idx, check in enumerate(self.get_checks(), start=1):
            spec = CHECK_TYPES.get(check["type"], {})
            if spec.get("target") and not check["target"]:
                problems.append(f"Zeile {idx}: '{spec['target']}' fehlt")
            if spec.get("value") and not check["value"]:
                problems.append(f"Zeile {idx}: '{spec['value']}' fehlt")
        return problems

    # -- Zeilen -----------------------------------------------------------

    def _append_row(self, check):
        row = self.table.rowCount()
        self.table.insertRow(row)

        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        enabled_item.setCheckState(Qt.Checked if check.get("enabled", True) else Qt.Unchecked)
        enabled_item.setToolTip("Deaktivierte Erwartungen werden beim Lauf übersprungen")
        self.table.setItem(row, self.COL_ENABLED, enabled_item)

        combo = QComboBox()
        for ctype, spec in CHECK_TYPES.items():
            combo.addItem(spec["label"], ctype)
        current = check.get("type", "element_visible")
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(lambda _, c=combo: self._on_type_changed(c))
        self.table.setCellWidget(row, self.COL_TYPE, combo)

        self.table.setItem(row, self.COL_TARGET, QTableWidgetItem(check.get("target", "") or ""))
        self.table.setItem(row, self.COL_VALUE, QTableWidgetItem(check.get("value", "") or ""))

        self._apply_type_spec(row)

    def _apply_type_spec(self, row):
        """Sperrt und beschriftet die Felder passend zum gewählten Erwartungstyp."""
        combo = self.table.cellWidget(row, self.COL_TYPE)
        if combo is None:
            return
        spec = CHECK_TYPES.get(combo.currentData(), {})

        for col, key in ((self.COL_TARGET, "target"), (self.COL_VALUE, "value")):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)

            if spec.get(key):
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                item.setForeground(QColor("#F8FAFC"))
                item.setToolTip(spec.get("hint", ""))
                if not item.text():
                    item.setData(Qt.DisplayRole, "")
            else:
                item.setText("")
                item.setFlags(Qt.ItemIsSelectable)
                item.setForeground(QColor("#475569"))
                item.setToolTip("Für diesen Erwartungstyp nicht erforderlich")

    def _on_type_changed(self, combo):
        row = self._row_of_widget(combo)
        if row is None:
            return
        self._loading = True
        self._apply_type_spec(row)
        self._loading = False
        self._update_hint()
        if not self._loading:
            self.changed_signal.emit()

    def _row_of_widget(self, widget):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, self.COL_TYPE) is widget:
                return row
        return None

    def add_check(self):
        self._append_row(new_check())
        self.table.selectRow(self.table.rowCount() - 1)
        self._update_count()
        self._update_hint()
        self.changed_signal.emit()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for row in rows:
            self.table.removeRow(row)
        self._update_count()
        self.changed_signal.emit()

    # -- Anzeige ----------------------------------------------------------

    def _on_item_changed(self, _item):
        if not self._loading:
            self._update_count()
            self.changed_signal.emit()

    def _update_count(self):
        total = self.table.rowCount()
        active = 0
        for row in range(total):
            item = self.table.item(row, self.COL_ENABLED)
            if item and item.checkState() == Qt.Checked:
                active += 1
        if total == 0:
            self.count_label.setText("— keine")
        else:
            self.count_label.setText(f"— {active} von {total} aktiv")

    def _update_hint(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) == 1:
            row = rows.pop()
            combo = self.table.cellWidget(row, self.COL_TYPE)
            if combo:
                spec = CHECK_TYPES.get(combo.currentData(), {})
                hint = spec.get("hint", "")
                if hint:
                    self.hint_label.setText(f"💡 {spec['label']}: {hint}")
                    return
        self.hint_label.setText(
            "Erwartungen werden nach dem Routine-Code geprüft. "
            "Ohne Erwartung gilt eine Routine nur als erfolgreich, wenn sie nicht abstürzt."
        )


class RoutineEditorWidget(QWidget):
    """
    Code Editor Widget to view and modify recorded Python routines,
    plus the declarative expectations attached to them.
    """
    routine_saved_signal = Signal(str)

    def __init__(self, project_manager: ProjectManager):
        super().__init__()
        self.pm = project_manager
        self.current_routine_id = None
        self._dirty = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header Info Card
        header_card = QFrame()
        header_card.setObjectName("cardPanel")
        h_layout = QHBoxLayout(header_card)

        self.info_label = QLabel("Wähle eine Routine im Explorer aus")
        self.info_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #38BDF8;")
        h_layout.addWidget(self.info_label)

        h_layout.addStretch()

        self.help_btn = QPushButton("❓ Verfügbare Helfer")
        self.help_btn.setToolTip("Zeigt, was im Routine-Code zur Verfügung steht")
        self.help_btn.clicked.connect(self.show_api_help)
        h_layout.addWidget(self.help_btn)

        self.save_btn = QPushButton("💾 Routine Speichern")
        self.save_btn.setObjectName("accentButton")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_routine)
        h_layout.addWidget(self.save_btn)

        layout.addWidget(header_card)

        # Splitter: Code oben, Erwartungen unten
        splitter = QSplitter(Qt.Vertical)

        self.editor = QPlainTextEdit()
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        self.editor.setPlaceholderText("# Python-Code für die Routine erscheint hier...")
        self.editor.textChanged.connect(self._mark_dirty)
        splitter.addWidget(self.editor)

        self.checks_editor = ChecksEditorWidget()
        self.checks_editor.changed_signal.connect(self._mark_dirty)
        splitter.addWidget(self.checks_editor)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        # Apply Syntax Highlighter
        self.highlighter = PythonSyntaxHighlighter(self.editor.document())

    # -- Zustand ----------------------------------------------------------

    def _mark_dirty(self):
        if self.current_routine_id and not self._dirty:
            self._dirty = True
            self._refresh_title()

    def _refresh_title(self):
        if not self.current_routine_id:
            self.info_label.setText("Wähle eine Routine im Explorer aus")
            return
        marker = " ●" if self._dirty else ""
        self.info_label.setText(f"📝 Routine-Editor: {self.current_routine_id}.py{marker}")

    def has_unsaved_changes(self) -> bool:
        return bool(self.current_routine_id and self._dirty)

    def confirm_discard(self) -> bool:
        """Fragt bei ungespeicherten Änderungen nach. True = weitermachen."""
        if not self.has_unsaved_changes():
            return True
        reply = QMessageBox.question(
            self, "Ungespeicherte Änderungen",
            f"Die Routine '{self.current_routine_id}' hat ungespeicherte Änderungen.\n\n"
            "Jetzt speichern?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save
        )
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Save:
            return self.save_routine(silent=True)
        return True

    # -- Laden / Speichern ------------------------------------------------

    def load_routine(self, routine_id: str):
        if routine_id == self.current_routine_id and self._dirty:
            return
        if not self.confirm_discard():
            return

        self.current_routine_id = routine_id
        code = self.pm.get_routine_code(routine_id)

        self.editor.blockSignals(True)
        self.editor.setPlainText(code)
        self.editor.blockSignals(False)

        self.checks_editor.load_checks(self.pm.get_routine_checks(routine_id))

        self._dirty = False
        self._refresh_title()
        self.save_btn.setEnabled(True)

    def save_routine(self, silent: bool = False) -> bool:
        if not self.current_routine_id:
            return False

        problems = self.checks_editor.validation_problems()
        if problems:
            detail = "\n".join(f"• {p}" for p in problems[:8])
            reply = QMessageBox.question(
                self, "Unvollständige Erwartungen",
                f"Folgende Erwartungen sind unvollständig und würden beim Lauf "
                f"fehlschlagen:\n\n{detail}\n\nTrotzdem speichern?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return False

        code = self.editor.toPlainText()
        name = self.current_routine_id.replace("_", " ").title()
        self.pm.save_routine(self.current_routine_id, name, "Bearbeitete Routine", code)
        self.pm.save_routine_checks(self.current_routine_id, self.checks_editor.get_checks())

        self._dirty = False
        self._refresh_title()

        if not silent:
            n = len(self.checks_editor.get_checks())
            suffix = f" ({n} Erwartung(en))" if n else ""
            QMessageBox.information(
                self, "Erfolg",
                f"Routine '{self.current_routine_id}' erfolgreich gespeichert{suffix}."
            )
        self.routine_saved_signal.emit(self.current_routine_id)
        return True

    # -- Hilfe ------------------------------------------------------------

    def show_api_help(self):
        QMessageBox.information(
            self, "Verfügbare Helfer im Routine-Code",
            "<h3>Im Routine-Code verfügbar</h3>"
            "<p><b>page</b> — die Playwright-Seite<br>"
            "<b>vars</b> — Projekt-Variablen und Datensatz-Spalten<br>"
            "<b>log(text)</b> — schreibt in das Ausführungsprotokoll</p>"
            "<h4>Erwartungen</h4>"
            "<p><b>expect(locator)</b> — Playwright-Assertion, bricht bei Fehlschlag ab<br>"
            "<b>check(bedingung, \"Beschreibung\")</b> — weiche Erwartung: wird "
            "protokolliert, die Routine läuft weiter<br>"
            "<b>require(bedingung, \"Beschreibung\")</b> — harte Erwartung: bricht ab</p>"
            "<h4>Struktur</h4>"
            "<p><b>with step(\"Login\"):</b> — gruppiert Aktionen und Erwartungen "
            "im Protokoll und im Report</p>"
            "<pre>def execute(page, vars):\n"
            "    page.goto(vars['BASE_URL'])\n\n"
            "    with step('Login'):\n"
            "        page.get_by_role('textbox', name='E-Mail').fill(vars['USERNAME'])\n"
            "        page.get_by_role('button').filter(has_text='check').click()\n\n"
            "    expect(page.get_by_role('link', name='Terminplaner')).to_be_visible()\n"
            "    check(page.url.endswith('/home'), 'Landet auf der Startseite')</pre>"
        )
