# py-auto-tester

GUI und Kommandozeile zum Aufnehmen, Strukturieren und Ausführen von
Playwright-Webtests. Routinen sind gewöhnliche Python-Dateien, lassen sich
per Browser-Aufnahme erzeugen und über anklickbare Erwartungen prüfen — auch
von Kollegen, die kein Python schreiben.

```
Routine   eine .py-Datei mit execute(page, vars) + optionalen Erwartungen
Gruppe    mehrere Routinen in fester Reihenfolge
Test      Gruppen und Routinen zu einem End-to-End-Ablauf
Datensatz CSV; der Test läuft je Zeile einmal durch
```

## Einrichten

```bash
uv sync                        # Abhängigkeiten
uv run playwright install      # Browser (einmalig)
```

Ohne `uv`:

```bash
pip install -e .
pip install pytest        # nur fuer die Tests; die dev-Gruppe ist kein Extra
playwright install
```

## Starten

```bash
py-auto-tester gui                 # Oberfläche
py-auto-tester list                # was ist im Projekt
py-auto-tester run login_flow      # ausführen
```

Ohne installiertes Paket:

```bash
uv run python main.py                          # Oberfläche
uv run python -m py_auto_tester run login_flow # Kommandozeile
```

Beim ersten Start entsteht `project_data/` mit einer Beispielroutine.

## Eine Routine schreiben

Jede Routine braucht `execute(page, vars)`. Im Namensraum stehen bereit:

| Name | Bedeutung |
|---|---|
| `page` | die Playwright-Seite |
| `vars` | Projekt-Variablen und Datensatz-Spalten |
| `log(text)` | schreibt ins Ausführungsprotokoll |
| `expect(locator)` | Playwright-Assertion, **bricht bei Fehlschlag ab** |
| `check(bedingung, "Text")` | weiche Erwartung: wird protokolliert, die Routine läuft weiter |
| `require(bedingung, "Text")` | harte Erwartung: bricht ab |
| `with step("Name"):` | gruppiert Aktionen im Protokoll und im Report |
| `re` | das `re`-Modul |

```python
# ROUTINE_NAME: Login und Terminplaner
# ROUTINE_DESC: Meldet sich an und öffnet den Terminplaner.

def execute(page, vars):
    page.goto(vars['BASE_URL'])

    with step('Anmeldung'):
        page.get_by_role('textbox', name='E-Mail').fill(vars['USERNAME'])
        page.get_by_role('textbox', name='Passwort').fill(vars['PASSWORD'])
        page.get_by_role('button').filter(has_text='check').click()

    log('Login abgeschickt')
    check(page.url.endswith('/home'), 'Landet auf der Startseite')
    expect(page.get_by_role('link', name='Terminplaner')).to_be_visible()
```

`check()` ist der Regelfall: ein Lauf zeigt damit **alle** Probleme auf
einmal statt nur des ersten. `require()` und `expect()` brechen ab — sinnvoll,
wenn ohne diesen Schritt nichts Weiteres funktionieren kann.

Hilfsfunktionen, Konstanten und Klassen auf Modulebene sind erlaubt und für
`execute()` sichtbar.

Eine Routine ohne `execute()` gilt als fehlgeschlagen — ein Tippfehler im
Funktionsnamen soll nicht als grüner Test durchgehen.

## Erwartungen ohne Python

Im Routine-Editor sitzt unter dem Code eine Tabelle „Erwartungen". Sie wird
nach dem Routine-Code ausgewertet und neben `<routine>.py` als
`<routine>.checks.json` gespeichert.

| Typ | Braucht | Beispiel |
|---|---|---|
| Element ist sichtbar / nicht sichtbar | Selektor | `role=link[name="Terminplaner"]` |
| Anzahl Elemente ist | Selektor + Zahl | `li.patient`, `5` |
| Text ist / ist nicht auf der Seite | Text | `Terminplaner` |
| URL enthält / passt auf Regex | Text bzw. Regex | `/aldashboard/home` |
| Seitentitel enthält | Text | `Praxis` |
| Feld hat Wert | Selektor + Wert | `#filter`, `alle` |
| Attribut hat Wert | Selektor + `attribut=wert` | `#submit`, `disabled=true` |
| Keine JS-Konsolenfehler | — | |
| Keine HTTP-Fehler (4xx/5xx) | — | |

