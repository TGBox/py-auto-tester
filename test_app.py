import os
import sys
import pytest
import shutil
from core.project_manager import ProjectManager

@pytest.fixture
def temp_pm(tmp_path):
    test_dir = os.path.join(tmp_path, "test_proj")
    pm = ProjectManager(test_dir)
    return pm

def test_project_manager_crud(temp_pm):
    # Routines
    rid = temp_pm.save_routine("test_rec", "Test Routine", "Desc", "def execute(page, vars):\n    pass")
    assert rid == "test_rec"
    routines = temp_pm.get_routines()
    assert len(routines) == 1
    assert routines[0]["id"] == "test_rec"

    # Groups
    temp_pm.save_group("grp1", "Group 1", "Desc", ["test_rec"])
    groups = temp_pm.get_groups()
    assert len(groups) == 1
    assert groups[0]["id"] == "grp1"

    # Tests
    temp_pm.save_test("t1", "Test 1", "Desc", ["group:grp1"], isolated_session=False)
    tests = temp_pm.get_tests()
    assert len(tests) == 1
    assert tests[0]["id"] == "t1"

    # Delete
    temp_pm.delete_routine("test_rec")
    assert len(temp_pm.get_routines()) == 0

def test_execution_engine_speed_modes(temp_pm):
    from core.models import RunConfig

    for speed, expected in (("fastest", 0), ("normal", 300), ("slow", 1000), ("step", 2500)):
        config = RunConfig(mode="routine", item_id="test_rec", speed_mode=speed)
        assert config.slow_mo_ms == expected

    # Unbekanntes Tempo faellt auf den schnellsten Modus zurueck
    assert RunConfig(mode="routine", item_id="x", speed_mode="turbo").speed_mode == "fastest"

def test_execution_engine_browser_and_device_profiles(temp_pm):
    from core.models import RunConfig, get_context_options

    config = RunConfig(mode="routine", item_id="test_rec",
                       browser_engine="firefox", device_profile="iphone_14")
    assert config.browser_engine == "firefox"
    assert config.device_profile == "iphone_14"

    opts = get_context_options("iphone_14")
    assert opts["viewport"] == {"width": 390, "height": 844}
    assert opts["is_mobile"] is True
    assert opts["has_touch"] is True

    opts_desk = get_context_options("desktop_1080p")
    assert opts_desk["viewport"] == {"width": 1920, "height": 1080}

    # Unbekanntes Profil bekommt einen brauchbaren Fallback
    assert get_context_options("gibtsnicht")["viewport"] == {"width": 1280, "height": 720}

    # Grossbuchstaben und Unsinn bei der Engine werden normalisiert
    assert RunConfig(mode="routine", item_id="x", browser_engine="FIREFOX").browser_engine == "firefox"
    assert RunConfig(mode="routine", item_id="x", browser_engine="netscape").browser_engine == "chromium"


def test_context_options_are_copies(temp_pm):
    """Ein Lauf darf das Geraeteprofil nicht global veraendern."""
    from core.models import get_context_options, DEVICE_PROFILES

    opts = get_context_options("iphone_14")
    opts["viewport"]["width"] = 1
    opts["is_mobile"] = False

    assert DEVICE_PROFILES["iphone_14"]["viewport"]["width"] == 390
    assert get_context_options("iphone_14")["is_mobile"] is True

def test_dataset_crud_and_worker_dataset_binding(temp_pm):
    # Create dataset
    ds_id = temp_pm.save_dataset("test_users", ["USERNAME", "ROLE"], [["admin@test.de", "Admin"], ["user@test.de", "User"]])
    assert ds_id == "test_users"

    datasets = temp_pm.get_datasets()
    assert len(datasets) == 1
    assert datasets[0]["id"] == "test_users"

    headers, rows, row_dicts = temp_pm.get_dataset_data("test_users")
    assert headers == ["USERNAME", "ROLE"]
    assert len(rows) == 2
    assert row_dicts[0]["USERNAME"] == "admin@test.de"
    assert row_dicts[1]["ROLE"] == "User"

    # Dataset binding check
    from core.models import RunConfig
    config = RunConfig(mode="routine", item_id="test_rec", dataset_id="test_users")
    assert config.dataset_id == "test_users"

def test_report_generator(temp_pm):
    from core.report_generator import ReportGenerator

    report_path = ReportGenerator.generate(
        target_name="demo_routine",
        mode="routine",
        browser_engine="chromium",
        device_profile="desktop_1080p",
        speed_mode="normal",
        dataset_id=None,
        total_duration=1.45,
        passed_count=1,
        failed_count=0,
        step_results=[{"name": "demo_routine", "status": "PASS", "duration": 1.45, "error": "", "screenshot": ""}],
        logs=["[INFO] Test pass"],
        reports_dir=temp_pm.reports_dir
    )

    assert os.path.exists(report_path)
    assert report_path.endswith(".html")

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "Test-Report: demo_routine" in content
        assert "GESAMTERFOLG" in content
        assert "CHROMIUM" in content


# ---------------------------------------------------------------------------
# Regression tests for the routine execution sandbox
# ---------------------------------------------------------------------------

