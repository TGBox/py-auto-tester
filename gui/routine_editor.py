import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QMessageBox, QFrame
)
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import QRegularExpression, Signal

from core.project_manager import ProjectManager

class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Simple, clean Python syntax highlighter for PySide6 QPlainTextEdit."""
    def __init__(self, document):
        super().__init__(document)

        self.highlighting_rules = []

        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#F472B6")) # Pink/Magenta
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "def", "class", "import", "from", "return", "if", "else", "elif",
            "for", "while", "in", "as", "with", "try", "except", "pass", "and", "or", "not"
        ]
        for word in keywords:
            pattern = QRegularExpression(rf"\b{word}\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # Playwright & Page calls
        page_format = QTextCharFormat()
        page_format.setForeground(QColor("#38BDF8")) # Cyan
        page_format.setFontWeight(QFont.Weight.Bold)
        pattern = QRegularExpression(r"\b(page|vars|execute|get_by_role|get_by_text|locator|click|fill|press|goto|dblclick)\b")
        self.highlighting_rules.append((pattern, page_format))

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


class RoutineEditorWidget(QWidget):
    """
    Code Editor Widget to view and modify recorded Python routines.
    """
    routine_saved_signal = Signal(str)

    def __init__(self, project_manager: ProjectManager):
        super().__init__()
        self.pm = project_manager
        self.current_routine_id = None
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

        self.save_btn = QPushButton("💾 Routine Speichern")
        self.save_btn.setObjectName("accentButton")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_routine)
        h_layout.addWidget(self.save_btn)

        layout.addWidget(header_card)

        # Code Editor
        self.editor = QPlainTextEdit()
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.setPlaceholderText("# Python-Code für die Routine erscheint hier...")
        layout.addWidget(self.editor)

        # Apply Syntax Highlighter
        self.highlighter = PythonSyntaxHighlighter(self.editor.document())

    def load_routine(self, routine_id: str):
        self.current_routine_id = routine_id
        code = self.pm.get_routine_code(routine_id)
        
        self.info_label.setText(f"📝 Routine-Editor: {routine_id}.py")
        self.editor.setPlainText(code)
        self.save_btn.setEnabled(True)

    def save_routine(self):
        if not self.current_routine_id:
            return

        code = self.editor.toPlainText()
        name = self.current_routine_id.replace("_", " ").title()
        self.pm.save_routine(self.current_routine_id, name, "Bearbeitete Routine", code)
        
        QMessageBox.information(self, "Erfolg", f"Routine '{self.current_routine_id}' erfolgreich gespeichert.")
        self.routine_saved_signal.emit(self.current_routine_id)
