"""
Übersichtsseite über alle Läufe: `project_data/runs/index.html`.

Liest die `run.json` jedes Laufverzeichnisses und erzeugt daraus Kennzahlen,
einen Erfolgsquoten-Verlauf und eine Tabelle mit Links auf die Einzelreports.

Zur Darstellung: die Balkenhöhe ist die Erfolgsquote, die Farbe sagt
bestanden/fehlgeschlagen — das ist bewusst keine Farbskala über die Höhe,
sondern eine zusätzliche Aussage (99% und 100% liegen optisch beieinander,
bedeuten aber Grundverschiedenes). Weil Grün und Rot für Rot-Grün-Blinde nur
knapp unterscheidbar sind, steht die Aussage überall zusätzlich als Text:
Tooltip, Legende, direkte Beschriftung des letzten Balkens und die Tabelle.
"""

import html
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from py_auto_tester.core.run_artifacts import list_runs

# Statusfarben aus dem Report, damit beide Seiten dieselbe Sprache sprechen
COLOR_PASS = "#10B981"
COLOR_FAIL = "#EF4444"

MAX_BARS = 40  # mehr Balken als das sind auf der Breite nicht mehr lesbar


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _parse_stamp(run_id: str) -> Optional[datetime]:
    try:
        return datetime.strptime(run_id[:15], "%Y%m%d_%H%M%S")
    except (ValueError, IndexError):
        return None