@pytest.fixture
def snippet_runner(temp_pm):
    """Returns (run, logs): run(code, routine_id) -> (success, error_msg)."""
    from core.models import RunConfig
    from core.runner import TestRunner

    runner = TestRunner(temp_pm, RunConfig(mode="routine", item_id="dummy"))
    logs = []

    def run(code, routine_id="r"):
        logs.clear()
        return runner.execute_snippet(
            code, page=object(), vars_dict={"BASE_URL": "https://example.com"},
            routine_id=routine_id, log=logs.append
        )

    return run, logs


def test_runner_is_free_of_qt(temp_pm):
    """
    Der Runner muss ohne Qt importierbar sein — sonst gibt es kein CI und keine
    kopflose Ausfuehrung.
    """
    import subprocess
    # find_spec statt find_module: die alte Finder-Schnittstelle ist ab
    # Python 3.12 entfernt und der Blocker waere dort wirkungslos.
    code = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('PySide6', 'PyQt5', 'PyQt6'):\n"
        "            raise ImportError('Qt ist hier nicht erlaubt: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "try:\n"
        "    import PySide6\n"
        "except ImportError as e:\n"
        "    assert 'nicht erlaubt' in str(e), 'Blocker greift nicht: ' + str(e)\n"
        "else:\n"
        "    raise AssertionError('Blocker greift nicht')\n"
        "import core.runner, core.models, core.junit_report, cli\n"
        "leaked = [m for m in sys.modules if m.startswith(('PySide6', 'PyQt'))]\n"
        "assert not leaked, 'Qt wurde importiert: ' + str(leaked)\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code],
                          cwd=os.path.dirname(os.path.abspath(__file__)),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_runner_reports_empty_sequence(temp_pm):
    """Regression: dieser Pfad hat den Lauf frueher zum Absturz gebracht."""
    from core.models import RunConfig
    from core.runner import TestRunner, CallbackListener

    finished = []
    runner = TestRunner(
        temp_pm, RunConfig(mode="test", item_id="does_not_exist"),
        listener=CallbackListener(on_finished=finished.append),
    )
    result = runner.run()  # kehrt zurueck, bevor Playwright startet

    assert len(finished) == 1 and finished[0] is result
    assert result.success is False
    assert result.steps == []
    assert "Keine Routinen" in result.summary
    assert result.report_path == ""


def test_finished_signal_emits_three_arguments(temp_pm):
    """Regression: the 'no routines' path used to emit 2 args into a 3-arg signal."""
    from gui.execution_worker import ExecutionEngineWorker

    worker = ExecutionEngineWorker(temp_pm, "test", "does_not_exist")
    received = []
    worker.finished_signal.connect(lambda *args: received.append(args))

    worker.run()  # returns before Playwright is ever started

    assert len(received) == 1
    assert len(received[0]) == 3, "finished_signal must be emitted with (success, summary, report_path)"
    success, summary, report_path = received[0]
    assert success is False
    assert "Keine Routinen" in summary
    assert report_path == ""


def test_worker_exposes_config_to_gui(temp_pm):
    """Die GUI liest mode/item_id/browser_engine direkt am Worker."""
    from gui.execution_worker import ExecutionEngineWorker

    worker = ExecutionEngineWorker(
        temp_pm, "group", "grp1", speed_mode="slow",
        browser_engine="WEBKIT", device_profile="pixel_7", dataset_id="ds1",
    )
    assert worker.mode == "group"
    assert worker.item_id == "grp1"
    assert worker.browser_engine == "webkit"
    assert worker.device_profile == "pixel_7"
    assert worker.dataset_id == "ds1"
    assert worker.get_slow_mo_ms() == 1000
    assert worker.get_context_options("pixel_7")["is_mobile"] is True

    # cancel() muss beim Runner ankommen
    assert worker.runner.is_cancelled is False
    worker.cancel()
    assert worker.runner.is_cancelled is True


def test_snippet_without_execute_function_fails(snippet_runner):
    """Regression: a routine that does nothing used to be reported as PASS."""
    run, _ = snippet_runner

    for code in ("", "   \n\n", "# nur ein Kommentar\n", "def execute_typo(page, vars):\n    pass\n"):
        success, err = run(code)
        assert success is False, f"expected FAIL for {code!r}"
        assert "execute(page, vars)" in err

    success, err = run("execute = 42\n")
    assert success is False
    assert "keine Funktion" in err


def test_snippet_with_execute_function_passes(snippet_runner):
    run, _ = snippet_runner
    success, err = run("def execute(page, vars):\n    pass\n")
    assert success is True
    assert err == ""


def test_snippet_legacy_top_level_code_passes_with_warning(snippet_runner):
    """Routines without an execute() wrapper still run, but are flagged."""
    run, logs = snippet_runner
    success, err = run("marker = []\nmarker.append(1)\n")
    assert success is True, err
    assert any("Legacy-Modus" in m for m in logs)


