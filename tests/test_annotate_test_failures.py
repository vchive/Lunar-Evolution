"""Keep archive retry evidence visible without downgrading unrelated regressions."""
from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "archive_retry_diagnostics", Path(__file__).resolve().parents[1] / "tools/annotate_test_failures.py",
)
assert _SPEC and _SPEC.loader
diagnostics = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(diagnostics)


def _report(path, *, failure=False, damage=None):
    root = ET.Element("testsuites")
    count = diagnostics._runner.ARCHIVE_EXECUTION_COUNT
    suite = ET.SubElement(root, "testsuite", {
        "tests": str(count), "failures": str(int(failure)), "errors": "0", "skipped": "0",
    })
    case = ET.SubElement(suite, "testcase", {
        "classname": "tests.test_measurement139_observation",
        "name": diagnostics._runner.ARCHIVE_RETRY_NODE.split("::", 1)[1],
    })
    if failure:
        ET.SubElement(case, "failure", {"message": "original scheduling failure"})
    for ordinal in range(count - 1):
        ET.SubElement(suite, "testcase", {
            "classname": "tests.test_historical", "name": f"test_case[{ordinal}]",
        })
    if damage == "other_node":
        case.set("name", "test_other")
    elif damage == "mixed_failures":
        ET.SubElement(suite[-1], "failure", {"message": "unrelated failure"})
        suite.set("failures", "2")
    elif damage == "error":
        ET.SubElement(suite[-1], "error", {"message": "setup failed"})
        suite.set("errors", "1")
    elif damage == "skip":
        ET.SubElement(suite[-1], "skipped")
        suite.set("skipped", "1")
    elif damage == "incomplete":
        suite.remove(suite[-1])
    elif damage == "wrong_count":
        suite.set("tests", str(count - 1))
    elif damage == "unreported_error":
        ET.SubElement(suite[-1], "error", {"message": "unreported setup failure"})
    elif damage == "malformed":
        path.write_text("<testsuites>")
        return path
    ET.ElementTree(root).write(path)
    return path


def test_missing_optional_archive_retry_is_silent_after_first_pass(tmp_path, capsys):
    original = _report(tmp_path / "archived.xml")
    retry = tmp_path / "archived.retry1.xml"
    assert diagnostics.annotate([original], archive_retry=retry) == 0
    output = capsys.readouterr().out
    assert "0 unavailable reports" in output and "JUnit report unavailable" not in output
    assert "::error" not in output and "::warning" not in output


def test_exact_known_archive_failure_becomes_retained_warning_after_complete_retry(tmp_path, capsys):
    original = _report(tmp_path / "archived.xml", failure=True)
    retry = _report(tmp_path / "archived.retry1.xml")
    before = {report: report.read_bytes() for report in (original, retry)}
    assert diagnostics.annotate([original], archive_retry=retry) == 0
    output = capsys.readouterr().out
    assert "::warning" in output and "::error" not in output
    assert "test_preparation_ceiling_does_not_leak_between_threads" in output
    assert "original scheduling failure" in output
    assert "1 failures/errors; 0 unavailable reports" in output
    assert "complete archive retry passed" in output
    assert {report: report.read_bytes() for report in (original, retry)} == before


@pytest.mark.parametrize("damage", [
    "other_node", "mixed_failures", "error", "skip", "incomplete", "wrong_count", "malformed",
])
def test_other_or_incomplete_original_failures_cannot_be_hidden_by_successful_retry(
    tmp_path, capsys, damage,
):
    original = _report(tmp_path / "archived.xml", failure=True, damage=damage)
    retry = _report(tmp_path / "archived.retry1.xml")
    assert diagnostics.annotate([original], archive_retry=retry) == 1
    output = capsys.readouterr().out
    assert "::error" in output and "cannot replace an unrecognized original" in output


@pytest.mark.parametrize("damage", [
    "missing", "failed", "error", "skip", "incomplete", "wrong_count", "unreported_error", "malformed",
])
def test_archive_retry_must_itself_pass_the_complete_inventory(tmp_path, capsys, damage):
    original = _report(tmp_path / "archived.xml", failure=True)
    retry = tmp_path / "archived.retry1.xml"
    if damage != "missing":
        _report(retry, failure=damage == "failed", damage=damage)
    assert diagnostics.annotate([original], archive_retry=retry) == 1
    output = capsys.readouterr().out
    assert "::error" in output and "original scheduling failure" in output
    assert "complete archive retry passed" not in output


def test_successful_archive_retry_does_not_hide_current_failure(tmp_path, capsys):
    original = _report(tmp_path / "archived.xml", failure=True)
    retry = _report(tmp_path / "archived.retry1.xml")
    current = _report(tmp_path / "current.xml", failure=True, damage="other_node")
    assert diagnostics.annotate([current, original], archive_retry=retry) == 1
    output = capsys.readouterr().out
    assert "::error" in output and "current.xml:" in output
    assert "::warning" in output and "archived.xml:" in output


@pytest.mark.parametrize("mutation", ["wrong_name", "missing_original", "duplicate_original", "passed_original"])
def test_archive_retry_cannot_be_repurposed_as_an_arbitrary_success_report(tmp_path, mutation, capsys):
    original = _report(tmp_path / "archived.xml", failure=mutation != "passed_original")
    retry = _report(tmp_path / ("current.retry1.xml" if mutation == "wrong_name" else "archived.retry1.xml"))
    reports = [] if mutation == "missing_original" else [original]
    if mutation == "duplicate_original":
        reports.append(original)
    assert diagnostics.annotate(reports, archive_retry=retry) == 1
    assert "::error" in capsys.readouterr().out


def test_archive_retry_uses_the_regression_runners_shared_policy(tmp_path, monkeypatch):
    original = _report(tmp_path / "archived.xml", failure=True)
    retry = _report(tmp_path / "archived.retry1.xml")
    calls = []

    def refuse(summary, **kwargs):
        calls.append((summary, kwargs))
        return False

    monkeypatch.setattr(diagnostics._runner, "_known_archive_failure", refuse)
    assert diagnostics.annotate([original], archive_retry=retry) == 1
    assert len(calls) == 1 and calls[0][0]["failures"] == 1
    assert calls[0][1] == {"expected_count": 2294, "frozen": True}


def test_archive_retry_cli_routes_the_optional_report_separately(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(diagnostics, "annotate", lambda reports, **kwargs: (
        calls.append((reports, kwargs)) or 0
    ))
    original, retry = tmp_path / "archived.xml", tmp_path / "archived.retry1.xml"
    assert diagnostics.main([str(original), "--archive-retry", str(retry)]) == 0
    assert calls == [([original], {"archive_retry": retry})]
