"""
Erwartungen (Assertions) für Routinen.

Zwei Wege führen hier zusammen:

* Code-API   — 'check()', 'require()' und 'step()' im Routine-Namespace,
               für alles, was sich nur in Python ausdrücken lässt.
* Deklarativ — eine Liste anklickbarer Erwartungen pro Routine, gespeichert
               als <routine>.checks.json, ausgewertet nach dem Snippet.

Beide erzeugen dieselben CheckResult-Objekte, damit Runner und Report nicht
zwischen den Quellen unterscheiden müssen.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_CHECK_TIMEOUT_MS = 5000


# ---------------------------------------------------------------------------
# Ergebnis-Modell
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    label: str
    status: str                 # "PASS" | "FAIL"
    kind: str = "code"          # "code" | "declarative" | "diagnostics"
    message: str = ""
    duration: float = 0.0
    step: str = ""              # optionaler step()-Kontext

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "kind": self.kind,
            "message": self.message,
            "duration": self.duration,
            "step": self.step,
        }


class CheckRecorder:
    """
    Sammelt Erwartungs-Ergebnisse einer Routine.

    'check()' ist weich: es protokolliert einen Fehlschlag und lässt die Routine
    weiterlaufen, damit ein Lauf alle Probleme auf einmal zeigt statt nur das
    erste. 'require()' bricht hart ab (AssertionError).
    """

    def __init__(self, log: Optional[Any] = None):
        self.results: List[CheckResult] = []
        self._log = log
        self._step_stack: List[str] = []

    # -- Kontext ----------------------------------------------------------

    @property
    def current_step(self) -> str:
        return " > ".join(self._step_stack)

    def push_step(self, label: str):
        self._step_stack.append(label)

    def pop_step(self):
        if self._step_stack:
            self._step_stack.pop()

    # -- Aufzeichnung -----------------------------------------------------

    def record(self, label: str, ok: bool, kind: str = "code",
               message: str = "", duration: float = 0.0) -> CheckResult:
        result = CheckResult(
            label=label,
            status="PASS" if ok else "FAIL",
            kind=kind,
            message=message,
            duration=duration,
            step=self.current_step,
        )
        self.results.append(result)
        if self._log:
            prefix = "  [CHECK OK]" if ok else "  [CHECK FEHLGESCHLAGEN]"
            where = f" ({result.step})" if result.step else ""
            detail = f" -> {message}" if message and not ok else ""
            self._log(f"{prefix} {label}{where}{detail}")
        return result

    # -- Auswertung -------------------------------------------------------

    @property
    def failed(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    def failure_summary(self) -> str:
        if not self.failed:
            return ""
        lines = [f"{self.failed_count} Erwartung(en) nicht erfüllt:"]
        for r in self.failed:
            where = f" [{r.step}]" if r.step else ""
            lines.append(f"  - {r.label}{where}")
            if r.message:
                # Playwright-Meldungen sind mehrzeilig — jede Zeile einrücken,
                # sonst bricht die Einrückung in Log, CLI und Report auf.
                for msg_line in str(r.message).splitlines():
                    lines.append(f"      {msg_line}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Code-API, die in den Routine-Namespace injiziert wird
# ---------------------------------------------------------------------------

class _StepContext:
    def __init__(self, recorder: CheckRecorder, label: str, log=None):
        self.recorder = recorder
        self.label = label
        self._log = log
        self._start = 0.0

    def __enter__(self):
        self._start = time.time()
        self.recorder.push_step(self.label)
        if self._log:
            self._log(f"  [SCHRITT] {self.label} ...")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.recorder.pop_step()
        if self._log:
            elapsed = time.time() - self._start
            if exc_type is None:
                self._log(f"  [SCHRITT] {self.label} ✓ ({elapsed:.2f}s)")
            else:
                self._log(f"  [SCHRITT] {self.label} ✗ ({elapsed:.2f}s)")
        return False  # Exceptions nicht unterdrücken


def build_check_api(recorder: CheckRecorder, log=None) -> Dict[str, Any]:
    """Erzeugt die Helfer, die einer Routine als Globals mitgegeben werden."""

    def check(condition: Any, label: str = "", message: str = "") -> bool:
        """Weiche Erwartung: protokolliert und läuft weiter."""
        ok = bool(condition)
        recorder.record(label or "Erwartung", ok, kind="code", message=message)
        return ok

    def require(condition: Any, label: str = "", message: str = ""):
        """Harte Erwartung: bricht die Routine bei Fehlschlag ab."""
        ok = bool(condition)
        recorder.record(label or "Erwartung", ok, kind="code", message=message)
        if not ok:
            raise AssertionError(label or "Erwartung nicht erfüllt")

    def step(label: str) -> _StepContext:
        return _StepContext(recorder, label, log=log)

    return {"check": check, "require": require, "step": step}


# ---------------------------------------------------------------------------
# Deklarative Erwartungen (GUI)
# ---------------------------------------------------------------------------

# Jeder Typ beschreibt sich selbst, damit die GUI die Eingabefelder ohne
# Sonderfälle rendern kann.
CHECK_TYPES: Dict[str, Dict[str, Any]] = {
    "element_visible": {
        "label": "Element ist sichtbar",
        "target": "Selektor",
        "value": None,
        "hint": 'z.B. role=link[name="Terminplaner"], text=Speichern, #login-form',
    },
    "element_hidden": {
        "label": "Element ist nicht sichtbar",
        "target": "Selektor",
        "value": None,
        "hint": 'z.B. .spinner, text=Wird geladen',
    },
    "element_count": {
        "label": "Anzahl Elemente ist",
        "target": "Selektor",
        "value": "Anzahl",
        "hint": 'Selektor + erwartete Anzahl, z.B. "tr.patient" und 5',
    },
    "text_present": {
        "label": "Text ist auf der Seite",
        "target": None,
        "value": "Text",
        "hint": "Sichtbarer Text, z.B. Terminplaner",
    },
    "text_absent": {
        "label": "Text ist NICHT auf der Seite",
        "target": None,
        "value": "Text",
        "hint": "z.B. Fehler, Zugriff verweigert",
    },
    "url_contains": {
        "label": "URL enthält",
        "target": None,
        "value": "Teilstring",
        "hint": "z.B. /aldashboard/home",
    },
    "url_matches": {
        "label": "URL passt auf Regex",
        "target": None,
        "value": "Regex",
        "hint": r"z.B. /patient/\d+$",
    },
    "title_contains": {
        "label": "Seitentitel enthält",
        "target": None,
        "value": "Teilstring",
        "hint": "Inhalt von <title>",
    },
    "input_value": {
        "label": "Feld hat Wert",
        "target": "Selektor",
        "value": "Erwarteter Wert",
        "hint": 'z.B. role=textbox[name="E-Mail"] und admin@demo.de',
    },
    "attribute_equals": {
        "label": "Attribut hat Wert",
        "target": "Selektor",
        "value": "attribut=wert",
        "hint": 'z.B. #submit und disabled=true',
    },
    "no_console_errors": {
        "label": "Keine JS-Konsolenfehler",
        "target": None,
        "value": None,
        "hint": "Wertet die erfassten Konsolenfehler dieses Schritts aus",
    },
    "no_http_errors": {
        "label": "Keine HTTP-Fehler (4xx/5xx)",
        "target": None,
        "value": None,
        "hint": "Wertet die erfassten Netzwerkfehler dieses Schritts aus",
    },
}

DIAGNOSTIC_CHECK_TYPES = ("no_console_errors", "no_http_errors")


def new_check(check_type: str = "element_visible") -> Dict[str, Any]:
    """Vorlage für eine neue Erwartung (GUI 'Hinzufügen')."""
    return {"type": check_type, "target": "", "value": "", "enabled": True}


def describe_check(check: Dict[str, Any]) -> str:
    """Menschenlesbare Kurzform, wie sie in Log und Report erscheint."""
    ctype = check.get("type", "")
    spec = CHECK_TYPES.get(ctype)
    if not spec:
        return f"Unbekannte Erwartung '{ctype}'"

    parts = [spec["label"]]
    target = (check.get("target") or "").strip()
    value = (check.get("value") or "").strip()

    if spec["target"] and target:
        parts.append(f"'{target}'")
    if spec["value"] and value:
        parts.append(f"= '{value}'" if spec["target"] else f"'{value}'")
    return " ".join(parts)


def _resolve_locator(page: Any, target: str):
    """
    Wandelt eine Selektor-Eingabe in einen Locator.
    Unterstützt Playwright-Selektor-Engines (role=, text=, css=, xpath=) direkt.
    """
    return page.locator(target)


def evaluate_check(
    check: Dict[str, Any],
    page: Any,
    diagnostics_entries: Optional[List[Any]] = None,
    timeout_ms: int = DEFAULT_CHECK_TIMEOUT_MS,
) -> CheckResult:
    """
    Wertet eine einzelne deklarative Erwartung aus.
    Wirft nie — ein Fehler bei der Auswertung ist ein FAIL mit Begründung.
    """
    from playwright.sync_api import expect as pw_expect

    label = describe_check(check)
    ctype = check.get("type", "")
    target = (check.get("target") or "").strip()
    value = (check.get("value") or "").strip()
    start = time.time()

    def done(ok: bool, message: str = "") -> CheckResult:
        return CheckResult(
            label=label,
            status="PASS" if ok else "FAIL",
            kind="declarative",
            message=message,
            duration=time.time() - start,
        )

    spec = CHECK_TYPES.get(ctype)
    if not spec:
        return done(False, f"Unbekannter Erwartungstyp '{ctype}'")

    # Pflichtfelder prüfen, bevor der Browser befragt wird
    if spec["target"] and not target:
        return done(False, f"Feld '{spec['target']}' ist leer")
    if spec["value"] and not value:
        return done(False, f"Feld '{spec['value']}' ist leer")

    try:
        # --- Diagnose-basierte Erwartungen (kein Seitenzugriff nötig)
        if ctype in DIAGNOSTIC_CHECK_TYPES:
            entries = diagnostics_entries or []
            if ctype == "no_console_errors":
                hits = [e for e in entries
                        if e.kind in ("console", "pageerror") and e.severity == "error"]
            else:
                hits = [e for e in entries if e.kind == "network" and e.severity == "error"]
            if hits:
                detail = "; ".join(h.short() for h in hits[:5])
                if len(hits) > 5:
                    detail += f" ... (+{len(hits) - 5} weitere)"
                return done(False, f"{len(hits)} Befund(e): {detail}")
            return done(True)

        # --- Seiten-basierte Erwartungen
        if ctype == "element_visible":
            pw_expect(_resolve_locator(page, target).first).to_be_visible(timeout=timeout_ms)
            return done(True)

        if ctype == "element_hidden":
            pw_expect(_resolve_locator(page, target).first).to_be_hidden(timeout=timeout_ms)
            return done(True)

        if ctype == "element_count":
            try:
                expected = int(value)
            except ValueError:
                return done(False, f"'{value}' ist keine ganze Zahl")
            pw_expect(_resolve_locator(page, target)).to_have_count(expected, timeout=timeout_ms)
            return done(True)

        if ctype == "text_present":
            pw_expect(page.get_by_text(value).first).to_be_visible(timeout=timeout_ms)
            return done(True)

        if ctype == "text_absent":
            pw_expect(page.get_by_text(value)).to_have_count(0, timeout=timeout_ms)
            return done(True)

        if ctype == "url_contains":
            page.wait_for_url(lambda url: value in url, timeout=timeout_ms)
            return done(True)

        if ctype == "url_matches":
            try:
                pattern = re.compile(value)
            except re.error as e:
                return done(False, f"Ungültiger Regex: {e}")
            page.wait_for_url(lambda url: bool(pattern.search(url)), timeout=timeout_ms)
            return done(True)

        if ctype == "title_contains":
            pw_expect(page).to_have_title(re.compile(re.escape(value)), timeout=timeout_ms)
            return done(True)

        if ctype == "input_value":
            pw_expect(_resolve_locator(page, target).first).to_have_value(value, timeout=timeout_ms)
            return done(True)

        if ctype == "attribute_equals":
            if "=" not in value:
                return done(False, "Wert muss die Form 'attribut=wert' haben")
            attr, expected = value.split("=", 1)
            pw_expect(_resolve_locator(page, target).first).to_have_attribute(
                attr.strip(), expected.strip(), timeout=timeout_ms
            )
            return done(True)

        return done(False, f"Erwartungstyp '{ctype}' ist nicht implementiert")

    except Exception as e:
        # Playwright-Assertion-Fehler sind sehr gesprächig -> auf das Wesentliche kürzen
        message = str(e).strip()
        first_block = message.split("\nCall log:")[0].strip()
        actual = ""
        for line in message.splitlines():
            line = line.strip()
            if line.startswith(("Actual value:", "unexpected value")):
                actual = line
                break
        detail = first_block if first_block else type(e).__name__
        if actual and actual not in detail:
            detail = f"{detail} | {actual}"
        return done(False, detail[:600])


def evaluate_checks(
    checks: List[Dict[str, Any]],
    page: Any,
    diagnostics_entries: Optional[List[Any]] = None,
    timeout_ms: int = DEFAULT_CHECK_TIMEOUT_MS,
    log: Optional[Any] = None,
) -> List[CheckResult]:
    """Wertet alle aktivierten Erwartungen einer Routine aus."""
    results: List[CheckResult] = []
    for check in checks or []:
        if not check.get("enabled", True):
            continue
        result = evaluate_check(check, page, diagnostics_entries, timeout_ms)
        results.append(result)
        if log:
            prefix = "  [CHECK OK]" if result.passed else "  [CHECK FEHLGESCHLAGEN]"
            detail = f" -> {result.message}" if result.message and not result.passed else ""
            log(f"{prefix} {result.label}{detail}")
    return results