def collect_runs(runs_dir: str) -> List[Dict[str, Any]]:
    """
    Sammelt die Läufe, neueste zuerst. Läufe ohne lesbare run.json werden
    mitgenommen, aber als unvollständig markiert — verschweigen wäre schlimmer.
    """
    entries: List[Dict[str, Any]] = []

    for run_id in list_runs(runs_dir):
        run_dir = os.path.join(runs_dir, run_id)
        stamp = _parse_stamp(run_id)
        entry: Dict[str, Any] = {
            "run_id": run_id,
            "timestamp": stamp,
            "readable": False,
            "has_report": os.path.exists(os.path.join(run_dir, "report.html")),
            "has_trace": os.path.isdir(os.path.join(run_dir, "trace")),
            "has_video": os.path.isdir(os.path.join(run_dir, "video")),
        }

        json_path = os.path.join(run_dir, "run.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            entries.append(entry)
            continue

        counts = data.get("counts") or {}
        passed = int(counts.get("passed", 0) or 0)
        failed = int(counts.get("failed", 0) or 0)
        skipped = int(counts.get("skipped", 0) or 0)
        total = passed + failed

        entry.update({
            "readable": True,
            "target": data.get("target", ""),
            "mode": data.get("mode", ""),
            "browser": data.get("browser_engine", ""),
            "device": data.get("device_profile", ""),
            "dataset": data.get("dataset_id") or "",
            "duration": float(data.get("duration", 0) or 0),
            "success": bool(data.get("success")),
            "cancelled": bool(data.get("cancelled")),
            "system_error": data.get("system_error", ""),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "checks_failed": int(counts.get("checks_failed", 0) or 0),
            "warnings": int(counts.get("warnings", 0) or 0),
            "pass_rate": (passed / total * 100.0) if total else 0.0,
            "has_steps": total > 0,
        })
        entries.append(entry)

    return entries


def _status_text(run: Dict[str, Any]) -> str:
    """Aussage in Worten — die Farbe allein darf sie nie tragen."""
    if not run.get("readable"):
        return "unvollständig"
    if run.get("system_error"):
        return "Systemfehler"
    if run.get("cancelled"):
        return "abgebrochen"
    return "bestanden" if run.get("success") else "fehlgeschlagen"


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """
    Balken mit oben abgerundeten Ecken, unten an der Grundlinie sitzend.
    Bei sehr flachen Balken wird der Radius mitgekürzt, sonst wölbt sich die
    Form nach innen.
    """
    r = max(0.0, min(r, w / 2.0, h))
    if h <= 0:
        return ""
    return (
        f"M{x:.2f},{y + h:.2f} "
        f"L{x:.2f},{y + r:.2f} "
        f"Q{x:.2f},{y:.2f} {x + r:.2f},{y:.2f} "
        f"L{x + w - r:.2f},{y:.2f} "
        f"Q{x + w:.2f},{y:.2f} {x + w:.2f},{y + r:.2f} "
        f"L{x + w:.2f},{y + h:.2f} Z"
    )


def _render_trend(runs: List[Dict[str, Any]]) -> str:
    """
    Erfolgsquote je Lauf als Balken, älteste links. Ein einzelner Lauf bekommt
    keinen Balken — eine Kennzahl allein ist kein Diagramm.
    """
    usable = [r for r in runs if r.get("readable") and r.get("has_steps")]
    if len(usable) < 2:
        return ""

    series = list(reversed(usable[:MAX_BARS]))  # chronologisch

    width, height = 900, 190
    pad_l, pad_r, pad_t, pad_b = 44, 16, 18, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    gap = 2.0  # Abstand als Fläche, nicht als Rahmen
    slot = plot_w / len(series)
    bar_w = max(3.0, slot - gap)

    grid, bars, labels = [], [], []

    for pct in (0, 50, 100):
        y = pad_t + plot_h - (pct / 100.0) * plot_h
        grid.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'class="grid"/>'
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" class="axis" text-anchor="end">{pct}%</text>'
        )

    for idx, run in enumerate(series):
        pct = max(0.0, min(100.0, run["pass_rate"]))
        h = (pct / 100.0) * plot_h
        x = pad_l + idx * slot + gap / 2.0
        y = pad_t + plot_h - h
        color = COLOR_PASS if run["success"] else COLOR_FAIL
        status = _status_text(run)
        when = run["timestamp"].strftime("%d.%m. %H:%M") if run["timestamp"] else run["run_id"]

        # Nullhöhe wäre unsichtbar: 2px Sockel, damit der Lauf nicht verschwindet
        if h < 2:
            h, y = 2.0, pad_t + plot_h - 2.0

        title = (
            f"{run.get('target', '')} — {when}\n"
            f"{status}: {run['passed']} von {run['passed'] + run['failed']} Schritten "
            f"({pct:.0f}%)"
        )
        if run.get("warnings"):
            title += f"\n{run['warnings']} Warnung(en)"

        bars.append(
            f'<g class="bar"><title>{_esc(title)}</title>'
            f'<rect x="{pad_l + idx * slot:.2f}" y="{pad_t}" width="{slot:.2f}" '
            f'height="{plot_h}" class="hit"/>'
            f'<path d="{_bar_path(x, y, bar_w, h)}" fill="{color}"/>'
            f'</g>'
        )

    # Nur der letzte Balken wird direkt beschriftet — eine Zahl an jedem
    # Balken liest niemand.
    last = series[-1]
    last_pct = max(0.0, min(100.0, last["pass_rate"]))
    last_h = max(2.0, (last_pct / 100.0) * plot_h)
    last_x = pad_l + (len(series) - 1) * slot + slot / 2.0
    last_y = pad_t + plot_h - last_h
    labels.append(
        f'<text x="{last_x:.1f}" y="{max(pad_t + 10, last_y - 7):.1f}" '
        f'class="datalabel" text-anchor="middle">{last_pct:.0f}%</text>'
    )

    first_when = series[0]["timestamp"]
    last_when = series[-1]["timestamp"]
    x_labels = ""
    if first_when and last_when:
        x_labels = (
            f'<text x="{pad_l}" y="{height - 10}" class="axis" text-anchor="start">'
            f'{first_when.strftime("%d.%m. %H:%M")}</text>'
            f'<text x="{width - pad_r}" y="{height - 10}" class="axis" text-anchor="end">'
            f'{last_when.strftime("%d.%m. %H:%M")}</text>'
        )

    return f"""
    <section class="card">
        <div class="card-head">
            <h2>Erfolgsquote je Lauf</h2>
            <div class="legend">
                <span class="legend-item"><span class="swatch" style="background:{COLOR_PASS}"></span>✅ bestanden</span>
                <span class="legend-item"><span class="swatch" style="background:{COLOR_FAIL}"></span>❌ fehlgeschlagen</span>
            </div>
        </div>
        <p class="hint">Balkenhöhe = Anteil erfolgreicher Schritte, Farbe und Symbol =
        Gesamtergebnis des Laufs. Älteste links, {len(series)} von {len(usable)} Läufen.</p>
        <svg viewBox="0 0 {width} {height}" class="trend" role="img"
             aria-label="Erfolgsquote der letzten {len(series)} Läufe. Genaue Werte in der Tabelle darunter.">
            {''.join(grid)}
            {''.join(bars)}
            {''.join(labels)}
            {x_labels}
        </svg>
    </section>
    """