def test_snippet_helpers_share_one_namespace(snippet_runner):
    """Regression: exec() with separate globals/locals broke helper functions."""
    run, _ = snippet_runner

    success, err = run(
        "TIMEOUT = 5\n"
        "\n"
        "def helper(page):\n"
        "    return TIMEOUT\n"
        "\n"
        "def execute(page, vars):\n"
        "    assert helper(page) == 5\n"
    )
    assert success is True, err

    success, err = run(
        "class Flow:\n"
        "    def go(self):\n"
        "        return Flow\n"
        "\n"
        "def execute(page, vars):\n"
        "    assert Flow().go() is Flow\n"
    )
    assert success is True, err


def test_snippet_error_points_at_routine_line(snippet_runner):
    """Regression: only 'Type: message' was reported, the line number was lost."""
    run, _ = snippet_runner

    success, err = run(
        "def execute(page, vars):\n"
        "    x = 1\n"
        "    raise ValueError('kaputt')\n",
        routine_id="demo_login",
    )
    assert success is False
    assert "ValueError: kaputt" in err
    assert "demo_login.py" in err
    assert "Zeile 3" in err
    assert "raise ValueError('kaputt')" in err

    # Deepest routine frame wins, and the call chain is shown
    success, err = run(
        "def inner():\n"
        "    raise RuntimeError('tief')\n"
        "\n"
        "def execute(page, vars):\n"
        "    inner()\n",
        routine_id="chain",
    )
    assert success is False
    assert "Zeile 2" in err
    assert "Aufrufkette" in err


def test_snippet_syntax_error_is_reported(snippet_runner):
    run, _ = snippet_runner
    success, err = run("def execute(page, vars)\n    pass\n", routine_id="broken")
    assert success is False
    assert "SyntaxError" in err
    assert "Zeile" in err


def test_snippet_module_level_exception_is_reported(snippet_runner):
    run, _ = snippet_runner
    success, err = run("raise KeyError('beim Laden')\n", routine_id="modlevel")
    assert success is False
    assert "KeyError" in err
    assert "Zeile 1" in err


def test_report_escapes_untrusted_text(temp_pm):
    """Regression: error text and logs were interpolated into HTML unescaped."""
    from core.report_generator import ReportGenerator

    report_path = ReportGenerator.generate(
        target_name='<img src=x onerror=alert(1)>',
        mode="routine",
        browser_engine="chromium",
        device_profile="desktop_1080p",
        speed_mode="normal",
        dataset_id=None,
        total_duration=1.0,
        passed_count=0,
        failed_count=1,
        step_results=[{
            "name": "<b>step</b>",
            "status": "FAIL",
            "duration": 0.5,
            "error": 'AssertionError: expected <div id="x"> & got \'a\'\n  [r.py, Zeile 3]',
            "screenshot": "",
        }],
        logs=["[FAIL] locator resolved to <select> & </script><script>bad()</script>"],
        reports_dir=temp_pm.reports_dir,
    )

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Nothing injected
    assert "<img src=x onerror" not in content
    assert "<b>step</b>" not in content
    assert "</script><script>bad()" not in content
    assert content.count("</script>") == 1

    # ...but the information is still there, escaped
    assert "&lt;img src=x onerror=alert(1)&gt;" in content
    assert "expected &lt;div id=&quot;x&quot;&gt; &amp; got" in content
    # Multi-line tracebacks keep their line breaks
    assert 'class="error-detail"' in content






# ---------------------------------------------------------------------------
# Erwartungen (checks) und Diagnose
# ---------------------------------------------------------------------------

def test_check_recorder_soft_and_hard(temp_pm):
    from core.checks import CheckRecorder, build_check_api

    logs = []
    recorder = CheckRecorder(log=logs.append)
    api = build_check_api(recorder, log=logs.append)

    # check() ist weich: Rueckgabewert False, aber keine Exception
    assert api["check"](False, "Weiche Erwartung") is False
    assert api["check"](True, "Erfuellte Erwartung") is True
    assert recorder.passed_count == 1
    assert recorder.failed_count == 1

    # require() bricht ab
    with pytest.raises(AssertionError):
        api["require"](False, "Harte Erwartung")
    assert recorder.failed_count == 2

    summary = recorder.failure_summary()
    assert "2 Erwartung(en) nicht erfüllt" in summary
    assert "Weiche Erwartung" in summary
    assert "Harte Erwartung" in summary
    assert any("CHECK FEHLGESCHLAGEN" in m for m in logs)


def test_check_recorder_step_context(temp_pm):
    from core.checks import CheckRecorder, build_check_api

    recorder = CheckRecorder()
    api = build_check_api(recorder)

    with api["step"]("Login"):
        api["check"](True, "Innen")
        with api["step"]("Formular"):
            api["check"](True, "Verschachtelt")
    api["check"](True, "Aussen")

    steps = {r.label: r.step for r in recorder.results}
    assert steps["Innen"] == "Login"
    assert steps["Verschachtelt"] == "Login > Formular"
    assert steps["Aussen"] == ""


def test_step_context_does_not_swallow_exceptions(temp_pm):
    from core.checks import CheckRecorder, build_check_api

    recorder = CheckRecorder()
    api = build_check_api(recorder)
    with pytest.raises(ValueError):
        with api["step"]("Riskant"):
            raise ValueError("muss durchkommen")
    # Der Kontext muss trotzdem wieder verlassen worden sein
    assert recorder.current_step == ""