Selektoren sind Playwright-Selektoren: `role=`, `text=`, CSS, XPath.

## Diagnose

Während jedes Schritts werden JS-Konsolenfehler, unbehandelte Seitenfehler,
fehlgeschlagene Requests und HTTP-Antworten ab Status 400 mitgeschnitten —
auch in Popups. Unter *Datei → Diagnose & Artefakte* legst du fest, wie stark
sie zählen:

| Einstellung | Wirkung |
|---|---|
| `warn` (Standard) | erscheint als Warnung im Report, Status bleibt PASS |
| `fail` | der Schritt wird rot |
| `log` | nur im Protokoll |

Dazu Ignore-Listen (reguläre Ausdrücke) für Konsolentexte und URLs. Ein
ignoriertes URL-Muster wirkt auch, wenn die URL als Konsolenmeldung auftaucht.

Empfehlung für den Anfang: bei `warn` bleiben, einen Lauf beobachten, das
dauerhaft Unwichtige in die Ignore-Listen aufnehmen — und erst danach auf
`fail` gehen.

Pro Test lässt sich das in `tests.json` überschreiben
(`console_policy`, `network_policy`), pro Lauf über die Kommandozeile.

## Artefakte pro Lauf

Jeder Lauf bekommt ein eigenes Verzeichnis. Der Ordner ist komplett
verschickbar, weil die Links im Report relativ sind.

```
project_data/runs/
    index.html                          Übersicht mit Erfolgsquoten-Verlauf
    20260910_143205_test_login_flow/
        report.html                     Report des Laufs
        run.json                        Ergebnis maschinenlesbar
        junit.xml                       für CI
        trace/terminplaner.zip          Playwright-Trace des Schritts
        video/<hash>.webm               Aufnahme der Browser-Session
        shots/terminplaner.png          Screenshot beim Fehler
```

Trace ansehen:

```bash
npx playwright show-trace project_data/runs/<lauf>/trace/<schritt>.zip
```

Der Trace enthält DOM-Snapshots, Netzwerkverkehr und eine Zeitleiste — das
ist das Werkzeug der Wahl, wenn ein Nightly-Lauf fehlschlug und niemand
zugesehen hat.

Zu den Modi: `off`, `on_failure` (Standard beim Trace), `always`. Video ist
standardmäßig aus, weil es Laufzeit und Plattenplatz kostet; es wird pro
Browser-Session aufgenommen, nicht pro Schritt, und entsteht erst beim
Schließen des Browsers — mit „Browser offen lassen" gibt es keine Aufnahme.
`keep_runs` (Standard 20) räumt ältere Laufverzeichnisse auf.

## Kommandozeile

Kein Qt, kein Display — für CI, Nightly-Läufe und den Aufgabenplaner.

```bash
py-auto-tester run login_flow --headless --junit-xml ergebnisse.xml
py-auto-tester run demo_login --mode routine --dataset demo_users -v
py-auto-tester run nightly --headless --console-policy fail --trace always
py-auto-tester index                       # Übersicht neu erzeugen
```

| Option | Zweck |
|---|---|
| `--headless` | ohne sichtbares Browserfenster |
| `--browser` | `chromium` / `firefox` / `webkit` |
| `--device` | Geräteprofil (Desktop, iPhone 14, Pixel 7, iPad Air) |
| `--dataset` | CSV-Datensatz, ein Durchlauf je Zeile |
| `--timeout` | Timeout je Playwright-Aktion in ms |
| `--stop-on-first-failure` | nach dem ersten Fehler abbrechen |
| `--console-policy`, `--network-policy` | Diagnose-Politik für diesen Lauf |
| `--trace`, `--video`, `--keep-runs` | Artefakte für diesen Lauf |
| `--junit-xml`, `--json` | Ergebnis zusätzlich hierhin schreiben |
| `-v` / `-q` | volles Protokoll / nur Exit-Code |

