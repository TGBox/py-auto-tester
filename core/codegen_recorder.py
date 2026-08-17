import os
import re
import subprocess
import tempfile
from typing import Optional, Tuple

class CodegenRecorder:
    """Manages spawning Playwright Codegen and formatting generated code."""

    @staticmethod
    def launch_codegen(url: str = "https://google.com") -> Tuple[Optional[str], str]:
        """
        Launches playwright codegen writing to a temporary file.
        Returns (recorded_code_snippet, error_message).
        """
        temp_file = os.path.join(tempfile.gettempdir(), "temp_playwright_rec.py")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

        cmd = ["playwright", "codegen", "-o", temp_file]
        if url and url.strip():
            cmd.append(url.strip())

        try:
            # Spawn playwright codegen and block until user closes browser
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if os.path.exists(temp_file):
                with open(temp_file, "r", encoding="utf-8") as f:
                    raw_code = f.read()
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
                
                snippet = CodegenRecorder.clean_code_to_routine(raw_code)
                return snippet, ""
            else:
                return None, "Keine Aufnahme gespeichert (Browser vor Interaktion geschlossen)."

        except subprocess.TimeoutExpired:
            return None, "Codegen Zeitüberschreitung (Timeout 10 Min)."
        except Exception as e:
            return None, f"Fehler beim Aufrufen von Playwright Codegen: {str(e)}"

    @staticmethod
    def clean_code_to_routine(raw_code: str) -> str:
        """
        Strips boilerplates (with sync_playwright(), browser = ..., context.close(), etc.)
        and formats Playwright statements into a modular function body.
        """
        lines = raw_code.splitlines()
        clean_lines = []
        in_run_fn = False
        
        for line in lines:
            stripped = line.strip()
            
            # Detect function body lines inside def run(...)
            if stripped.startswith("def run("):
                in_run_fn = True
                continue
                
            if in_run_fn:
                # Stop if closing or with block
                if stripped.startswith("context.close()") or stripped.startswith("browser.close()") or stripped.startswith("with sync_playwright()"):
                    break
                    
                # Skip setup boilerplates (browser = ..., context = ..., page = ...)
                if any(stripped.startswith(prefix) for prefix in [
                    "browser =", "context =", "page = browser.", "page = context.",
                    "# ---------------------"
                ]):
                    continue
                    
                if stripped:
                    clean_lines.append("    " + stripped)

        if not clean_lines:
            # Fallback if raw_code didn't match standard run function structure
            for line in lines:
                s = line.strip()
                if s and not s.startswith(("import ", "from ", "with ", "def ", "browser", "context", "playwright")):
                    clean_lines.append("    " + s)

        body = "\n".join(clean_lines) if clean_lines else "    # Keine Aktionen aufgenommen\n    pass"
        
        routine_template = (
            "def execute(page, vars):\n"
            "    \"\"\"Automatisch aufgenommene Routine.\"\"\"\n"
            f"{body}\n"
        )
        return routine_template