def test_describe_check_and_diagnostic_evaluation(temp_pm):
    from core.checks import describe_check, evaluate_check
    from core.diagnostics import DiagnosticEntry

    assert "Terminplaner" in describe_check(
        {"type": "element_visible", "target": "role=link[name=\"Terminplaner\"]"}
    )
    assert "Unbekannte Erwartung" in describe_check({"type": "gibtsnicht"})

    entries = [
        DiagnosticEntry(kind="console", severity="error", message="TypeError irgendwo"),
        DiagnosticEntry(kind="network", severity="error", message="HTTP 500",
                        status=500, method="GET", url="http://x/api"),
    ]

    # Diagnose-Erwartungen brauchen keine Seite
    r = evaluate_check({"type": "no_console_errors"}, page=None, diagnostics_entries=entries)
    assert r.status == "FAIL"
    assert "TypeError" in r.message

    r = evaluate_check({"type": "no_http_errors"}, page=None, diagnostics_entries=entries)
    assert r.status == "FAIL"
    assert "500" in r.message

    r = evaluate_check({"type": "no_console_errors"}, page=None, diagnostics_entries=[])
    assert r.status == "PASS"


def test_evaluate_check_rejects_incomplete_config(temp_pm):
    from core.checks import evaluate_check

    # Fehlende Pflichtfelder werden erkannt, ohne die Seite zu befragen
    r = evaluate_check({"type": "element_visible", "target": ""}, page=None)
    assert r.status == "FAIL"
    assert "Selektor" in r.message

    r = evaluate_check({"type": "url_contains", "value": ""}, page=None)
    assert r.status == "FAIL"

    r = evaluate_check({"type": "voelliger_unsinn"}, page=None)
    assert r.status == "FAIL"
    assert "Unbekannter Erwartungstyp" in r.message


def test_diagnostics_filters_noise_and_duplicates(temp_pm):
    """Ignore-Muster und Ressourcen-Dubletten muessen greifen."""
    from core.diagnostics import PageDiagnostics

    class FakeMsg:
        def __init__(self, type_, text, url=""):
            self.type = type_
            self.text = text
            self.location = {"url": url, "lineNumber": 7}

    diag = PageDiagnostics(
        ignore_console=[r"ResizeObserver loop"],
        ignore_urls=[r"google-analytics\.com"],
    )

    diag._on_console(FakeMsg("error", "Echter Fehler", "https://app.local/main.js"))
    diag._on_console(FakeMsg("warning", "Wird ignoriert, weil warning aus ist"))
    diag._on_console(FakeMsg("error", "ResizeObserver loop completed"))
    diag._on_console(FakeMsg("error", "Analytics kaputt", "https://google-analytics.com/x.js"))
    diag._on_console(FakeMsg("error", "Fehler in https://google-analytics.com/x.js"))
    # Dublette zum Netzwerk-Listener
    diag._on_console(FakeMsg("error", "Failed to load resource: the server responded with 404"))

    messages = [e.message for e in diag.entries]
    assert messages == ["Echter Fehler"], messages
    assert diag.entries[0].location.endswith(":7")


def test_diagnostics_network_and_severity(temp_pm):
    from core.diagnostics import PageDiagnostics

    class FakeReq:
        method = "GET"
        def __init__(self, url): self.url = url

    class FakeResp:
        def __init__(self, status, url):
            self.status = status
            self.url = url
            self.request = FakeReq(url)

    diag = PageDiagnostics(ignore_urls=[r"favicon\.ico"])
    diag._on_response(FakeResp(200, "http://x/ok"))
    diag._on_response(FakeResp(304, "http://x/cached"))
    diag._on_response(FakeResp(404, "http://x/favicon.ico"))
    diag._on_response(FakeResp(500, "http://x/api"))
    diag._on_response(FakeResp(401, "http://x/auth"))

    errors, warnings = PageDiagnostics.split(diag.entries)
    assert [e.status for e in errors] == [500]
    assert [w.status for w in warnings] == [401], "401 ist Teil vieler Auth-Flows -> nur Warnung"

    taken = diag.take()
    assert len(taken) == 2
    assert diag.entries == [], "take() muss den Puffer leeren"


def test_diagnostics_handler_never_raises(temp_pm):
    """Ein kaputtes Event darf den Testlauf nie abbrechen."""
    from core.diagnostics import PageDiagnostics

    class Explosive:
        @property
        def text(self): raise RuntimeError("boom")
        @property
        def status(self): raise RuntimeError("boom")

    diag = PageDiagnostics()
    # Kein Handler darf werfen ...
    diag._on_console(Explosive())
    diag._on_response(Explosive())
    diag._on_page_error(Explosive())
    diag._on_request_failed(Explosive())
    # ... und kein nackter Objekt-Repr darf als Fehlermeldung durchrutschen
    assert diag.entries == [], [e.message for e in diag.entries]


