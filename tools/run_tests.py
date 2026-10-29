"""Run release regressions or the focused offline native E2E suite.

Historical files are restored from fixed Git commits outside the current checkout. Their
bytes and exact test inventories remain unchanged; no provider or campaign is invoked.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path, PurePosixPath

from _pytest.junitxml import bin_xml_escape, mangle_test_address

REPO = Path(__file__).resolve().parents[1]
ARCHIVE_INDEX = "docs/history-archive.json"
ARCHIVE_COMMIT = "c6947fdfbf43d84e83cc29cc215e7bc0250db83a"
FROZEN_COMMIT = "5560eb9f67463badc31fed17e309bb5dc1dabf8f"
PRODUCT_COMMIT = "519fea5ca70ac1ede3df356ee7391112801ab45d"
MANIFEST_PATH = "specs/123-small-evaluator-diagnostic/measurement/manifest.json"
MANIFEST_SHA256 = "9d05c7d95eb427f60d7be7a93dbfb8c7c53ec50904169e0391053292315f60a7"
PIN_COUNTS = {"product_files": 77, "measurement_files": 14, "historical_files": 69}
ARCHIVE_FILE_COUNT = 844
ARCHIVE_TEST_FILE_COUNT = 73
ARCHIVE_COLLECTION_COUNT = 2318
ARCHIVE_EXECUTION_COUNT = 2294
REGISTRATION_COUNT = 24
ARCHIVE_COLLECTION_SHA256 = "1f5259be4ab980b16b60dfef08e7c8842f3562ecc7e3974b002f863cbc249001"
UV_VERSION = "0.11.8"
SHARD_ALGORITHM = "sha256-path-utf8-mod-v1"
HEAVY_SHARD_ALGORITHM = "sha256-path-utf8-mod-six-drs-brs-heavy-v3"
HEAVY_CURRENT_FILE = "tests/test_rsi_multi_episode_rejection_flow.py"
HEAVY_BRS_CURRENT_FILE = "tests/test_rsi_brs_reserved_serial_integration.py"
HEAVY_CURRENT_FILES = (HEAVY_CURRENT_FILE, HEAVY_BRS_CURRENT_FILE)
HEAVY_DRS_CURRENT_NODES = tuple(
    f"{HEAVY_CURRENT_FILE}::"
    "test_original_three_attempt_mixed_drs_and_terminal_readonly_replay"
    f"[{identity}]"
    for identity in ("V2-T1-RPP", "V2-T2-PRP", "V2-T3-RRR")
)
HEAVY_BRS_CURRENT_NODES = tuple(
    f"{HEAVY_BRS_CURRENT_FILE}::"
    "test_natural_reserved_children_complete_in_original_order"
    f"[{identity}]"
    for identity in ("rejected-rejected", "published-published", "published-rejected", "three-child-mixed")
)
# Preserve the original DRS role identities; each BRS wave gets its own fresh
# pytest process instead of sharing one ordinary file shard with all four.
HEAVY_CURRENT_NODES = (*HEAVY_DRS_CURRENT_NODES, *HEAVY_BRS_CURRENT_NODES)
NATIVE_E2E_SELECTION = (
    "tests/test_automatic_detach_phase_c.py",
    "tests/test_conversational_automatic_bundle.py",
    "tests/test_automatic_solve_bundle.py",
    "tests/test_automatic_cancel_phase_b.py",
    "tests/test_automatic_solve_deadline_integration.py",
    "tests/test_automatic_runtime_processes.py",
    "tests/test_identity_installation.py",
)
ARCHIVE_RETRY_NODE = (
    "tests/test_measurement139_observation.py::"
    "test_preparation_ceiling_does_not_leak_between_threads"
)
_DIAGNOSTICS = ContextVar("regression_diagnostics", default=None)
_DIAGNOSTIC_OBSERVATION = ContextVar("regression_diagnostic_observation", default=None)
_DIAGNOSTIC_ATTEMPT = ContextVar("regression_diagnostic_attempt", default=1)
_DIAGNOSTIC_TEST_STACK_SECONDS = 300


@contextmanager
def _diagnostics(enabled, *, suite, role):
    """Scope explicitly selected diagnostics to this invocation, including failures."""
    token = _DIAGNOSTICS.set((suite, role) if enabled else None)
    observation_token = _DIAGNOSTIC_OBSERVATION.set(None)
    attempt_token = _DIAGNOSTIC_ATTEMPT.set(1)
    try:
        yield
    finally:
        _DIAGNOSTIC_ATTEMPT.reset(attempt_token)
        _DIAGNOSTIC_OBSERVATION.reset(observation_token)
        _DIAGNOSTICS.reset(token)


@contextmanager
def _diagnostic_phase(phase, **counts):
    context = _DIAGNOSTICS.get()
    if context is None:
        yield None
        return
    suite, role = context
    common = {"schema": "lunar-ci-stage-diagnostic-v1", "suite": suite, "role": role,
              "phase": phase, **counts}
    print("lunar-ci-diagnostic " + json.dumps({**common, "event": "start"}, sort_keys=True),
          flush=True)
    started = time.monotonic()
    observation = {"exit_code": None}
    token = _DIAGNOSTIC_OBSERVATION.set(observation)
    error_type = None
    try:
        yield observation
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        _DIAGNOSTIC_OBSERVATION.reset(token)
        print("lunar-ci-diagnostic " + json.dumps({
            **common, **observation, "event": "end", "error_type": error_type,
            "elapsed_seconds": time.monotonic() - started,
        }, sort_keys=True), flush=True)


@contextmanager
def _diagnostic_attempt(number):
    token = _DIAGNOSTIC_ATTEMPT.set(number)
    try:
        yield
    finally:
        _DIAGNOSTIC_ATTEMPT.reset(token)


class RegressionError(RuntimeError):
    pass


def _capture(command, root, *, environment=None):
    result = subprocess.run(
        command, cwd=root, env=environment, text=True, capture_output=True, check=False,
    )
    observation = _DIAGNOSTIC_OBSERVATION.get()
    if observation is not None:
        observation["exit_code"] = result.returncode
    if result.returncode:
        raise RegressionError(f"command failed ({result.returncode}): {' '.join(map(str, command[:3]))}\n"
                              + result.stdout + result.stderr)
    return result.stdout.strip()


def _git(root, *arguments):
    return _capture(["git", *arguments], root)


def _environment(root):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    return environment


def _load_index(repo):
    index = json.loads((repo / ARCHIVE_INDEX).read_bytes())
    if (index.get("schema_version") != "1" or index.get("archive_commit") != ARCHIVE_COMMIT
            or index.get("file_count") != ARCHIVE_FILE_COUNT
            or len(index.get("files", {})) != ARCHIVE_FILE_COUNT
            or len(index.get("rootdirs", [])) != 35
            or len(index.get("support_files", [])) != 3
            or len(index.get("test_files", [])) != ARCHIVE_TEST_FILE_COUNT
            or index.get("archived_tests") != {
                "collected": ARCHIVE_COLLECTION_COUNT, "executed": ARCHIVE_EXECUTION_COUNT,
                "collection_sha256": ARCHIVE_COLLECTION_SHA256,
            }
            or index.get("frozen_registration") != {
                "commit": FROZEN_COMMIT, "product_commit": PRODUCT_COMMIT,
                "manifest": MANIFEST_PATH, "manifest_sha256": MANIFEST_SHA256,
                "pin_counts": PIN_COUNTS, "exact_test_count": REGISTRATION_COUNT,
            }):
        raise RegressionError("historical archive index identity changed")
    return index


def _regular_file(root, name):
    relative = PurePosixPath(name)
    path = root / relative
    if (relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name
            or path.is_symlink() or not path.is_file()
            or path.resolve() != path.absolute()):
        raise RegressionError(f"invalid registered file: {name}")
    return path


@contextmanager
def _snapshot(repo, commit, label):
    # A configured TMPDIR inside the product tree must not restore retired files there.
    with tempfile.TemporaryDirectory(prefix="le-regression-") as directory:
        snapshot = Path(directory).resolve() / label
        if snapshot.is_relative_to(repo.resolve()):
            raise RegressionError("historical temporary directory must be outside the checkout")
        added = False
        try:
            _git(repo, "worktree", "add", "--detach", str(snapshot), commit)
            added = True
            yield snapshot
        finally:
            if added or snapshot.exists():
                _git(repo, "worktree", "remove", "--force", str(snapshot))


def _verify_archive(snapshot, index):
    if _git(snapshot, "rev-parse", "HEAD") != ARCHIVE_COMMIT:
        raise RegressionError("archived worktree is not the fixed migration baseline")
    selections = (*index["rootdirs"], *index["support_files"], *index["test_files"])
    tracked = set(_git(snapshot, "ls-files", "--", *selections).splitlines())
    if tracked != set(index["files"]):
        raise RegressionError("historical archive file set changed")
    for name, expected in index["files"].items():
        raw = _regular_file(snapshot, name).read_bytes()
        if expected != {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}:
            raise RegressionError(f"archived file changed: {name}")
    _git(snapshot, "diff", "--exit-code", "HEAD", "--", "src", "pyproject.toml")


def _verify_frozen(snapshot):
    if _git(snapshot, "rev-parse", "HEAD") != FROZEN_COMMIT:
        raise RegressionError("frozen worktree is not the fixed Feature 123 commit")
    _git(snapshot, "diff", "--exit-code", PRODUCT_COMMIT, FROZEN_COMMIT, "--", "src", "pyproject.toml")
    raw = _regular_file(snapshot, MANIFEST_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise RegressionError("immutable Feature 123 manifest changed")
    manifest = json.loads(raw)
    if manifest["product_commit"] != PRODUCT_COMMIT:
        raise RegressionError("registered product commit changed")
    for group, count in PIN_COUNTS.items():
        pins = manifest[group]
        if len(pins) != count:
            raise RegressionError(f"registered {group} count changed")
        for name, digest in pins.items():
            if hashlib.sha256(_regular_file(snapshot, name).read_bytes()).hexdigest() != digest:
                raise RegressionError(f"registered file changed: {name}")
    tracked = set(_git(snapshot, "ls-files", "src", "pyproject.toml").splitlines())
    sources = {path.relative_to(snapshot).as_posix() for path in (snapshot / "src").rglob("*.py")}
    if (tracked != set(manifest["product_files"])
            or sources != {name for name in tracked if name.startswith("src/") and name.endswith(".py")}):
        raise RegressionError("registered product file set changed")
    return manifest


def _archived_package(snapshot):
    project = tomllib.loads((snapshot / "pyproject.toml").read_text())["project"]
    packages = {target.partition(":")[0].split(".")[0]
                for target in project["scripts"].values()}
    if len(packages) != 1:
        raise RegressionError("archived package identity is ambiguous")
    package = packages.pop()
    if not package.isidentifier():
        raise RegressionError("archived package identity is invalid")
    _regular_file(snapshot, f"src/{package}/__init__.py")
    return package


def _archive_python(snapshot):
    version = _capture(["uv", "--version"], snapshot).split()
    if len(version) < 2 or version[:2] != ["uv", UV_VERSION]:
        raise RegressionError(f"historical console identity requires uv {UV_VERSION}")
    environment = _environment(snapshot)
    _capture(["uv", "venv", "--offline", "--no-config", "--no-python-downloads",
              "--python", sys.executable, str(snapshot / ".venv")],
             snapshot, environment=environment)
    python = snapshot / ".venv/bin/python"
    # The current package install warms the same build/test wheels in uv's cache.
    # Offline installation gives the historical launcher its own real editable import path.
    _capture(["uv", "pip", "install", "--offline", "--no-config", "--python", str(python),
              "-e", f"{snapshot}[dev]", f"pytest=={importlib.metadata.version('pytest')}"],
             snapshot, environment=environment)
    return python


def _verify_imports(root, *, python=sys.executable, package="lunar_evolution"):
    code = (
        "import importlib, json, sys; "
        "modules = [importlib.import_module(sys.argv[1]), "
        "importlib.import_module(sys.argv[1] + '.evaluator_bundle')]; "
        "print(json.dumps([module.__file__ for module in modules]))"
    )
    origins = json.loads(_capture([str(python), "-c", code, package], root,
                                  environment=_environment(root)))
    expected = [root / "src" / package / name for name in ("__init__.py", "evaluator_bundle.py")]
    if [Path(path).resolve() for path in origins] != [path.resolve() for path in expected]:
        raise RegressionError("Python imported the product from a different checkout")
    return origins


def _collect(root, selections, *, python=sys.executable):
    selections = tuple(selections)
    with _diagnostic_phase("collection", selection_count=len(selections)) as observation:
        output = _capture(
            [str(python), "-m", "pytest", "-o", "addopts=", "--collect-only", "-q", "--color=no", *selections],
            root, environment=_environment(root),
        )
        nodes = tuple(line for line in output.splitlines()
                      if line.startswith("tests/") and "::" in line)
        if observation is not None:
            observation["collected_count"] = len(nodes)
        if not nodes or len(set(nodes)) != len(nodes):
            raise RegressionError("pytest collection was empty or contained duplicate node IDs")
    return nodes


def _registration_selection(snapshot, manifest, *, python=sys.executable):
    paths = [name for name in manifest["measurement_files"]
             if name.startswith("tests/test_") and name.endswith("_registration.py")]
    if len(paths) != 1:
        raise RegressionError("original registration test identity is ambiguous")
    path = paths[0]
    parsed = ast.parse(_regular_file(snapshot, path).read_text())
    functions = {item.name for item in parsed.body if isinstance(item, ast.FunctionDef)
                 and item.name.startswith("test_")
                 and any(argument.arg == "registered" for argument in item.args.args)}
    nodes = _collect(snapshot, (path,), python=python)
    selected = tuple(node for node in nodes
                     if node.split("::", 1)[1].split("[", 1)[0] in functions)
    if len(selected) != REGISTRATION_COUNT:
        raise RegressionError("original registration collection must contain exactly 24 nodes")
    return path, selected


def _archive_selection(nodes, bound):
    digest = hashlib.sha256(("\n".join(sorted(nodes)) + "\n").encode()).hexdigest()
    if len(nodes) != ARCHIVE_COLLECTION_COUNT or digest != ARCHIVE_COLLECTION_SHA256:
        raise RegressionError("archived test collection differs from its original inventory")
    removed = tuple(node for node in nodes if node.startswith(bound))
    if (len(bound) != REGISTRATION_COUNT or len(set(bound)) != REGISTRATION_COUNT
            or len(removed) != REGISTRATION_COUNT or set(removed) != set(bound)
            or len(nodes) - len(removed) != ARCHIVE_EXECUTION_COUNT):
        raise RegressionError("archived collection must defer exactly the 24 original registration nodes")
    return ARCHIVE_EXECUTION_COUNT


def _shard_bounds(shard_index, shard_count):
    if (type(shard_index) is not int or type(shard_count) is not int
            or shard_count <= 0 or not 0 <= shard_index < shard_count):
        raise RegressionError("invalid current shard index/count")


def _current_nodes(nodes):
    """Validate supplied identities without filesystem access or callbacks."""
    if type(nodes) not in (tuple, list) or not nodes:
        raise RegressionError("current inventory must be a nonempty list or tuple")
    checked = []
    keys = set()
    for node in nodes:
        if type(node) is not str or any(
            ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF
            for char in node
        ):
            raise RegressionError("invalid current collection node")
        filename, separator, address = node.partition("::")
        path = PurePosixPath(filename)
        base, bracket, parameters = address.partition("[")
        if (not separator or not base or any(not part for part in base.split("::"))
                or (bracket and not parameters.endswith("]"))
                or not filename or "\\" in filename or "[" in filename
                or path.is_absolute() or ".." in path.parts
                or len(path.parts) < 2 or path.parts[0] != "tests"
                or path.suffix != ".py" or path.as_posix() != filename):
            raise RegressionError("invalid current collection node")
        key = _junit_case_key(node)
        if bin_xml_escape(key[0]) != key[0]:
            raise RegressionError("invalid current collection classname")
        if key in keys:
            raise RegressionError("current inventory contained duplicate node/case keys")
        keys.add(key)
        checked.append(node)
    return tuple(sorted(checked))


def _junit_case_key(node):
    # Match pytest's address mangling: parameter text may itself contain :: or /.
    names = mangle_test_address(node)
    return ".".join(names[:-1]), bin_xml_escape(names[-1])


def _inventory_sha256(nodes):
    return hashlib.sha256(("\n".join(sorted(nodes)) + "\n").encode("utf-8")).hexdigest()


def partition_current_nodes(nodes, *, shard_index, shard_count):
    """Select complete files deterministically; an unassigned shard can be empty."""
    _shard_bounds(shard_index, shard_count)
    checked = _current_nodes(nodes)
    return tuple(node for node in checked if int(hashlib.sha256(
        node.partition("::")[0].encode("utf-8"),
    ).hexdigest(), 16) % shard_count == shard_index)


def _heavy_index(heavy_index):
    if type(heavy_index) is not int or not 0 <= heavy_index < len(HEAVY_CURRENT_NODES):
        raise RegressionError("invalid current heavy index")


def _heavy_inventory(nodes):
    checked = _current_nodes(nodes)
    actual = tuple(node for node in checked if node.partition("::")[0] in HEAVY_CURRENT_FILES)
    if actual != tuple(sorted(HEAVY_CURRENT_NODES)):
        raise RegressionError("explicit heavy files changed their exact collection inventory")
    return checked


def partition_isolated_current_nodes(nodes, *, shard_index, shard_count):
    """Keep six whole-file shards and reserve every explicit DRS/BRS heavy node."""
    _shard_bounds(shard_index, shard_count)
    if shard_count != 6:
        raise RegressionError("isolated heavy schedule requires six ordinary shards")
    checked = _heavy_inventory(nodes)
    return tuple(node for node in partition_current_nodes(
        checked, shard_index=shard_index, shard_count=shard_count,
    ) if node.partition("::")[0] not in HEAVY_CURRENT_FILES)


def partition_heavy_current_nodes(nodes, *, heavy_index):
    """Select one reviewed function-scoped mixed case without hashing other nodes."""
    _heavy_index(heavy_index)
    _heavy_inventory(nodes)
    return (HEAVY_CURRENT_NODES[heavy_index],)


def _junit_summary(report, *, pytest_exit_code, expected_count, frozen=False,
                   expected_nodes=None):
    """Read one retained report without running tests or changing evidence."""
    summary = {
        "exit_code": pytest_exit_code, "pytest_exit_code": pytest_exit_code, "junit": str(report),
    }
    try:
        tree = ET.parse(report).getroot()
        suites = list(tree.iter("testsuite"))
        cases = list(tree.iter("testcase"))
        summary.update({field: sum(int(suite.attrib[field]) for suite in suites)
                        for field in ("tests", "failures", "errors", "skipped")})
        summary["failed_testcases"] = [
            {key: case.attrib.get(key) for key in ("classname", "name", "file")}
            for case in cases if case.find("failure") is not None
        ]
        summary["reported_testcases"] = len(cases)
        summary["failure_elements"] = len(list(tree.iter("failure")))
        summary["error_elements"] = len(list(tree.iter("error")))
        summary["skipped_elements"] = len(list(tree.iter("skipped")))
        summary["junit_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
        complete = (
            bool(suites) and summary["tests"] == expected_count
            and len(cases) == expected_count
            and not summary["failures"] and not summary["errors"]
            and not summary["failure_elements"] and not summary["error_elements"]
        )
        if frozen:
            complete = complete and summary["skipped"] == summary["skipped_elements"] == 0
        if expected_nodes is not None:
            expected = sorted(_junit_case_key(node) for node in _current_nodes(expected_nodes))
            actual = [(case.get("classname", ""), case.get("name", "")) for case in cases]
            exact = (len(expected) == expected_count and len(actual) == len(set(actual))
                     and sorted(actual) == expected
                     and summary["failures"] == summary["failure_elements"]
                     and summary["errors"] == summary["error_elements"]
                     and summary["skipped"] == summary["skipped_elements"])
            summary["exact_case_keys"] = exact
            summary["expected_inventory_sha256"] = _inventory_sha256(expected_nodes)
            if not exact:
                summary["validation_error"] = "JUnit case keys differ from selected current inventory"
            complete = complete and exact
        if not complete:
            summary["exit_code"] = pytest_exit_code or 1
            summary.setdefault("validation_error", "JUnit did not confirm the expected executed test set")
    except (OSError, KeyError, ValueError, ET.ParseError):
        summary["exit_code"] = pytest_exit_code or 1
        summary["validation_error"] = "pytest did not produce a readable JUnit report"
    return summary


def _pytest_attempt(root, selections, report, *, expected_count, frozen=False, python=sys.executable,
                    expected_nodes=None):
    if report.exists():
        report.unlink()
    diagnostics = _DIAGNOSTICS.get() is not None
    verbosity = "-v" if diagnostics else "-q"
    command = [str(python), "-m", "pytest", "-o", "addopts=", verbosity, "--color=no"]
    if diagnostics:
        # Pytest's built-in observer dumps stacks without ending or retrying a test.
        command.extend(["-o", f"faulthandler_timeout={_DIAGNOSTIC_TEST_STACK_SECONDS}"])
    command.extend([f"--junitxml={report}", *selections])
    with _diagnostic_phase("pytest", expected_count=expected_count,
                           attempt=_DIAGNOSTIC_ATTEMPT.get()) as observation:
        result = subprocess.run(command, cwd=root, env=_environment(root), check=False)
        if observation is not None:
            observation["exit_code"] = result.returncode
        summary = _junit_summary(
            report, pytest_exit_code=result.returncode, expected_count=expected_count, frozen=frozen,
            **({"expected_nodes": expected_nodes} if expected_nodes is not None else {}),
        )
        if observation is not None:
            observation["validation_exit_code"] = summary["exit_code"]
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def _known_archive_failure(summary, *, expected_count, frozen):
    failed = summary.get("failed_testcases", [])
    return (
        frozen and expected_count == ARCHIVE_EXECUTION_COUNT
        and summary.get("exit_code") == summary.get("pytest_exit_code") == 1
        and summary.get("tests") == summary.get("reported_testcases") == expected_count
        and summary.get("failures") == summary.get("failure_elements") == 1
        and summary.get("errors") == summary.get("error_elements") == 0
        and summary.get("skipped") == summary.get("skipped_elements") == 0
        and len(failed) == 1
        and failed[0].get("classname") == "tests.test_measurement139_observation"
        and failed[0].get("name") == ARCHIVE_RETRY_NODE.split("::", 1)[1]
        and failed[0].get("file") in (None, ARCHIVE_RETRY_NODE.split("::", 1)[0])
        and isinstance(summary.get("junit_sha256"), str)
    )


def _pytest_phase(root, selections, report, *, expected_count, frozen=False, python=sys.executable,
                  historical_retry=False, expected_nodes=None):
    retry_report = report.with_name(f"{report.stem}.retry1{report.suffix}")
    if historical_retry:
        # Do not leave a previous invocation's successful retry beside a new failed attempt.
        retry_report.unlink(missing_ok=True)
    with _diagnostic_attempt(1):
        first = _pytest_attempt(
            root, selections, report, expected_count=expected_count, frozen=frozen, python=python,
            **({"expected_nodes": expected_nodes} if expected_nodes is not None else {}),
        )
    if not historical_retry or not _known_archive_failure(
        first, expected_count=expected_count, frozen=frozen,
    ):
        return first
    # The fixed archive cannot be edited. Preserve its sole known scheduling failure verbatim,
    # retry the complete inventory once, and keep both attempts in the final machine report.
    print(json.dumps({
        "phase": "historical_archive", "retry": 1,
        "retry_reason": ARCHIVE_RETRY_NODE, "first_attempt": first,
    }, sort_keys=True), flush=True)
    with _diagnostic_attempt(2):
        second = _pytest_attempt(
            root, selections, retry_report, expected_count=expected_count, frozen=frozen, python=python,
            **({"expected_nodes": expected_nodes} if expected_nodes is not None else {}),
        )
    result = {
        **second, "retry_reason": ARCHIVE_RETRY_NODE, "attempts": [first, second],
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def run_native_e2e(repo, junit_dir):
    repo, junit_dir = repo.resolve(), junit_dir.resolve()
    junit_dir.mkdir(parents=True, exist_ok=True)
    report = junit_dir / "native-e2e.xml"
    report.unlink(missing_ok=True)
    origins = _verify_imports(repo)
    nodes = _collect(repo, NATIVE_E2E_SELECTION)
    if {node.split("::", 1)[0] for node in nodes} != set(NATIVE_E2E_SELECTION):
        raise RegressionError("native E2E collection must include every selected test file")
    version = {
        "suite": "native-e2e", "offline": True,
        "commit": _git(repo, "rev-parse", "HEAD"), "working_tree": True,
        "imports": origins, "selection": NATIVE_E2E_SELECTION,
        "collected": len(nodes), "python": sys.executable,
    }
    print(json.dumps(version, sort_keys=True), flush=True)
    result = _pytest_phase(repo, NATIVE_E2E_SELECTION, report,
                           expected_count=len(nodes))
    print(json.dumps({**version, **result}, sort_keys=True), flush=True)
    return result["exit_code"]


def _checkout_identity(repo, origins):
    with _diagnostic_phase("checkout-identity") as observation:
        commit = _git(repo, "rev-parse", "HEAD")
        if observation is not None:
            # A later spawn failure must not inherit the first command's exit.
            observation["exit_code"] = None
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        if observation is not None:
            observation["exit_code"] = 0
        return {
            "commit": commit, "tree": tree,
            "working_tree": True, "imports": origins, "python": sys.executable,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        }


def _console_json(record, *, rendered=None):
    """Keep complete inventories in sidecars without repeating them in CI logs."""
    if _DIAGNOSTICS.get() is None:
        return json.dumps(record, sort_keys=True) if rendered is None else rendered
    return json.dumps({key: value for key, value in record.items()
                       if key not in {"full_nodes", "selected_nodes"}}, sort_keys=True)


def _write_summary(path, result):
    rendered = json.dumps(result, sort_keys=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(rendered + "\n")
    print(_console_json(result, rendered=rendered), flush=True)


def _fresh_reports(junit_dir, names):
    if any((junit_dir / name).exists() or (junit_dir / name).is_symlink() for name in names):
        raise RegressionError("new regression suites require fresh report paths")


def _exclude_current_history(repo, index):
    if any((repo / relative).exists() for relative in (*index["test_files"], *index["support_files"])):
        raise RegressionError("historical test files must not also run against the current product")


def run_current(repo, junit_dir, *, shard_index, shard_count, isolate_heavy=False):
    # Reject malformed requests before resolving or touching any report path.
    _shard_bounds(shard_index, shard_count)
    if type(isolate_heavy) is not bool or (isolate_heavy and shard_count != 6):
        raise RegressionError("isolated heavy schedule requires six ordinary shards")
    return _run_current_selection(
        repo, junit_dir, shard_index=shard_index, shard_count=shard_count,
        isolate_heavy=isolate_heavy,
    )


def run_current_heavy(repo, junit_dir, *, heavy_index):
    _heavy_index(heavy_index)
    return _run_current_selection(repo, junit_dir, heavy_index=heavy_index, isolate_heavy=True)


def _run_current_selection(repo, junit_dir, *, shard_index=None, shard_count=None,
                           heavy_index=None, isolate_heavy=False):
    repo, junit_dir = repo.resolve(), junit_dir.resolve()
    label = f"current-shard-{shard_index}" if heavy_index is None else f"current-heavy-{heavy_index}"
    report = junit_dir / f"{label}.xml"
    sidecar = junit_dir / f"{label}.summary.json"
    _fresh_reports(junit_dir, (report.name, sidecar.name))
    junit_dir.mkdir(parents=True, exist_ok=True)
    index = _load_index(repo)
    _exclude_current_history(repo, index)
    origins = _verify_imports(repo)
    full_nodes = _current_nodes(_collect(repo, ("tests",)))
    if heavy_index is not None:
        selected = partition_heavy_current_nodes(full_nodes, heavy_index=heavy_index)
    else:
        partition = partition_isolated_current_nodes if isolate_heavy else partition_current_nodes
        selected = partition(full_nodes, shard_index=shard_index, shard_count=shard_count)
    if not selected:
        raise RegressionError("current shard selected no test files")
    files = tuple(sorted({node.partition("::")[0] for node in selected}))
    for filename in files:
        _regular_file(repo, filename)
    selections = selected if heavy_index is not None else files
    recollected = _current_nodes(_collect(repo, selections))
    if recollected != selected:
        raise RegressionError("selected current selections changed their exact collection inventory")
    version = {
        "schema_version": 1, "suite": "current" if heavy_index is None else "current-heavy",
        "offline": True,
        **_checkout_identity(repo, origins),
        "shard_algorithm": HEAVY_SHARD_ALGORITHM if isolate_heavy else SHARD_ALGORITHM,
        "full_nodes": full_nodes,
        "full_collected": len(full_nodes), "full_inventory_sha256": _inventory_sha256(full_nodes),
        "selected_nodes": selected, "selected_inventory_sha256": _inventory_sha256(selected),
        "selected_files": files, "collected": len(selected),
    }
    if heavy_index is None:
        version.update(shard_index=shard_index, shard_count=shard_count)
    else:
        version.update(heavy_index=heavy_index, heavy_count=len(HEAVY_CURRENT_NODES))
    if isolate_heavy:
        version.update(heavy_nodes=HEAVY_CURRENT_NODES,
                       heavy_inventory_sha256=_inventory_sha256(HEAVY_CURRENT_NODES),
                       selection_mode="files" if heavy_index is None else "node")
    print(_console_json(version), flush=True)
    phase = _pytest_phase(
        repo, selections, report, expected_count=len(selected), expected_nodes=selected,
    )
    result = {**version, **phase}
    _write_summary(sidecar, result)
    return result["exit_code"]


def run_history(repo, junit_dir):
    repo, junit_dir = repo.resolve(), junit_dir.resolve()
    sidecar = junit_dir / "history.summary.json"
    _fresh_reports(junit_dir, (sidecar.name, "archived.xml", "archived.retry1.xml", "frozen123.xml"))
    junit_dir.mkdir(parents=True, exist_ok=True)
    index = _load_index(repo)
    _exclude_current_history(repo, index)
    with (_snapshot(repo, ARCHIVE_COMMIT, "history") as archive,
          _snapshot(repo, FROZEN_COMMIT, "registration") as frozen):
        _verify_archive(archive, index)
        manifest = _verify_frozen(frozen)
        archive_python, frozen_python = _archive_python(archive), _archive_python(frozen)
        current_origins = _verify_imports(repo)
        checkout = _checkout_identity(repo, current_origins)
        _verify_imports(archive, python=archive_python, package=_archived_package(archive))
        _verify_imports(frozen, python=frozen_python, package=_archived_package(frozen))
        registration_test, bound = _registration_selection(frozen, manifest, python=frozen_python)
        if hashlib.sha256(_regular_file(archive, registration_test).read_bytes()).hexdigest() != (
            manifest["measurement_files"][registration_test]
        ):
            raise RegressionError("archived registration tests differ from the immutable original")
        archive_nodes = _collect(archive, index["test_files"], python=archive_python)
        archive_count = _archive_selection(archive_nodes, bound)
        frozen_nodes = _collect(frozen, bound, python=frozen_python)
        if len(frozen_nodes) != REGISTRATION_COUNT or set(frozen_nodes) != set(bound):
            raise RegressionError("frozen collection did not select exactly the 24 original registration nodes")
        versions = {
            "archived": {"commit": ARCHIVE_COMMIT, "historical_only": True,
                         "files": ARCHIVE_FILE_COUNT, "collection_sha256": ARCHIVE_COLLECTION_SHA256},
            "frozen123": {"commit": FROZEN_COMMIT, "product_commit": PRODUCT_COMMIT,
                          "historical_only": True, "pins": PIN_COUNTS},
        }
        print(json.dumps({"checkout": checkout, **versions}, sort_keys=True), flush=True)
        archived = _pytest_phase(
            archive, (*index["test_files"], *(f"--deselect={node}" for node in bound)),
            junit_dir / "archived.xml", expected_count=archive_count,
            frozen=True, python=archive_python, historical_retry=True,
        )
        registration = _pytest_phase(
            frozen, bound, junit_dir / "frozen123.xml", expected_count=REGISTRATION_COUNT,
            frozen=True, python=frozen_python,
        )
        _verify_archive(archive, index)
        _verify_frozen(frozen)
        result = {
            "schema_version": 1, "suite": "history", "offline": True, "checkout": checkout,
            "archived": {**versions["archived"], **archived},
            "frozen123": {**versions["frozen123"], **registration},
            "exit_code": archived["exit_code"] or registration["exit_code"],
        }
    _write_summary(sidecar, result)
    return result["exit_code"]


def run(repo, junit_dir):
    repo, junit_dir = repo.resolve(), junit_dir.resolve()
    junit_dir.mkdir(parents=True, exist_ok=True)
    index = _load_index(repo)
    with (_snapshot(repo, ARCHIVE_COMMIT, "history") as archive,
          _snapshot(repo, FROZEN_COMMIT, "registration") as frozen):
        _verify_archive(archive, index)
        manifest = _verify_frozen(frozen)
        archive_python, frozen_python = _archive_python(archive), _archive_python(frozen)
        current_origins = _verify_imports(repo)
        _verify_imports(archive, python=archive_python, package=_archived_package(archive))
        _verify_imports(frozen, python=frozen_python, package=_archived_package(frozen))
        registration_test, bound = _registration_selection(frozen, manifest, python=frozen_python)
        if hashlib.sha256(_regular_file(archive, registration_test).read_bytes()).hexdigest() != (
            manifest["measurement_files"][registration_test]
        ):
            raise RegressionError("archived registration tests differ from the immutable original")
        if any((repo / relative).exists() for relative in (*index["test_files"], *index["support_files"])):
            raise RegressionError("historical test files must not also run against the current product")
        current_nodes = _collect(repo, ("tests",))
        archive_nodes = _collect(archive, index["test_files"], python=archive_python)
        archive_count = _archive_selection(archive_nodes, bound)
        frozen_nodes = _collect(frozen, bound, python=frozen_python)
        if len(frozen_nodes) != REGISTRATION_COUNT or set(frozen_nodes) != set(bound):
            raise RegressionError("frozen collection did not select exactly the 24 original registration nodes")
        versions = {
            "current": {"commit": _git(repo, "rev-parse", "HEAD"), "working_tree": True,
                        "imports": current_origins},
            "archived": {"commit": ARCHIVE_COMMIT, "historical_only": True,
                         "files": ARCHIVE_FILE_COUNT, "collection_sha256": ARCHIVE_COLLECTION_SHA256},
            "frozen123": {"commit": FROZEN_COMMIT, "product_commit": PRODUCT_COMMIT,
                          "historical_only": True, "pins": PIN_COUNTS},
        }
        print(json.dumps(versions, sort_keys=True), flush=True)
        current = _pytest_phase(repo, ("tests",), junit_dir / "current.xml",
                                expected_count=len(current_nodes))
        archived = _pytest_phase(
            archive, (*index["test_files"], *(f"--deselect={node}" for node in bound)),
            junit_dir / "archived.xml", expected_count=archive_count,
            frozen=True, python=archive_python, historical_retry=True,
        )
        registration = _pytest_phase(
            frozen, bound, junit_dir / "frozen123.xml", expected_count=REGISTRATION_COUNT,
            frozen=True, python=frozen_python,
        )
        # Verify tracked originals again after tests; ignored test outputs are not evidence.
        _verify_archive(archive, index)
        _verify_frozen(frozen)
        result = {name: {**versions[name], **phase} for name, phase in (
            ("current", current), ("archived", archived), ("frozen123", registration),
        )}
        result["exit_code"] = current["exit_code"] or archived["exit_code"] or registration["exit_code"]
    print(json.dumps(result, sort_keys=True), flush=True)
    return result["exit_code"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit-dir", type=Path, required=True)
    parser.add_argument("--suite", choices=("all", "native-e2e", "current", "current-heavy", "history"),
                        default="all")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--isolate-heavy", action="store_true")
    parser.add_argument("--heavy-index", type=int)
    parser.add_argument("--diagnostics", action="store_true",
                        help="Flush phase events and show original pytest node progress")
    arguments = parser.parse_args(argv)
    if arguments.suite == "current":
        try:
            _shard_bounds(arguments.shard_index, arguments.shard_count)
            if arguments.isolate_heavy and arguments.shard_count != 6:
                raise RegressionError("isolated heavy schedule requires six ordinary shards")
        except RegressionError as exc:
            parser.error(str(exc))
    elif arguments.shard_index is not None or arguments.shard_count is not None:
        parser.error("shard index/count are only valid for the current suite")
    if arguments.isolate_heavy and arguments.suite != "current":
        parser.error("isolate-heavy is only valid for the current suite")
    if arguments.suite == "current-heavy":
        try:
            _heavy_index(arguments.heavy_index)
        except RegressionError as exc:
            parser.error(str(exc))
    elif arguments.heavy_index is not None:
        parser.error("heavy index is only valid for the current-heavy suite")
    role = (f"current-{arguments.shard_index}" if arguments.suite == "current"
            and arguments.shard_index is not None else
            f"heavy-{arguments.heavy_index}" if arguments.suite == "current-heavy" else arguments.suite)
    with _diagnostics(arguments.diagnostics, suite=arguments.suite, role=role):
        return _dispatch(arguments)


def _dispatch(arguments):
    try:
        if arguments.suite == "current":
            options = {"isolate_heavy": True} if arguments.isolate_heavy else {}
            return run_current(REPO, arguments.junit_dir,
                               shard_index=arguments.shard_index, shard_count=arguments.shard_count,
                               **options)
        if arguments.suite == "current-heavy":
            return run_current_heavy(REPO, arguments.junit_dir, heavy_index=arguments.heavy_index)
        if arguments.suite == "history":
            return run_history(REPO, arguments.junit_dir)
        if arguments.suite == "native-e2e":
            return run_native_e2e(REPO, arguments.junit_dir)
        return run(REPO, arguments.junit_dir)
    except (RegressionError, OSError, ValueError) as exc:
        print(f"regression runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