Das Ziel wird automatisch als Test, Gruppe oder Routine erkannt; `--mode`
erzwingt eine Deutung.

Exit-Codes: `0` bestanden · `1` mindestens ein Schritt fehlgeschlagen ·
`2` Aufruffehler · `3` Systemfehler · `130` abgebrochen.

## Projektstruktur

```
src/py_auto_tester/
    cli.py                 Kommandozeile
    app.py                 Start der Oberfläche
    core/
        runner.py          die Engine — ohne Qt, damit CI möglich ist
        models.py          RunConfig, StepResult, RunResult, Geräteprofile
        checks.py          Erwartungen: Code-API und deklarativ
        diagnostics.py     Konsolen- und Netzwerkerfassung
        run_artifacts.py   Laufverzeichnisse und Aufbewahrung
        report_generator.py / junit_report.py / run_index.py
        project_manager.py Persistenz
        codegen_recorder.py Aufnahme über Playwright Codegen
    gui/
        execution_worker.py QThread-Adapter auf den Runner
        main_window.py, tree_manager.py, routine_editor.py,
        runner_widget.py, dataset_editor.py, styles.py
```

Die Engine kennt Qt nicht. Die Oberfläche ist ein Adapter, der
Runner-Ereignisse auf Qt-Signale übersetzt — deshalb laufen Tests und CI ohne
Display, und ein Test hält diese Trennung fest, indem er PySide6-Importe
blockiert.

## Tests

```bash
uv sync                          # einmalig; installiert auch pytest
uv run pytest                    # alles
uv run pytest -m "not e2e"       # nur die schnellen Unit-Tests
uv run pytest -m e2e             # nur die Browser-Tests
```

`pytest` steht in `[dependency-groups] dev` und wird von `uv sync` und
`uv run` automatisch mitinstalliert. Wichtig ist der Unterschied zu
`[project.optional-dependencies]`: dort würde `uv run pytest` das pytest
im venv *nicht* finden, auf ein pytest im PATH ausweichen und damit ein
Python ohne die Projektabhängigkeiten benutzen — das sieht dann nach
kaputten Tests aus, ist aber nur die falsche Umgebung. Zum Prüfen:

```bash
uv run python -c "import sys; print(sys.executable)"
```

Das muss auf `.venv` zeigen.

Tests, die PySide6 brauchen, werden ohne PySide6 übersprungen; der
Kern (`core/`, `cli.py`) lädt ohne Qt *und* ohne Playwright, damit
`list` und `index` auch in einer schmalen Umgebung funktionieren.

Die E2E-Tests starten einen lokalen Webserver mit Testseiten unter
`tests/e2e/site/` und fahren echtes Chromium dagegen. Fehlt der Browser,
werden sie übersprungen statt zu scheitern.

## Zugangsdaten

`project_data/` ist von der Versionierung ausgenommen: dort liegen
`variables.json`, Datensätze mit Anmeldedaten und die Läufe mit Traces und
Videos. `variables.example.json` ist die Vorlage — kopieren nach
`project_data/variables.json` und ausfüllen.

Sollen Routinen versioniert werden, ist die Zeile `project_data/` in der
`.gitignore` die Stelle, die aufgeweicht werden muss — dann aber `variables.json`
und `datasets/` weiterhin ausschließen.

## Bekannte Grenzen

- `expect()` wird nicht als Erwartung mitgezählt; nur `check()` und
  `require()` erscheinen in der Erwartungsliste. Eine fehlgeschlagene
  `expect()` bricht den Schritt ab und erscheint mit Traceback-Zeile.
- Video ist pro Browser-Session, nicht pro Schritt.
- Der Abbruch wirkt zwischen Routinen, nicht mitten in einer hängenden
  Playwright-Aktion.
- Die Aufnahme (Codegen) blockiert die Oberfläche, solange das
  Aufnahmefenster offen ist.
