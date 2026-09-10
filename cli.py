#!/usr/bin/env python
"""
Kommandozeilen-Einstieg für py-auto-tester — für CI, Nightly-Läufe und
Aufgabenplaner. Braucht kein Qt und kein Display.

    python cli.py list
    python cli.py run login_flow --headless --junit-xml ergebnisse.xml
    python cli.py run demo_login --mode routine --dataset demo_users

Exit-Codes:
    0  alles bestanden
    1  mindestens ein Schritt fehlgeschlagen
    2  Aufruffehler (Ziel unbekannt, ungültige Option)
    3  Systemfehler während der Ausführung
    130 abgebrochen (Strg+C)
"""

import argparse
import json
import os
import signal
import sys

from core.project_manager import ProjectManager
from core.models import RunConfig, RunResult, SPEED_MODES, BROWSER_ENGINES, DEVICE_PROFILES
from core.runner import TestRunner, RunnerListener
from core import junit_report

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_SYSTEM = 3
EXIT_CANCELLED = 130


# --------------------------------------------------------------------------- #
# Ausgabe
# --------------------------------------------------------------------------- #

class ConsoleListener(RunnerListener):
    """Schreibt den Verlauf nach stdout — kompakt oder ausführlich."""

    def __init__(self, verbose: bool = False, quiet: bool = False):
        self.verbose = verbose
        self.quiet = quiet
        self._index = 0
        self._total = 0

    def on_log(self, message):
        if self.verbose and not self.quiet:
            print(message, flush=True)

    def on_progress(self, current, total):
        self._total = total

    def on_step_result(self, result):
        if self.quiet:
            return
        self._index += 1
        status = result.get("status", "")
        icon = {"PASS": "PASS", "FAIL": "FAIL", "SKIPPED": "SKIP"}.get(status, status)

        checks = result.get("checks") or []
        n_ok = sum(1 for c in checks if c.get("status") == "PASS")
        n_bad = len(checks) - n_ok
        extra = []
        if checks:
            extra.append(f"{n_ok} ok" + (f", {n_bad} nicht erfüllt" if n_bad else ""))
        if result.get("warnings"):
            extra.append(f"{len(result['warnings'])} Warnung(en)")
        suffix = f"   [{', '.join(extra)}]" if extra else ""

        counter = f"[{self._index}/{self._total}]" if self._total else f"[{self._index}]"
        name = result.get("name", "")
        dots = "." * max(3, 42 - len(name))
        print(f"  {counter} {name} {dots} {icon}  {result.get('duration', 0):.2f}s{suffix}",
              flush=True)

        # Fehlerdetails immer zeigen, auch ohne --verbose
        if status == "FAIL" and result.get("error"):
            for line in result["error"].splitlines():
                print(f"        {line}", flush=True)


def print_summary(result: RunResult, quiet: bool = False):
    if quiet:
        return
    print()
    print("  " + result.summary)
    if result.artifacts_dir:
        print(f"  Artefakte: {result.artifacts_dir}")
    if result.report_path:
        print(f"  Report: {result.report_path}")

    traces = [s.trace for s in result.steps if s.trace]
    if traces:
        print(f"  Traces: {len(traces)} — ansehen mit: "
              f"npx playwright show-trace \"{traces[0]}\"")
    if result.videos:
        print(f"  Videos: {len(result.videos)}")


# --------------------------------------------------------------------------- #
# Unterbefehle
# --------------------------------------------------------------------------- #