def test_routine_checks_persistence(temp_pm):
    temp_pm.save_routine("mit_checks", "Mit Checks", "", "def execute(page, vars):\n    pass\n")
    assert temp_pm.get_routine_checks("mit_checks") == []

    checks = [
        {"type": "element_visible", "target": "#ok", "value": "", "enabled": True},
        {"type": "url_contains", "target": "", "value": "/home", "enabled": False},
    ]
    temp_pm.save_routine_checks("mit_checks", checks)
    reloaded = temp_pm.get_routine_checks("mit_checks")
    assert len(reloaded) == 2
    assert reloaded[0]["target"] == "#ok"
    assert reloaded[1]["enabled"] is False

    # Muell wird beim Lesen verworfen
    temp_pm.save_routine_checks("mit_checks", [{"kein_typ": 1}] + checks)
    assert len(temp_pm.get_routine_checks("mit_checks")) == 2

    # Leere Liste entfernt die Datei
    temp_pm.save_routine_checks("mit_checks", [])
    assert temp_pm.get_routine_checks("mit_checks") == []

    # Routine loeschen raeumt die Erwartungen mit auf
    temp_pm.save_routine_checks("mit_checks", checks)
    temp_pm.delete_routine("mit_checks")
    assert temp_pm.get_routine_checks("mit_checks") == []


def test_settings_defaults_and_sanitizing(temp_pm):
    settings = temp_pm.get_settings()
    assert settings["console_policy"] == "warn"
    assert settings["network_policy"] == "warn"
    assert settings["check_timeout_ms"] == 5000
    assert settings["capture_console_warnings"] is False
    assert isinstance(settings["ignore_urls"], list)

    temp_pm.save_settings({
        "console_policy": "unsinn",
        "network_policy": "fail",
        "check_timeout_ms": "keine zahl",
        "ignore_console": ["gueltig", "", "  "],
        "ignore_urls": "kein array",
    })
    settings = temp_pm.get_settings()
    assert settings["console_policy"] == "warn", "ungueltige Policy faellt auf Default zurueck"
    assert settings["network_policy"] == "fail", "gueltige Policy bleibt erhalten"
    assert settings["check_timeout_ms"] == 5000
    assert settings["ignore_console"] == ["gueltig"]
    assert settings["ignore_urls"] == []

    # Defaults werden nicht global veraendert
    from core.project_manager import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["console_policy"] == "warn"
    assert len(DEFAULT_SETTINGS["ignore_urls"]) == 3


def test_report_renders_checks_and_warnings(temp_pm):
    from core.report_generator import ReportGenerator

    report_path = ReportGenerator.generate(
        target_name="mit_erwartungen", mode="routine", browser_engine="chromium",
        device_profile="desktop_1080p", speed_mode="normal", dataset_id="demo_users",
        total_duration=2.0, passed_count=0, failed_count=1,
        step_results=[{
            "name": "schritt", "status": "FAIL", "duration": 1.0,
            "error": "1 Erwartung(en) nicht erfüllt", "screenshot": "",
            "url": "http://example.com/home",
            "checks": [
                {"label": "URL enthält '/home'", "status": "PASS", "kind": "declarative",
                 "message": "", "step": ""},
                {"label": "Element sichtbar '<b>x</b>'", "status": "FAIL", "kind": "code",
                 "message": "Actual value: <nicht da>", "step": "Login"},
            ],
            "warnings": [
                {"kind": "console", "severity": "warning", "message": "warn <b>text</b>",
                 "location": "app.js:12", "status": None, "method": "", "url": ""},
                {"kind": "network", "severity": "warning", "message": "HTTP 401",
                 "location": "", "status": 401, "method": "GET", "url": "http://x/auth"},
            ],
        }],
        logs=["[WARN] irgendwas"],
        reports_dir=temp_pm.reports_dir,
        checks_passed=1, checks_failed=1, warnings_count=2,
    )

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Erwartungen (2)" in content
    assert "1 nicht erfüllt" in content
    assert "Warnungen (2)" in content
    assert "Konsole (1)" in content
    assert "Netzwerk (1)" in content
    assert "demo_users" in content, "Datensatz wird jetzt im Report gezeigt"
    assert "http://example.com/home" in content, "URL des Schritts wird gezeigt"
    assert ">Login<" in content, "step()-Kontext erscheint am Check"
    # Auch Check- und Warntexte sind escaped
    assert "<b>x</b>" not in content
    assert "<b>text</b>" not in content
    assert "&lt;b&gt;x&lt;/b&gt;" in content


# ---------------------------------------------------------------------------
# Modelle, JUnit-Export und CLI
# ---------------------------------------------------------------------------

def _demo_result():
    from core.models import RunConfig, RunResult, StepResult
    return RunResult(
        config=RunConfig(mode="test", item_id="login_flow", dataset_id="demo_users",
                         browser_engine="firefox", device_profile="iphone_14"),
        duration=12.5,
        steps=[
            StepResult(name="login", routine_id="login", status="PASS", duration=4.0,
                       checks=[{"label": "URL ok", "status": "PASS", "kind": "code",
                                "message": "", "step": ""}]),
            StepResult(name="planer", routine_id="planer", status="FAIL", duration=3.0,
                       error="1 Erwartung(en) nicht erfüllt:\n  - Element ist sichtbar 'x'",
                       url="http://x/planer", screenshot="/tmp/shot.png",
                       checks=[{"label": "Element ist sichtbar 'x'", "status": "FAIL",
                                "kind": "declarative", "message": "not found\nActual: None",
                                "step": "Öffnen"}],
                       warnings=[{"kind": "network", "severity": "warning", "message": "HTTP 401",
                                  "status": 401, "method": "GET", "url": "http://x/auth",
                                  "location": ""}]),
            StepResult(name="rest", routine_id="rest", status="SKIPPED",
                       error="Nicht ausgeführt (Lauf vorher beendet)"),
        ],
        logs=["[INFO] los"],
    )


