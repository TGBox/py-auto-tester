import os
import base64
import html
from datetime import datetime
from typing import List, Dict, Any, Optional

class ReportGenerator:
    """Generates self-contained HTML execution reports with inline base64 screenshots."""

    @staticmethod
    def _esc(value: Any) -> str:
        """
        Escapes untrusted text (error messages, log output, locator text, page
        content) before it is interpolated into the HTML report.
        """
        return html.escape("" if value is None else str(value), quote=True)

    @staticmethod
    def _render_checks(checks: List[Dict[str, Any]]) -> str:
        """Rendert die Erwartungen eines Schritts als Liste."""
        if not checks:
            return ""
        esc = ReportGenerator._esc
        items = []
        for c in checks:
            ok = c.get("status") == "PASS"
            icon = "✔" if ok else "✘"
            cls = "check-ok" if ok else "check-bad"
            kind = c.get("kind", "code")
            kind_label = {
                "code": "Code",
                "declarative": "GUI",
                "diagnostics": "Diagnose",
            }.get(kind, kind)

            step_ctx = f'<span class="check-step">{esc(c["step"])}</span>' if c.get("step") else ""
            message = ""
            if c.get("message") and not ok:
                message = f'<div class="check-msg">{esc(c["message"])}</div>'

            items.append(
                f'<li class="{cls}">'
                f'<span class="check-icon">{icon}</span>'
                f'<span class="check-kind">{esc(kind_label)}</span>'
                f'{step_ctx}'
                f'<span class="check-label">{esc(c.get("label", ""))}</span>'
                f'{message}'
                f'</li>'
            )

        n_bad = sum(1 for c in checks if c.get("status") != "PASS")
        title = f"Erwartungen ({len(checks)})"
        if n_bad:
            title += f" – {n_bad} nicht erfüllt"
        open_attr = " open" if n_bad else ""
        return (
            f'<details class="sub-block"{open_attr}>'
            f'<summary>🎯 {title}</summary>'
            f'<ul class="check-list">{"".join(items)}</ul>'
            f'</details>'
        )

    @staticmethod
    def _render_warnings(warnings: List[Dict[str, Any]]) -> str:
        """Rendert Konsolen- und Netzwerkbefunde, die den Status nicht rot machen."""
        if not warnings:
            return ""
        esc = ReportGenerator._esc

        console = [w for w in warnings if w.get("kind") in ("console", "pageerror")]
        network = [w for w in warnings if w.get("kind") == "network"]

        blocks = []
        if console:
            rows = []
            for w in console:
                loc = f'<div class="warn-loc">{esc(w["location"])}</div>' if w.get("location") else ""
                rows.append(f'<li>{esc(w.get("message", ""))}{loc}</li>')
            blocks.append(
                f'<div class="warn-group"><div class="warn-head">Konsole ({len(console)})</div>'
                f'<ul>{"".join(rows)}</ul></div>'
            )
        if network:
            rows = []
            for w in network:
                status = w.get("status")
                prefix = f'<span class="warn-status">{esc(status)}</span> ' if status else ""
                method = f'{esc(w.get("method", ""))} ' if w.get("method") else ""
                rows.append(f'<li>{prefix}{method}{esc(w.get("url", "")) or esc(w.get("message", ""))}</li>')
            blocks.append(
                f'<div class="warn-group"><div class="warn-head">Netzwerk ({len(network)})</div>'
                f'<ul>{"".join(rows)}</ul></div>'
            )

        return (
            f'<details class="sub-block warn-block">'
            f'<summary>⚠ Warnungen ({len(warnings)})</summary>'
            f'{"".join(blocks)}'
            f'</details>'
        )

    @staticmethod
    def _image_to_base64(filepath: str) -> str:
        if filepath and os.path.exists(filepath):
            try:
                with open(filepath, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                    return f"data:image/png;base64,{encoded}"
            except Exception:
                pass
        return ""

    @staticmethod
    def generate(
        target_name: str,
        mode: str,
        browser_engine: str,
        device_profile: str,
        speed_mode: str,
        dataset_id: Optional[str],
        total_duration: float,
        passed_count: int,
        failed_count: int,
        step_results: List[Dict[str, Any]],
        logs: List[str],
        reports_dir: str,
        checks_passed: int = 0,
        checks_failed: int = 0,
        warnings_count: int = 0,
        output_path: Optional[str] = None,
        videos: Optional[List[str]] = None,
        screenshot_base: Optional[str] = None,
    ) -> str:
        """
        Generates self-contained HTML report file and returns its absolute filepath.
        """
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if output_path:
            filepath = output_path
            parent = os.path.dirname(os.path.abspath(filepath))
            if parent:
                os.makedirs(parent, exist_ok=True)
        else:
            os.makedirs(reports_dir, exist_ok=True)
            file_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(reports_dir, f"report_{file_timestamp}.html")

        total_steps = passed_count + failed_count
        pass_rate = int((passed_count / total_steps * 100)) if total_steps > 0 else 0

        esc = ReportGenerator._esc

        # Build Step Table Rows HTML
        table_rows_html = []
        for idx, step in enumerate(step_results, start=1):
            s_name = step.get("name", f"Schritt {idx}")
            s_status = step.get("status", "PASS")
            s_duration = step.get("duration", 0.0) or 0.0
            s_error = step.get("error", "")
            s_shot = step.get("screenshot", "")

            badge_class = "pass" if s_status == "PASS" else "fail"
            badge_icon = "✅ PASS" if s_status == "PASS" else "❌ FAIL"

            shot_html = ""
            if s_shot:
                # Pfade sind relativ zum Laufverzeichnis -> zum Einbetten auflösen
                shot_abs = s_shot
                if screenshot_base and not os.path.isabs(s_shot):
                    shot_abs = os.path.join(screenshot_base, s_shot)
                b64_src = ReportGenerator._image_to_base64(shot_abs)
                if b64_src:
                    shot_html = (
                        '<div class="screenshot-box"><p>🖼️ Fehler-Screenshot:</p>'
                        f'<img src="{b64_src}" alt="Screenshot" onclick="openModal(this.src)"/></div>'
                    )

            trace_html = ""
            if step.get("trace"):
                trace_rel = esc(step["trace"])
                trace_html = (
                    '<div class="trace-box">'
                    f'🎬 <a href="{trace_rel}" download>Trace herunterladen</a>'
                    '<div class="trace-hint">Ansehen mit: '
                    f'<code>npx playwright show-trace {trace_rel}</code>'
                    ' — zeigt DOM-Snapshots, Netzwerk und Zeitleiste des Schritts.</div>'
                    '</div>'
                )

            # Error text may be a multi-line traceback -> keep line breaks
            if s_error:
                error_html = f'<pre class="error-detail">{esc(s_error)}</pre>'
            elif not step.get("checks") and not step.get("warnings"):
                error_html = '<span style="color: #64748B;">Keine Fehler</span>'
            else:
                error_html = ""

            checks_html = ReportGenerator._render_checks(step.get("checks") or [])
            warnings_html = ReportGenerator._render_warnings(step.get("warnings") or [])

            # Badge-Spalte: Status + Zähler für Erwartungen und Warnungen
            step_checks = step.get("checks") or []
            n_ok = sum(1 for c in step_checks if c.get("status") == "PASS")
            n_bad = len(step_checks) - n_ok
            counters = []
            if n_ok:
                counters.append(f'<span class="pill pill-ok" title="erfüllte Erwartungen">✔ {n_ok}</span>')
            if n_bad:
                counters.append(f'<span class="pill pill-bad" title="nicht erfüllte Erwartungen">✘ {n_bad}</span>')
            if step.get("warnings"):
                counters.append(
                    f'<span class="pill pill-warn" title="Warnungen">⚠ {len(step["warnings"])}</span>'
                )
            if step.get("trace"):
                counters.append(
                    '<span class="pill pill-trace" title="Trace vorhanden">🎬 Trace</span>'
                )
            counters_html = f'<div class="pill-row">{"".join(counters)}</div>' if counters else ""

            url_html = ""
            if step.get("url"):
                url_html = f'<div class="step-url" title="URL am Ende des Schritts">{esc(step["url"])}</div>'

            row_html = f"""
            <tr>
                <td><strong>#{idx}</strong></td>
                <td>
                    <strong>{esc(s_name)}</strong>
                    {url_html}
                </td>
                <td>
                    <span class="badge {badge_class}">{badge_icon}</span>
                    {counters_html}
                </td>
                <td>{s_duration:.2f}s</td>
                <td>
                    {error_html}
                    {checks_html}
                    {warnings_html}
                    {trace_html}
                    {shot_html}
                </td>
            </tr>
            """
            table_rows_html.append(row_html)

        table_body = "\n".join(table_rows_html)
        logs_joined = esc("\n".join(logs))

        # Video gehört zur Browser-Session, nicht zu einem einzelnen Schritt
        video_html = ""
        if videos:
            players = []
            for idx, video in enumerate(videos, start=1):
                v = esc(video)
                players.append(
                    f'<div class="video-item"><div class="video-label">Session {idx}</div>'
                    f'<video src="{v}" controls preload="metadata"></video>'
                    f'<div class="video-path"><a href="{v}" download>{v}</a></div></div>'
                )
            video_html = (
                '<details class="video-block">'
                f'<summary>🎥 Videoaufnahme ({len(videos)})</summary>'
                '<p class="video-note">Eine Aufnahme pro Browser-Session — sie umfasst '
                'alle Schritte, die in dieser Session gelaufen sind.</p>'
                f'<div class="video-grid">{"".join(players)}</div>'
                '</details>'
            )

        # Full HTML Document
        html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test-Report: {esc(target_name)}</title>
    <style>
        :root {{
            --bg-color: #0F172A;
            --card-bg: #1E293B;
            --text-color: #F8FAFC;
            --text-muted: #94A3B8;
            --border-color: #334155;
            --accent-blue: #38BDF8;
            --pass-color: #10B981;
            --fail-color: #EF4444;
        }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 24px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .header-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        }}
        .title-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
            margin-bottom: 16px;
        }}
        .title-row h1 {{
            margin: 0;
            font-size: 24px;
            color: var(--accent-blue);
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
        }}
        .metric-card {{
            background: #0F172A;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px 16px;
            text-align: center;
        }}
        .metric-card .val {{
            font-size: 22px;
            font-weight: bold;
            margin-top: 4px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: bold;
        }}
        .badge.pass {{ background-color: rgba(16, 185, 129, 0.2); color: var(--pass-color); border: 1px solid var(--pass-color); }}
        .badge.fail {{ background-color: rgba(239, 68, 68, 0.2); color: var(--fail-color); border: 1px solid var(--fail-color); }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: var(--card-bg);
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            margin-bottom: 24px;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}
        th {{
            background-color: #0F172A;
            color: var(--accent-blue);
            font-weight: 600;
        }}
        tr:hover {{
            background-color: rgba(255,255,255,0.03);
        }}
        /* Zähler-Pillen in der Statusspalte */
        .pill-row {{ margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }}
        .pill {{
            display: inline-block; padding: 1px 7px; border-radius: 9999px;
            font-size: 11px; font-weight: bold; white-space: nowrap;
        }}
        .pill-ok   {{ background: rgba(16,185,129,0.15);  color: var(--pass-color); }}
        .pill-bad  {{ background: rgba(239,68,68,0.15);   color: var(--fail-color); }}
        .pill-warn {{ background: rgba(245,158,11,0.15);  color: #F59E0B; }}
        .pill-trace{{ background: rgba(56,189,248,0.15);  color: var(--accent-blue); }}

        /* Trace-Hinweis pro Schritt */
        .trace-box {{
            margin: 0 0 8px 0; padding: 8px 10px; border-radius: 6px;
            background: #0F172A; border: 1px solid var(--border-color);
            font-size: 12px;
        }}
        .trace-box a {{ color: var(--accent-blue); }}
        .trace-hint {{ color: var(--text-muted); font-size: 11px; margin-top: 4px; }}
        .trace-hint code {{
            font-family: Consolas, monospace; color: #CBD5E1;
            background: rgba(255,255,255,0.05); padding: 1px 4px; border-radius: 3px;
            word-break: break-all;
        }}

        /* Videoaufnahmen */
        .video-block {{
            background-color: var(--card-bg); border: 1px solid var(--border-color);
            border-radius: 8px; padding: 16px; margin-bottom: 24px;
        }}
        .video-block summary {{ font-weight: bold; color: var(--accent-blue); cursor: pointer; }}
        .video-note {{ color: var(--text-muted); font-size: 12px; }}
        .video-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px;
        }}
        .video-item video {{
            width: 100%; border-radius: 6px; border: 1px solid var(--border-color);
            background: #000;
        }}
        .video-label {{ font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }}
        .video-path {{ font-size: 11px; margin-top: 4px; word-break: break-all; }}
        .video-path a {{ color: var(--accent-blue); font-family: Consolas, monospace; }}

        .step-url {{
            font-size: 11px; color: var(--text-muted); margin-top: 4px;
            font-family: Consolas, monospace; word-break: break-all;
        }}

        /* Erwartungen & Warnungen pro Schritt */
        .sub-block {{
            margin: 0 0 8px 0; padding: 8px 10px; border-radius: 6px;
            background: #0F172A; border: 1px solid var(--border-color);
        }}
        .sub-block summary {{ font-size: 12px; }}
        .warn-block summary {{ color: #F59E0B; }}

        .check-list {{ list-style: none; margin: 8px 0 0 0; padding: 0; font-size: 12px; }}
        .check-list li {{
            padding: 4px 0; border-top: 1px solid var(--border-color);
            display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px;
        }}
        .check-list li:first-child {{ border-top: none; }}
        .check-icon {{ font-weight: bold; }}
        .check-ok  .check-icon {{ color: var(--pass-color); }}
        .check-bad .check-icon {{ color: var(--fail-color); }}
        .check-bad .check-label {{ color: #FCA5A5; }}
        .check-kind {{
            font-size: 10px; text-transform: uppercase; letter-spacing: .04em;
            color: var(--text-muted); border: 1px solid var(--border-color);
            border-radius: 4px; padding: 0 4px;
        }}
        .check-step {{ font-size: 11px; color: var(--accent-blue); }}
        .check-msg {{
            flex-basis: 100%; margin: 2px 0 0 18px; font-size: 11px;
            color: var(--text-muted); white-space: pre-wrap; word-break: break-word;
            font-family: Consolas, monospace;
        }}

        .warn-group {{ margin-top: 8px; }}
        .warn-head {{
            font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
            color: #F59E0B; margin-bottom: 4px;
        }}
        .warn-group ul {{ margin: 0; padding-left: 18px; font-size: 12px; color: #CBD5E1; }}
        .warn-group li {{ padding: 2px 0; word-break: break-word; }}
        .warn-loc {{
            font-size: 11px; color: var(--text-muted);
            font-family: Consolas, monospace; word-break: break-all;
        }}
        .warn-status {{ font-weight: bold; color: #F59E0B; }}

        .error-detail {{
            margin: 0 0 8px 0;
            white-space: pre-wrap;
            word-break: break-word;
            color: #FCA5A5;
            background-color: #0F172A;
            border-left: 3px solid var(--fail-color);
        }}
        .screenshot-box {{
            margin-top: 8px;
        }}
        .screenshot-box img {{
            max-width: 320px;
            border-radius: 6px;
            border: 1px solid var(--fail-color);
            cursor: pointer;
            transition: transform 0.2s;
        }}
        .screenshot-box img:hover {{
            transform: scale(1.03);
        }}
        details {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
        }}
        summary {{
            font-weight: bold;
            color: var(--accent-blue);
            cursor: pointer;
        }}
        pre {{
            background-color: #0F172A;
            padding: 14px;
            border-radius: 6px;
            overflow-x: auto;
            color: #CBD5E1;
            font-family: Consolas, monospace;
            font-size: 12px;
        }}

        /* Modal Image Preview */
        .modal {{
            display: none;
            position: fixed;
            z-index: 999;
            left: 0; top: 0; width: 100%; height: 100%;
            background-color: rgba(0,0,0,0.85);
            justify-content: center; align-items: center;
        }}
        .modal img {{
            max-width: 90%; max-height: 90%;
            border-radius: 8px;
            border: 2px solid var(--accent-blue);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-card">
            <div class="title-row">
                <h1>⚡ Test-Ausführungsbericht</h1>
                <span class="badge {'pass' if failed_count == 0 else 'fail'}">{ 'GESAMTERFOLG' if failed_count == 0 else 'FEHLGESCHLAGEN' }</span>
            </div>
            
            <div class="metrics-grid">
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Ausführungsziel</div>
                    <div class="val" style="color: var(--accent-blue);">{esc(target_name)} ({esc(mode.upper())})</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Erfolgsquote</div>
                    <div class="val" style="color: {'#10B981' if pass_rate == 100 else '#EF4444'}">{pass_rate}% ({passed_count}/{total_steps})</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Gesamtlaufzeit</div>
                    <div class="val">{total_duration:.2f}s</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Browser Engine</div>
                    <div class="val" style="font-size: 18px;">{esc(browser_engine.upper())}</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Geräte-Profil</div>
                    <div class="val" style="font-size: 18px;">{esc(device_profile)}</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Erwartungen</div>
                    <div class="val" style="color: {'#10B981' if checks_failed == 0 else '#EF4444'}">{checks_passed} ✔ / {checks_failed} ✘</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Warnungen</div>
                    <div class="val" style="color: {'#94A3B8' if warnings_count == 0 else '#F59E0B'}">{warnings_count}</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Datensatz</div>
                    <div class="val" style="font-size: 16px;">{esc(dataset_id) if dataset_id else '—'}</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Zeitstempel</div>
                    <div class="val" style="font-size: 14px; margin-top: 10px;">{timestamp_str}</div>
                </div>
            </div>
        </div>

        <h2>📋 Ausführungsschritte ({total_steps})</h2>
        <table>
            <thead>
                <tr>
                    <th style="width: 50px;">#</th>
                    <th style="width: 250px;">Routine / Schritt</th>
                    <th style="width: 110px;">Status</th>
                    <th style="width: 100px;">Dauer</th>
                    <th>Ergebnis / Fehlerdetails</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>

        {video_html}

        <details>
            <summary>📜 Ausführliches Konsolen-Protokoll (Logs anzeigen)</summary>
            <pre>{logs_joined}</pre>
        </details>
    </div>

    <!-- Modal for full size screenshot -->
    <div id="imgModal" class="modal" onclick="this.style.display='none'">
        <img id="modalImg" src="" alt="Full Preview">
    </div>

    <script>
        function openModal(src) {{
            document.getElementById('modalImg').src = src;
            document.getElementById('imgModal').style.display = 'flex';
        }}
    </script>
</body>
</html>
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        return filepath
