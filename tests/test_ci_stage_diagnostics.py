"""Opt-in CI observations preserve the runner's original execution contracts."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("diagnostic_runner", ROOT / "tools/run_tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
PREFIX = "lunar-ci-diagnostic "
NODE = "tests/test_inert.py::test_inert"


def _events(output):
    return [json.loads(line[len(PREFIX):]) for line in output.splitlines()
            if line.startswith(PREFIX)]


def _xml(report, *, count=1):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(count), failures="0", errors="0", skipped="0")
    for index in range(count):
        ET.SubElement(suite, "testcase", classname="tests.test_inert",
                      name="test_inert" if count == 1 else f"test_inert_{index}")
    report.write_bytes(ET.tostring(root))


@pytest.mark.parametrize("enabled", [False, True])
def test_collection_keeps_generator_arguments_and_flushes_before_process(
    tmp_path, monkeypatch, capsys, enabled,
):
    calls, prints = [], []
    original_print = print

    def observe_print(*args, **kwargs):
        prints.append(kwargs.get("flush"))
        original_print(*args, **kwargs)

    def execute(command, **kwargs):
        before = _events(capsys.readouterr().out)
        assert len(before) == int(enabled)
        if enabled:
            assert before[0]["event"] == "start" and before[0]["phase"] == "collection"
            assert before[0]["selection_count"] == 1
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=NODE + "\n1 test collected\n", stderr="")

    monkeypatch.setattr(runner, "print", observe_print, raising=False)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    monkeypatch.setenv("LUNAR_DIAGNOSTIC_TEST_SECRET", "must-not-be-logged")
    with runner._diagnostics(enabled, suite="current", role="current-2"):
        assert runner._collect(tmp_path, (x for x in ("tests",))) == (NODE,)
    assert calls[0][0] == [sys.executable, "-m", "pytest", "-o", "addopts=",
                           "--collect-only", "-q", "--color=no", "tests"]
    assert calls[0][1]["capture_output"] is True
    output = capsys.readouterr().out
    assert "must-not-be-logged" not in output and "LUNAR_DIAGNOSTIC_TEST_SECRET" not in output
    events = _events(output)
    assert len(events) == int(enabled)
    if enabled:
        assert all(prints) and len(prints) == 2
        assert events[0] == {"schema": "lunar-ci-stage-diagnostic-v1", "suite": "current",
            "role": "current-2", "phase": "collection", "event": "end", "selection_count": 1,
            "exit_code": 0, "collected_count": 1, "error_type": None,
            "elapsed_seconds": events[0]["elapsed_seconds"]}
        assert events[0]["elapsed_seconds"] >= 0
    else:
        assert prints == []


@pytest.mark.parametrize("failure,exit_code,error_type", [
    ("process", 2, "RegressionError"), ("spawn", None, "OSError"),
    ("inventory", 0, "RegressionError"),
])
def test_collection_end_preserves_failure_or_unknown_process_exit(
    tmp_path, monkeypatch, capsys, failure, exit_code, error_type,
):
    def execute(*_args, **_kwargs):
        if failure == "spawn":
            raise OSError("launch failed")
        return SimpleNamespace(returncode=2 if failure == "process" else 0,
                               stdout="", stderr="collection failed")
    monkeypatch.setattr(runner.subprocess, "run", execute)
    with (runner._diagnostics(True, suite="history", role="history"),
          pytest.raises((runner.RegressionError, OSError))):
        runner._collect(tmp_path, ("tests",))
    start, end = _events(capsys.readouterr().out)
    assert start["event"] == "start" and end["event"] == "end"
    assert end["exit_code"] == exit_code and end["error_type"] == error_type
    assert runner._DIAGNOSTIC_OBSERVATION.get() is None


@pytest.mark.parametrize("enabled", [False, True])
def test_pytest_changes_only_observers_and_retains_original_junit_fields(
    tmp_path, monkeypatch, capsys, enabled,
):
    report = tmp_path / "original.xml"
    calls = []
    def execute(command, **kwargs):
        before = _events(capsys.readouterr().out)
        assert len(before) == int(enabled)
        _xml(report)
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    with runner._diagnostics(enabled, suite="current-heavy", role="heavy-6"):
        result = runner._pytest_attempt(tmp_path, (NODE,), report, expected_count=1,
                                        expected_nodes=(NODE,))
    assert runner._DIAGNOSTIC_TEST_STACK_SECONDS == 300
    observer = ["-o", "faulthandler_timeout=300"] if enabled else []
    assert calls[0][0] == [sys.executable, "-m", "pytest", "-o", "addopts=",
        "-v" if enabled else "-q", "--color=no", *observer, f"--junitxml={report}", NODE]
    assert set(calls[0][1]) == {"cwd", "env", "check"}
    assert result["exit_code"] == result["pytest_exit_code"] == 0
    assert result["exact_case_keys"] is True and result["tests"] == 1
    assert not any("diagnostic" in key for key in result)
    events = _events(capsys.readouterr().out)
    assert len(events) == int(enabled)
    if enabled:
        assert events[0]["role"] == "heavy-6" and events[0]["expected_count"] == 1
        assert events[0]["attempt"] == 1 and events[0]["validation_exit_code"] == 0


def test_pytest_raw_success_does_not_hide_junit_validation_failure(tmp_path, monkeypatch, capsys):
    report = tmp_path / "incomplete.xml"
    def execute(*_args, **_kwargs):
        _xml(report)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    with runner._diagnostics(True, suite="current", role="current-0"):
        result = runner._pytest_attempt(tmp_path, ("tests",), report, expected_count=2)
    end = _events(capsys.readouterr().out)[-1]
    assert result["exit_code"] == end["validation_exit_code"] == 1
    assert result["pytest_exit_code"] == end["exit_code"] == 0


def test_pytest_spawn_error_emits_unknown_exit_and_propagates(tmp_path, monkeypatch, capsys):
    def execute(*_args, **_kwargs):
        raise OSError("spawn failed")
    monkeypatch.setattr(runner.subprocess, "run", execute)
    with runner._diagnostics(True, suite="history", role="history"), pytest.raises(OSError):
        runner._pytest_attempt(tmp_path, ("tests",), tmp_path / "absent.xml", expected_count=1)
    end = _events(capsys.readouterr().out)[-1]
    assert end["exit_code"] is None and end["error_type"] == "OSError"
    assert "validation_exit_code" not in end


def test_cli_context_resets_on_failure_nested_disabled_and_independent_context(tmp_path, monkeypatch):
    seen = []
    def history(*_args):
        seen.append(runner._DIAGNOSTICS.get())
        if len(seen) == 1:
            with runner._diagnostics(False, suite="all", role="all"):
                assert runner._DIAGNOSTICS.get() is None
            assert runner._DIAGNOSTICS.get() == ("history", "history")
            raise runner.RegressionError("inert failure")
        return 0
    monkeypatch.setattr(runner, "run_history", history)
    args = ["--suite", "history", "--junit-dir", str(tmp_path)]
    assert runner.main([*args, "--diagnostics"]) == 1
    assert runner._DIAGNOSTICS.get() is None
    assert runner.main(args) == 0 and seen == [("history", "history"), None]
    isolated = copy_context()
    with runner._diagnostics(True, suite="current", role="current-1"):
        assert isolated.run(runner._DIAGNOSTICS.get) is None
    assert runner._DIAGNOSTICS.get() is None


@pytest.mark.parametrize("flags", [
    ["--suite", "current", "--shard-index", "0", "--shard-count", "0"],
    ["--suite", "current-heavy", "--heavy-index", "7"],
    ["--suite", "history", "--isolate-heavy"],
])
def test_invalid_diagnostic_cli_refuses_before_context_or_effects(tmp_path, monkeypatch, capsys, flags):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid flags activated diagnostics or dispatched")
    monkeypatch.setattr(runner, "_diagnostics", forbidden)
    monkeypatch.setattr(runner, "_dispatch", forbidden)
    with pytest.raises(SystemExit) as error:
        runner.main(["--diagnostics", "--junit-dir", str(tmp_path / "reports"), *flags])
    assert error.value.code == 2 and _events(capsys.readouterr().out) == []
    assert not (tmp_path / "reports").exists()


def test_known_historical_retry_keeps_only_two_original_attempts(tmp_path, monkeypatch):
    attempts = []
    first = {"exit_code": 1, "pytest_exit_code": 1, "tests": 2294, "reported_testcases": 2294,
        "failures": 1, "failure_elements": 1, "errors": 0, "error_elements": 0,
        "skipped": 0, "skipped_elements": 0, "junit_sha256": "a" * 64,
        "failed_testcases": [{"classname": "tests.test_measurement139_observation",
                              "name": runner.ARCHIVE_RETRY_NODE.split("::")[1], "file": None}]}
    second = {"exit_code": 0, "pytest_exit_code": 0}
    def attempt(*_args, **_kwargs):
        attempts.append(runner._DIAGNOSTIC_ATTEMPT.get())
        return first if len(attempts) == 1 else second
    monkeypatch.setattr(runner, "_pytest_attempt", attempt)
    with runner._diagnostics(True, suite="history", role="history"):
        result = runner._pytest_phase(tmp_path, ("tests",), tmp_path / "archived.xml",
                                      expected_count=2294, frozen=True, historical_retry=True)
    assert attempts == [1, 2] and result["attempts"] == [first, second]
    assert runner._DIAGNOSTIC_ATTEMPT.get() == 1


def test_real_inert_pytest_shows_nodes_between_phase_events_without_changing_cases(tmp_path, capfd):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_inert.py").write_text("def test_inert():\n    assert 2 + 2 == 4\n")
    summaries = []
    for enabled in (False, True):
        report = tmp_path / ("verbose.xml" if enabled else "quiet.xml")
        with runner._diagnostics(enabled, suite="current-heavy", role="heavy-6"):
            summaries.append(runner._pytest_attempt(tmp_path, (NODE,), report, expected_count=1,
                                                     expected_nodes=(NODE,)))
        output = capfd.readouterr().out
        events = _events(output)
        assert len(events) == (2 if enabled else 0)
        if enabled:
            assert output.index('"event": "start"') < output.index(NODE + " PASSED")
            assert output.index(NODE + " PASSED") < output.index('"event": "end"')
        else:
            assert NODE + " PASSED" not in output
    fields = ("exit_code", "pytest_exit_code", "tests", "failures", "errors", "skipped",
              "reported_testcases", "exact_case_keys", "expected_inventory_sha256")
    assert all(summaries[0][field] == summaries[1][field] for field in fields)
    assert summaries[1]["exit_code"] == 0


def test_workflow_enables_unbuffered_diagnostics_without_changing_roles():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert 'PYTHONUNBUFFERED: "1"' in workflow
    commands = [line for line in workflow.splitlines() if "python tools/run_tests.py " in line]
    assert len(commands) == 3 and all(" --diagnostics " in line for line in commands)
    assert all("| python tools/ci_console.py --log .lunar-evolution/test-results/pytest.log"
               in line for line in commands)
    assert workflow.count("set -o pipefail") == 4
    assert [line.split("--suite ", 1)[1].split()[0] for line in commands] == [
        "current", "current-heavy", "history"]


def test_real_stall_observer_dumps_stack_without_changing_exit_or_junit(monkeypatch, capfd):
    # Keep this single natural subprocess outside the product checkout even when
    # the outer regression uses an in-repository basetemp. The private pytest.ini
    # also fixes its root and collection identity independently of ancestor config.
    with tempfile.TemporaryDirectory(prefix="lunar-ci-stack-") as directory:
        root = Path(directory).resolve()
        assert not root.is_relative_to(ROOT)
        (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        tests = root / "tests"
        tests.mkdir()
        script = tests / "test_inert.py"
        script.write_text(
            "import time\n\n"
            "def test_inert():\n"
            "    private_value = 'stack-local-value-must-not-be-dumped'\n"
            "    time.sleep(0.2)\n"
            "    assert private_value\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(runner, "_DIAGNOSTIC_TEST_STACK_SECONDS", 0.05)
        monkeypatch.setenv("LUNAR_STACK_TEST_SECRET", "stack-env-value-must-not-be-dumped")
        report = root / "original.xml"
        with runner._diagnostics(True, suite="current-heavy", role="heavy-6"):
            result = runner._pytest_attempt(root, (NODE,), report, expected_count=1,
                                            expected_nodes=(NODE,))
        captured = capfd.readouterr()
        assert "Timeout (" in captured.err
        assert str(script) in captured.err and "in test_inert" in captured.err
        for private in ("stack-local-value-must-not-be-dumped", "stack-env-value-must-not-be-dumped",
                        "LUNAR_STACK_TEST_SECRET"):
            assert private not in captured.out + captured.err
        assert result["exit_code"] == result["pytest_exit_code"] == 0
        assert result["tests"] == result["reported_testcases"] == 1
        assert result["failures"] == result["errors"] == result["skipped"] == 0
        assert result["exact_case_keys"] is True
        start, end = _events(captured.out)
        assert start["attempt"] == end["attempt"] == 1
        assert end["exit_code"] == end["validation_exit_code"] == 0


@pytest.mark.parametrize("enabled", [False, True])
def test_large_inventory_console_projection_preserves_full_sidecar_and_artifact_set(
    tmp_path, monkeypatch, capsys, enabled,
):
    # Exercise the initial record and the terminal sidecar through the actual
    # heavy-role runner, without executing any product or mixed acceptance body.
    nodes = tuple(sorted((
        *runner.HEAVY_CURRENT_NODES,
        *(f"tests/test_inert.py::test_inert_{index:05d}" for index in range(26364)),
    )))
    assert len(nodes) == 26371
    selected = (runner.HEAVY_CURRENT_NODES[6],)
    filename = selected[0].partition("::")[0]
    source = tmp_path / filename
    source.parent.mkdir()
    source.write_text("# Inert runner fixture; no test body is dispatched.\n", encoding="utf-8")
    origins = [str(tmp_path / "src/lunar_evolution/__init__.py"),
               str(tmp_path / "src/lunar_evolution/evaluator_bundle.py")]
    monkeypatch.setattr(runner, "_load_index", lambda _root: {
        "test_files": [], "support_files": [],
    })
    monkeypatch.setattr(runner, "_verify_imports", lambda _root: origins)
    monkeypatch.setattr(runner, "_git", lambda _root, _operation, ref:
                        "a" * 40 if ref == "HEAD" else "b" * 40)
    collections = []

    def collect(root, selections):
        assert root == tmp_path
        collections.append(tuple(selections))
        if len(collections) == 1:
            assert tuple(selections) == ("tests",)
            return nodes
        assert tuple(selections) == selected
        return selected

    monkeypatch.setattr(runner, "_collect", collect)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "job-provenance.json").write_text("{}\n", encoding="utf-8")
    (reports / "pytest.log").write_text("", encoding="utf-8")
    report = reports / "current-heavy-6.xml"
    executions = []

    def execute(command, **kwargs):
        assert command[-1] == selected[0] and kwargs["cwd"] == tmp_path
        executions.append(command)
        document = ET.Element("testsuites")
        suite = ET.SubElement(document, "testsuite", tests="1", failures="0", errors="0", skipped="0")
        classname, name = runner._junit_case_key(selected[0])
        ET.SubElement(suite, "testcase", classname=classname, name=name)
        report.write_bytes(ET.tostring(document))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", execute)
    with runner._diagnostics(enabled, suite="current-heavy", role="heavy-6"):
        assert runner.run_current_heavy(tmp_path, reports, heavy_index=6) == 0
    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines() if not line.startswith(PREFIX)]
    assert len(records) == 3 and len(executions) == 1
    initial, _pytest_result, final = records
    summary_path = reports / "current-heavy-6.summary.json"
    retained = json.loads(summary_path.read_bytes())
    assert retained["full_nodes"] == list(nodes) and retained["selected_nodes"] == list(selected)
    assert retained["full_collected"] == 26371 and retained["collected"] == 1
    assert retained["full_inventory_sha256"] == runner._inventory_sha256(nodes)
    assert retained["selected_inventory_sha256"] == runner._inventory_sha256(selected)
    assert retained["exit_code"] == retained["pytest_exit_code"] == 0
    assert retained["exact_case_keys"] is True
    assert {path.name for path in reports.iterdir()} == {
        "job-provenance.json", "pytest.log", "current-heavy-6.xml", "current-heavy-6.summary.json",
    }
    omitted = {"full_nodes", "selected_nodes"} if enabled else set()
    assert set(final) == set(retained) - omitted
    assert final == {key: value for key, value in retained.items() if key not in omitted}
    for key in ("full_collected", "collected", "full_inventory_sha256", "selected_inventory_sha256",
                "commit", "tree", "imports", "heavy_nodes", "selected_files", "selection_mode"):
        assert initial[key] == retained[key]
    if enabled:
        assert all(key not in initial for key in omitted)
        assert max(len(line) for line in output.splitlines()) < 8192
    else:
        assert initial["full_nodes"] == list(nodes) and initial["selected_nodes"] == list(selected)
        assert summary_path.read_text(encoding="utf-8") == json.dumps(final, sort_keys=True) + "\n"
        assert not _events(output)


@pytest.mark.parametrize("enabled", [False, True])
def test_checkout_identity_phase_keeps_git_commands_and_returned_identity(
    tmp_path, monkeypatch, capsys, enabled,
):
    calls = []

    def git(root, *arguments):
        assert root == tmp_path
        if not calls:
            events = _events(capsys.readouterr().out)
            assert len(events) == int(enabled)
            if enabled:
                assert events[0]["phase"] == "checkout-identity" and events[0]["event"] == "start"
        calls.append(arguments)
        return "a" * 40 if arguments[-1] == "HEAD" else "b" * 40

    monkeypatch.setattr(runner, "_git", git)
    origins = ["fixture-package", "fixture-evaluator"]
    with runner._diagnostics(enabled, suite="current-heavy", role="heavy-6"):
        result = runner._checkout_identity(tmp_path, origins)
    assert calls == [("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}")]
    assert result == {"commit": "a" * 40, "tree": "b" * 40, "working_tree": True,
                      "imports": origins, "python": sys.executable,
                      "python_version": f"{sys.version_info.major}.{sys.version_info.minor}"}
    events = _events(capsys.readouterr().out)
    assert len(events) == int(enabled)
    if enabled:
        assert events[0]["phase"] == "checkout-identity" and events[0]["event"] == "end"
        assert events[0]["exit_code"] == 0 and events[0]["error_type"] is None


@pytest.mark.parametrize("failure,exit_code,error_type", [
    ("first", 3, "RegressionError"), ("second", 7, "RegressionError"),
    ("second-spawn", None, "OSError"),
])
def test_checkout_identity_phase_preserves_failed_or_unknown_git_exit(
    tmp_path, monkeypatch, capsys, failure, exit_code, error_type,
):
    calls = []

    def execute(command, **_kwargs):
        calls.append(command)
        if failure == "second-spawn" and len(calls) == 2:
            raise OSError("inert second command spawn failure")
        failed = (failure == "first" and len(calls) == 1
                  or failure == "second" and len(calls) == 2)
        return SimpleNamespace(returncode=exit_code if failed else 0,
                               stdout="fixture-identity", stderr="inert Git failure" if failed else "")

    monkeypatch.setattr(runner.subprocess, "run", execute)
    with (runner._diagnostics(True, suite="current", role="current-0"),
          pytest.raises((runner.RegressionError, OSError))):
        runner._checkout_identity(tmp_path, [])
    start, end = _events(capsys.readouterr().out)
    assert start["phase"] == end["phase"] == "checkout-identity"
    assert end["exit_code"] == exit_code and end["error_type"] == error_type
    assert len(calls) == (1 if failure == "first" else 2)
    assert runner._DIAGNOSTIC_OBSERVATION.get() is None


def test_diagnostic_summary_exclusive_creation_does_not_replace_original_or_print_partial(
    tmp_path, capsys,
):
    report = tmp_path / "original.summary.json"
    original = {"full_nodes": [NODE], "selected_nodes": [NODE], "full_collected": 1,
                "collected": 1, "full_inventory_sha256": runner._inventory_sha256((NODE,))}
    expected = json.dumps(original, sort_keys=True) + "\n"
    with runner._diagnostics(True, suite="current", role="current-0"):
        runner._write_summary(report, original)
        capsys.readouterr()
        with pytest.raises(FileExistsError):
            runner._write_summary(report, {"full_nodes": [], "collected": 0})
    assert report.read_text(encoding="utf-8") == expected
    assert capsys.readouterr().out == ""
    assert list(tmp_path.iterdir()) == [report]