def cmd_list(args) -> int:
    pm = ProjectManager(args.project)

    tests = pm.get_tests()
    groups = pm.get_groups()
    routines = pm.get_routines()
    datasets = pm.get_datasets()

    print(f"Projekt: {pm.root_dir}\n")

    print(f"TESTS ({len(tests)})")
    for t in tests:
        print(f"  {t['id']:<28} {t.get('name', '')}  [{len(t.get('item_ids', []))} Element(e)]")
    if not tests:
        print("  (keine)")

    print(f"\nGRUPPEN ({len(groups)})")
    for g in groups:
        print(f"  {g['id']:<28} {g.get('name', '')}  [{len(g.get('routine_ids', []))} Routine(n)]")
    if not groups:
        print("  (keine)")

    print(f"\nROUTINEN ({len(routines)})")
    for r in routines:
        n_checks = len(pm.get_routine_checks(r["id"]))
        checks = f"  [{n_checks} Erwartung(en)]" if n_checks else ""
        print(f"  {r['id']:<28} {r.get('name', '')}{checks}")
    if not routines:
        print("  (keine)")

    print(f"\nDATENSÄTZE ({len(datasets)})")
    for d in datasets:
        print(f"  {d['id']:<28} {d.get('name', '')}")
    if not datasets:
        print("  (keine)")

    return EXIT_OK


def _resolve_mode(pm: ProjectManager, item_id: str, mode: str):
    """Findet heraus, ob item_id ein Test, eine Gruppe oder eine Routine ist."""
    if mode != "auto":
        return mode, None

    if any(t["id"] == item_id for t in pm.get_tests()):
        return "test", None
    if any(g["id"] == item_id for g in pm.get_groups()):
        return "group", None
    if any(r["id"] == item_id for r in pm.get_routines()):
        return "routine", None

    known = (
        [f"test:{t['id']}" for t in pm.get_tests()]
        + [f"group:{g['id']}" for g in pm.get_groups()]
        + [f"routine:{r['id']}" for r in pm.get_routines()]
    )
    hint = "\n  ".join(known) if known else "(Projekt ist leer)"
    return None, f"'{item_id}' ist weder Test, Gruppe noch Routine.\nVerfügbar:\n  {hint}"


def cmd_run(args) -> int:
    pm = ProjectManager(args.project)

    mode, error = _resolve_mode(pm, args.target, args.mode)
    if error:
        print(f"Fehler: {error}", file=sys.stderr)
        return EXIT_USAGE

    if args.dataset and not any(d["id"] == args.dataset for d in pm.get_datasets()):
        available = ", ".join(d["id"] for d in pm.get_datasets()) or "(keine)"
        print(f"Fehler: Datensatz '{args.dataset}' existiert nicht. Verfügbar: {available}",
              file=sys.stderr)
        return EXIT_USAGE

    # Policy-Overrides für diesen Lauf (ohne die Projektdatei zu ändern)
    settings_override = {}
    if args.console_policy:
        settings_override["console_policy"] = args.console_policy
    if args.network_policy:
        settings_override["network_policy"] = args.network_policy
    if args.trace:
        settings_override["trace_mode"] = args.trace
    if args.video:
        settings_override["video_mode"] = args.video
    if args.keep_runs is not None:
        settings_override["keep_runs"] = args.keep_runs

    config = RunConfig(
        mode=mode,
        item_id=args.target,
        headed=not args.headless,
        speed_mode=args.speed,
        auto_close=True,
        browser_engine=args.browser,
        device_profile=args.device,
        dataset_id=args.dataset,
        stop_on_first_failure=args.stop_on_first_failure,
        action_timeout_ms=args.timeout,
    )

    listener = ConsoleListener(verbose=args.verbose, quiet=args.quiet)
    runner = TestRunner(pm, config, listener=listener)
    runner.settings.update(settings_override)

    # Strg+C soll sauber abbrechen, nicht mitten in Playwright abstürzen
    def handle_sigint(_sig, _frame):
        print("\n  Abbruch angefordert, beende laufenden Schritt...", flush=True)
        runner.cancel()

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except (ValueError, OSError):
        pass  # z.B. in einem Nicht-Haupt-Thread

    if not args.quiet:
        print(f"Lauf: {mode} '{args.target}'  ({config.browser_engine}, "
              f"{'headless' if args.headless else 'headed'}, {config.device_profile})")
        if args.dataset:
            print(f"Datensatz: {args.dataset}")
        print()

    result = runner.run()

    print_summary(result, args.quiet)

    if args.junit_xml:
        path = junit_report.write(result, args.junit_xml)
        if not args.quiet:
            print(f"  JUnit-XML: {path}")

    if args.json:
        payload = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
        if args.json == "-":
            print(payload)
        else:
            parent = os.path.dirname(os.path.abspath(args.json))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(args.json, "w", encoding="utf-8") as f:
                f.write(payload)
            if not args.quiet:
                print(f"  JSON: {args.json}")

    if result.system_error:
        return EXIT_SYSTEM
    if result.cancelled:
        return EXIT_CANCELLED
    return EXIT_OK if result.success else EXIT_FAILED