def test_run_result_counts_and_summary(temp_pm):
    result = _demo_result()

    assert result.passed_count == 1
    assert result.failed_count == 1
    assert result.skipped_count == 1
    assert result.checks_passed == 1
    assert result.checks_failed == 1
    assert result.warnings_count == 1
    assert result.success is False

    summary = result.summary
    assert "Erfolgreich: 1" in summary
    assert "Fehlgeschlagen: 1" in summary
    assert "Übersprungen: 1" in summary
    assert "Erwartungen: 1 erfüllt, 1 nicht erfüllt" in summary
    assert "Warnungen: 1" in summary


def test_run_result_success_conditions(temp_pm):
    from core.models import RunConfig, RunResult, StepResult

    cfg = RunConfig(mode="routine", item_id="x")
    ok = RunResult(config=cfg, steps=[StepResult(name="a", status="PASS")])
    assert ok.success is True

    # Ein leerer Lauf ist kein Erfolg
    assert RunResult(config=cfg).success is False
    # Abbruch ebenfalls nicht
    assert RunResult(config=cfg, steps=[StepResult(name="a", status="PASS")],
                     cancelled=True).success is False
    # Systemfehler ebenfalls nicht
    assert RunResult(config=cfg, steps=[StepResult(name="a", status="PASS")],
                     system_error="kaputt").success is False


def test_run_result_to_dict_is_json_serializable(temp_pm):
    import json
    payload = json.loads(json.dumps(_demo_result().to_dict(), ensure_ascii=False))
    assert payload["target"] == "login_flow"
    assert payload["mode"] == "test"
    assert payload["browser_engine"] == "firefox"
    assert payload["counts"]["skipped"] == 1
    assert len(payload["steps"]) == 3
    assert payload["steps"][1]["checks"][0]["status"] == "FAIL"


def test_junit_report_structure(temp_pm):
    from xml.etree import ElementTree as ET
    from core import junit_report

    path = junit_report.write(_demo_result(), os.path.join(temp_pm.root_dir, "out", "junit.xml"))
    assert os.path.exists(path)

    root = ET.parse(path).getroot()
    assert root.tag == "testsuite"
    assert root.get("tests") == "3"
    assert root.get("failures") == "1"
    assert root.get("skipped") == "1"

    props = {p.get("name"): p.get("value") for p in root.findall("properties/property")}
    assert props["browser_engine"] == "firefox"
    assert props["dataset_id"] == "demo_users"
    assert props["checks_failed"] == "1"

    cases = {c.get("name"): c for c in root.findall("testcase")}
    assert set(cases) == {"login", "planer", "rest"}

    assert cases["login"].find("failure") is None
    assert "[PASS] URL ok" in cases["login"].find("system-out").text

    assert cases["rest"].find("skipped") is not None

    failure = cases["planer"].find("failure")
    assert failure is not None
    # message nennt die Ursache, nicht die Zaehlzeile
    assert "Element ist sichtbar" in failure.get("message")
    assert "nicht erfüllt:" not in failure.get("message")
    assert "Öffnen" in failure.get("message"), "step()-Kontext gehoert in die Meldung"
    # Der Text wiederholt die Erwartungsliste nicht doppelt
    assert failure.text.count("Element ist sichtbar 'x'") == 1
    assert "URL: http://x/planer" in failure.text
    assert "Screenshot: /tmp/shot.png" in failure.text
    assert "[WARN] 401 GET http://x/auth" in cases["planer"].find("system-out").text


def test_junit_report_records_system_error(temp_pm):
    from xml.etree import ElementTree as ET
    from core import junit_report
    from core.models import RunConfig, RunResult

    result = RunResult(config=RunConfig(mode="test", item_id="x"), system_error="Browser weg")
    root = ET.fromstring(junit_report.to_string(result))
    assert root.get("errors") == "1"
    error = root.find("testcase/error")
    assert error is not None and "Browser weg" in error.get("message")


def test_check_failure_summary_indents_multiline_messages(temp_pm):
    """Mehrzeilige Playwright-Meldungen muessen die Einrueckung behalten."""
    from core.checks import CheckRecorder

    recorder = CheckRecorder()
    recorder.record("Element sichtbar", False, kind="declarative",
                    message="Locator expected to be visible\nActual value: None")
    summary = recorder.failure_summary()

    lines = summary.splitlines()
    assert lines[1] == "  - Element sichtbar"
    assert lines[2] == "      Locator expected to be visible"
    assert lines[3] == "      Actual value: None"


