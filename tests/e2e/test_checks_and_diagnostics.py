"""
Erwartungen und Diagnose gegen einen echten Browser.

Deckt ab: Code-API (check/require/step/log), deklarative Erwartungen aus der
GUI, Konsolen- und Netzwerkerfassung sowie die drei Policy-Stufen.
"""

import os

import pytest

from .conftest import run_target


# --------------------------------------------------------------------------- #
# Projekt mit allen Fällen
# --------------------------------------------------------------------------- #

def build_project(pm, base, **settings):
    if settings:
        current = pm.get_settings()
        current.update(settings)
        pm.save_settings(current)

    pm.save_variables({"BASE_URL": f"{base}/index.html",
                       "USERNAME": "admin@demo.de", "PASSWORD": "geheim"})

    # 1) Alles korrekt: Code-API und GUI-Erwartungen zusammen
    pm.save_routine("login_ok", "Login Ok", "", f"""
def execute(page, vars):
    page.goto(vars['BASE_URL'])
    with step('Anmeldung'):
        page.get_by_label('E-Mail').fill(vars['USERNAME'])
        page.get_by_label('Passwort').fill(vars['PASSWORD'])
        check(page.get_by_role('button').count() == 1, 'Genau ein Anmelde-Button')
        page.get_by_role('button').filter(has_text='check').click()
    log('Login abgeschickt')
    check(page.url.endswith('home.html'), 'Landet auf der Startseite')
    expect(page.get_by_role('link', name='Terminplaner')).to_be_visible()
""")
    pm.save_routine_checks("login_ok", [
        {"type": "element_visible", "target": 'role=link[name="Terminplaner"]',
         "value": "", "enabled": True},
        {"type": "url_contains", "target": "", "value": "home.html", "enabled": True},
        {"type": "text_present", "target": "", "value": "Willkommen", "enabled": True},
        {"type": "text_absent", "target": "", "value": "Zugriff verweigert", "enabled": True},
        {"type": "element_count", "target": "li.patient", "value": "3", "enabled": True},
        {"type": "title_contains", "target": "", "value": "Startseite", "enabled": True},
        {"type": "input_value", "target": "#filter", "value": "alle", "enabled": True},
        {"type": "attribute_equals", "target": "#submit", "value": "disabled=true",
         "enabled": True},
        {"type": "no_console_errors", "target": "", "value": "", "enabled": True},
        {"type": "no_http_errors", "target": "", "value": "", "enabled": True},
        # Deaktiviert -> muss übersprungen werden
        {"type": "element_hidden", "target": "#gibtesnicht", "value": "", "enabled": False},
    ])

    # 2) Code läuft, GUI-Erwartung trifft nicht zu
    pm.save_routine("gui_check_fails", "Gui Check Fails", "", f"""
def execute(page, vars):
    page.goto("{base}/home.html")
""")
    pm.save_routine_checks("gui_check_fails", [
        {"type": "element_visible", "target": 'role=link[name="Rechnungen"]',
         "value": "", "enabled": True},
        {"type": "text_present", "target": "", "value": "Willkommen", "enabled": True},
    ])

    # 3) Weiches check() schlägt fehl, Routine läuft weiter
    pm.save_routine("soft_check_fails", "Soft Check Fails", "", f"""
def execute(page, vars):
    page.goto("{base}/home.html")
    check(1 == 2, 'Eins ist zwei')
    check(True, 'Diese stimmt')
    log('nach den Checks noch am Leben')
""")

    # 4) Seite mit JS-Fehlern und 404
    pm.save_routine("noisy_page", "Noisy Page", "", f"""
def execute(page, vars):
    page.goto("{base}/noisy.html")
    page.wait_for_timeout(500)
""")

    # 5) Dieselbe Seite mit Diagnose-Erwartungen
    pm.save_routine("noisy_with_check", "Noisy With Check", "", f"""
def execute(page, vars):
    page.goto("{base}/noisy.html")
    page.wait_for_timeout(500)
""")
    pm.save_routine_checks("noisy_with_check", [
        {"type": "no_console_errors", "target": "", "value": "", "enabled": True},
        {"type": "no_http_errors", "target": "", "value": "", "enabled": True},
    ])

    # 6) require() bricht hart ab
    pm.save_routine("hard_require", "Hard Require", "", f"""
def execute(page, vars):
    page.goto("{base}/home.html")
    require(False, 'Abbruchbedingung')
    log('DIESE ZEILE DARF NIE LAUFEN')
""")

    pm.save_group("alle", "Alle", "", [
        "login_ok", "gui_check_fails", "soft_check_fails",
        "noisy_page", "noisy_with_check", "hard_require",
    ])
    pm.save_test("e2e", "E2E", "", ["group:alle"], isolated_session=False)
    return pm


