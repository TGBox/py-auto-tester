import os
import json
import re
from typing import Dict, List, Any, Optional

class ProjectManager:
    """Manages project data: Routines, Groups, Tests, and Variables."""
    def __init__(self, root_dir: str = "project_data"):
        self.root_dir = os.path.abspath(root_dir)
        self.routines_dir = os.path.join(self.root_dir, "routines")
        self.groups_file = os.path.join(self.root_dir, "groups.json")
        self.tests_file = os.path.join(self.root_dir, "tests.json")
        self.variables_file = os.path.join(self.root_dir, "variables.json")
        
        self.ensure_structure()

    def ensure_structure(self):
        """Ensure directories and default JSON files exist."""
        os.makedirs(self.routines_dir, exist_ok=True)
        
        if not os.path.exists(self.groups_file):
            self._write_json(self.groups_file, [])
            
        if not os.path.exists(self.tests_file):
            self._write_json(self.tests_file, [])
            
        if not os.path.exists(self.variables_file):
            self._write_json(self.variables_file, {
                "BASE_URL": "https://example.com",
                "USERNAME": "demo_user",
                "PASSWORD": "password123"
            })

    def _read_json(self, filepath: str) -> Any:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return [] if not filepath.endswith("variables.json") else {}

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

    def delete_routine(self, routine_id: str):
        filepath = os.path.join(self.routines_dir, f"{routine_id}.py")
        if os.path.exists(filepath):
            os.remove(filepath)
            
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
