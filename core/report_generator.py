import os
import base64
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

class ReportGenerator:
    """Generates self-contained HTML execution reports with inline base64 screenshots."""

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
        reports_dir: str
    ) -> str:
        """
        Generates self-contained HTML report file and returns its absolute filepath.
        """
        os.makedirs(reports_dir, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{file_timestamp}.html"
        filepath = os.path.join(reports_dir, filename)

        total_steps = passed_count + failed_count
        pass_rate = int((passed_count / total_steps * 100)) if total_steps > 0 else 0

        # Build Step Table Rows HTML
        table_rows_html = []
        for idx, step in enumerate(step_results, start=1):
            s_name = step.get("name", f"Schritt {idx}")
            s_status = step.get("status", "PASS")
            s_duration = step.get("duration", 0.0)
            s_error = step.get("error", "")
            s_shot = step.get("screenshot", "")

            badge_class = "pass" if s_status == "PASS" else "fail"
            badge_icon = "✅ PASS" if s_status == "PASS" else "❌ FAIL"

            shot_html = ""
            if s_shot:
                b64_src = ReportGenerator._image_to_base64(s_shot)
                if b64_src:
                    shot_html = f'<br/><div class="screenshot-box"><p>🖼️ Fehler-Screenshot:</p><img src="{b64_src}" alt="Screenshot" onclick="openModal(this.src)"/></div>'

            row_html = f"""
            <tr>
                <td><strong>#{idx}</strong></td>
                <td><strong>{s_name}</strong></td>
                <td><span class="badge {badge_class}">{badge_icon}</span></td>
                <td>{s_duration:.2f}s</td>
                <td>
                    {s_error if s_error else '<span style="color: #64748B;">Keine Fehler</span>'}
                    {shot_html}
                </td>
            </tr>
            """
            table_rows_html.append(row_html)

        table_body = "\n".join(table_rows_html)
        logs_joined = "\n".join(logs)

        # Full HTML Document
        html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test-Report: {target_name}</title>
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
                    <div class="val" style="color: var(--accent-blue);">{target_name} ({mode.upper()})</div>
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
                    <div class="val" style="font-size: 18px;">{browser_engine.upper()}</div>
                </div>
                <div class="metric-card">
                    <div style="color: var(--text-muted); font-size: 12px;">Geräte-Profil</div>
                    <div class="val" style="font-size: 18px;">{device_profile}</div>
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
