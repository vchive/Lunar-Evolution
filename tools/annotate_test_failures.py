"""Publish bounded JUnit failure details as GitHub Actions annotations.

The regression runner remains responsible for test selection and exit status. This
read-only helper exposes failures through the public check API when logs require login.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAX_FAILURES = 10  # GitHub Actions displays at most ten error annotations per step.
MAX_REASON = 2000
_RUNNER_SPEC = importlib.util.spec_from_file_location("regression_runner", REPO / "tools/run_tests.py")
assert _RUNNER_SPEC and _RUNNER_SPEC.loader
_runner = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(_runner)


def _escape(value: str, *, property_value: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        value = value.replace(":", "%3A").replace(",", "%2C")
    return value


def _identity(case: ET.Element, repo: Path) -> tuple[str, str | None]:
    """Recover pytest's node ID, including class and parametrized case names."""
    classname, name = case.get("classname", ""), case.get("name", "unknown")
    parts = classname.split(".") if classname else []
    for split in range(len(parts), 0, -1):
        filename = "/".join(parts[:split]) + ".py"
        if (repo / filename).is_file():
            return "::".join((filename, *parts[split:], name)), filename
    filename = case.get("file")
    return "::".join(part for part in (filename or classname, name) if part), filename


def _annotation(level: str, message: str, *, filename: str | None = None) -> None:
    properties = "title=Test regression"
    if filename:
        properties += ",file=" + _escape(filename, property_value=True)
    print(f"::{level} {properties}::{_escape(message)}", flush=True)


def _archive_retry(reports: list[Path], retry: Path | None) -> tuple[Path | None, str | None]:
    if retry is None:
        return None, None
    original = retry.with_name("archived.xml")
    if retry.name != "archived.retry1.xml" or sum(
        report.absolute() == original.absolute() for report in reports
    ) != 1:
        return None, "Archive retry must accompany exactly one original archived.xml report"
    first = _runner._junit_summary(
        original, pytest_exit_code=1, expected_count=_runner.ARCHIVE_EXECUTION_COUNT, frozen=True,
    )
    recognized = _runner._known_archive_failure(
        first, expected_count=_runner.ARCHIVE_EXECUTION_COUNT, frozen=True,
    )
    if not retry.exists():
        return None, "Required archive retry report is unavailable" if recognized else None
    if not recognized:
        return None, "Archive retry cannot replace an unrecognized original result"
    second = _runner._junit_summary(
        retry, pytest_exit_code=0, expected_count=_runner.ARCHIVE_EXECUTION_COUNT, frozen=True,
    )
    if second["exit_code"]:
        return None, "Archive retry did not confirm all 2294 tests without failures, errors or skips"
    return original, None


def annotate(reports: list[Path], *, repo: Path = REPO, archive_retry: Path | None = None) -> int:
    recovered, retry_error = _archive_retry(reports, archive_retry)
    failures = 0
    blocking = 0
    unreadable = 0
    if retry_error:
        _annotation("error", retry_error)
    # Missing retry reports are optional unless the original result requires one. All supplied
    # ordinary reports remain mandatory, and a generated retry is inspected for failure details.
    selected = [*reports, *([archive_retry] if archive_retry and archive_retry.exists() else [])]
    for report in selected:
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError) as exc:
            unreadable += 1
            _annotation("warning", f"{report.name}: JUnit report unavailable: {str(exc)[:MAX_REASON]}")
            continue
        for case in root.iter("testcase"):
            for problem in (*case.findall("failure"), *case.findall("error")):
                failures += 1
                is_recovered = recovered is not None and report.absolute() == recovered.absolute()
                if not is_recovered:
                    blocking += 1
                if failures > MAX_FAILURES:
                    continue
                node_id, filename = _identity(case, repo)
                reason = problem.get("message") or problem.text or "No failure details recorded"
                reason = reason[:MAX_REASON]
                _annotation(
                    "warning" if is_recovered else "error",
                    f"{report.name}: {node_id}\n{reason}", filename=filename,
                )
    if failures > MAX_FAILURES:
        _annotation("warning", f"{failures - MAX_FAILURES} additional failures are in the test artifacts")
    print(f"JUnit diagnostics: {failures} failures/errors; {unreadable} unavailable reports", flush=True)
    if recovered is not None:
        print("Known archive scheduling failure retained; complete archive retry passed", flush=True)
    return int(bool(blocking or unreadable or retry_error))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--archive-retry", type=Path, help="optional retained archived.retry1.xml")
    arguments = parser.parse_args(argv)
    return annotate(arguments.reports, archive_retry=arguments.archive_retry)


if __name__ == "__main__":
    sys.exit(main())
