"""
Artefakte eines Laufs an einem Ort.

Statt Screenshots im Temp-Ordner und Reports mit Zeitstempelnamen bekommt jeder
Lauf ein eigenes Verzeichnis:

    project_data/runs/20260910_143205_test_login_flow/
        report.html
        run.json
        junit.xml
        trace/terminplaner_oeffnen.zip
        video/session_1.webm
        shots/terminplaner_oeffnen.png

Damit ist ein Lauf komplett verschickbar (Ordner zippen) und die relativen
Links im Report funktionieren.
"""

import json
import os
import re
import shutil
from datetime import datetime
from typing import List, Optional

# Verzeichnisname eines Laufs: 20260910_143205_test_login_flow
RUN_DIR_PATTERN = re.compile(r"^\d{8}_\d{6}_")

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(value: str, fallback: str = "unbenannt") -> str:
    """
    Dateisystemtauglicher Name aus beliebigem Text.

    Trennzeichen werden ersetzt, und Punktfolgen zu einem Punkt eingekürzt —
    ein '..' im Namen ist zwar nicht ausbruchsfähig (die Trennzeichen sind ja
    weg), sieht aber nach Pfad-Trickserei aus und irritiert nur.
    """
    cleaned = _SAFE.sub("_", (value or "").strip())
    cleaned = re.sub(r"\.{2,}", ".", cleaned).strip("._")
    return cleaned[:80] or fallback


class RunArtifacts:
    """Legt das Laufverzeichnis an und liefert Pfade darin."""

    def __init__(self, runs_dir: str, mode: str, item_id: str,
                 timestamp: Optional[datetime] = None):
        stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
        base_id = f"{stamp}_{safe_name(mode, 'lauf')}_{safe_name(item_id)}"
        root = os.path.abspath(runs_dir)

        # Der Zeitstempel geht nur auf Sekunden — zwei Läufe in derselben
        # Sekunde würden sich sonst dasselbe Verzeichnis teilen und ihre
        # Reports gegenseitig überschreiben.
        self.run_id = base_id
        self.dir = os.path.join(root, self.run_id)
        suffix = 2
        while True:
            try:
                os.makedirs(self.dir, exist_ok=False)
                break
            except FileExistsError:
                self.run_id = f"{base_id}_{suffix}"
                self.dir = os.path.join(root, self.run_id)
                suffix += 1
            except OSError:
                # Verzeichnis nicht anlegbar -> mit exist_ok arbeiten und
                # den Fehler dem Aufrufer überlassen
                os.makedirs(self.dir, exist_ok=True)
                break

        self._used_names: dict = {}

    # -- Pfade ------------------------------------------------------------

    @property
    def report_path(self) -> str:
        return os.path.join(self.dir, "report.html")

    @property
    def run_json_path(self) -> str:
        return os.path.join(self.dir, "run.json")

    @property
    def junit_path(self) -> str:
        return os.path.join(self.dir, "junit.xml")

    def subdir(self, kind: str) -> str:
        """Unterordner anlegen (trace / video / shots) und Pfad zurückgeben."""
        path = os.path.join(self.dir, kind)
        os.makedirs(path, exist_ok=True)
        return path

    def unique_path(self, kind: str, name: str, suffix: str) -> str:
        """
        Pfad für ein Artefakt. Läuft dieselbe Routine mehrfach (Datensatzzeilen,
        Wiederholungen), wird durchnummeriert statt überschrieben.
        """
        base = safe_name(name)
        key = (kind, base, suffix)
        count = self._used_names.get(key, 0)
        self._used_names[key] = count + 1
        filename = f"{base}{suffix}" if count == 0 else f"{base}_{count + 1}{suffix}"
        return os.path.join(self.subdir(kind), filename)

    def relative(self, path: str) -> str:
        """Pfad relativ zum Laufverzeichnis, für Links im Report."""
        if not path:
            return ""
        try:
            rel = os.path.relpath(os.path.abspath(path), self.dir)
        except ValueError:  # anderes Laufwerk unter Windows
            return path
        return rel.replace(os.sep, "/")

    # -- Schreiben --------------------------------------------------------

    def write_json(self, data) -> str:
        with open(self.run_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return self.run_json_path

    # -- Aufräumen --------------------------------------------------------

    def discard_empty_subdirs(self):
        """Leere trace/video/shots-Ordner wieder entfernen."""
        for kind in ("trace", "video", "shots"):
            path = os.path.join(self.dir, kind)
            if os.path.isdir(path):
                try:
                    if not os.listdir(path):
                        os.rmdir(path)
                except OSError:
                    pass


def list_runs(runs_dir: str) -> List[str]:
    """Laufverzeichnisse, neueste zuerst."""
    if not os.path.isdir(runs_dir):
        return []
    entries = []
    for name in os.listdir(runs_dir):
        full = os.path.join(runs_dir, name)
        if os.path.isdir(full) and RUN_DIR_PATTERN.match(name):
            entries.append(name)
    return sorted(entries, reverse=True)


def prune_runs(runs_dir: str, keep: int) -> List[str]:
    """
    Behält die neuesten `keep` Laufverzeichnisse und löscht ältere.
    keep <= 0 bedeutet: nichts löschen. Gibt die gelöschten Namen zurück.
    """
    if keep is None or keep <= 0:
        return []

    runs = list_runs(runs_dir)
    removed = []
    for name in runs[keep:]:
        target = os.path.join(runs_dir, name)
        # Sicherheitsnetz: nur Verzeichnisse mit Laufnamen direkt unter runs_dir
        if not RUN_DIR_PATTERN.match(name) or not os.path.isdir(target):
            continue
        try:
            shutil.rmtree(target)
            removed.append(name)
        except OSError:
            continue
    return removed
