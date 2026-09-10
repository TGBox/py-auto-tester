"""
Gemeinsame Fixtures für die End-to-End-Tests.

Diese Tests starten einen echten Browser. Sie sind mit `e2e` markiert und
lassen sich abwählen:

    pytest -m "not e2e"          # nur die schnellen Unit-Tests
    pytest -m e2e                # nur die Browser-Tests

Fehlt Playwright oder der Browser, werden sie übersprungen statt zu scheitern.
"""

import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).parent / "site"


def pytest_collection_modifyitems(items):
    """Alles in diesem Ordner ist ein E2E-Test."""
    for item in items:
        item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session", autouse=True)
def require_playwright():
    """Ohne Playwright oder installierten Browser: überspringen, nicht scheitern."""
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright ist nicht installiert (uv sync)",
    )
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        pytest.skip(
            f"Chromium ist nicht startbar ({type(e).__name__}). "
            "Einmalig einrichten mit: playwright install chromium"
        )


@pytest.fixture(scope="session")
def site_url():
    """Lokaler Webserver mit den Testseiten; liefert die Basis-URL."""
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(
        ("127.0.0.1", 0),
        functools.partial(QuietHandler, directory=str(SITE_DIR)),
    )
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def project_factory(tmp_path):
    """
    Erzeugt ein frisches Projekt in einem temporären Verzeichnis.
    Rückgabe ist eine Funktion, damit ein Test mehrere Projekte anlegen kann.
    """
    from py_auto_tester.core.project_manager import ProjectManager

    counter = {"n": 0}

    def make(**settings) -> "ProjectManager":
        counter["n"] += 1
        pm = ProjectManager(tmp_path / f"projekt_{counter['n']}")
        base = {
            "console_policy": "warn",
            "network_policy": "warn",
            "check_timeout_ms": 1500,
            "trace_mode": "off",
            "video_mode": "off",
            "keep_runs": 0,
        }
        base.update(settings)
        pm.save_settings(base)
        return pm

    return make


def run_target(pm, mode, item_id, **config_kwargs):
    """
    Führt ein Ziel kopflos aus und gibt (RunResult, {schrittname: dict}) zurück.
    """
    from py_auto_tester.core.models import RunConfig
    from py_auto_tester.core.runner import TestRunner, CallbackListener

    steps = []
    logs = []
    config = RunConfig(
        mode=mode, item_id=item_id, headed=False, speed_mode="fastest",
        auto_close=True, action_timeout_ms=1500, **config_kwargs
    )
    runner = TestRunner(
        pm, config,
        listener=CallbackListener(on_step_result=steps.append, on_log=logs.append),
    )
    result = runner.run()
    result.logs = logs or result.logs
    return result, {s["name"]: s for s in steps}
