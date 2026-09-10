"""
JUnit-XML-Export, damit Läufe in CI-Systemen (Jenkins, GitLab, Azure DevOps,
GitHub Actions) als Testergebnisse erscheinen.

Abbildung:
  ein Lauf    -> <testsuite>
  ein Schritt -> <testcase>, classname = Ziel, name = Routine (+ Datensatzzeile)
  Fehler      -> <failure>
  übersprungen-> <skipped>
  Warnungen   -> <system-out>
"""

import os
from typing import Optional
from xml.etree import ElementTree as ET

from py_auto_tester.core.models import RunResult


def _failure_message(step) -> str:
    """
    Einzeilige Ursache für das message-Attribut. CI-Oberflächen zeigen nur
    diese Zeile in der Übersicht, also gehört dort die Ursache hin und nicht
    die Zählzeile „N Erwartung(en) nicht erfüllt".
    """
    failed = [c for c in step.checks if c.get("status") == "FAIL"]
    if failed:
        first = failed[0]
        label = first.get("label", "Erwartung nicht erfüllt")
        where = f" [{first['step']}]" if first.get("step") else ""
        msg = (first.get("message") or "").strip().splitlines()
        detail = f": {msg[0]}" if msg else ""
        text = f"{label}{where}{detail}"
        if len(failed) > 1:
            text += f"  (+{len(failed) - 1} weitere)"
        return text[:400]

    for line in (step.error or "").splitlines():
        line = line.strip()
        if line and not line.endswith(":"):
            return line[:400]
    return "Fehlgeschlagen"


def _suite_name(result: RunResult) -> str:
    cfg = result.config
    if not cfg:
        return "py-auto-tester"
    return f"py-auto-tester.{cfg.mode}.{cfg.item_id}"


def build_tree(result: RunResult) -> ET.ElementTree:
    cfg = result.config
    suite = ET.Element("testsuite", {
        "name": _suite_name(result),
        "tests": str(len(result.steps)),
        "failures": str(result.failed_count),
        "errors": "1" if result.system_error else "0",
        "skipped": str(result.skipped_count),
        "time": f"{result.duration:.3f}",
    })

    # Laufkontext als Properties, damit man im CI sieht, wie getestet wurde
    props = ET.SubElement(suite, "properties")
    if cfg:
        for name, value in (
            ("browser_engine", cfg.browser_engine),
            ("device_profile", cfg.device_profile),
            ("speed_mode", cfg.speed_mode),
            ("dataset_id", cfg.dataset_id or ""),
            ("mode", cfg.mode),
            ("target", cfg.item_id),
        ):
            ET.SubElement(props, "property", {"name": name, "value": str(value)})
    ET.SubElement(props, "property", {
        "name": "checks_passed", "value": str(result.checks_passed)})
    ET.SubElement(props, "property", {
        "name": "checks_failed", "value": str(result.checks_failed)})
    ET.SubElement(props, "property", {
        "name": "warnings", "value": str(result.warnings_count)})

    classname = f"{cfg.mode}.{cfg.item_id}" if cfg else "run"

    for step in result.steps:
        case = ET.SubElement(suite, "testcase", {
            "classname": classname,
            "name": step.name,
            "time": f"{step.duration:.3f}",
        })

        if step.status == "SKIPPED":
            ET.SubElement(case, "skipped", {"message": step.error or "übersprungen"})
        elif step.status == "FAIL":
            failure = ET.SubElement(case, "failure", {
                "message": _failure_message(step),
                "type": "AssertionError",
            })
            # step.error enthaelt bereits die nicht erfuellten Erwartungen —
            # hier nicht noch ein zweites Mal auflisten.
            detail = [step.error or "Fehlgeschlagen"]
            if step.url:
                detail.append(f"\nURL: {step.url}")
            if step.screenshot:
                detail.append(f"Screenshot: {step.screenshot}")
            failure.text = "\n".join(detail)

        # Erfüllte Erwartungen und Warnungen als system-out
        out_lines = []
        for c in step.checks:
            icon = "PASS" if c.get("status") == "PASS" else "FAIL"
            where = f" [{c['step']}]" if c.get("step") else ""
            out_lines.append(f"[{icon}] {c.get('label', '')}{where}")
        for w in step.warnings:
            if w.get("kind") == "network":
                out_lines.append(
                    f"[WARN] {w.get('status', '')} {w.get('method', '')} {w.get('url', '')}".rstrip()
                )
            else:
                out_lines.append(f"[WARN] {w.get('message', '')}")
        if out_lines:
            ET.SubElement(case, "system-out").text = "\n".join(out_lines)

    if result.system_error:
        case = ET.SubElement(suite, "testcase", {
            "classname": classname, "name": "Systemfehler", "time": "0",
        })
        err = ET.SubElement(case, "error", {"message": result.system_error[:400],
                                            "type": "RuntimeError"})
        err.text = result.system_error

    return ET.ElementTree(suite)


def write(result: RunResult, path: str) -> str:
    """Schreibt die JUnit-XML-Datei und gibt ihren Pfad zurück."""
    tree = build_tree(result)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def to_string(result: RunResult) -> str:
    tree = build_tree(result)
    ET.indent(tree, space="  ")
    return ET.tostring(tree.getroot(), encoding="unicode")