def test_cli_parser_and_mode_resolution(temp_pm):
    import cli

    parser = cli.build_parser()
    args = parser.parse_args(["run", "login_flow", "--headless", "--junit-xml", "x.xml"])
    assert args.command == "run"
    assert args.target == "login_flow"
    assert args.headless is True
    assert args.junit_xml == "x.xml"
    assert args.browser == "chromium"
    assert args.speed == "fastest"
    assert args.mode == "auto"

    # Ziel automatisch erkennen
    temp_pm.save_routine("r1", "R1", "", "def execute(page, vars):\n    pass\n")
    temp_pm.save_group("g1", "G1", "", ["r1"])
    temp_pm.save_test("t1", "T1", "", ["group:g1"])

    assert cli._resolve_mode(temp_pm, "t1", "auto")[0] == "test"
    assert cli._resolve_mode(temp_pm, "g1", "auto")[0] == "group"
    assert cli._resolve_mode(temp_pm, "r1", "auto")[0] == "routine"

    mode, error = cli._resolve_mode(temp_pm, "tippfehler", "auto")
    assert mode is None
    assert "weder Test, Gruppe noch Routine" in error
    assert "routine:r1" in error, "Fehlermeldung soll die verfuegbaren Ziele nennen"

    # Explizites --mode ueberschreibt die Erkennung
    assert cli._resolve_mode(temp_pm, "egal", "routine")[0] == "routine"


def test_cli_exit_codes_are_distinct(temp_pm):
    import cli
    codes = {cli.EXIT_OK, cli.EXIT_FAILED, cli.EXIT_USAGE,
             cli.EXIT_SYSTEM, cli.EXIT_CANCELLED}
    assert len(codes) == 5
    assert cli.EXIT_OK == 0


def test_cli_run_rejects_unknown_target(temp_pm, capsys=None):
    import cli
    parser = cli.build_parser()
    args = parser.parse_args(["--project", temp_pm.root_dir, "run", "gibtsnicht", "--headless"])
    assert cli.cmd_run(args) == cli.EXIT_USAGE


def test_cli_run_rejects_unknown_dataset(temp_pm):
    import cli
    temp_pm.save_routine("r1", "R1", "", "def execute(page, vars):\n    pass\n")
    parser = cli.build_parser()
    args = parser.parse_args(["--project", temp_pm.root_dir, "run", "r1",
                              "--dataset", "gibtsnicht", "--headless"])
    assert cli.cmd_run(args) == cli.EXIT_USAGE


# ---------------------------------------------------------------------------
# Artefakte pro Lauf
# ---------------------------------------------------------------------------

def test_safe_name_sanitizing(temp_pm):
    from core.run_artifacts import safe_name

    assert safe_name("login flow") == "login_flow"
    assert "/" not in safe_name("a/b/c")
    assert "\\" not in safe_name("a\\b")
    # Punktfolgen werden eingekuerzt, damit kein '..' im Namen steht
    assert ".." not in safe_name("x/../y")
    # Ein einzelner Punkt darf bleiben (Versionsnummern)
    assert safe_name("v1.2") == "v1.2"
    # Rein unbrauchbare Eingaben bekommen den Fallback
    assert safe_name("") == "unbenannt"
    assert safe_name("...", fallback="leer") == "leer"
    assert safe_name("///") == "unbenannt"
    assert len(safe_name("a" * 500)) <= 80


def test_run_artifacts_layout_and_unique_names(temp_pm):
    from core.run_artifacts import RunArtifacts

    art = RunArtifacts(temp_pm.runs_dir, "test", "login_flow")
    assert os.path.isdir(art.dir)
    assert art.report_path == os.path.join(art.dir, "report.html")
    assert art.junit_path.endswith("junit.xml")

    p1 = art.unique_path("trace", "schritt", ".zip")
    p2 = art.unique_path("trace", "schritt", ".zip")
    p3 = art.unique_path("shots", "schritt", ".png")
    assert p1.endswith(os.path.join("trace", "schritt.zip"))
    assert p2.endswith(os.path.join("trace", "schritt_2.zip")), "darf nicht ueberschreiben"
    assert p3.endswith(os.path.join("shots", "schritt.png")), "andere Art -> eigener Zaehler"

    assert art.relative(p1) == "trace/schritt.zip"
    assert art.relative("") == ""

    # Leere Unterordner werden entfernt, gefuellte bleiben
    art.subdir("video")
    with open(p3, "w") as f:
        f.write("x")  # shots/ enthaelt jetzt eine Datei
    art.discard_empty_subdirs()
    assert not os.path.isdir(os.path.join(art.dir, "video")), "leer -> weg"
    assert not os.path.isdir(os.path.join(art.dir, "trace")), \
        "reservierte Namen allein halten den Ordner nicht"
    assert os.path.isdir(os.path.join(art.dir, "shots")), "enthaelt eine Datei -> bleibt"


