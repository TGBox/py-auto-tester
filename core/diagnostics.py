"""
Passive Diagnose-Erfassung während der Testausführung.

Sammelt JS-Konsolenfehler, unbehandelte Seitenfehler (pageerror), fehlgeschlagene
Requests und HTTP-Antworten mit Status >= 400 — ohne den Testablauf zu verändern.
Die Bewertung (ignorieren / warnen / Failure) passiert erst in der Engine anhand
der konfigurierten Policy.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern

# Konsolen-Meldungen dieser Typen werden erfasst
CONSOLE_ERROR_TYPES = ("error",)
CONSOLE_WARNING_TYPES = ("warning",)

# Diese Status-Codes gelten nie als Fehler, auch wenn sie >= 400 sind
_NEVER_NETWORK_ERROR = (401, 403)  # oft legitimer Teil von Auth-Flows -> nur Warnung

# Chromium schreibt für jede fehlgeschlagene Ressource zusätzlich eine
# Konsolenmeldung. Die ist eine Dublette zu dem, was der response-/
# requestfailed-Listener schon sauber mit Status, Methode und URL erfasst —
# sonst zählt jeder 404 doppelt.
_RESOURCE_LOAD_NOISE = re.compile(
    r"^(failed to load resource|the resource .* was preloaded|net::err_)",
    re.IGNORECASE,
)

# URLs innerhalb eines Meldungstexts finden, um ignore_urls auch dort anzuwenden
_URL_IN_TEXT = re.compile(r"https?://[^\s'\"()]+", re.IGNORECASE)

# Nackte Objekt-Reprs sind keine Fehlermeldung, sondern ein Zeichen dafuer, dass
# das Event nicht die erwartete Form hatte. Landet sonst als Muell im Report.
_OBJECT_REPR = re.compile(r"^<.*\bobject at 0x[0-9a-fA-F]+>$")


@dataclass
class DiagnosticEntry:
    """Ein erfasstes Ereignis aus dem Browser."""
    kind: str                 # "console" | "pageerror" | "network"
    severity: str             # "error" | "warning"
    message: str
    location: str = ""
    status: Optional[int] = None
    method: str = ""
    url: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
            "status": self.status,
            "method": self.method,
            "url": self.url,
        }

    def short(self) -> str:
        if self.kind == "network":
            return f"{self.status} {self.method} {self.url}".strip()
        if self.location:
            return f"{self.message}  ({self.location})"
        return self.message


def _compile_patterns(patterns: Optional[List[str]]) -> List[Pattern]:
    """Kompiliert Ignore-Regexes; ungültige Muster werden übersprungen, nicht geworfen."""
    compiled = []
    for raw in patterns or []:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            compiled.append(re.compile(raw, re.IGNORECASE))
        except re.error:
            continue
    return compiled


class PageDiagnostics:
    """
    Hängt sich an Playwright-Pages und sammelt Auffälligkeiten ein.

    Bewusst tolerant: jede Ausnahme in einem Event-Handler wird verworfen, damit
    die Diagnose niemals einen Testlauf zum Absturz bringt.
    """

    def __init__(
        self,
        ignore_console: Optional[List[str]] = None,
        ignore_urls: Optional[List[str]] = None,
        capture_console_warnings: bool = False,
        capture_request_failures: bool = True,
        on_event: Optional[Callable[[DiagnosticEntry], None]] = None,
    ):
        self._ignore_console = _compile_patterns(ignore_console)
        self._ignore_urls = _compile_patterns(ignore_urls)
        self.capture_console_warnings = capture_console_warnings
        self.capture_request_failures = capture_request_failures
        self._on_event = on_event

        self.entries: List[DiagnosticEntry] = []
        self._attached_pages: List[Any] = []

    # ------------------------------------------------------------------ attach

    def attach(self, page: Any):
        """Registriert die Listener an einer Page (idempotent)."""
        if page is None or any(p is page for p in self._attached_pages):
            return
        self._attached_pages.append(page)

        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("response", self._on_response)
        if self.capture_request_failures:
            page.on("requestfailed", self._on_request_failed)

    def attach_context(self, context: Any):
        """Erfasst auch Popups / neue Tabs, die während des Tests aufgehen."""
        if context is None:
            return
        try:
            context.on("page", self.attach)
        except Exception:
            pass
        for page in getattr(context, "pages", []) or []:
            self.attach(page)

    # ------------------------------------------------------------------ record

    def _record(self, entry: DiagnosticEntry):
        self.entries.append(entry)
        if self._on_event:
            try:
                self._on_event(entry)
            except Exception:
                pass

    def _is_ignored_console(self, text: str) -> bool:
        return any(p.search(text) for p in self._ignore_console)

    def _is_ignored_url(self, url: str) -> bool:
        return bool(url) and any(p.search(url) for p in self._ignore_urls)

    def _is_ignored_anywhere(self, text: str, location: str = "") -> bool:
        """
        True, wenn der Eintrag unterdrückt werden soll — entweder weil der Text
        auf ein ignore_console-Muster passt, oder weil die Herkunft (bzw. eine
        URL im Text) auf ein ignore_urls-Muster passt. Eine ignorierte URL soll
        auch dann still sein, wenn sie als Konsolenmeldung auftaucht.
        """
        if self._is_ignored_console(text):
            return True
        if self._is_ignored_url(location):
            return True
        return any(self._is_ignored_url(u) for u in _URL_IN_TEXT.findall(text or ""))

    # ---------------------------------------------------------------- handlers

    def _on_console(self, msg: Any):
        try:
            msg_type = getattr(msg, "type", "") or ""
            if callable(msg_type):
                msg_type = msg_type()

            if msg_type in CONSOLE_ERROR_TYPES:
                severity = "error"
            elif msg_type in CONSOLE_WARNING_TYPES and self.capture_console_warnings:
                severity = "warning"
            else:
                return

            text = (getattr(msg, "text", "") or "").strip()
            if not text:
                return

            loc = getattr(msg, "location", None) or {}
            source_url = loc.get("url", "") if isinstance(loc, dict) else ""
            location = source_url
            if location and isinstance(loc, dict) and loc.get("lineNumber") is not None:
                location += f":{loc['lineNumber']}"

            # Dubletten zu Netzwerk-Befunden nicht doppelt zählen
            if _RESOURCE_LOAD_NOISE.match(text):
                return

            if self._is_ignored_anywhere(text, source_url):
                return

            self._record(DiagnosticEntry(
                kind="console", severity=severity, message=text, location=location
            ))
        except Exception:
            pass

    def _on_page_error(self, error: Any):
        try:
            message = (getattr(error, "message", None) or str(error) or "").strip()
            if not message or _OBJECT_REPR.match(message):
                return
            stack = getattr(error, "stack", "") or ""
            location = ""
            if stack:
                for line in str(stack).splitlines()[1:]:
                    line = line.strip()
                    if line:
                        location = line.lstrip("at ").strip()
                        break
            if self._is_ignored_anywhere(message, location):
                return
            self._record(DiagnosticEntry(
                kind="pageerror", severity="error",
                message=f"Unbehandelter JS-Fehler: {message}", location=location
            ))
        except Exception:
            pass

    def _on_response(self, response: Any):
        try:
            status = getattr(response, "status", None)
            if callable(status):
                status = status()
            if status is None or int(status) < 400:
                return
            status = int(status)

            url = getattr(response, "url", "") or ""
            if callable(url):
                url = url()
            if self._is_ignored_url(url):
                return

            method = ""
            request = getattr(response, "request", None)
            if request is not None:
                method = getattr(request, "method", "") or ""
                if callable(method):
                    method = method()

            severity = "warning" if status in _NEVER_NETWORK_ERROR else "error"
            self._record(DiagnosticEntry(
                kind="network", severity=severity,
                message=f"HTTP {status}", status=status,
                method=method, url=url,
            ))
        except Exception:
            pass

    def _on_request_failed(self, request: Any):
        try:
            url = getattr(request, "url", "") or ""
            if callable(url):
                url = url()
            if self._is_ignored_url(url):
                return

            failure = getattr(request, "failure", None)
            if callable(failure):
                failure = failure()
            reason = ""
            if isinstance(failure, dict):
                reason = failure.get("errorText", "")
            elif failure:
                reason = str(failure)

            # Vom Benutzer/Test abgebrochene Requests sind kein Befund
            if "ERR_ABORTED" in (reason or "").upper():
                return

            # Ohne URL und ohne Grund ist der Eintrag informationslos
            if not url and not reason:
                return

            method = getattr(request, "method", "") or ""
            if callable(method):
                method = method()

            self._record(DiagnosticEntry(
                kind="network", severity="warning",
                message=f"Request fehlgeschlagen: {reason or 'unbekannt'}",
                method=method, url=url,
            ))
        except Exception:
            pass

    # ------------------------------------------------------------------ access

    def take(self) -> List[DiagnosticEntry]:
        """Gibt die gesammelten Einträge zurück und leert den Puffer."""
        collected = self.entries
        self.entries = []
        return collected

    def reset(self):
        self.entries = []

    @staticmethod
    def split(entries: List[DiagnosticEntry]):
        """Teilt Einträge in (errors, warnings) anhand der severity."""
        errors = [e for e in entries if e.severity == "error"]
        warnings = [e for e in entries if e.severity != "error"]
        return errors, warnings

    @staticmethod
    def summarize(entries: List[DiagnosticEntry]) -> str:
        """Kurzfassung für Log- und Fehlermeldungen."""
        if not entries:
            return ""
        console = [e for e in entries if e.kind in ("console", "pageerror")]
        network = [e for e in entries if e.kind == "network"]
        parts = []
        if console:
            parts.append(f"{len(console)}x Konsole")
        if network:
            parts.append(f"{len(network)}x Netzwerk")
        return ", ".join(parts)