# --------------------------------------------------------------------------- #
# Argumente
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py-auto-tester",
        description="Playwright-Testsuiten ohne GUI ausführen (für CI und Nightly-Läufe).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  python cli.py list\n"
            "  python cli.py run login_flow --headless --junit-xml ergebnisse.xml\n"
            "  python cli.py run demo_login --mode routine --dataset demo_users -v\n"
            "  python cli.py run nightly --headless --console-policy fail\n"
        ),
    )
    parser.add_argument("--project", default="project_data",
                        help="Projektordner (Standard: project_data)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Tests, Gruppen, Routinen und Datensätze anzeigen")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="Test, Gruppe oder Routine ausführen")
    p_run.add_argument("target", help="ID eines Tests, einer Gruppe oder einer Routine")
    p_run.add_argument("--mode", choices=["auto", "test", "group", "routine"], default="auto",
                       help="Was das Ziel ist (Standard: automatisch erkennen)")
    p_run.add_argument("--headless", action="store_true",
                       help="Ohne sichtbares Browserfenster (für CI empfohlen)")
    p_run.add_argument("--browser", choices=list(BROWSER_ENGINES), default="chromium")
    p_run.add_argument("--device", choices=list(DEVICE_PROFILES), default="desktop_1080p")
    p_run.add_argument("--speed", choices=list(SPEED_MODES), default="fastest")
    p_run.add_argument("--dataset", default=None, help="CSV-Datensatz für iterative Läufe")
    p_run.add_argument("--timeout", type=int, default=15000,
                       help="Timeout je Playwright-Aktion in ms (Standard: 15000)")
    p_run.add_argument("--stop-on-first-failure", action="store_true",
                       help="Nach dem ersten Fehler abbrechen statt weiterzulaufen")
    p_run.add_argument("--console-policy", choices=["log", "warn", "fail"], default=None,
                       help="Umgang mit JS-Konsolenfehlern (überschreibt die Projekteinstellung)")
    p_run.add_argument("--network-policy", choices=["log", "warn", "fail"], default=None,
                       help="Umgang mit HTTP-Fehlern (überschreibt die Projekteinstellung)")
    p_run.add_argument("--trace", choices=["off", "on_failure", "always"], default=None,
                       help="Playwright-Trace aufzeichnen (überschreibt die Projekteinstellung)")
    p_run.add_argument("--video", choices=["off", "on_failure", "always"], default=None,
                       help="Video aufzeichnen (eine Aufnahme pro Browser-Session)")
    p_run.add_argument("--keep-runs", type=int, default=None, metavar="N",
                       help="Nur die neuesten N Laufverzeichnisse behalten (0 = alle)")
    p_run.add_argument("--junit-xml", default=None, metavar="DATEI",
                       help="JUnit-XML zusätzlich hierhin schreiben (liegt immer im Laufordner)")
    p_run.add_argument("--json", default=None, metavar="DATEI",
                       help="Ergebnis als JSON schreiben ('-' für stdout)")
    p_run.add_argument("-v", "--verbose", action="store_true",
                       help="Vollständiges Ausführungsprotokoll zeigen")
    p_run.add_argument("-q", "--quiet", action="store_true",
                       help="Nur über den Exit-Code berichten")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return EXIT_CANCELLED


if __name__ == "__main__":
    sys.exit(main())
