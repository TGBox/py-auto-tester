DARK_THEME_QSS = """
/* Py-Auto-Tester Modern Dark Theme */

QMainWindow {
    background-color: #121824;
    color: #E2E8F0;
}

QWidget {
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
    color: #CBD5E1;
}

/* Sidebar & Panels */
QFrame#sidebarFrame {
    background-color: #1E293B;
    border-right: 1px solid #334155;
}

QFrame#headerPanel {
    background-color: #1E293B;
    border-bottom: 1px solid #334155;
    padding: 8px;
}

QFrame#cardPanel {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 12px;
}

/* Buttons */
QPushButton {
    background-color: #334155;
    color: #F8FAFC;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #475569;
    border-color: #64748B;
}

QPushButton:pressed {
    background-color: #0F172A;
}

QPushButton#accentButton {
    background-color: #2563EB;
    border-color: #3B82F6;
    color: #FFFFFF;
}

QPushButton#accentButton:hover {
    background-color: #1D4ED8;
    border-color: #60A5FA;
}

QPushButton#recordButton {
    background-color: #DC2626;
    border-color: #EF4444;
    color: #FFFFFF;
}

QPushButton#recordButton:hover {
    background-color: #B91C1C;
}

QPushButton#runButton {
    background-color: #059669;
    border-color: #10B981;
    color: #FFFFFF;
}

QPushButton#runButton:hover {
    background-color: #047857;
}

QPushButton#stopButton {
    background-color: #D97706;
    border-color: #F59E0B;
    color: #FFFFFF;
}

QPushButton#stopButton:hover {
    background-color: #B45309;
}

/* TreeWidget */
QTreeWidget {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}

QTreeWidget::item {
    padding: 6px 8px;
    border-radius: 4px;
}

QTreeWidget::item:hover {
    background-color: #1E293B;
}

QTreeWidget::item:selected {
    background-color: #1E3A8A;
    color: #60A5FA;
}

/* TabWidget */
QTabWidget::pane {
    border: 1px solid #334155;
    background-color: #1E293B;
    border-radius: 6px;
}

QTabBar::tab {
    background-color: #0F172A;
    color: #94A3B8;
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1E293B;
    color: #38BDF8;
    font-weight: bold;
    border-bottom: 2px solid #38BDF8;
}

QTabBar::tab:hover:!selected {
    background-color: #1E293B;
    color: #E2E8F0;
}

/* LineEdit & TextEdit */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #F8FAFC;
    padding: 6px 10px;
    selection-background-color: #2563EB;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #38BDF8;
}

/* Splitter */
QSplitter::handle {
    background-color: #334155;
    margin: 2px;
}

QSplitter::handle:hover {
    background-color: #38BDF8;
}

/* ProgressBar */
QProgressBar {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 6px;
    text-align: center;
    color: #F8FAFC;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #10B981;
    border-radius: 5px;
}

/* GroupBox */
QGroupBox {
    border: 1px solid #334155;
    border-radius: 6px;
    margin-top: 12px;
    font-weight: bold;
    color: #38BDF8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

/* ScrollBar */
QScrollBar:vertical {
    background-color: #0F172A;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: #475569;
}
"""
