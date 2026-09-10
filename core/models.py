"""
Datenmodelle für Ausführung und Ergebnis.

Bewusst frei von Qt und Playwright, damit Runner, CLI, Report und Tests
dieselben Typen benutzen können.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Tempo und Geräteprofile
# --------------------------------------------------------------------------- #

SPEED_MODES: Dict[str, int] = {
    "fastest": 0,
    "normal": 300,
    "slow": 1000,
    "step": 2500,
}

BROWSER_ENGINES = ("chromium", "firefox", "webkit")

DEVICE_PROFILES: Dict[str, Dict[str, Any]] = {
    "desktop_1080p": {"viewport": {"width": 1920, "height": 1080}},
    "desktop_768p": {"viewport": {"width": 1366, "height": 768}},
    "iphone_14": {
        "viewport": {"width": 390, "height": 844},
        "is_mobile": True,
        "has_touch": True,
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        ),
    },
    "pixel_7": {
        "viewport": {"width": 412, "height": 915},
        "is_mobile": True,
        "has_touch": True,
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
        ),
    },
    "ipad_air": {
        "viewport": {"width": 820, "height": 1180},
        "is_mobile": True,
        "has_touch": True,
    },
}

FALLBACK_VIEWPORT = {"viewport": {"width": 1280, "height": 720}}


def get_slow_mo_ms(speed_mode: str) -> int:
    return SPEED_MODES.get(speed_mode, 0)


def get_context_options(profile: str) -> Dict[str, Any]:
    """Playwright-Context-Optionen für ein Geräteprofil (Kopie, nie das Original)."""
    opts = DEVICE_PROFILES.get(profile, FALLBACK_VIEWPORT)
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in opts.items()}


# --------------------------------------------------------------------------- #
# Konfiguration eines Laufs
# --------------------------------------------------------------------------- #

@dataclass
class RunConfig:
    """Alles, was einen Lauf beschreibt — unabhängig davon, wer ihn startet."""
    mode: str                       # "routine" | "group" | "test"
    item_id: str
    headed: bool = True
    speed_mode: str = "fastest"
    auto_close: bool = True
    browser_engine: str = "chromium"
    device_profile: str = "desktop_1080p"
    dataset_id: Optional[str] = None

    # Ausführungsverhalten
    stop_on_first_failure: bool = False
    action_timeout_ms: int = 15000

    def __post_init__(self):
        self.browser_engine = (self.browser_engine or "chromium").lower()
        if self.browser_engine not in BROWSER_ENGINES:
            self.browser_engine = "chromium"
        if self.speed_mode not in SPEED_MODES:
            self.speed_mode = "fastest"
        try:
            self.action_timeout_ms = max(500, int(self.action_timeout_ms))
        except (TypeError, ValueError):
            self.action_timeout_ms = 15000

    @property
    def slow_mo_ms(self) -> int:
        return get_slow_mo_ms(self.speed_mode)

    def context_options(self) -> Dict[str, Any]:
        return get_context_options(self.device_profile)


# --------------------------------------------------------------------------- #
# Ergebnisse
# --------------------------------------------------------------------------- #

@dataclass
class StepResult:
    """Ergebnis einer ausgeführten Routine (ein Schritt eines Laufs)."""
    name: str
    routine_id: str = ""
    status: str = "PASS"                    # "PASS" | "FAIL" | "SKIPPED"
    duration: float = 0.0
    error: str = ""
    screenshot: str = ""
    trace: str = ""                          # Pfad zur trace.zip dieses Schritts
    url: str = ""
    dataset_row: int = 0
    checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def checks_passed(self) -> int:
        return sum(1 for c in self.checks if c.get("status") == "PASS")

    @property
    def checks_failed(self) -> int:
        return sum(1 for c in self.checks if c.get("status") == "FAIL")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "routine_id": self.routine_id,
            "status": self.status,
            "duration": self.duration,
            "error": self.error,
            "screenshot": self.screenshot,
            "trace": self.trace,
            "url": self.url,
            "dataset_row": self.dataset_row,
            "checks": list(self.checks),
            "warnings": list(self.warnings),
        }


@dataclass
class RunResult:
    """Gesamtergebnis eines Laufs."""
    config: Optional[RunConfig] = None
    steps: List[StepResult] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    duration: float = 0.0
    cancelled: bool = False
    system_error: str = ""
    report_path: str = ""

    # Artefakte des Laufs
    artifacts_dir: str = ""
    videos: List[str] = field(default_factory=list)

    # ---- abgeleitete Zahlen -------------------------------------------------

    @property
    def passed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "PASS")

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "FAIL")

    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "SKIPPED")

    @property
    def checks_passed(self) -> int:
        return sum(s.checks_passed for s in self.steps)

    @property
    def checks_failed(self) -> int:
        return sum(s.checks_failed for s in self.steps)

    @property
    def warnings_count(self) -> int:
        return sum(len(s.warnings) for s in self.steps)

    @property
    def success(self) -> bool:
        return (
            self.failed_count == 0
            and not self.cancelled
            and not self.system_error
            and bool(self.steps)
        )

    @property
    def summary(self) -> str:
        if self.system_error:
            return f"Systemfehler: {self.system_error}"
        if not self.steps:
            return "Keine Routinen in der Ausführungssequenz."

        parts = [
            f"Ausführung beendet in {self.duration:.2f}s",
            f"Erfolgreich: {self.passed_count}",
            f"Fehlgeschlagen: {self.failed_count}",
        ]
        if self.skipped_count:
            parts.append(f"Übersprungen: {self.skipped_count}")
        if self.checks_passed or self.checks_failed:
            parts.append(
                f"Erwartungen: {self.checks_passed} erfüllt, {self.checks_failed} nicht erfüllt"
            )
        if self.warnings_count:
            parts.append(f"Warnungen: {self.warnings_count}")
        if self.cancelled:
            parts.append("ABGEBROCHEN")
        return " | ".join(parts)

    def step_dicts(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self.steps]

    def to_dict(self) -> Dict[str, Any]:
        cfg = self.config
        return {
            "target": cfg.item_id if cfg else "",
            "mode": cfg.mode if cfg else "",
            "browser_engine": cfg.browser_engine if cfg else "",
            "device_profile": cfg.device_profile if cfg else "",
            "speed_mode": cfg.speed_mode if cfg else "",
            "dataset_id": cfg.dataset_id if cfg else None,
            "success": self.success,
            "cancelled": self.cancelled,
            "system_error": self.system_error,
            "duration": self.duration,
            "counts": {
                "passed": self.passed_count,
                "failed": self.failed_count,
                "skipped": self.skipped_count,
                "checks_passed": self.checks_passed,
                "checks_failed": self.checks_failed,
                "warnings": self.warnings_count,
            },
            "summary": self.summary,
            "report_path": self.report_path,
            "artifacts_dir": self.artifacts_dir,
            "videos": list(self.videos),
            "steps": self.step_dicts(),
        }
