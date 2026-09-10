"""
py-auto-tester — GUI und Kommandozeile zum Aufnehmen, Strukturieren und
Ausführen von Playwright-Webtests.

Dieses Modul bleibt bewusst leer von Importen: `py_auto_tester.core` und
`py_auto_tester.cli` müssen ohne Qt ladbar sein (CI, kopflose Läufe), und ein
Import von PySide6 hier würde das für alles darunter kaputt machen.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
