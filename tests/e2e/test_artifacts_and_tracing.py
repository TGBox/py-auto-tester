"""
Artefakte pro Lauf: Tracing, Video, Screenshots, Aufbewahrung, Laufübersicht.
"""

import json
import os
import zipfile

import pytest

from .conftest import run_target


def build_project(pm, base):
    pm.save_variables({"BASE_URL": f"{base}/index.html"})
    pm.save_routine("gut", "Gut", "", f"""
def execute(page, vars):
    page.goto("{base}/home.html")
    check(True, 'alles fein')
""")
    pm.save_routine("schlecht", "Schlecht", "", f"""
def execute(page, vars):
    page.goto("{base}/home.html")
    page.get_by_role('link', name='Gibtsnicht').click(timeout=800)
""")
    pm.save_group("beide", "Beide", "", ["gut", "schlecht"])
    pm.save_test("t", "T", "", ["group:beide"], isolated_session=False)
    return pm


# --------------------------------------------------------------------------- #
# Tracing
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def on_failure_run(site_url, tmp_path_factory):
    from py_auto_tester.core.project_manager import ProjectManager

    pm = ProjectManager(tmp_path_factory.mktemp("trace_projekt"))
    pm.save_settings({"console_policy": "warn", "network_policy": "warn",
                      "check_timeout_ms": 1200, "trace_mode": "on_failure",
                      "video_mode": "off", "keep_runs": 0})
    build_project(pm, site_url)
    result, steps = run_target(pm, "test", "t")
    return result, steps, pm


def test_run_gets_its_own_artifact_directory(on_failure_run):
    result, _, _ = on_failure_run

    assert result.artifacts_dir and os.path.isdir(result.artifacts_dir)
    assert result.report_path == os.path.join(result.artifacts_dir, "report.html")
    for name in ("run.json", "junit.xml", "report.html"):
        assert os.path.exists(os.path.join(result.artifacts_dir, name)), name


def test_trace_only_for_the_failing_step(on_failure_run):
    _, steps, _ = on_failure_run

    assert not steps["gut"]["trace"], "erfolgreicher Schritt braucht keinen Trace"

    trace = steps["schlecht"]["trace"]
    assert trace and os.path.exists(trace)
    assert os.path.basename(os.path.dirname(trace)) == "trace"
    assert zipfile.is_zipfile(trace)

    with zipfile.ZipFile(trace) as archive:
        names = archive.namelist()
    assert any(n.endswith(".trace") for n in names), names[:10]


def test_screenshot_lands_in_the_run_directory(on_failure_run):
    result, steps, _ = on_failure_run
    shot = steps["schlecht"]["screenshot"]

    assert shot.startswith(result.artifacts_dir), \
        "Screenshots gehoeren zum Lauf, nicht in den Temp-Ordner"
    assert os.path.exists(shot)


def test_report_links_artifacts_relatively(on_failure_run):
    result, _, _ = on_failure_run
    with open(result.report_path, encoding="utf-8") as f:
        html = f.read()

    assert 'href="trace/schlecht.zip"' in html, "relativer Link, damit der Ordner verschickbar ist"
    assert "npx playwright show-trace" in html
    assert "pill-trace" in html
    assert "data:image/png;base64," in html, "Screenshot bleibt eingebettet"


def test_run_json_describes_the_run(on_failure_run):
    result, _, _ = on_failure_run
    with open(os.path.join(result.artifacts_dir, "run.json"), encoding="utf-8") as f:
        data = json.load(f)

    assert data["artifacts_dir"] == result.artifacts_dir
    assert data["counts"]["failed"] == 1
    assert any(step["trace"] for step in data["steps"])


def test_trace_mode_always_traces_every_step(site_url, project_factory):
    pm = build_project(project_factory(trace_mode="always"), site_url)
    _, steps = run_target(pm, "test", "t")

    assert steps["gut"]["trace"] and os.path.exists(steps["gut"]["trace"])
    assert steps["schlecht"]["trace"] != steps["gut"]["trace"]


def test_trace_mode_off_leaves_nothing_behind(site_url, project_factory):
    pm = build_project(project_factory(trace_mode="off"), site_url)
    result, steps = run_target(pm, "test", "t")

    assert not any(s["trace"] for s in steps.values())
    assert not os.path.isdir(os.path.join(result.artifacts_dir, "trace")), \
        "leere Unterordner werden aufgeraeumt"


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #

