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
import tomllib
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

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
NATIVE_E2E_SELECTION = (
    "tests/test_automatic_detach_phase_c.py",
    "tests/test_conversational_automatic_bundle.py",
    "tests/test_automatic_solve_bundle.py",
    "tests/test_automatic_cancel_phase_b.py",
    "tests/test_automatic_solve_deadline_integration.py",
    "tests/test_automatic_runtime_processes.py",
    "tests/test_identity_installation.py",
)


class RegressionError(RuntimeError):
    pass


def _capture(command, root, *, environment=None):
    result = subprocess.run(
        command, cwd=root, env=environment, text=True, capture_output=True, check=False,
    )
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
    output = _capture(
        [str(python), "-m", "pytest", "-o", "addopts=", "--collect-only", "-q", "--color=no", *selections],
        root, environment=_environment(root),
    )
    nodes = tuple(line for line in output.splitlines() if line.startswith("tests/") and "::" in line)
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


def _pytest_phase(root, selections, report, *, expected_count, frozen=False, python=sys.executable,
                  retries=0):
    if report.exists():
        report.unlink()
    command = [str(python), "-m", "pytest", "-o", "addopts=", "-q", "--color=no",
               f"--junitxml={report}", *selections]
    result = subprocess.run(command, cwd=root, env=_environment(root), check=False)
    summary = {"exit_code": result.returncode, "junit": str(report)}
    try:
        suites = list(ET.parse(report).getroot().iter("testsuite"))
        summary.update({field: sum(int(suite.attrib.get(field, "0")) for suite in suites)
                        for field in ("tests", "failures", "errors", "skipped")})
        complete = summary["tests"] == expected_count and not summary["failures"] and not summary["errors"]
        if frozen:
            complete = complete and summary["skipped"] == 0
        if not complete:
            summary["exit_code"] = result.returncode or 1
            summary["validation_error"] = "JUnit did not confirm the expected executed test set"
    except (OSError, ValueError, ET.ParseError):
        summary["exit_code"] = result.returncode or 1
        summary["validation_error"] = "pytest did not produce a readable JUnit report"
    # The immutable historical archive contains one known Python 3.12 scheduling-sensitive
    # observation test. Retry only that sealed phase once; a second failure remains blocking.
    if summary["exit_code"] and retries:
        print(json.dumps({"retry": retries, "phase": "historical_archive"}, sort_keys=True), flush=True)
        return _pytest_phase(
            root, selections, report, expected_count=expected_count, frozen=frozen,
            python=python, retries=retries - 1,
        )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


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
            frozen=True, python=archive_python, retries=1,
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
    parser.add_argument("--suite", choices=("all", "native-e2e"), default="all")
    arguments = parser.parse_args(argv)
    try:
        if arguments.suite == "native-e2e":
            return run_native_e2e(REPO, arguments.junit_dir)
        return run(REPO, arguments.junit_dir)
    except (RegressionError, OSError, ValueError) as exc:
        print(f"regression runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
