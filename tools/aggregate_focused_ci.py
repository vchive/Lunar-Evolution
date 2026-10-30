"""Check focused gates against original current/heavy JUnit; never execute tests."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

_SPEC = importlib.util.spec_from_file_location("focused_ci_runner", Path(__file__).with_name(
    "run_tests.py"))
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)
REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "tools/ci-focused-groups.json"
ROLES = tuple([f"current-{index}" for index in range(6)]
              + [f"heavy-{index}" for index in range(len(runner.HEAVY_CURRENT_NODES))])
_FIXED_U_BOOTSTRAP_FILE = "tests/test_native_fixed_u_input_bootstrap.py"
_FIXED_U_BOOTSTRAP_GROUP = "native-fixed-u-input-bootstrap"
_FIXED_U_ROOT_FUNCTION = "test_actual_root_input_grants_bind_original_fd_acl_and_exact_combinations"
_FIXED_U_ROOT_NODES = frozenset(
    f"{_FIXED_U_BOOTSTRAP_FILE}::{_FIXED_U_ROOT_FUNCTION}[{change}-{kind}]"
    for change in (
        "exact", "missing", "missing-request", "mixed-files", "duplicate", "mixed", "no-marker",
        "node-pin", "root-pin", "role", "fd", "replace", "hardlink", "directory-mode", "file-mode",
        "default", "extra", "expired",
    )
    for kind in ("producer", "rsi")
)
_FIXED_U_ROOT_SKIP = "root-owned original input prerequisite; never elevate"


class GateError(ValueError):
    """Original execution evidence did not satisfy the focused gate."""


def _require(condition, message):
    if not condition:
        raise GateError(message)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    _require(not path.is_symlink() and path.is_file(), f"Missing regular input: {path.name}")
    return path.read_bytes()


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def _json(raw):
    value = json.loads(raw, object_pairs_hook=_pairs)
    _require(type(value) is dict, "Expected JSON object")
    return value


def _count(record, name, expected):
    _require(type(record.get(name)) is int and record[name] == expected,
             f"Incorrect {name}")


def _manifest(raw):
    value = _json(raw)
    _require(set(value) == {"schema", "groups"}
             and value["schema"] == "lunar-ci-focused-groups-v1", "Invalid group manifest")
    groups = value["groups"]
    _require(type(groups) is list and len(groups) == 83, "Expected 83 focused groups")
    identities = set()
    for group in groups:
        _require(type(group) is dict and set(group) == {
            "id", "label", "files", "expected_tests", "zero_skips"}, "Invalid focused group")
        identity, files = group["id"], group["files"]
        _require(type(identity) is str and identity and identity not in identities,
                 "Duplicate or invalid focused group")
        identities.add(identity)
        _require(type(group["label"]) is str and bool(group["label"]), "Missing group label")
        _require(type(files) is list and files and all(type(name) is str for name in files)
                 and len(set(files)) == len(files), "Invalid focused files")
        for name in files:
            path = PurePosixPath(name)
            _require(len(path.parts) >= 2 and path.parts[0] == "tests"
                     and path.suffix == ".py" and path.as_posix() == name
                     and not path.is_absolute() and ".." not in path.parts and "\\" not in name,
                     "Invalid focused file path")
        expected = group["expected_tests"]
        # Exact collection counts and platform skip permission are independent.
        # A counted platform group still requires every original testcase.
        _require(type(group["zero_skips"]) is bool and (
            (type(expected) is int and expected > 0)
            or (not group["zero_skips"] and expected is None)), "Invalid focused count rule")
        if identity == _FIXED_U_BOOTSTRAP_GROUP or _FIXED_U_BOOTSTRAP_FILE in files:
            _require(identity == _FIXED_U_BOOTSTRAP_GROUP
                     and files == [_FIXED_U_BOOTSTRAP_FILE] and expected == 87
                     and group["zero_skips"] is False, "Invalid fixed-U bootstrap rule")
    _require(sum(group["zero_skips"] for group in groups) == 65,
             "Expected 65 explicit count/zero-skip gates")
    return groups


def _nodes(record, name):
    value = record.get(name)
    checked = runner._current_nodes(value)
    _require(type(value) is list and value == list(checked), f"Noncanonical {name}")
    return checked


def _identity(provenance, summary, context, role):
    _require(provenance.get("schema") == "lunar-ci-job-provenance-v1"
             and provenance.get("role") == role, "Incorrect job provenance role")
    for field in ("commit", "tree", "parents", "run_id", "run_attempt", "imports"):
        _require(provenance.get(field) == context[field], f"Provenance {field} differs")
    _require(provenance.get("executable") == context["executable"]
             and provenance.get("python") == context["python"],
             "Provenance Python differs")
    for field in ("commit", "tree", "imports", "python_version"):
        _require(summary.get(field) == context[field], f"Summary {field} differs")
    _require(summary.get("python") == context["executable"]
             and summary.get("working_tree") is True and summary.get("offline") is True
             and type(summary.get("schema_version")) is int
             and summary["schema_version"] == 1, "Incorrect runner identity")


def _fixed_u_bootstrap_skip_gate(group, nodes, skipped):
    """Require ordinary C/ACL bodies and only finite nonroot prerequisite skips.

    Root skips remain skips in the receipt. They establish neither execution of
    those bodies nor installed whole-scope acceptance.
    """
    if group["id"] != _FIXED_U_BOOTSTRAP_GROUP:
        return
    roots = {node for node in nodes if node.partition("::")[2].partition("[")[0]
             == _FIXED_U_ROOT_FUNCTION}
    _require(roots == _FIXED_U_ROOT_NODES and len(nodes) - len(roots) == 51,
             "Fixed-U bootstrap root/ordinary inventory differs")
    _require(all(item["node"] in roots and item["message"] == _FIXED_U_ROOT_SKIP
                 and item["type"] == "pytest.skip" for item in skipped),
             "Fixed-U bootstrap ordinary or unrecognized skip refused")


def _report(directory, role, context, full_nodes):
    label = ("current-shard-" + role.removeprefix("current-") if role.startswith("current-")
             else "current-heavy-" + role.removeprefix("heavy-"))
    filenames = {f"{label}.xml", f"{label}.summary.json", "job-provenance.json", "pytest.log"}
    _require(not directory.is_symlink() and directory.is_dir(), "Missing role directory")
    _require({path.name for path in directory.iterdir()} == filenames,
             "Unexpected or missing role inputs")
    raw = {name: _read(directory / name) for name in filenames}
    summary = _json(raw[f"{label}.summary.json"])
    _identity(_json(raw["job-provenance.json"]), summary, context, role)
    nodes = _nodes(summary, "full_nodes")
    _require(full_nodes is None or nodes == full_nodes, "Full inventories disagree")
    _count(summary, "full_collected", len(nodes))
    _require(summary.get("full_inventory_sha256") == runner._inventory_sha256(nodes),
             "Full inventory digest differs")
    _require(summary.get("shard_algorithm") == runner.HEAVY_SHARD_ALGORITHM
             and summary.get("heavy_nodes") == list(runner.HEAVY_CURRENT_NODES)
             and summary.get("heavy_inventory_sha256") == runner._inventory_sha256(
                 runner.HEAVY_CURRENT_NODES), "Heavy inventory differs")
    index = int(role.rsplit("-", 1)[1])
    if role.startswith("current-"):
        _require(summary.get("suite") == "current" and summary.get("selection_mode") == "files",
                 "Incorrect current selection mode")
        _count(summary, "shard_index", index)
        _count(summary, "shard_count", 6)
        expected = runner.partition_isolated_current_nodes(nodes, shard_index=index, shard_count=6)
    else:
        _require(summary.get("suite") == "current-heavy" and summary.get("selection_mode") == "node",
                 "Incorrect heavy selection mode")
        _count(summary, "heavy_index", index)
        _count(summary, "heavy_count", len(runner.HEAVY_CURRENT_NODES))
        expected = runner.partition_heavy_current_nodes(nodes, heavy_index=index)
    selected = _nodes(summary, "selected_nodes")
    _require(selected == expected and summary.get("selected_files") == sorted({
        node.partition("::")[0] for node in selected}), "Selected inventory differs")
    _count(summary, "collected", len(selected))
    for field in ("selected_inventory_sha256", "expected_inventory_sha256"):
        _require(summary.get(field) == runner._inventory_sha256(selected),
                 "Selected inventory digest differs")
    for field in ("exit_code", "pytest_exit_code"):
        _count(summary, field, 0)
    _require(summary.get("exact_case_keys") is True and not summary.get("validation_error"),
             "Runner did not confirm exact execution")
    report = directory / f"{label}.xml"
    _require(summary.get("junit") == str(Path(context["checkout"]) /
             ".lunar-evolution/test-results" / report.name), "Report source path differs")
    _require(summary.get("junit_sha256") == _digest(raw[report.name]), "Original JUnit digest differs")
    checked = runner._junit_summary(report, pytest_exit_code=0, expected_count=len(selected),
                                    expected_nodes=selected)
    _require(checked["exit_code"] == 0 and checked.get("exact_case_keys") is True,
             "Original JUnit does not match exact nodes")
    for field in ("tests", "reported_testcases", "failures", "errors", "skipped",
                  "failure_elements", "error_elements", "skipped_elements", "failed_testcases"):
        _require(summary.get(field) == checked.get(field), f"JUnit {field} differs from summary")
    root = ET.fromstring(raw[report.name])
    _require(root.tag == "testsuites" and len(root) == 1 and root[0].tag == "testsuite"
             and len(list(root.iter("testsuite"))) == 1, "Unexpected JUnit suite shape")
    cases = list(root.iter("testcase"))
    _require(len(cases) == len(root[0].findall("testcase"))
             and all(len(case.findall("skipped")) <= 1 for case in cases)
             and len(list(root.iter("skipped"))) == sum(
                 len(case.findall("skipped")) for case in cases),
             "Unexpected JUnit case shape")
    indexed = {(case.get("classname"), case.get("name")): case for case in cases}
    return nodes, selected, indexed, {name: _digest(value) for name, value in sorted(raw.items())}


def aggregate(artifacts_dir, manifest_raw, context, *, upstream_result):
    """Validate retained inputs without pytest collection, execution or mutation."""
    _require(upstream_result == "success", "Required execution jobs did not all succeed")
    _require(context["python_version"] in {"3.11", "3.12", "3.13"}, "Unsupported Python version")
    groups = _manifest(manifest_raw)
    expected_dirs = {f"test-results-python-{context['python_version']}-{role}" for role in ROLES}
    _require(not artifacts_dir.is_symlink() and artifacts_dir.is_dir()
             and {path.name for path in artifacts_dir.iterdir()} == expected_dirs,
             "Missing, extra or duplicate execution roles")
    full_nodes, all_cases, selected_union, inputs = None, {}, set(), {}
    for role in ROLES:
        name = f"test-results-python-{context['python_version']}-{role}"
        nodes, selected, cases, hashes = _report(artifacts_dir / name, role, context, full_nodes)
        full_nodes = nodes
        _require(not selected_union.intersection(selected) and not all_cases.keys() & cases.keys(),
                 "Execution roles overlap")
        selected_union.update(selected)
        all_cases.update(cases)
        inputs[name] = hashes
    _require(selected_union == set(full_nodes), "Execution roles do not cover the full inventory")
    by_file = {}
    for node in full_nodes:
        by_file.setdefault(node.partition("::")[0], []).append(node)
    results = []
    for group in groups:
        _require(all(name in by_file for name in group["files"]), "Focused file missing from inventory")
        nodes = tuple(sorted(node for name in group["files"] for node in by_file[name]))
        if group["expected_tests"] is not None:
            _require(len(nodes) == group["expected_tests"], f"Focused count differs: {group['id']}")
        skipped = []
        for node in nodes:
            case = all_cases[runner._junit_case_key(node)]
            skip = case.find("skipped")
            if skip is not None:
                skipped.append({"node": node, "message": skip.get("message"),
                                "type": skip.get("type"), "text": skip.text})
        _require(not group["zero_skips"] or not skipped, f"Focused skip refused: {group['id']}")
        _fixed_u_bootstrap_skip_gate(group, nodes, skipped)
        results.append({"id": group["id"], "tests": len(nodes), "failures": 0, "errors": 0,
                        "skipped": skipped, "inventory_sha256": runner._inventory_sha256(nodes),
                        "expected_tests": group["expected_tests"], "zero_skips": group["zero_skips"]})
    return {"schema": "lunar-ci-derived-focused-gate-v1", "status": "passed",
            "derived_from_original_reports": True, "test_execution_performed": False,
            "source": context, "manifest_sha256": _digest(manifest_raw), "inputs": inputs,
            "full_collected": len(full_nodes),
            "full_inventory_sha256": runner._inventory_sha256(full_nodes), "groups": results}


def _context(repo, python_version):
    _require(f"{sys.version_info.major}.{sys.version_info.minor}" == python_version,
             "Aggregate interpreter differs from requested version")
    run_id, attempt = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "")
    _require(run_id.isdecimal() and int(run_id) > 0 and attempt.isdecimal() and int(attempt) > 0,
             "Missing workflow run/attempt")
    return {"commit": runner._git(repo, "rev-parse", "HEAD"),
            "tree": runner._git(repo, "rev-parse", "HEAD^{tree}"),
            "parents": runner._git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:],
            "imports": runner._verify_imports(repo), "executable": sys.executable,
            "python_version": python_version, "python": sys.version, "checkout": str(repo),
            "run_id": run_id, "run_attempt": attempt}


def write_receipt(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--python-version", choices=("3.11", "3.12", "3.13"), required=True)
    parser.add_argument("--upstream-result", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _require(not args.output.exists() and not args.output.is_symlink(), "Output already exists")
        _require(args.upstream_result == "success", "Required execution jobs did not all succeed")
        result = aggregate(args.artifacts_dir, _read(MANIFEST), _context(REPO, args.python_version),
                           upstream_result=args.upstream_result)
        write_receipt(args.output, result)
    except (GateError, runner.RegressionError, OSError, ValueError, KeyError, TypeError,
            ET.ParseError) as exc:
        print(f"Focused gate refused: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {len(result['groups'])} focused groups from {len(ROLES)} original execution reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
