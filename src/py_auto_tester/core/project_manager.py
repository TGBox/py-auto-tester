import os
import json
import csv
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

DEFAULT_SETTINGS: Dict[str, Any] = {
    # "log" = nur protokollieren, "warn" = Warnung im Report (Status bleibt PASS),
    # "fail" = Schritt wird rot
    "console_policy": "warn",
    "network_policy": "warn",
    "capture_console_warnings": False,
    "ignore_console": [],
    "ignore_urls": [
        r"google-analytics\.com",
        r"googletagmanager\.com",
        r"favicon\.ico",
    ],
    "check_timeout_ms": 5000,

    # Artefakte pro Lauf
    "trace_mode": "on_failure",   # "off" | "on_failure" | "always"
    "video_mode": "off",          # "off" | "on_failure" | "always"
    "keep_runs": 20,              # 0 = nie aufräumen
}

POLICY_VALUES = ("log", "warn", "fail")
ARTIFACT_MODES = ("off", "on_failure", "always")


class ProjectManager:
    """Manages project data: Routines, Groups, Tests, Variables, and Datasets."""
    def __init__(self, root_dir: str = "project_data"):
        self.root_dir = os.path.abspath(root_dir)
        self.routines_dir = os.path.join(self.root_dir, "routines")
        self.datasets_dir = os.path.join(self.root_dir, "datasets")
        self.reports_dir = os.path.join(self.root_dir, "reports")
        self.runs_dir = os.path.join(self.root_dir, "runs")
        self.groups_file = os.path.join(self.root_dir, "groups.json")
        self.tests_file = os.path.join(self.root_dir, "tests.json")
        self.variables_file = os.path.join(self.root_dir, "variables.json")
        self.settings_file = os.path.join(self.root_dir, "settings.json")

        # Meldungen über beschädigte Dateien; die GUI zeigt sie beim Start,
        # die CLI schreibt sie nach stderr.
        self.load_warnings: List[str] = []

        self.ensure_structure()

    def ensure_structure(self):
        """Ensure directories and default JSON files exist."""
        os.makedirs(self.routines_dir, exist_ok=True)
        os.makedirs(self.datasets_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.runs_dir, exist_ok=True)
        
        if not os.path.exists(self.groups_file):
            self._write_json(self.groups_file, [])
            
        if not os.path.exists(self.tests_file):
            self._write_json(self.tests_file, [])
            
        if not os.path.exists(self.variables_file):
            # Kein erfundenes Passwort als Vorbelegung — das landet sonst
            # in Screenshots und Reports und sieht wie ein echter Wert aus.
            self._write_json(self.variables_file, {
                "BASE_URL": "https://example.com",
                "USERNAME": "",
                "PASSWORD": ""
            })

    def _default_for(self, filepath: str) -> Any:
        """Leerwert passend zum Dateityp."""
        return {} if filepath.endswith(("variables.json", "settings.json")) else []

    def _read_json(self, filepath: str) -> Any:
        """
        Liest eine JSON-Datei.

        Eine fehlende Datei ist normal und liefert den Leerwert. Eine
        *beschädigte* Datei wird zur Seite gelegt (`.corrupt-<zeitstempel>`),
        bevor der Leerwert zurückgeht — sonst überschreibt das nächste
        Speichern die einzige Kopie und alle Tests sind still verloren.
        Die Warnungen landen in `self.load_warnings`.
        """
        if not os.path.exists(filepath):
            return self._default_for(filepath)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._quarantine(filepath, f"unlesbares JSON: {e}")
            return self._default_for(filepath)
        except OSError as e:
            # Kein Lesezugriff, Datei gesperrt: nichts kaputtmachen, nur melden
            self._warn(f"'{os.path.basename(filepath)}' konnte nicht gelesen werden: {e}")
            return self._default_for(filepath)

    def _warn(self, message: str):
        self.load_warnings.append(message)

    def drain_load_warnings(self) -> List[str]:
        """
        Gibt die aufgelaufenen Warnungen zurück und leert die Liste.

        Warnungen entstehen beim *Lesen*, nicht beim Anlegen des Managers —
        Aufrufer müssen also nach dem Zugriff drainen, nicht davor.
        """
        drained = list(self.load_warnings)
        self.load_warnings = []
        return drained

    def _quarantine(self, filepath: str, reason: str):
        """Beschädigte Datei umbenennen, damit sie nicht überschrieben wird."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{filepath}.corrupt-{stamp}"
        counter = 2
        while os.path.exists(backup):
            backup = f"{filepath}.corrupt-{stamp}_{counter}"
            counter += 1
        try:
            os.replace(filepath, backup)
            self._warn(
                f"'{os.path.basename(filepath)}' ist beschädigt ({reason}). "
                f"Die Datei wurde nach '{os.path.basename(backup)}' gesichert; "
                "es wird mit einem leeren Stand weitergearbeitet."
            )
        except OSError as e:
            self._warn(
                f"'{os.path.basename(filepath)}' ist beschädigt ({reason}) und konnte "
                f"nicht gesichert werden ({e}). NICHT SPEICHERN, sonst ist der Inhalt weg."
            )

    def _write_json(self, filepath: str, data: Any):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # --- Routines ---
    def get_routines(self) -> List[Dict[str, Any]]:
        """Returns list of routines scanned from routines_dir."""
        routines = []
        if not os.path.exists(self.routines_dir):
            return routines
            
        for filename in sorted(os.listdir(self.routines_dir)):
            if filename.endswith(".py"):
                filepath = os.path.join(self.routines_dir, filename)
                routine_id = os.path.splitext(filename)[0]
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                    
                meta = self._parse_routine_metadata(code)
                routines.append({
                    "id": routine_id,
                    "name": meta.get("name", routine_id.replace("_", " ").title()),
                    "description": meta.get("description", ""),
                    "filename": filename,
                    "filepath": filepath,
                    "code": code
                })
        return routines

    def _parse_routine_metadata(self, code: str) -> Dict[str, str]:
        """Extract title/description from docstrings if present."""
        name_match = re.search(r'# ROUTINE_NAME:\s*(.+)', code)
        desc_match = re.search(r'# ROUTINE_DESC:\s*(.+)', code)
        return {
            "name": name_match.group(1).strip() if name_match else "",
            "description": desc_match.group(1).strip() if desc_match else ""
        }

    def save_routine(self, routine_id: str, name: str, description: str, code_content: str) -> str:
        """Saves a routine code snippet file."""
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', routine_id.lower())
        if not safe_id:
            safe_id = "routine_1"
            
        filename = f"{safe_id}.py"
        filepath = os.path.join(self.routines_dir, filename)
        
        # Ensure metadata header comments
        header = f"# ROUTINE_NAME: {name}\n# ROUTINE_DESC: {description}\n\n"
        if not code_content.startswith("# ROUTINE_NAME"):
            code_content = header + code_content
            
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code_content)
            
        return safe_id

    def get_routine_code(self, routine_id: str) -> str:
        filepath = os.path.join(self.routines_dir, f"{routine_id}.py")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    # --- Routine-Erwartungen (deklarative Checks) ---
    def _checks_path(self, routine_id: str) -> str:
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', routine_id.lower())
        return os.path.join(self.routines_dir, f"{safe_id}.checks.json")

    def get_routine_checks(self, routine_id: str) -> List[Dict[str, Any]]:
        """Liest die deklarativen Erwartungen einer Routine."""
        filepath = self._checks_path(routine_id)
        if not os.path.exists(filepath):
            return []
        data = self._read_json(filepath)
        if not isinstance(data, list):
            return []
        # Nur wohlgeformte Einträge zurückgeben
        checks = []
        for item in data:
            if isinstance(item, dict) and item.get("type"):
                checks.append({
                    "type": item.get("type", ""),
                    "target": item.get("target", "") or "",
                    "value": item.get("value", "") or "",
                    "enabled": bool(item.get("enabled", True)),
                })
        return checks

    def save_routine_checks(self, routine_id: str, checks: List[Dict[str, Any]]):
        """Speichert die Erwartungen; eine leere Liste entfernt die Datei."""
        filepath = self._checks_path(routine_id)
        if not checks:
            if os.path.exists(filepath):
                os.remove(filepath)
            return
        self._write_json(filepath, checks)

    def delete_routine(self, routine_id: str):
        filepath = os.path.join(self.routines_dir, f"{routine_id}.py")
        if os.path.exists(filepath):
            os.remove(filepath)

        checks_path = self._checks_path(routine_id)
        if os.path.exists(checks_path):
            os.remove(checks_path)


        # Clean up reference in groups
        groups = self.get_groups()
        updated_groups = []
        for g in groups:
            g["routine_ids"] = [rid for rid in g.get("routine_ids", []) if rid != routine_id]
            updated_groups.append(g)
        self._write_json(self.groups_file, updated_groups)

    # --- Groups ---
    def get_groups(self) -> List[Dict[str, Any]]:
        return self._read_json(self.groups_file)

    def save_group(self, group_id: str, name: str, description: str, routine_ids: List[str]):
        groups = self.get_groups()
        existing = next((g for g in groups if g["id"] == group_id), None)
        
        if existing:
            existing["name"] = name
            existing["description"] = description
            existing["routine_ids"] = routine_ids
        else:
            groups.append({
                "id": group_id,
                "name": name,
                "description": description,
                "routine_ids": routine_ids
            })
            
        self._write_json(self.groups_file, groups)

    def delete_group(self, group_id: str):
        groups = [g for g in self.get_groups() if g["id"] != group_id]
        self._write_json(self.groups_file, groups)
        
        # Clean up tests referencing this group
        tests = self.get_tests()
        for t in tests:
            t["item_ids"] = [iid for iid in t.get("item_ids", []) if iid != f"group:{group_id}"]
        self._write_json(self.tests_file, tests)

    # --- Tests ---
    def get_tests(self) -> List[Dict[str, Any]]:
        return self._read_json(self.tests_file)

    def save_test(self, test_id: str, name: str, description: str, item_ids: List[str], isolated_session: bool = False):
        tests = self.get_tests()
        existing = next((t for t in tests if t["id"] == test_id), None)
        
        if existing:
            existing["name"] = name
            existing["description"] = description
            existing["item_ids"] = item_ids
            existing["isolated_session"] = isolated_session
        else:
            tests.append({
                "id": test_id,
                "name": name,
                "description": description,
                "item_ids": item_ids,
                "isolated_session": isolated_session
            })
            
        self._write_json(self.tests_file, tests)

    def delete_test(self, test_id: str):
        tests = [t for t in self.get_tests() if t["id"] != test_id]
        self._write_json(self.tests_file, tests)

    # --- Variables ---
    def get_variables(self) -> Dict[str, str]:
        return self._read_json(self.variables_file)

    def save_variables(self, variables: Dict[str, str]):
        self._write_json(self.variables_file, variables)

    # --- Settings (Diagnose-Policy) ---
    def get_settings(self) -> Dict[str, Any]:
        """Einstellungen inkl. Defaults für alles, was nicht gespeichert ist."""
        stored = self._read_json(self.settings_file)
        if not isinstance(stored, dict):
            stored = {}

        settings = dict(DEFAULT_SETTINGS)
        settings["ignore_console"] = list(DEFAULT_SETTINGS["ignore_console"])
        settings["ignore_urls"] = list(DEFAULT_SETTINGS["ignore_urls"])
        settings.update(stored)

        # Sanitizing, damit eine handeditierte Datei nichts kaputt macht
        for key in ("console_policy", "network_policy"):
            if settings.get(key) not in POLICY_VALUES:
                settings[key] = DEFAULT_SETTINGS[key]
        for key in ("ignore_console", "ignore_urls"):
            value = settings.get(key)
            settings[key] = [str(p) for p in value if str(p).strip()] if isinstance(value, list) else []
        try:
            settings["check_timeout_ms"] = max(500, int(settings.get("check_timeout_ms", 5000)))
        except (TypeError, ValueError):
            settings["check_timeout_ms"] = DEFAULT_SETTINGS["check_timeout_ms"]
        settings["capture_console_warnings"] = bool(settings.get("capture_console_warnings", False))

        for key in ("trace_mode", "video_mode"):
            if settings.get(key) not in ARTIFACT_MODES:
                settings[key] = DEFAULT_SETTINGS[key]
        try:
            settings["keep_runs"] = max(0, int(settings.get("keep_runs", 20)))
        except (TypeError, ValueError):
            settings["keep_runs"] = DEFAULT_SETTINGS["keep_runs"]

        return settings

    def save_settings(self, settings: Dict[str, Any]):
        self._write_json(self.settings_file, settings)

    # --- Datasets ---
    def get_datasets(self) -> List[Dict[str, Any]]:
        """Scans datasets_dir for .csv datasets."""
        datasets = []
        if not os.path.exists(self.datasets_dir):
            return datasets

        for filename in sorted(os.listdir(self.datasets_dir)):
            if filename.endswith(".csv"):
                dataset_id = os.path.splitext(filename)[0]
                filepath = os.path.join(self.datasets_dir, filename)
                datasets.append({
                    "id": dataset_id,
                    "name": dataset_id.replace("_", " ").title(),
                    "filename": filename,
                    "filepath": filepath
                })
        return datasets

    def get_dataset_data(self, dataset_id: str) -> Tuple[List[str], List[List[str]], List[Dict[str, str]]]:
        """
        Reads CSV dataset file and returns (headers, row_lists, row_dicts).
        """
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', dataset_id.lower())
        filepath = os.path.join(self.datasets_dir, f"{safe_id}.csv")
        if not os.path.exists(filepath):
            return [], [], []

        headers = []
        rows = []
        row_dicts = []

        try:
            with open(filepath, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                lines = list(reader)
                if lines:
                    headers = [h.strip() for h in lines[0]]
                    for r in lines[1:]:
                        row_vals = [cell.strip() for cell in r]
                        rows.append(row_vals)
                        # Build dictionary
                        row_dict = {}
                        for idx, h in enumerate(headers):
                            row_dict[h] = row_vals[idx] if idx < len(row_vals) else ""
                        row_dicts.append(row_dict)
        except Exception:
            pass

        return headers, rows, row_dicts

    def save_dataset(self, dataset_id: str, headers: List[str], rows: List[List[str]]) -> str:
        """Saves headers and rows into CSV dataset file."""
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', dataset_id.lower())
        if not safe_id:
            safe_id = "dataset_1"

        filepath = os.path.join(self.datasets_dir, f"{safe_id}.csv")
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)

        return safe_id

    def delete_dataset(self, dataset_id: str):
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', dataset_id.lower())
        filepath = os.path.join(self.datasets_dir, f"{safe_id}.csv")
        if os.path.exists(filepath):
            os.remove(filepath)