@pytest.fixture(scope="module")
def warn_run(site_url, tmp_path_factory):
    """Ein vollständiger Lauf mit der Standard-Policy 'warn' — einmal pro Modul."""
    from py_auto_tester.core.project_manager import ProjectManager

    pm = ProjectManager(tmp_path_factory.mktemp("warn_projekt"))
    pm.save_settings({"console_policy": "warn", "network_policy": "warn",
                      "check_timeout_ms": 1500, "trace_mode": "off",
                      "video_mode": "off", "keep_runs": 0})
    build_project(pm, site_url)
    result, steps = run_target(pm, "test", "e2e")
    return result, steps, pm


# --------------------------------------------------------------------------- #
# Der fehlerfreie Fall
# --------------------------------------------------------------------------- #

def test_all_routines_ran(warn_run):
    result, steps, _ = warn_run
    assert len(steps) == 6, sorted(steps)


def test_correct_routine_passes_with_all_checks(warn_run):
    _, steps, _ = warn_run
    step = steps["login_ok"]

    assert step["status"] == "PASS", step["error"]
    # 10 aktive deklarative Erwartungen (1 deaktiviert) + 2 check() im Code
    assert len(step["checks"]) == 12, len(step["checks"])
    assert all(c["status"] == "PASS" for c in step["checks"])
    assert {c["kind"] for c in step["checks"]} == {"code", "declarative"}
    assert not step["warnings"], "saubere Seite darf keine Warnungen erzeugen"
    assert "home.html" in step["url"]


def test_step_context_is_recorded(warn_run):
    result, steps, _ = warn_run
    checks = {c["label"]: c["step"] for c in steps["login_ok"]["checks"]}

    inner = [label for label in checks if "Anmelde-Button" in label]
    assert inner and checks[inner[0]] == "Anmeldung"

    outer = [label for label in checks if "Startseite" in label]
    assert outer and checks[outer[0]] == "", "ausserhalb des Blocks: kein Kontext"

    assert any("[SCHRITT] Anmeldung" in line for line in result.logs)


def test_log_helper_reaches_the_protocol(warn_run):
    result, _, _ = warn_run
    assert any("Login abgeschickt" in line for line in result.logs)


# --------------------------------------------------------------------------- #
# Fehlschlagende Erwartungen
# --------------------------------------------------------------------------- #

def test_failing_gui_check_fails_the_step(warn_run):
    _, steps, _ = warn_run
    step = steps["gui_check_fails"]

    assert step["status"] == "FAIL"
    failed = [c for c in step["checks"] if c["status"] == "FAIL"]
    passed = [c for c in step["checks"] if c["status"] == "PASS"]

    assert len(failed) == 1 and "Rechnungen" in failed[0]["label"]
    assert len(passed) == 1, "die andere Erwartung muss weiterhin gelten"
    assert "Erwartung" in step["error"]
    assert step["screenshot"] and os.path.exists(step["screenshot"])


def test_soft_check_continues_the_routine(warn_run):
    result, steps, _ = warn_run
    step = steps["soft_check_fails"]

    assert step["status"] == "FAIL"
    assert sum(1 for c in step["checks"] if c["status"] == "FAIL") == 1
    assert any("nach den Checks noch am Leben" in line for line in result.logs), \
        "check() ist weich und darf die Routine nicht abbrechen"


