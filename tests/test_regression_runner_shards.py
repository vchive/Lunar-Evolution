"""File-shard release contracts using mock collection and local inert JUnit XML."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("regression_runner_shards", _ROOT / "tools/run_tests.py")
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)
_COMMIT = "a" * 40
_TREE = "b" * 40


def _forbidden(*_args, **_kwargs):
    raise AssertionError("invalid input or isolated suite performed an unexpected effect")


def _assigned(path, count):
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest(), 16) % count


def _inventory(count=3):
    buckets = {index: [] for index in range(count)}
    for ordinal in range(1000):
        path = f"tests/test_bucket_{ordinal}.py"
        bucket = buckets[_assigned(path, count)]
        if len(bucket) < 2:
            bucket.append(path)
        if all(len(files) == 2 for files in buckets.values()):
            break
    assert all(len(files) == 2 for files in buckets.values())
    return tuple(sorted(
        node
        for files in buckets.values()
        for path in files
        for node in (
            f"{path}::test_plain",
            f"{path}::TestGroup::test_parameter[dict::with/slash]",
            f"{path}::TestGroup::test_parameter[unicode-λ]",
        )
    ))


def _digest(nodes):
    return hashlib.sha256(("\n".join(sorted(nodes)) + "\n").encode("utf-8")).hexdigest()


def _key(node):
    path, identity = node.split("::", 1)
    unparameterized, delimiter, parameter = identity.partition("[")
    components = unparameterized.split("::")
    module = path[:-3].replace("/", ".")
    return ".".join((module, *components[:-1])), components[-1] + delimiter + parameter


def _xml(nodes, *, skip=False, failure=False, error=False, counters=None):
    root = ET.Element("testsuites")
    attributes = {
        "tests": str(len(nodes)), "failures": str(int(failure)),
        "errors": str(int(error)), "skipped": str(int(skip)),
    }
    attributes.update(counters or {})
    suite = ET.SubElement(root, "testsuite", attributes)
    for ordinal, node in enumerate(nodes):
        classname, name = _key(node)
        case = ET.SubElement(suite, "testcase", {"classname": classname, "name": name})
        if ordinal == 0:
            if skip:
                ET.SubElement(case, "skipped", {"message": "unsupported platform"})
            if failure:
                ET.SubElement(case, "failure", {"message": "inert failure"})
            if error:
                ET.SubElement(case, "error", {"message": "inert error"})
    return ET.tostring(root)


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_partition_conserves_every_node_and_file_across_collection_order(count):
    nodes = _inventory(count)
    shards = [runner.partition_current_nodes(nodes, shard_index=index, shard_count=count)
              for index in range(count)]
    assert all(type(shard) is tuple and shard == tuple(sorted(shard)) for shard in shards)
    assert sum(map(len, shards)) == len(nodes)
    assert set().union(*map(set, shards)) == set(nodes)
    for index, shard in enumerate(shards):
        assert runner.partition_current_nodes(
            list(reversed(nodes)), shard_index=index, shard_count=count,
        ) == shard
        assert all(_assigned(node.split("::", 1)[0], count) == index for node in shard)
        files = {node.split("::", 1)[0] for node in shard}
        assert set(shard) == {node for node in nodes if node.split("::", 1)[0] in files}
        assert all(set(shard).isdisjoint(other) for other in shards[index + 1:])


def test_empty_pure_partition_does_not_invent_or_reassign_a_file():
    nodes = ("tests/test_one.py::TestGroup::test_parameter[::/value]",)
    selected = (_assigned("tests/test_one.py", 3) + 1) % 3
    assert runner.partition_current_nodes(nodes, shard_index=selected, shard_count=3) == ()


@pytest.mark.parametrize("nodes", [
    None, "tests/test_one.py::test_one", b"tests/test_one.py::test_one", 1, {}, (), [],
    ("tests/test_one.py::test_one", "tests/test_one.py::test_one"),
    (None,), (1,), ("tests/test_one.py",), ("tests/test_one.py::",),
    ("./tests/test_one.py::test_one",), ("/tests/test_one.py::test_one",),
    ("tests/../test_one.py::test_one",), ("tests//test_one.py::test_one",),
    ("tests\\test_one.py::test_one",), ("tests/test_one.txt::test_one",),
    ("tests/test_one.py::test_one\n",),
    ("tests/test_\ud800.py::test_one",), ("tests/test_one.py::test_\udfff",),
    ("tests/test_one.py::TestGroup::::test_one",), ("tests/test_one.py::test_one[unterminated",),
    ("tests/test_one.py::[parameter-without-address]",),
    ("tests/test_a.py::Test::test_x", "tests/test_a/Test.py::test_x"),
], ids=[f"invalid-inventory-{index}" for index in range(25)])
def test_partition_refuses_noncanonical_empty_or_duplicate_inventories(nodes):
    with pytest.raises(runner.RegressionError):
        runner.partition_current_nodes(nodes, shard_index=0, shard_count=3)


@pytest.mark.parametrize("index,count", [
    (False, 3), (True, 3), (0.0, 3), ("0", 3), (-1, 3), (3, 3), (4, 3),
    (0, False), (0, True), (0, 0), (0, -1), (0, 3.0), (0, "3"), (None, 3), (0, None),
])
def test_invalid_shard_bounds_refuse_before_run_current_effects(tmp_path, monkeypatch, index, count):
    for name in ("_verify_imports", "_collect", "_git", "_pytest_phase"):
        monkeypatch.setattr(runner, name, _forbidden)
    monkeypatch.setattr(Path, "resolve", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(Path, "unlink", _forbidden)
    with pytest.raises(runner.RegressionError):
        runner.run_current(tmp_path, tmp_path / "reports", shard_index=index, shard_count=count)


@pytest.mark.parametrize("suite", ["all", "native-e2e", "history"])
@pytest.mark.parametrize("flags", [
    ["--shard-index", "0"], ["--shard-count", "3"],
    ["--shard-index", "0", "--shard-count", "3"],
])
def test_other_suites_refuse_shard_flags_before_dispatch(tmp_path, monkeypatch, suite, flags):
    for name in ("run", "run_native_e2e", "run_current", "run_history"):
        monkeypatch.setattr(runner, name, _forbidden)
    try:
        result = runner.main(["--junit-dir", str(tmp_path), "--suite", suite, *flags])
    except SystemExit as refusal:
        result = refusal.code
    assert result != 0


@pytest.mark.parametrize("flags", [[], ["--shard-index", "0"], ["--shard-count", "3"],
                                    ["--shard-index", "3", "--shard-count", "3"],
                                    ["--shard-index", "0", "--shard-count", "0"]])
def test_current_cli_requires_valid_complete_shard_flags_before_dispatch(tmp_path, monkeypatch, flags):
    monkeypatch.setattr(runner, "run_current", _forbidden)
    try:
        result = runner.main(["--junit-dir", str(tmp_path), "--suite", "current", *flags])
    except SystemExit as refusal:
        result = refusal.code
    assert result != 0


@pytest.mark.parametrize("suite", [None, "all", "native-e2e", "history", "current"])
def test_cli_routes_new_suites_and_preserves_default_all(tmp_path, monkeypatch, suite):
    calls = []
    for name, target in (("run", "all"), ("run_native_e2e", "native-e2e"),
                         ("run_history", "history"), ("run_current", "current")):
        monkeypatch.setattr(runner, name, lambda *args, _target=target, **kwargs: (
            calls.append((_target, args, kwargs)) or 7
        ))
    arguments = ["--junit-dir", str(tmp_path)]
    if suite is not None:
        arguments.extend(("--suite", suite))
    if suite == "current":
        arguments.extend(("--shard-index", "1", "--shard-count", "3"))
    assert runner.main(arguments) == 7
    assert calls == [(suite or "all", (runner.REPO, tmp_path),
                      {"shard_index": 1, "shard_count": 3} if suite == "current" else {})]


@pytest.mark.parametrize("suite,artifact", [
    ("current", "current-shard-1.xml"), ("current", "current-shard-1.summary.json"),
    ("history", "archived.xml"), ("history", "archived.retry1.xml"),
    ("history", "frozen123.xml"), ("history", "history.summary.json"),
])
@pytest.mark.parametrize("kind", ["file", "directory", "live_symlink", "dangling_symlink"])
def test_new_suites_preserve_existing_evidence_before_any_execution(
    tmp_path, monkeypatch, suite, artifact, kind,
):
    reports = tmp_path / "reports"
    reports.mkdir()
    retained = reports / artifact
    original = b"original retained regression evidence\n"
    target = tmp_path / "retained-target"
    if kind == "file":
        retained.write_bytes(original)
    elif kind == "directory":
        retained.mkdir()
        (retained / "original.txt").write_bytes(original)
    else:
        if kind == "live_symlink":
            target.write_bytes(original)
        retained.symlink_to(target)
    inode = retained.lstat().st_ino
    for name in ("_load_index", "_verify_imports", "_collect", "_git", "_snapshot", "_pytest_phase"):
        monkeypatch.setattr(runner, name, _forbidden)
    monkeypatch.setattr(runner.subprocess, "run", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(Path, "unlink", _forbidden)
    with pytest.raises(runner.RegressionError):
        if suite == "current":
            runner.run_current(tmp_path, reports, shard_index=1, shard_count=3)
        else:
            runner.run_history(tmp_path, reports)
    assert retained.lstat().st_ino == inode
    if kind == "directory":
        assert (retained / "original.txt").read_bytes() == original
    elif kind == "dangling_symlink":
        assert retained.is_symlink() and retained.readlink() == target
        assert not target.exists()
    else:
        assert retained.read_bytes() == original
        if kind == "live_symlink":
            assert retained.is_symlink() and retained.readlink() == target


def test_summary_exclusive_creation_preserves_evidence_that_arrived_after_preflight(tmp_path, capsys):
    summary = tmp_path / "current-shard-1.summary.json"
    runner._fresh_reports(tmp_path, (summary.name,))
    original = b'{"retained": "first writer"}\n'
    summary.write_bytes(original)
    inode = summary.stat().st_ino
    with pytest.raises(FileExistsError):
        runner._write_summary(summary, {"retained": "second writer"})
    assert summary.read_bytes() == original and summary.stat().st_ino == inode
    assert capsys.readouterr().out == ""


def _current_mocks(tmp_path, monkeypatch, *, collection_drift=None, xml_drift=None, skip=False):
    nodes = _inventory()
    selected = tuple(node for node in nodes if _assigned(node.split("::", 1)[0], 3) == 1)
    files = tuple(sorted({node.split("::", 1)[0] for node in selected}))
    for relative in files:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"# local inert selected file\n")
    imports = [str(tmp_path / "src/lunar_evolution/__init__.py"),
               str(tmp_path / "src/lunar_evolution/evaluator_bundle.py")]
    calls = []

    def git(_repo, *arguments):
        assert _repo == tmp_path
        if arguments == ("rev-parse", "HEAD"):
            return _COMMIT
        if arguments == ("rev-parse", "HEAD^{tree}"):
            return _TREE
        raise AssertionError(arguments)

    def collect(root, selection, **kwargs):
        assert root == tmp_path
        calls.append(("collect", tuple(selection)))
        if tuple(selection) == ("tests",):
            return nodes
        assert tuple(selection) == files
        if collection_drift == "missing":
            return selected[:-1]
        if collection_drift == "extra":
            return (*selected, next(node for node in nodes if node not in selected))
        if collection_drift == "duplicate":
            return (*selected[:-1], selected[0])
        return tuple(reversed(selected))

    def execute(command, **kwargs):
        calls.append(("execute", tuple(command)))
        assert kwargs["cwd"] == tmp_path
        assert tuple(command[-len(files):]) == files
        xml_nodes = selected
        if xml_drift == "missing":
            xml_nodes = selected[:-1]
        elif xml_drift == "extra":
            xml_nodes = (*selected, "tests/test_unselected.py::test_extra")
        elif xml_drift == "duplicate":
            xml_nodes = (*selected[:-1], selected[0])
        elif xml_drift == "wrong_class":
            xml_nodes = tuple(node.replace("::TestGroup::", "::OtherGroup::") for node in selected)
        elif xml_drift == "wrong_parameter":
            xml_nodes = tuple(node.replace("[dict::with/slash]", "[dict::with/other]") for node in selected)
        report = Path(next(item.split("=", 1)[1] for item in command if item.startswith("--junitxml=")))
        raw = _xml(xml_nodes, skip=skip)
        if xml_drift == "missing_xml":
            return SimpleNamespace(returncode=0)
        if xml_drift == "malformed":
            raw = b"<testsuites>"
        report.write_bytes(raw)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "_git", git)
    monkeypatch.setattr(runner, "_verify_imports", lambda root: imports)
    monkeypatch.setattr(runner, "_collect", collect)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    monkeypatch.setattr(runner, "_load_index", lambda _: {
        "test_files": ["tests/test_retired.py"], "support_files": ["tests/retired_support.py"],
    })
    for name in ("_snapshot", "_archive_python"):
        monkeypatch.setattr(runner, name, _forbidden)
    return nodes, selected, files, imports, calls


@pytest.mark.parametrize("skip", [False, True])
def test_current_records_actual_source_shard_inventory_junit_and_visible_skips(
    tmp_path, monkeypatch, capsys, skip,
):
    nodes, selected, files, imports, calls = _current_mocks(tmp_path, monkeypatch, skip=skip)
    reports = tmp_path / "reports"
    assert runner.run_current(tmp_path, reports, shard_index=1, shard_count=3) == 0
    summary = json.loads((reports / "current-shard-1.summary.json").read_bytes())
    assert summary == json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["schema_version"] == 1
    assert summary["suite"] == "current" and summary["offline"] is True
    assert summary["commit"] == _COMMIT and summary["tree"] == _TREE
    assert summary["working_tree"] is True and summary["imports"] == imports
    assert summary["python"] == sys.executable
    assert summary["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert (summary["shard_index"], summary["shard_count"]) == (1, 3)
    assert summary["shard_algorithm"] == "sha256-path-utf8-mod-v1"
    assert summary["full_nodes"] == list(nodes)
    assert summary["full_collected"] == len(nodes)
    assert summary["full_inventory_sha256"] == _digest(nodes)
    assert summary["selected_nodes"] == list(selected)
    assert summary["selected_files"] == list(files)
    assert summary["selected_inventory_sha256"] == _digest(selected)
    assert summary["collected"] == summary["tests"] == summary["reported_testcases"] == len(selected)
    assert summary["skipped"] == summary["skipped_elements"] == int(skip)
    assert summary["failures"] == summary["errors"] == summary["exit_code"] == 0
    assert summary["junit"] == str(reports / "current-shard-1.xml")
    assert summary["junit_sha256"] == hashlib.sha256((reports / "current-shard-1.xml").read_bytes()).hexdigest()
    assert not (reports / "current.xml").exists()
    assert [call[0] for call in calls] == ["collect", "collect", "execute"]


@pytest.mark.parametrize("drift", ["missing", "extra", "duplicate"])
def test_selected_recollection_drift_refuses_before_executing_tests(tmp_path, monkeypatch, drift):
    *_, calls = _current_mocks(tmp_path, monkeypatch, collection_drift=drift)
    with pytest.raises(runner.RegressionError):
        runner.run_current(tmp_path, tmp_path / "reports", shard_index=1, shard_count=3)
    assert [call[0] for call in calls] == ["collect", "collect"]


@pytest.mark.parametrize("drift", [
    "missing", "extra", "duplicate", "wrong_class", "wrong_parameter", "missing_xml", "malformed",
])
def test_current_junit_drift_cannot_report_success_even_with_pytest_zero(tmp_path, monkeypatch, drift):
    _current_mocks(tmp_path, monkeypatch, xml_drift=drift)
    reports = tmp_path / "reports"
    assert runner.run_current(tmp_path, reports, shard_index=1, shard_count=3) != 0
    summary = json.loads((reports / "current-shard-1.summary.json").read_bytes())
    assert summary["pytest_exit_code"] == 0 and summary["exit_code"] != 0
    assert summary["validation_error"]
    if drift != "missing_xml":
        assert (reports / "current-shard-1.xml").exists()


def test_current_refuses_empty_selected_shard_without_running_or_reassigning(tmp_path, monkeypatch):
    node = "tests/test_one.py::test_one"
    selected = (_assigned("tests/test_one.py", 3) + 1) % 3
    monkeypatch.setattr(runner, "_verify_imports", lambda _: [])
    monkeypatch.setattr(runner, "_collect", lambda *_args, **_kwargs: (node,))
    monkeypatch.setattr(runner, "_load_index", lambda _: {"test_files": [], "support_files": []})
    monkeypatch.setattr(runner, "_git", lambda *_args: _COMMIT)
    monkeypatch.setattr(runner, "_pytest_phase", _forbidden)
    with pytest.raises(runner.RegressionError):
        runner.run_current(tmp_path, tmp_path / "reports", shard_index=selected, shard_count=3)


@pytest.mark.parametrize("node", [
    "tests/test_one.py::test_one", "tests/nested/test_one.py::TestGroup::test_one[param::/value]",
    "tests/test_one.py::TestGroup::TestNested::test_one[λ]",
])
def test_junit_case_key_preserves_class_and_complete_parameter_identity(node):
    assert runner._junit_case_key(node) == _key(node)


def test_junit_case_key_escapes_nonxml_parameter_using_pytest_literal_spelling():
    assert runner._junit_case_key("tests/test_one.py::test_one[\uffff]") == (
        "tests.test_one", "test_one[#xFFFF]",
    )


def test_partition_refuses_distinct_nodes_with_same_escaped_junit_key():
    nodes = ("tests/test_one.py::test_one[\uffff]", "tests/test_one.py::test_one[#xFFFF]")
    with pytest.raises(runner.RegressionError):
        runner.partition_current_nodes(nodes, shard_index=0, shard_count=3)


def test_real_inert_pytest_class_and_parameter_ids_match_retained_junit(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_local.py").write_text(
        "import pytest\n"
        "class TestLocal:\n"
        "    @pytest.mark.parametrize('value', [1, 2], ids=['dict::with/slash', 'plain'])\n"
        "    def test_value(self, value):\n"
        "        assert value in (1, 2)\n",
        encoding="utf-8",
    )
    nodes = runner._collect(tmp_path, ("tests",))
    assert nodes == (
        "tests/test_local.py::TestLocal::test_value[dict::with/slash]",
        "tests/test_local.py::TestLocal::test_value[plain]",
    )
    report = tmp_path / "local.xml"
    result = runner._pytest_phase(
        tmp_path, ("tests",), report, expected_count=2, expected_nodes=nodes,
    )
    assert result["exit_code"] == result["pytest_exit_code"] == 0
    assert result["tests"] == result["reported_testcases"] == 2
    assert sorted((case.get("classname"), case.get("name"))
                  for case in ET.parse(report).iter("testcase")) == sorted(map(_key, nodes))


@pytest.mark.parametrize("damage", ["failure", "error", "unreported_skip", "wrong_skip_count"])
def test_exact_case_inventory_still_requires_failure_error_and_skip_counters_to_match(tmp_path, damage):
    nodes = ("tests/test_one.py::test_one",)
    raw = _xml(
        nodes, failure=damage == "failure", error=damage == "error",
        skip=damage == "unreported_skip",
        counters={"skipped": "0"} if damage == "unreported_skip" else (
            {"skipped": "1"} if damage == "wrong_skip_count" else {}
        ),
    )
    report = tmp_path / "shard.xml"
    report.write_bytes(raw)
    result = runner._junit_summary(report, pytest_exit_code=0, expected_count=1, expected_nodes=nodes)
    assert result["exit_code"] != 0 and result["validation_error"]


@pytest.mark.parametrize("exit_codes", [(0, 0), (1, 0), (0, 2)])
def test_history_retains_original_source_pins_retry_rules_and_reports_only_history(
    tmp_path, monkeypatch, capsys, exit_codes,
):
    checkout = tmp_path / "checkout"
    archive = tmp_path / "archive"
    frozen = tmp_path / "frozen"
    for root in (checkout, archive, frozen):
        root.mkdir()
    registration = "tests/test_original_registration.py"
    (archive / "tests").mkdir()
    (archive / registration).write_bytes(b"original registration")
    bound = tuple(f"{registration}::test_registered[{index}]" for index in range(24))
    index = {"test_files": [registration], "support_files": ["tests/support.py"]}
    manifest = {"measurement_files": {registration: hashlib.sha256(b"original registration").hexdigest()}}
    snapshots, verifications, phases, collections, imports = [], [], [], [], []

    @contextmanager
    def snapshot(repo, commit, label):
        assert repo == checkout
        root = archive if commit == runner.ARCHIVE_COMMIT else frozen
        snapshots.append((commit, label))
        yield root

    def collect(root, selection, **kwargs):
        collections.append((root, tuple(selection), kwargs))
        assert root in (archive, frozen)
        return bound

    def phase(root, selection, report, **kwargs):
        phases.append((root, tuple(selection), report, kwargs))
        return {"exit_code": exit_codes[len(phases) - 1], "junit": str(report)}

    def verify_imports(root, **kwargs):
        imports.append((root, kwargs))
        return [str(root / "src/product/__init__.py"), str(root / "src/product/evaluator_bundle.py")]

    monkeypatch.setattr(runner, "_snapshot", snapshot)
    monkeypatch.setattr(runner, "_load_index", lambda _: index)
    monkeypatch.setattr(runner, "_verify_archive", lambda *_: verifications.append("archive"))
    monkeypatch.setattr(runner, "_verify_frozen", lambda *_: (verifications.append("frozen") or manifest))
    monkeypatch.setattr(runner, "_archive_python", lambda root: root / ".venv/bin/python")
    monkeypatch.setattr(runner, "_archived_package", lambda _: "product")
    monkeypatch.setattr(runner, "_verify_imports", verify_imports)
    monkeypatch.setattr(runner, "_registration_selection", lambda *_args, **_kwargs: (registration, bound))
    monkeypatch.setattr(runner, "_collect", collect)
    monkeypatch.setattr(runner, "_archive_selection", lambda *_: runner.ARCHIVE_EXECUTION_COUNT)
    monkeypatch.setattr(runner, "_pytest_phase", phase)
    monkeypatch.setattr(runner, "_git", lambda _, *args: _TREE if args[-1] == "HEAD^{tree}" else _COMMIT)
    reports = tmp_path / "reports"
    assert runner.run_history(checkout, reports) == (exit_codes[0] or exit_codes[1])
    result = json.loads((reports / "history.summary.json").read_bytes())
    assert result == json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["suite"] == "history" and result["offline"] is True
    assert result["checkout"]["commit"] == _COMMIT and result["checkout"]["tree"] == _TREE
    assert result["checkout"]["working_tree"] is True
    assert result["checkout"]["imports"] == [str(checkout / "src/product/__init__.py"),
                                                str(checkout / "src/product/evaluator_bundle.py")]
    assert result["archived"]["commit"] == runner.ARCHIVE_COMMIT
    assert result["archived"]["collection_sha256"] == runner.ARCHIVE_COLLECTION_SHA256
    assert result["frozen123"]["commit"] == runner.FROZEN_COMMIT
    assert result["frozen123"]["product_commit"] == runner.PRODUCT_COMMIT
    assert result["frozen123"]["pins"] == runner.PIN_COUNTS
    assert "current" not in result and not (reports / "current.xml").exists()
    assert [item[0] for item in snapshots] == [runner.ARCHIVE_COMMIT, runner.FROZEN_COMMIT]
    assert verifications == ["archive", "frozen", "archive", "frozen"]
    assert [item[0] for item in imports] == [checkout, archive, frozen]
    assert [item[0] for item in collections] == [archive, frozen]
    assert [item[0] for item in phases] == [archive, frozen]
    assert phases[0][1] == (registration, *(f"--deselect={node}" for node in bound))
    assert phases[1][1] == bound
    assert [item[2].name for item in phases] == ["archived.xml", "frozen123.xml"]
    assert phases[0][3] == {
        "expected_count": 2294, "frozen": True, "python": archive / ".venv/bin/python",
        "historical_retry": True,
    }
    assert phases[1][3] == {
        "expected_count": 24, "frozen": True, "python": frozen / ".venv/bin/python",
    }


def test_parallel_runner_keeps_all_historical_identity_and_count_constants():
    assert runner.ARCHIVE_COMMIT == "c6947fdfbf43d84e83cc29cc215e7bc0250db83a"
    assert runner.FROZEN_COMMIT == "5560eb9f67463badc31fed17e309bb5dc1dabf8f"
    assert runner.PRODUCT_COMMIT == "519fea5ca70ac1ede3df356ee7391112801ab45d"
    assert runner.MANIFEST_SHA256 == "9d05c7d95eb427f60d7be7a93dbfb8c7c53ec50904169e0391053292315f60a7"
    assert runner.PIN_COUNTS == {"product_files": 77, "measurement_files": 14, "historical_files": 69}
    assert runner.ARCHIVE_COLLECTION_COUNT == 2318
    assert runner.ARCHIVE_EXECUTION_COUNT == 2294
    assert runner.REGISTRATION_COUNT == 24
    assert runner.UV_VERSION == "0.11.8"