def test_video_always_records_per_session(site_url, project_factory):
    pm = build_project(project_factory(video_mode="always"), site_url)
    result, _ = run_target(pm, "test", "t")

    assert len(result.videos) >= 1, result.videos
    video = result.videos[0]
    assert os.path.exists(video) and os.path.getsize(video) > 1000
    assert os.path.basename(os.path.dirname(video)) == "video"

    with open(result.report_path, encoding="utf-8") as f:
        html = f.read()
    assert "Videoaufnahme" in html and '<video src="video/' in html


def test_video_on_failure_is_discarded_after_a_clean_run(site_url, project_factory):
    pm = build_project(project_factory(video_mode="on_failure"), site_url)
    result, _ = run_target(pm, "routine", "gut")

    assert result.success, result.summary
    assert result.videos == []
    video_dir = os.path.join(result.artifacts_dir, "video")
    assert not os.path.isdir(video_dir) or not os.listdir(video_dir)


def test_video_on_failure_is_kept_after_a_failure(site_url, project_factory):
    pm = build_project(project_factory(video_mode="on_failure"), site_url)
    result, _ = run_target(pm, "routine", "schlecht")

    assert not result.success
    assert len(result.videos) >= 1
    assert os.path.exists(result.videos[0])


# --------------------------------------------------------------------------- #
# Aufbewahrung
# --------------------------------------------------------------------------- #

def test_keep_runs_prunes_oldest(site_url, project_factory):
    from py_auto_tester.core.run_artifacts import list_runs

    pm = build_project(project_factory(keep_runs=0), site_url)
    for _ in range(4):
        run_target(pm, "routine", "gut")
    assert len(list_runs(pm.runs_dir)) == 4

    settings = pm.get_settings()
    settings["keep_runs"] = 2
    pm.save_settings(settings)

    result, _ = run_target(pm, "routine", "gut")
    remaining = list_runs(pm.runs_dir)

    assert len(remaining) == 2, remaining
    assert os.path.basename(result.artifacts_dir) in remaining, \
        "der gerade erzeugte Lauf darf nicht wegaufgeraeumt werden"


# --------------------------------------------------------------------------- #
# Laufübersicht
# --------------------------------------------------------------------------- #

def test_run_index_is_written_and_lists_runs(site_url, project_factory):
    from py_auto_tester.core import run_index

    pm = build_project(project_factory(keep_runs=0), site_url)
    run_target(pm, "routine", "gut")
    result, _ = run_target(pm, "test", "t")

    index_path = os.path.join(pm.runs_dir, "index.html")
    assert os.path.exists(index_path), "der Runner erzeugt die Uebersicht selbst"

    runs = run_index.collect_runs(pm.runs_dir)
    assert len(runs) == 2
    assert runs[0]["timestamp"] >= runs[1]["timestamp"], "neueste zuerst"
    assert runs[0]["readable"]

    with open(index_path, encoding="utf-8") as f:
        html = f.read()

    # Aussage steht als Text da, nicht nur als Farbe
    assert "bestanden" in html and "fehlgeschlagen" in html
    assert "legend-item" in html
    assert 'class="bar"' in html, "zwei Laeufe -> Verlauf wird gezeichnet"
    assert "report.html" in html, "Links auf die Einzelreports"


def test_run_index_survives_a_broken_run_json(site_url, project_factory):
    from py_auto_tester.core import run_index

    pm = build_project(project_factory(keep_runs=0), site_url)
    result, _ = run_target(pm, "routine", "gut")

    with open(os.path.join(result.artifacts_dir, "run.json"), "w") as f:
        f.write("kein json")

    path = run_index.generate(pm.runs_dir)
    runs = run_index.collect_runs(pm.runs_dir)

    assert len(runs) == 1
    assert runs[0]["readable"] is False
    with open(path, encoding="utf-8") as f:
        assert "unvollständig" in f.read(), "der Lauf wird gezeigt, nicht verschwiegen"


def test_run_index_shows_a_single_run_without_a_chart(site_url, project_factory):
    pm = build_project(project_factory(keep_runs=0), site_url)
    run_target(pm, "routine", "gut")

    with open(os.path.join(pm.runs_dir, "index.html"), encoding="utf-8") as f:
        html = f.read()

    assert 'class="bar"' not in html, "ein einzelner Balken ist kein Diagramm"
    assert 'class="tile"' in html, "die Kennzahlen tragen den Fall"