def _render_tiles(runs: List[Dict[str, Any]]) -> str:
    readable = [r for r in runs if r.get("readable")]
    latest = readable[0] if readable else None

    recent = [r for r in readable if r.get("has_steps")][:10]
    rate = (sum(r["pass_rate"] for r in recent) / len(recent)) if recent else None

    tiles = []

    if latest:
        status = _status_text(latest)
        color = COLOR_PASS if latest.get("success") else COLOR_FAIL
        icon = "✅" if latest.get("success") else "❌"
        when = latest["timestamp"].strftime("%d.%m.%Y %H:%M") if latest["timestamp"] else "—"
        tiles.append(
            f'<div class="tile"><div class="tile-label">Letzter Lauf</div>'
            f'<div class="tile-value" style="color:{color}">{icon} {_esc(status)}</div>'
            f'<div class="tile-sub">{_esc(latest.get("target", ""))} · {when}</div></div>'
        )

    tiles.append(
        f'<div class="tile"><div class="tile-label">Läufe erfasst</div>'
        f'<div class="tile-value">{len(runs)}</div>'
        f'<div class="tile-sub">{len(readable)} mit Ergebnisdaten</div></div>'
    )

    if rate is not None:
        tiles.append(
            f'<div class="tile"><div class="tile-label">Ø Erfolgsquote</div>'
            f'<div class="tile-value">{rate:.0f}%</div>'
            f'<div class="tile-sub">über die letzten {len(recent)} Läufe</div></div>'
        )

    failing = [r for r in readable if r.get("has_steps") and not r.get("success")]
    tiles.append(
        f'<div class="tile"><div class="tile-label">Fehlgeschlagen</div>'
        f'<div class="tile-value" style="color:{COLOR_FAIL if failing else "#94A3B8"}">'
        f'{len(failing)}</div>'
        f'<div class="tile-sub">von {len([r for r in readable if r.get("has_steps")])} '
        f'bewertbaren Läufen</div></div>'
    )

    return f'<section class="tiles">{"".join(tiles)}</section>'