def test_require_aborts_the_routine(warn_run):
    result, steps, _ = warn_run
    step = steps["hard_require"]

    assert step["status"] == "FAIL"
    assert not any("DIESE ZEILE DARF NIE LAUFEN" in line for line in result.logs)
    assert "hard_require.py" in step["error"] and "Zeile" in step["error"], \
        "der Traceback muss auf die Routine-Zeile zeigen"


# --------------------------------------------------------------------------- #
# Diagnose
# --------------------------------------------------------------------------- #

def test_warn_policy_keeps_pass_but_records_findings(warn_run):
    _, steps, _ = warn_run
    step = steps["noisy_page"]

    assert step["status"] == "PASS", step["error"]
    warnings = step["warnings"]
    assert len(warnings) >= 2, warnings

    assert any(w["kind"] in ("console", "pageerror") and "termin" in w["message"]
               for w in warnings), "console.error muss erfasst werden"
    assert any(w["kind"] == "pageerror" for w in warnings), \
        "unbehandelter JS-Fehler muss erfasst werden"
    assert any(w["kind"] == "network" and w["status"] == 404 for w in warnings)

    assert not any("Synchronous XHR" in w["message"] for w in warnings), \
        "console.warn ist standardmaessig aus"
    assert not any("failed to load resource" in w["message"].lower() for w in warnings), \
        "Chromiums Ressourcen-Meldung ist eine Dublette zum Netzwerk-Befund"


def test_diagnostic_checks_can_fail_a_step(warn_run):
    _, steps, _ = warn_run
    step = steps["noisy_with_check"]

    assert step["status"] == "FAIL"
    failed = [c for c in step["checks"] if c["status"] == "FAIL"]
    assert len(failed) == 2, [c["label"] for c in failed]
    assert any("Befund" in c["message"] for c in failed)


def test_fail_policy_turns_findings_into_failures(site_url, project_factory):
    pm = project_factory(console_policy="fail", network_policy="fail")
    build_project(pm, site_url)

    _, steps = run_target(pm, "routine", "noisy_page")
    step = steps["noisy_page"]

    assert step["status"] == "FAIL"
    assert "JS-Konsolenfehler" in step["error"]
    assert "HTTP-Fehler" in step["error"]
    assert not step["warnings"], "als Fehler gewertet, also keine Warnung mehr"


def test_ignore_patterns_silence_findings(site_url, project_factory):
    pm = project_factory(
        console_policy="fail", network_policy="fail",
        ignore_console=[r"Cannot read properties", r"Unbehandelter Fehler im Timer"],
        ignore_urls=[r"fehlt-nicht-vorhanden\.png", r"api-kaputt\.json"],
    )
    build_project(pm, site_url)

    _, steps = run_target(pm, "routine", "noisy_page")
    step = steps["noisy_page"]

    assert step["status"] == "PASS", step["error"]
    assert not step["warnings"], step["warnings"]


# --------------------------------------------------------------------------- #
# Report und Zusammenfassung
# --------------------------------------------------------------------------- #

def test_summary_and_report_cover_checks_and_warnings(warn_run):
    result, _, _ = warn_run

    assert "Erwartungen:" in result.summary
    assert "Warnungen:" in result.summary
    assert os.path.exists(result.report_path)

    with open(result.report_path, encoding="utf-8") as f:
        html = f.read()

    assert "Erwartungen (" in html
    assert "Warnungen (" in html
    assert "404" in html
    assert ">GUI<" in html and ">Code<" in html, "Herkunft der Erwartung wird gezeigt"
    assert "<script>bad" not in html, "Seiteninhalt muss escaped sein"


# --------------------------------------------------------------------------- #
# Persistenz
# --------------------------------------------------------------------------- #

def test_routine_checks_survive_reload_and_deletion(warn_run):
    _, _, pm = warn_run

    checks = pm.get_routine_checks("login_ok")
    assert len(checks) == 11
    assert any(c["enabled"] is False for c in checks)

    path = os.path.join(pm.routines_dir, "login_ok.checks.json")
    assert os.path.exists(path)

    pm.delete_routine("login_ok")
    assert not os.path.exists(path), "delete_routine muss die Erwartungen mitnehmen"
    assert pm.get_routine_checks("login_ok") == []
