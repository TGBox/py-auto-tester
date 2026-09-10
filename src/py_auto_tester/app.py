"""
Start der grafischen Oberfläche.

Getrennt von `cli.py`, damit die Kommandozeile ohne Qt lädt — dieses Modul
importiert PySide6 erst beim Aufruf von `run_gui()`.
"""

import os
import sys

DEFAULT_PROJECT_DIR = "project_data"


def ensure_project(project_dir: str = DEFAULT_PROJECT_DIR) -> str:
    """
    Legt die Projektstruktur an, falls sie fehlt, und schreibt eine kleine
    Beispielroutine — aber nur in ein noch leeres Projekt.
    """
    from py_auto_tester.core.project_manager import ProjectManager

    pm = ProjectManager(project_dir)

    if pm.get_routines():
        return pm.root_dir

    pm.save_routine(
        "beispiel_suche",
        "Beispiel: Suche öffnen",
        "Beispielroutine — gefahrlos löschbar.",
        "def execute(page, vars):\n"
        "    # 'vars' enthält die Projekt-Variablen (Datei > Variablen verwalten)\n"
        "    page.goto(vars.get('BASE_URL', 'https://example.com'))\n"
        "\n"
        "    with step('Startseite prüfen'):\n"
        "        check(page.title() != '', 'Seite hat einen Titel')\n"
        "\n"
        "    # expect(...) bricht bei Fehlschlag ab, check(...) läuft weiter.\n"
        "    expect(page.locator('h1')).to_be_visible()\n",
    )
    pm.save_routine_checks("beispiel_suche", [
        {"type": "element_visible", "target": "h1", "value": "", "enabled": True},
    ])

    if not pm.get_datasets():
        pm.save_dataset("beispiel_daten", ["USERNAME", "ROLE"],
                        [["erste@example.com", "Admin"],
                         ["zweite@example.com", "Benutzer"]])

    return pm.root_dir


def run_gui(project_dir: str = DEFAULT_PROJECT_DIR) -> int:
    """Startet die Anwendung. Gibt den Exit-Code zurück."""
    from PySide6.QtWidgets import QApplication
    from py_auto_tester.gui.main_window import MainWindow

    ensure_project(project_dir)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("py-auto-tester")

    window = MainWindow(project_dir)
    window.show()
    return app.exec()


def main() -> int:
    project_dir = os.environ.get("PY_AUTO_TESTER_PROJECT", DEFAULT_PROJECT_DIR)
    return run_gui(project_dir)


if __name__ == "__main__":
    sys.exit(main())