def test_run_artifacts_same_second_gets_own_dir(temp_pm):
    """Regression: zwei Laeufe in derselben Sekunde teilten sich das Verzeichnis."""
    from datetime import datetime
    from core.run_artifacts import RunArtifacts

    stamp = datetime(2026, 9, 10, 14, 32, 5)
    a1 = RunArtifacts(temp_pm.runs_dir, "test", "gleich", timestamp=stamp)
    a2 = RunArtifacts(temp_pm.runs_dir, "test", "gleich", timestamp=stamp)
    a3 = RunArtifacts(temp_pm.runs_dir, "test", "gleich", timestamp=stamp)

    assert len({a1.dir, a2.dir, a3.dir}) == 3
    assert a1.run_id == "20260910_143205_test_gleich"
    assert a2.run_id.endswith("_2")
    assert a3.run_id.endswith("_3")


def test_prune_runs_keeps_newest_and_spares_foreign_dirs(temp_pm):
    from core.run_artifacts import list_runs, prune_runs

    for stamp in ("20260101_120000", "20260102_120000", "20260103_120000",
                  "20260104_120000"):
        os.makedirs(os.path.join(temp_pm.runs_dir, f"{stamp}_test_x"), exist_ok=True)

    # Etwas, das nicht wie ein Lauf heisst, darf nie geloescht werden
    foreign = os.path.join(temp_pm.runs_dir, "eigene_notizen")
    os.makedirs(foreign, exist_ok=True)

    assert len(list_runs(temp_pm.runs_dir)) == 4
    assert list_runs(temp_pm.runs_dir)[0].startswith("20260104"), "neueste zuerst"

    removed = prune_runs(temp_pm.runs_dir, keep=2)
    assert len(removed) == 2
    remaining = list_runs(temp_pm.runs_dir)
    assert len(remaining) == 2
    assert all(r.startswith(("20260103", "20260104")) for r in remaining), remaining
    assert os.path.isdir(foreign), "fremder Ordner muss bleiben"

    # keep=0 raeumt nicht auf
    assert prune_runs(temp_pm.runs_dir, keep=0) == []
    assert len(list_runs(temp_pm.runs_dir)) == 2


def test_artifact_settings_defaults_and_sanitizing(temp_pm):
    settings = temp_pm.get_settings()
    assert settings["trace_mode"] == "on_failure"
    assert settings["video_mode"] == "off", "Video kostet Laufzeit -> standardmaessig aus"
    assert settings["keep_runs"] == 20

    temp_pm.save_settings({"trace_mode": "vielleicht", "video_mode": "always",
                           "keep_runs": -3})
    settings = temp_pm.get_settings()
    assert settings["trace_mode"] == "on_failure"
    assert settings["video_mode"] == "always", "gueltiger Wert bleibt"
    assert settings["keep_runs"] == 0

    temp_pm.save_settings({"keep_runs": "viele"})
    assert temp_pm.get_settings()["keep_runs"] == 20


def test_report_links_trace_and_video(temp_pm):
    from core.report_generator import ReportGenerator

    out = os.path.join(temp_pm.runs_dir, "testlauf", "report.html")
    path = ReportGenerator.generate(
        target_name="t", mode="test", browser_engine="chromium",
        device_profile="desktop_1080p", speed_mode="fastest", dataset_id=None,
        total_duration=1.0, passed_count=0, failed_count=1,
        step_results=[{
            "name": "schritt", "status": "FAIL", "duration": 1.0,
            "error": "kaputt", "screenshot": "", "url": "",
            "trace": "trace/schritt.zip", "checks": [], "warnings": [],
        }],
        logs=[], reports_dir=temp_pm.reports_dir,
        output_path=out,
        videos=["video/session.webm"],
    )

    assert path == out, "output_path muss den Zeitstempelnamen ersetzen"
    assert os.path.exists(out)

    with open(out, encoding="utf-8") as f:
        content = f.read()

    assert 'href="trace/schritt.zip"' in content, "Trace relativ verlinkt"
    assert "npx playwright show-trace" in content
    assert "pill-trace" in content
    assert '<video src="video/session.webm"' in content
    assert "Videoaufnahme (1)" in content


def test_report_without_output_path_keeps_old_behaviour(temp_pm):
    """Der alte Aufruf ohne output_path muss weiter funktionieren."""
    from core.report_generator import ReportGenerator

    path = ReportGenerator.generate(
        target_name="t", mode="routine", browser_engine="chromium",
        device_profile="desktop_1080p", speed_mode="fastest", dataset_id=None,
        total_duration=1.0, passed_count=1, failed_count=0,
        step_results=[{"name": "a", "status": "PASS", "duration": 1.0,
                       "error": "", "screenshot": ""}],
        logs=[], reports_dir=temp_pm.reports_dir,
    )
    assert path.startswith(temp_pm.reports_dir)
    assert os.path.basename(path).startswith("report_")
    assert "<video" not in open(path, encoding="utf-8").read()


def test_cli_accepts_artifact_options(temp_pm):
    import cli

    args = cli.build_parser().parse_args([
        "run", "x", "--headless", "--trace", "always", "--video", "on_failure",
        "--keep-runs", "5",
    ])
    assert args.trace == "always"
    assert args.video == "on_failure"
    assert args.keep_runs == 5

    # Ohne Angabe bleibt es bei der Projekteinstellung
    args = cli.build_parser().parse_args(["run", "x"])
    assert args.trace is None and args.video is None and args.keep_runs is None
