"""Current naming and historical evidence use separate, complete regression phases."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("regression_runner", REPO / "tools/run_tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture(scope="module")
def archive():
    with runner._snapshot(REPO, runner.ARCHIVE_COMMIT, "history") as snapshot:
        yield snapshot


@pytest.fixture(scope="module")
def frozen():
    with runner._snapshot(REPO, runner.FROZEN_COMMIT, "registration") as snapshot:
        yield snapshot


@pytest.fixture(scope="module")
def archive_python(archive):
    return runner._archive_python(archive)


@pytest.fixture(scope="module")
def original_selection(frozen):
    return runner._registration_selection(frozen, runner._verify_frozen(frozen))


@pytest.fixture(scope="module")
def archive_nodes(archive):
    return runner._collect(archive, runner._load_index(REPO)["test_files"])


def test_archive_index_verifies_complete_original_file_set_and_bytes(archive):
    index = runner._load_index(REPO)
    runner._verify_archive(archive, index)
    assert len(index["files"]) == 844
    assert len(index["rootdirs"]) == 35
    assert len(index["test_files"]) == 73
    assert len(index["support_files"]) == 3
    assert not archive.is_relative_to(REPO)


@pytest.mark.parametrize("damage", ["omission", "changed"])
def test_archive_inventory_rejects_missing_or_modified_originals(archive, monkeypatch, damage):
    index = copy.deepcopy(runner._load_index(REPO))
    relative = next(iter(index["files"]))
    if damage == "omission":
        index["files"].pop(relative)
    else:
        original = Path.read_bytes
        monkeypatch.setattr(Path, "read_bytes", lambda path: (
            original(path) + b"changed" if path == archive / relative else original(path)
        ))
    with pytest.raises(runner.RegressionError, match="file set changed|archived file changed"):
        runner._verify_archive(archive, index)


@pytest.mark.parametrize("field,value", [
    ("archive_commit", "0" * 40), ("file_count", 843),
    ("archived_tests", {"collected": 2318, "executed": 2293}),
    ("frozen_registration", {}),
])
def test_archive_index_cannot_change_fixed_identity_or_counts(tmp_path, field, value):
    index = copy.deepcopy(runner._load_index(REPO))
    index[field] = value
    destination = tmp_path / runner.ARCHIVE_INDEX
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(index))
    with pytest.raises(runner.RegressionError, match="archive index"):
        runner._load_index(tmp_path)


def test_frozen_snapshot_verifies_every_original_product_and_registration_pin(frozen, monkeypatch):
    observed = set()
    read_bytes = Path.read_bytes

    def record(path):
        observed.add(path.relative_to(frozen).as_posix())
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record)
    manifest = runner._verify_frozen(frozen)
    assert {group: len(manifest[group]) for group in runner.PIN_COUNTS} == runner.PIN_COUNTS
    expected = {name for group in runner.PIN_COUNTS for name in manifest[group]}
    assert observed == expected | {runner.MANIFEST_PATH}
    assert runner._git(frozen, "rev-parse", "HEAD") == runner.FROZEN_COMMIT


@pytest.mark.parametrize("group", ["product_files", "measurement_files", "historical_files"])
def test_registered_byte_drift_is_rejected_without_editing_historical_files(frozen, monkeypatch, group):
    manifest = runner._verify_frozen(frozen)
    changed = frozen / next(iter(manifest[group]))
    read_bytes = Path.read_bytes

    def drift(path):
        content = read_bytes(path)
        return content + b"changed" if path == changed else content

    monkeypatch.setattr(Path, "read_bytes", drift)
    with pytest.raises(runner.RegressionError, match="registered file changed"):
        runner._verify_frozen(frozen)


def test_manifest_identity_is_checked_before_its_file_pins(frozen, monkeypatch):
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: (
        read_bytes(path) + b"\n" if path == frozen / runner.MANIFEST_PATH else read_bytes(path)
    ))
    with pytest.raises(runner.RegressionError, match="immutable Feature 123 manifest changed"):
        runner._verify_frozen(frozen)


@pytest.mark.parametrize("name", ["../outside", "/outside", "folder/../inside", "folder//file"])
def test_registered_files_reject_noncanonical_and_escaping_paths(tmp_path, name):
    with pytest.raises(runner.RegressionError, match="invalid registered file"):
        runner._regular_file(tmp_path, name)


def test_registered_files_reject_symlinked_parents(tmp_path):
    (tmp_path / "actual").mkdir()
    (tmp_path / "actual/file").write_bytes(b"original")
    (tmp_path / "linked").symlink_to(tmp_path / "actual", target_is_directory=True)
    with pytest.raises(runner.RegressionError, match="invalid registered file"):
        runner._regular_file(tmp_path, "linked/file")


def test_archive_has_real_isolated_console_and_import_identity(archive, archive_python, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(REPO / "src"))
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nonexistent")
    monkeypatch.setenv("PYTEST_PLUGINS", "unwanted_plugin")
    environment = runner._environment(archive)
    assert environment["PYTHONPATH"] == str(archive / "src")
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "PYTEST_ADDOPTS" not in environment and "PYTEST_PLUGINS" not in environment
    package = runner._archived_package(archive)
    origins = runner._verify_imports(archive, python=archive_python, package=package)
    assert all(Path(path).is_relative_to(archive / "src" / package) for path in origins)
    script = archive / "specs/082-http-deadline-measurement/measurement/runtime_identity.py"
    spec = importlib.util.spec_from_file_location("original_runtime_identity", script)
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    captured = identity.capture(archive)
    assert captured["interpreter"]["path"] == str(archive_python)
    assert all(Path(row["path"]).is_relative_to(archive / "src")
               for row in captured["modules"].values())


def test_offline_environment_creation_uses_fixed_installer_and_current_pytest(tmp_path, monkeypatch):
    calls = []

    def capture(command, root, **kwargs):
        calls.append((command, root, kwargs))
        return "uv 0.11.8" if command == ["uv", "--version"] else ""

    monkeypatch.setattr(runner, "_capture", capture)
    python = runner._archive_python(tmp_path)
    assert python == tmp_path / ".venv/bin/python"
    assert len(calls) == 3
    assert all("--offline" in command for command, _, _ in calls[1:])
    assert "--no-python-downloads" in calls[1][0]
    assert any(item.startswith("pytest==") for item in calls[2][0])
    assert "-e" in calls[2][0] and f"{tmp_path}[dev]" in calls[2][0]


def test_incompatible_installer_cannot_change_the_historical_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_capture", lambda *_args, **_kwargs: "uv 0.12.0")
    with pytest.raises(runner.RegressionError, match="requires uv 0.11.8"):
        runner._archive_python(tmp_path)


def test_fixed_historical_collections_preserve_all_2318_tests(archive_nodes, original_selection):
    path, bound = original_selection
    assert path.endswith("_registration.py")
    assert len(bound) == 24
    assert runner._archive_selection(archive_nodes, bound) == 2294
    assert len(archive_nodes) == 2294 + 24


@pytest.mark.parametrize("mutation", ["omission", "prefix_collision", "changed_bound", "duplicate_bound"])
def test_historical_selection_cannot_silently_drop_tests(archive_nodes, original_selection, mutation):
    _, bound = original_selection
    nodes = archive_nodes
    if mutation == "omission":
        nodes = nodes[1:]
    elif mutation == "prefix_collision":
        nodes = (*nodes, bound[0] + "_additional")
    elif mutation == "changed_bound":
        bound = (*bound[:-1], "tests/test_missing.py::test_missing")
    else:
        bound = (*bound[:-1], bound[0])
    with pytest.raises(runner.RegressionError, match="collection|24"):
        runner._archive_selection(nodes, bound)


def test_detached_worktree_is_removed_when_body_raises():
    before = runner._git(REPO, "worktree", "list", "--porcelain")
    with (pytest.raises(runner.RegressionError, match="fixture failure"),
          runner._snapshot(REPO, runner.ARCHIVE_COMMIT, "cleanup") as snapshot):
        assert snapshot.is_dir()
        raise runner.RegressionError("fixture failure")
    assert not snapshot.exists()
    assert runner._git(REPO, "worktree", "list", "--porcelain") == before


@pytest.mark.parametrize("exit_codes", [(1, 0, 0), (0, 2, 0), (0, 0, 3), (0, 0, 0)])
def test_all_three_phase_results_propagate_with_distinct_versions(tmp_path, monkeypatch, exit_codes):
    current, history, frozen = (tmp_path / name for name in ("current", "history", "frozen"))
    for directory in (current, history, frozen):
        directory.mkdir()
    registration = "tests/test_original_registration.py"
    (history / "tests").mkdir()
    (history / registration).write_bytes(b"original tests")
    manifest = {"measurement_files": {registration: hashlib.sha256(b"original tests").hexdigest()}}
    index = {"test_files": [registration], "support_files": []}
    bound = tuple(f"{registration}::test_case[{i}]" for i in range(24))
    phases, closed, verifications = [], [], []

    @contextmanager
    def snapshot(_repo, commit, _label):
        directory = history if commit == runner.ARCHIVE_COMMIT else frozen
        try:
            yield directory
        finally:
            closed.append(directory)

    def phase(root, selections, report, **kwargs):
        phases.append((root, selections, report, kwargs))
        return {"exit_code": exit_codes[len(phases) - 1]}

    monkeypatch.setattr(runner, "_snapshot", snapshot)
    monkeypatch.setattr(runner, "_load_index", lambda _repo: index)
    monkeypatch.setattr(runner, "_verify_archive", lambda *_: verifications.append("archive"))
    monkeypatch.setattr(runner, "_verify_frozen", lambda *_: (verifications.append("frozen") or manifest))
    monkeypatch.setattr(runner, "_archive_python", lambda root: root / ".venv/bin/python")
    monkeypatch.setattr(runner, "_verify_imports", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(runner, "_archived_package", lambda _: "archived_product")
    monkeypatch.setattr(runner, "_registration_selection", lambda *_args, **_kwargs: (registration, bound))
    monkeypatch.setattr(runner, "_collect", lambda root, *_args, **_kwargs: (
        ("tests/test_current.py::test_current",) if root == current else bound
    ))
    monkeypatch.setattr(runner, "_archive_selection", lambda *_: 2294)
    monkeypatch.setattr(runner, "_git", lambda *_: "current-revision")
    monkeypatch.setattr(runner, "_pytest_phase", phase)
    assert runner.run(current, tmp_path / "junit") == next((code for code in exit_codes if code), 0)
    assert [row[0] for row in phases] == [current, history, frozen]
    assert [row[2].name for row in phases] == ["current.xml", "archived.xml", "frozen123.xml"]
    assert [row[3]["expected_count"] for row in phases] == [1, 2294, 24]
    assert phases[0][1] == ("tests",)
    assert phases[1][1] == (registration, *(f"--deselect={node}" for node in bound))
    assert phases[2][1] == bound
    assert all(row[3]["frozen"] for row in phases[1:])
    assert "historical_retry" not in phases[0][3]
    assert phases[1][3]["historical_retry"] is True
    assert "historical_retry" not in phases[2][3]
    assert closed == [frozen, history]
    assert verifications == ["archive", "frozen", "archive", "frozen"]


@pytest.mark.parametrize("content,count,expected", [
    ("def test_one():\n    assert True\n", 1, 0),
    ("def test_one():\n    assert False\n", 1, 1),
    ("import pytest\ndef test_one():\n    pytest.skip('fixture')\n", 1, 1),
    ("def test_one():\n    assert True\n", 2, 1),
])
def test_real_pytest_phase_requires_exact_count_and_no_historical_skips(tmp_path, content, count, expected):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_fixture.py").write_text(content)
    report = tmp_path / "result.xml"
    result = runner._pytest_phase(tmp_path, ("tests",), report, expected_count=count, frozen=True)
    assert result["exit_code"] == expected
    assert result["tests"] == 1
    assert report.is_file()


@pytest.mark.parametrize("suite", [None, "all", "native-e2e"])
def test_cli_routes_native_suite_without_changing_default_release_path(tmp_path, monkeypatch, suite):
    calls = []
    monkeypatch.setattr(runner, "run", lambda *args: (calls.append(("all", args)) or 3))
    monkeypatch.setattr(runner, "run_native_e2e", lambda *args: (
        calls.append(("native-e2e", args)) or 2
    ))
    arguments = ["--junit-dir", str(tmp_path)]
    if suite is not None:
        arguments.extend(("--suite", suite))
    native = suite == "native-e2e"
    assert runner.main(arguments) == (2 if native else 3)
    assert calls == [("native-e2e" if native else "all", (runner.REPO, tmp_path))]


@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_native_e2e_checks_imports_and_exact_collection_without_archive_setup(
    tmp_path, monkeypatch, capsys, exit_code,
):
    imports = ["checkout/__init__.py", "checkout/evaluator_bundle.py"]
    nodes = tuple(f"{name}::test_integration" for name in runner.NATIVE_E2E_SELECTION)
    calls = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("native E2E must not load archived regression state")

    def phase(root, selections, report, **kwargs):
        calls.append((root, selections, report, kwargs))
        return {"exit_code": exit_code, "tests": len(nodes), "skipped": 0}

    for name in ("_load_index", "_snapshot", "_archive_python"):
        monkeypatch.setattr(runner, name, forbidden)
    monkeypatch.setattr(runner, "_verify_imports", lambda root: imports)
    monkeypatch.setattr(runner, "_collect", lambda root, selection: (
        calls.append((root, selection)) or nodes
    ))
    monkeypatch.setattr(runner, "_git", lambda *_args: "product-revision")
    monkeypatch.setattr(runner, "_pytest_phase", phase)
    report_dir = tmp_path / "reports"
    assert runner.run_native_e2e(tmp_path, report_dir) == exit_code
    assert calls == [
        (tmp_path, runner.NATIVE_E2E_SELECTION),
        (tmp_path, runner.NATIVE_E2E_SELECTION, report_dir / "native-e2e.xml",
         {"expected_count": len(nodes)}),
    ]
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["suite"] == "native-e2e" and summary["offline"] is True
    assert summary["commit"] == "product-revision" and summary["working_tree"] is True
    assert summary["imports"] == imports and summary["collected"] == len(nodes)
    assert summary["exit_code"] == exit_code and summary["skipped"] == 0


@pytest.mark.parametrize("mutation", ["missing", "unexpected"])
def test_native_e2e_rejects_incomplete_or_unexpected_file_coverage(tmp_path, monkeypatch, mutation):
    nodes = tuple(f"{name}::test_integration" for name in runner.NATIVE_E2E_SELECTION)
    nodes = nodes[:-1] if mutation == "missing" else (*nodes, "tests/test_other.py::test_other")
    monkeypatch.setattr(runner, "_verify_imports", lambda _: [])
    monkeypatch.setattr(runner, "_collect", lambda *_args: nodes)
    monkeypatch.setattr(runner, "_pytest_phase", lambda *_args, **_kwargs: pytest.fail(
        "incomplete E2E selection must not execute"
    ))
    with pytest.raises(runner.RegressionError, match="every selected test file"):
        runner.run_native_e2e(tmp_path, tmp_path / "reports")


def test_native_e2e_preflight_failure_removes_stale_success_report(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "native-e2e.xml"
    report.write_text("old successful run")

    def reject(_root):
        raise runner.RegressionError("checkout import mismatch")

    monkeypatch.setattr(runner, "_verify_imports", reject)
    with pytest.raises(runner.RegressionError, match="checkout import mismatch"):
        runner.run_native_e2e(tmp_path, reports)
    assert not report.exists()


@pytest.mark.parametrize("output", ["", "tests/test_one.py::test_one\ntests/test_one.py::test_one"])
def test_collection_refuses_empty_or_duplicate_test_inventory(tmp_path, monkeypatch, output):
    monkeypatch.setattr(runner, "_capture", lambda *_args, **_kwargs: output)
    with pytest.raises(runner.RegressionError, match="empty or contained duplicate"):
        runner._collect(tmp_path, ("tests",))


def test_native_junit_validation_keeps_platform_skips_visible(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_fixture.py").write_text(
        "import pytest\ndef test_platform():\n    pytest.skip('unsupported platform')\n"
    )
    result = runner._pytest_phase(tmp_path, ("tests",), tmp_path / "native-e2e.xml", expected_count=1)
    assert result["exit_code"] == 0
    assert result["tests"] == result["skipped"] == 1
    assert result["failures"] == result["errors"] == 0


def _archive_junit(*, failure=True, damage=None):
    root = ET.Element("testsuites")
    count = runner.ARCHIVE_EXECUTION_COUNT
    suite = ET.SubElement(root, "testsuite", {
        "tests": str(count), "failures": "1" if failure else "0", "errors": "0", "skipped": "0",
    })
    known = ET.SubElement(suite, "testcase", {
        "classname": "tests.test_measurement139_observation",
        "name": runner.ARCHIVE_RETRY_NODE.split("::", 1)[1],
    })
    if failure:
        ET.SubElement(known, "failure", {"message": "first scheduling failure"}).text = "original trace"
    for ordinal in range(count - 1):
        ET.SubElement(suite, "testcase", {
            "classname": "tests.test_historical", "name": f"test_case[{ordinal}]",
        })
    if damage == "other_node":
        known.set("classname", "tests.test_other")
    elif damage == "similar_node":
        known.set("name", known.get("name") + "_similar")
    elif damage == "wrong_file":
        known.set("file", "tests/test_other.py")
    elif damage == "mixed_failures":
        ET.SubElement(suite[-1], "failure")
        suite.set("failures", "2")
    elif damage == "mixed_errors":
        ET.SubElement(suite[-1], "error")
        suite.set("errors", "1")
    elif damage == "skipped":
        ET.SubElement(suite[-1], "skipped")
        suite.set("skipped", "1")
    elif damage == "incomplete_cases":
        suite.remove(suite[-1])
    elif damage == "wrong_count":
        suite.set("tests", str(count - 1))
    elif damage == "duplicate_failure":
        ET.SubElement(known, "failure")
    elif damage == "unreported_error":
        ET.SubElement(suite[-1], "error")
    elif damage == "unreported_skip":
        ET.SubElement(suite[-1], "skipped")
    elif damage == "missing_counters":
        del suite.attrib["errors"]
    return ET.tostring(root)


def _pytest_reports(monkeypatch, reports):
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        content, exit_code = reports[len(calls) - 1]
        report = Path(next(item.partition("=")[2] for item in command if item.startswith("--junitxml=")))
        if content is not None:
            report.write_bytes(content)
        return SimpleNamespace(returncode=exit_code)

    monkeypatch.setattr(runner.subprocess, "run", execute)
    return calls


def test_known_archive_retry_preserves_both_junits_and_attempt_results(tmp_path, monkeypatch, capsys):
    first, second = _archive_junit(), _archive_junit(failure=False)
    calls = _pytest_reports(monkeypatch, [(first, 1), (second, 0)])
    report = tmp_path / "archived.xml"
    retry_report = tmp_path / "archived.retry1.xml"
    retry_report.write_bytes(b"stale success")
    selection = ("tests/test_historical.py", "--deselect=tests/test_registration.py::test_original")
    result = runner._pytest_phase(
        tmp_path, selection, report, expected_count=runner.ARCHIVE_EXECUTION_COUNT,
        frozen=True, historical_retry=True,
    )
    assert len(calls) == 2
    assert calls[0][0][-2:] == calls[1][0][-2:] == list(selection)
    assert report.read_bytes() == first and retry_report.read_bytes() == second
    assert result["exit_code"] == 0 and result["retry_reason"] == runner.ARCHIVE_RETRY_NODE
    attempts = result["attempts"]
    assert [attempt["exit_code"] for attempt in attempts] == [1, 0]
    assert [attempt["junit"] for attempt in attempts] == [str(report), str(retry_report)]
    assert [attempt["junit_sha256"] for attempt in attempts] == [
        hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest(),
    ]
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0] == attempts[0]
    assert output[1]["first_attempt"] == attempts[0]
    assert output[-1] == result


@pytest.mark.parametrize("damage", [
    "other_node", "similar_node", "wrong_file", "mixed_failures", "mixed_errors", "skipped",
    "incomplete_cases", "wrong_count", "duplicate_failure", "unreported_error", "unreported_skip",
    "missing_counters", "malformed_xml", "missing_xml",
])
def test_archive_retry_rejects_unrecognized_or_incomplete_failure_evidence(tmp_path, monkeypatch, damage):
    first = _archive_junit(damage=damage)
    if damage == "malformed_xml":
        first = b"<testsuites>"
    elif damage == "missing_xml":
        first = None
    calls = _pytest_reports(monkeypatch, [(first, 1)])
    result = runner._pytest_phase(
        tmp_path, ("tests",), tmp_path / "archived.xml",
        expected_count=runner.ARCHIVE_EXECUTION_COUNT, frozen=True, historical_retry=True,
    )
    assert len(calls) == 1 and result["exit_code"] == 1
    assert "attempts" not in result and not (tmp_path / "archived.retry1.xml").exists()


@pytest.mark.parametrize("exit_code", [0, 2, 3, 4, 5, -9])
def test_archive_retry_requires_actual_pytest_test_failure_exit(tmp_path, monkeypatch, exit_code):
    calls = _pytest_reports(monkeypatch, [(_archive_junit(), exit_code)])
    result = runner._pytest_phase(
        tmp_path, ("tests",), tmp_path / "archived.xml",
        expected_count=runner.ARCHIVE_EXECUTION_COUNT, frozen=True, historical_retry=True,
    )
    assert len(calls) == 1 and result["exit_code"] != 0
    assert result["pytest_exit_code"] == exit_code and "attempts" not in result


@pytest.mark.parametrize("historical_retry,frozen,count", [
    (False, True, runner.ARCHIVE_EXECUTION_COUNT),
    (True, False, runner.ARCHIVE_EXECUTION_COUNT),
    (True, True, runner.ARCHIVE_EXECUTION_COUNT + 1),
])
def test_current_and_other_inventory_failures_are_never_retried(
    tmp_path, monkeypatch, historical_retry, frozen, count,
):
    calls = _pytest_reports(monkeypatch, [(_archive_junit(), 1)])
    result = runner._pytest_phase(
        tmp_path, ("tests",), tmp_path / "current.xml", expected_count=count,
        frozen=frozen, historical_retry=historical_retry,
    )
    assert len(calls) == 1 and result["exit_code"] == 1 and "attempts" not in result


def test_second_known_archive_failure_still_blocks_without_a_third_attempt(tmp_path, monkeypatch):
    failure = _archive_junit()
    calls = _pytest_reports(monkeypatch, [(failure, 1), (failure, 1)])
    result = runner._pytest_phase(
        tmp_path, ("tests",), tmp_path / "archived.xml",
        expected_count=runner.ARCHIVE_EXECUTION_COUNT, frozen=True, historical_retry=True,
    )
    assert len(calls) == 2 and result["exit_code"] == 1
    assert [attempt["exit_code"] for attempt in result["attempts"]] == [1, 1]
    assert all(Path(attempt["junit"]).read_bytes() == failure for attempt in result["attempts"])


@pytest.mark.parametrize("damage", ["missing_xml", "mixed_errors", "incomplete_cases"])
def test_incomplete_archive_retry_still_blocks_and_preserves_first_failure(tmp_path, monkeypatch, damage):
    first = _archive_junit()
    second = None if damage == "missing_xml" else _archive_junit(failure=False, damage=damage)
    calls = _pytest_reports(monkeypatch, [(first, 1), (second, 0)])
    report = tmp_path / "archived.xml"
    result = runner._pytest_phase(
        tmp_path, ("tests",), report, expected_count=runner.ARCHIVE_EXECUTION_COUNT,
        frozen=True, historical_retry=True,
    )
    assert len(calls) == 2 and result["exit_code"] == 1
    assert [attempt["exit_code"] for attempt in result["attempts"]] == [1, 1]
    assert result["attempts"][1]["pytest_exit_code"] == 0
    assert "validation_error" in result["attempts"][1]
    assert report.read_bytes() == first


def test_real_pytest_known_archive_node_matches_the_retry_identity(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_measurement139_observation.py").write_text(
        "def test_preparation_ceiling_does_not_leak_between_threads():\n    assert False\n"
    )
    result = runner._pytest_phase(
        tmp_path, ("tests",), tmp_path / "archived.xml", expected_count=1, frozen=True,
    )
    assert result["exit_code"] == result["pytest_exit_code"] == 1
    assert result["failed_testcases"] == [{
        "classname": "tests.test_measurement139_observation",
        "name": runner.ARCHIVE_RETRY_NODE.split("::", 1)[1], "file": None,
    }]