def _render_table(runs: List[Dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        when = run["timestamp"].strftime("%d.%m.%Y %H:%M:%S") if run["timestamp"] else "—"
        status = _status_text(run)

        if not run.get("readable"):
            report = (
                f'<a href="{_esc(run["run_id"])}/report.html">Report</a>'
                if run.get("has_report") else '<span class="muted">—</span>'
            )
            rows.append(
                f'<tr class="incomplete"><td>{when}</td>'
                f'<td><strong>{_esc(run["run_id"])}</strong></td>'
                f'<td class="status">◌ {status}</td>'
                f'<td colspan="4">run.json fehlt oder ist unlesbar — Lauf wurde '
                f'abgebrochen oder läuft noch</td>'
                f'<td>{report}</td></tr>'
            )
            continue

        cls = "ok" if run["success"] else "bad"
        icon = "✅" if run["success"] else "❌"
        steps = f'{run["passed"]}/{run["passed"] + run["failed"]}'
        if run["skipped"]:
            steps += f' <span class="muted">(+{run["skipped"]} übersprungen)</span>'

        extras = []
        if run.get("has_trace"):
            extras.append(f'<a href="{_esc(run["run_id"])}/trace/">Trace</a>')
        if run.get("has_video"):
            extras.append(f'<a href="{_esc(run["run_id"])}/video/">Video</a>')
        extras_html = " · ".join(extras) or '<span class="muted">—</span>'

        report = (
            f'<a href="{_esc(run["run_id"])}/report.html">Report</a>'
            if run.get("has_report") else '<span class="muted">—</span>'
        )

        warn = (
            f'<span class="warn">⚠ {run["warnings"]}</span>'
            if run.get("warnings") else '<span class="muted">—</span>'
        )

        rows.append(
            f'<tr class="{cls}">'
            f'<td>{when}</td>'
            f'<td><strong>{_esc(run.get("target", ""))}</strong>'
            f'<div class="muted">{_esc(run.get("mode", ""))}</div></td>'
            f'<td class="status">{icon} {_esc(status)}</td>'
            f'<td>{steps}</td>'
            f'<td>{run["pass_rate"]:.0f}%</td>'
            f'<td>{warn}</td>'
            f'<td>{run["duration"]:.1f}s</td>'
            f'<td>{report} · {extras_html}</td>'
            f'</tr>'
        )

    if not rows:
        rows.append('<tr><td colspan="8" class="muted">Noch keine Läufe vorhanden.</td></tr>')

    return f"""
    <section class="card">
        <div class="card-head"><h2>Alle Läufe</h2></div>
        <div class="table-scroll">
        <table>
            <thead><tr>
                <th>Zeitpunkt</th><th>Ziel</th><th>Ergebnis</th><th>Schritte</th>
                <th>Quote</th><th>Warnungen</th><th>Dauer</th><th>Dateien</th>
            </tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        </div>
    </section>
    """


def generate(runs_dir: str) -> str:
    """Schreibt runs/index.html und gibt den Pfad zurück."""
    os.makedirs(runs_dir, exist_ok=True)
    runs = collect_runs(runs_dir)
    filepath = os.path.join(runs_dir, "index.html")

    generated = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    content = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>py-auto-tester — Laufübersicht</title>
<style>
    :root {{
        --bg: #0F172A; --card: #1E293B; --ink: #F8FAFC; --muted: #94A3B8;
        --border: #334155; --accent: #38BDF8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
        font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
        background: var(--bg); color: var(--ink);
        margin: 0; padding: 24px; line-height: 1.5;
    }}
    .container {{ max-width: 1180px; margin: 0 auto; }}
    header {{ margin-bottom: 24px; }}
    h1 {{ font-size: 24px; color: var(--accent); margin: 0 0 4px 0; }}
    .sub {{ color: var(--muted); font-size: 13px; }}

    .tiles {{
        display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
        gap: 16px; margin-bottom: 24px;
    }}
    .tile {{
        background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; padding: 14px 16px;
    }}
    .tile-label {{ color: var(--muted); font-size: 12px; }}
    .tile-value {{ font-size: 22px; font-weight: bold; margin-top: 4px; }}
    .tile-sub {{ color: var(--muted); font-size: 11px; margin-top: 2px; }}

    .card {{
        background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; padding: 18px; margin-bottom: 24px;
    }}
    .card-head {{
        display: flex; justify-content: space-between; align-items: baseline;
        gap: 16px; flex-wrap: wrap; margin-bottom: 4px;
    }}
    .card-head h2 {{ font-size: 16px; margin: 0; }}
    .hint {{ color: var(--muted); font-size: 12px; margin: 0 0 8px 0; }}

    .legend {{ display: flex; gap: 14px; font-size: 12px; color: var(--muted); }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 5px; }}
    .swatch {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}

    /* Diagramm: dünne Marken, ruhige Achsen */
    .trend {{ width: 100%; height: auto; display: block; }}
    .grid {{ stroke: var(--border); stroke-width: 1; }}
    .axis {{ fill: var(--muted); font-size: 10px; }}
    .datalabel {{ fill: var(--ink); font-size: 11px; font-weight: bold; }}
    .bar .hit {{ fill: transparent; }}
    .bar:hover .hit {{ fill: rgba(255,255,255,0.05); }}
    .bar {{ cursor: default; }}

    .table-scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--accent); font-weight: 600; font-size: 12px; white-space: nowrap; }}
    tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
    td.status {{ white-space: nowrap; }}
    tr.ok td.status {{ color: {COLOR_PASS}; }}
    tr.bad td.status {{ color: {COLOR_FAIL}; }}
    tr.incomplete td {{ color: var(--muted); font-style: italic; }}
    .muted {{ color: var(--muted); font-size: 11px; }}
    .warn {{ color: #F59E0B; }}
    a {{ color: var(--accent); }}
    footer {{ color: var(--muted); font-size: 11px; margin-top: 8px; }}
</style>
</head>
<body>
<div class="container">
    <header>
        <h1>⚡ Laufübersicht</h1>
        <div class="sub">Erzeugt am {generated}</div>
    </header>

    {_render_tiles(runs)}
    {_render_trend(runs)}
    {_render_table(runs)}

    <footer>
        Ein Verzeichnis je Lauf mit Report, run.json, junit.xml und Artefakten.
        Wie viele behalten werden, steuert „Läufe aufbewahren" in den
        Diagnose-Einstellungen.
    </footer>
</div>
</body>
</html>
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath
