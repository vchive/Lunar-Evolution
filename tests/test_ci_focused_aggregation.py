"""Focused CI gates consume inert original-report fixtures without running pytest."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("ci_focused_aggregation", _ROOT /
                                             "tools/aggregate_focused_ci.py")
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _inventory(nodes):
    return _digest(("\n".join(sorted(nodes)) + "\n").encode())


def _key(node):
    filename, address = node.split("::", 1)
    base, bracket, parameter = address.partition("[")
    parts = [filename[:-3].replace("/", "."), *base.split("::")]
    return ".".join(parts[:-1]), parts[-1] + bracket + parameter


def _json(path, value):
    path.write_text(json.dumps(value))


def _fixed_u_root_nodes():
    """Independently read the finite literal root parameter domain, without pytest."""
    filename = "tests/test_native_fixed_u_input_bootstrap.py"
    function = "test_actual_root_input_grants_bind_original_fd_acl_and_exact_combinations"
    tree = ast.parse((_ROOT / filename).read_text())
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function)
    parameters = {}
    for decorator in node.decorator_list:
        if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"):
            name = ast.literal_eval(decorator.args[0])
            parameters[name] = (ast.literal_eval(decorator.args[1]), {
                keyword.arg: ast.literal_eval(keyword.value) for keyword in decorator.keywords})
    assert parameters["kind"][0] == [1, 2]
    kinds = parameters["kind"][1]["ids"]
    assert kinds == ["producer", "rsi"]
    return {f"{filename}::{function}[{change}-{kind}]"
            for change in parameters["change"][0] for kind in kinds}


@pytest.fixture
def evidence(tmp_path, request):
    context = {"commit": "a" * 40, "tree": "b" * 40, "parents": ["c" * 40, "d" * 40],
               "run_id": "123", "run_attempt": "1", "python_version": "3.13",
               "python": "3.13.12 (fixture)",
               "checkout": "/runner/work/project/project",
               "executable": "/runner/work/project/project/.venv/bin/python",
               "imports": ["/runner/work/project/project/src/lunar_evolution/" + name
                           for name in ("__init__.py", "evaluator_bundle.py")]}
    groups = [{"id": f"group-{index}", "label": f"Original group {index}",
               "files": [f"tests/test_group_{index}.py"],
               "expected_tests": 1 if index < 62 or index >= 78 else None,
               "zero_skips": index < 62 or index in {79, 80, 82}}
              for index in range(83)]
    fixed_u = getattr(request, "param", "")
    if fixed_u:
        groups[81].update(id="native-fixed-u-input-bootstrap",
                          files=["tests/test_native_fixed_u_input_bootstrap.py"], expected_tests=87)
    nodes = [f"{group['files'][0]}::TestGroup::test_value[dict::with/slash]" for group in groups]
    if fixed_u:
        nodes.pop(81)
        roots = sorted(_fixed_u_root_nodes())
        if fixed_u == "root-inventory-drift":
            roots[-1] = roots[-1].replace("[", "[unlisted-", 1)
        nodes += roots + [f"tests/test_native_fixed_u_input_bootstrap.py::test_ordinary[{index}]"
                          for index in range(51)]
    nodes += list(gate.runner.HEAVY_CURRENT_NODES)
    nodes.sort()
    root = tmp_path / "inputs"
    root.mkdir()
    paths = {}
    for role in gate.ROLES:
        index = int(role.rsplit("-", 1)[1])
        heavy = role.startswith("heavy-")
        selected = ([gate.runner.HEAVY_CURRENT_NODES[index]] if heavy else [
            node for node in nodes if node.partition("::")[0] not in gate.runner.HEAVY_CURRENT_FILES
            and int(hashlib.sha256(node.partition("::")[0].encode()).hexdigest(), 16) % 6 == index])
        label = f"current-{'heavy' if heavy else 'shard'}-{index}"
        directory = root / f"test-results-python-3.13-{role}"
        directory.mkdir()
        paths[role] = directory
        xml = ET.Element("testsuites")
        suite = ET.SubElement(xml, "testsuite", tests=str(len(selected)), failures="0",
                              errors="0", skipped="0")
        for node in selected:
            classname, name = _key(node)
            ET.SubElement(suite, "testcase", classname=classname, name=name)
        raw = ET.tostring(xml)
        (directory / f"{label}.xml").write_bytes(raw)
        provenance = {key: value for key, value in context.items()
                      if key in {"commit", "tree", "parents", "run_id", "run_attempt", "imports"}}
        provenance.update(schema="lunar-ci-job-provenance-v1", role=role,
                          executable=context["executable"], python="3.13.12 (fixture)")
        _json(directory / "job-provenance.json", provenance)
        summary = {key: context[key] for key in ("commit", "tree", "imports", "python_version")}
        summary.update(schema_version=1, offline=True, working_tree=True,
                       python=context["executable"], suite="current-heavy" if heavy else "current",
                       selection_mode="node" if heavy else "files",
                       shard_algorithm=gate.runner.HEAVY_SHARD_ALGORITHM,
                       full_nodes=nodes, full_collected=len(nodes),
                       full_inventory_sha256=_inventory(nodes), selected_nodes=selected,
                       selected_files=sorted({node.partition("::")[0] for node in selected}),
                       selected_inventory_sha256=_inventory(selected), collected=len(selected),
                       expected_inventory_sha256=_inventory(selected),
                       heavy_nodes=list(gate.runner.HEAVY_CURRENT_NODES),
                       heavy_inventory_sha256=_inventory(gate.runner.HEAVY_CURRENT_NODES),
                       exit_code=0, pytest_exit_code=0, exact_case_keys=True,
                       junit=f"{context['checkout']}/.lunar-evolution/test-results/{label}.xml",
                       junit_sha256=_digest(raw), tests=len(selected), reported_testcases=len(selected),
                       failures=0, errors=0, skipped=0, failure_elements=0, error_elements=0,
                       skipped_elements=0, failed_testcases=[])
        summary.update({"heavy_index": index, "heavy_count": len(gate.runner.HEAVY_CURRENT_NODES)} if heavy else {
            "shard_index": index, "shard_count": 6})
        _json(directory / f"{label}.summary.json", summary)
        (directory / "pytest.log").write_text("Original fixture execution log\n")
    return {"root": root, "paths": paths, "context": context, "groups": groups,
            "manifest": json.dumps({"schema": "lunar-ci-focused-groups-v1", "groups": groups}).encode()}


def _run(evidence, **kwargs):
    return gate.aggregate(evidence["root"], evidence["manifest"], evidence["context"],
                          upstream_result=kwargs.get("upstream_result", "success"))


def _summary(evidence, role="current-0"):
    path = next(evidence["paths"][role].glob("*.summary.json"))
    return path, json.loads(path.read_bytes())


def _xml_change(evidence, role, change, *, keep_hash=False):
    directory = evidence["paths"][role]
    path = next(directory.glob("*.xml"))
    root = ET.fromstring(path.read_bytes())
    change(root[0])
    raw = ET.tostring(root)
    path.write_bytes(raw)
    summary_path, summary = _summary(evidence, role)
    if not keep_hash:
        summary["junit_sha256"] = _digest(raw)
    _json(summary_path, summary)


def _role_for(evidence, group):
    filename = evidence["groups"][group]["files"][0]
    return "current-" + str(int(hashlib.sha256(filename.encode()).hexdigest(), 16) % 6)


def test_valid_original_reports_produce_only_derived_json_and_preserve_inputs(evidence, tmp_path):
    before = {path: path.read_bytes() for path in evidence["root"].rglob("*") if path.is_file()}
    result = _run(evidence)
    assert result["status"] == "passed" and len(result["groups"]) == 83
    assert result["test_execution_performed"] is False
    assert len(result["inputs"]) == len(gate.ROLES) == 13
    assert result["full_collected"] == 83 + len(gate.runner.HEAVY_CURRENT_NODES)
    assert all(group["tests"] == 1 for group in result["groups"])
    assert all(path.read_bytes() == raw for path, raw in before.items())
    output = tmp_path / "derived.json"
    gate.write_receipt(output, result)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        gate.write_receipt(output, {"status": "replacement"})
    assert output.read_bytes() == original
    assert not list(tmp_path.glob("*.xml"))


@pytest.mark.parametrize("upstream", ["failure", "cancelled", "skipped", "", "neutral"])
def test_failed_upstream_refuses_before_reading_any_input(evidence, monkeypatch, upstream):
    monkeypatch.setattr(gate, "_manifest", lambda *_: pytest.fail("read input after failed upstream"))
    with pytest.raises(gate.GateError, match="did not all succeed"):
        _run(evidence, upstream_result=upstream)


@pytest.mark.parametrize("change", ["missing", "extra", "symlink"])
def test_exact_ordinary_and_heavy_role_directories_are_required(evidence, change):
    directory = evidence["paths"]["current-0"]
    if change == "missing":
        directory.rename(directory.with_name("wrong-role"))
    elif change == "extra":
        (evidence["root"] / "unexpected").mkdir()
    else:
        target = directory.with_name("original")
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
        target.rename(evidence["root"].parent / "outside")
    with pytest.raises(gate.GateError):
        _run(evidence)


@pytest.mark.parametrize("field,value", [
    ("run_id", "other"), ("run_attempt", "2"), ("commit", "e" * 40),
    ("tree", "f" * 40), ("parents", ["f" * 40]), ("role", "current-1"),
    ("imports", ["/other/src/lunar_evolution/__init__.py"]),
    ("executable", "/other/python"), ("python", "3.12.1"),
])
def test_provenance_drift_refuses(evidence, field, value):
    path = evidence["paths"]["current-0"] / "job-provenance.json"
    record = json.loads(path.read_bytes())
    record[field] = value
    _json(path, record)
    with pytest.raises(gate.GateError):
        _run(evidence)


@pytest.mark.parametrize("field,value", [
    ("commit", "e" * 40), ("tree", "e" * 40), ("imports", []),
    ("python", "/other/python"), ("python_version", "3.12"),
    ("full_inventory_sha256", "0" * 64), ("selected_inventory_sha256", "0" * 64),
    ("expected_inventory_sha256", "0" * 64), ("junit_sha256", "0" * 64),
    ("shard_index", 5), ("shard_count", 3), ("shard_algorithm", "old"),
    ("heavy_nodes", []), ("exit_code", 1), ("pytest_exit_code", 1),
    ("exact_case_keys", False), ("collected", 999), ("tests", 999),
    ("full_collected", 999), ("selected_files", []), ("selected_nodes", []),
    ("working_tree", False), ("offline", False), ("validation_error", "failed"),
    ("junit", "/other/current-shard-0.xml"),
])
def test_summary_drift_refuses(evidence, field, value):
    path, record = _summary(evidence)
    record[field] = value
    _json(path, record)
    with pytest.raises((gate.GateError, gate.runner.RegressionError)):
        _run(evidence)


def test_self_consistent_changed_full_inventory_in_one_role_refuses(evidence):
    path, record = _summary(evidence, "heavy-2")
    record["full_nodes"].append("tests/test_extra.py::test_extra")
    record["full_nodes"].sort()
    record["full_collected"] += 1
    record["full_inventory_sha256"] = _inventory(record["full_nodes"])
    _json(path, record)
    with pytest.raises(gate.GateError, match="inventories disagree"):
        _run(evidence)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "failure", "error", "counter"])
def test_original_xml_nodes_elements_and_counters_are_independently_checked(evidence, mutation):
    def change(suite):
        case = suite[0]
        if mutation == "missing":
            suite.remove(case)
        elif mutation == "extra":
            ET.SubElement(suite, "testcase", classname="tests.extra", name="test_extra")
        elif mutation == "duplicate":
            suite.append(copy.deepcopy(case))
        elif mutation in {"failure", "error"}:
            ET.SubElement(case, mutation, message="counter deliberately still zero")
        else:
            suite.set("tests", "999")
    _xml_change(evidence, "current-0", change)
    with pytest.raises(gate.GateError):
        _run(evidence)


@pytest.mark.parametrize("group,allowed", [(0, False), (77, True), (78, True), (79, False)])
def test_explicit_zero_skip_gate_and_original_allowed_skip_semantics(evidence, group, allowed):
    role = _role_for(evidence, group)
    classname = evidence["groups"][group]["files"][0][:-3].replace("/", ".") + ".TestGroup"
    def change(suite):
        case = next(case for case in suite if case.get("classname") == classname)
        ET.SubElement(case, "skipped", type="pytest.skip", message="Original platform contract")
        suite.set("skipped", "1")
    _xml_change(evidence, role, change)
    path, summary = _summary(evidence, role)
    summary.update(skipped=1, skipped_elements=1)
    _json(path, summary)
    if allowed:
        result = _run(evidence)
        assert result["groups"][group]["skipped"][0]["message"] == "Original platform contract"
    else:
        with pytest.raises(gate.GateError, match="Focused skip refused"):
            _run(evidence)


@pytest.mark.parametrize("group", [0, 78, 79])
def test_count_gate_cannot_be_satisfied_by_another_group(evidence, group):
    manifest = json.loads(evidence["manifest"])
    manifest["groups"][group]["expected_tests"] = 2
    evidence["manifest"] = json.dumps(manifest).encode()
    with pytest.raises(gate.GateError, match="Focused count differs"):
        _run(evidence)


@pytest.mark.parametrize("group,expected", [(0, None), (78, 0), (78, True), (79, -1)])
def test_invalid_expected_count_never_changes_skip_permission(evidence, group, expected):
    manifest = json.loads(evidence["manifest"])
    manifest["groups"][group]["expected_tests"] = expected
    with pytest.raises(gate.GateError, match="Invalid focused count rule"):
        gate._manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize("evidence", ["fixed-u"], indirect=True)
@pytest.mark.parametrize("mode,allowed", [
    ("none", True), ("root", True), ("one-root", True),
    ("ordinary", False), ("all", False), ("wrong-reason", False), ("wrong-type", False),
])
def test_fixed_u_bootstrap_requires_all_ordinary_bodies_and_only_finite_nonroot_skips(evidence, mode, allowed):
    roots = sorted(_fixed_u_root_nodes())
    role = _role_for(evidence, 81)
    _, summary = _summary(evidence, role)
    nodes = [node for node in summary["selected_nodes"]
             if node.partition("::")[0] == "tests/test_native_fixed_u_input_bootstrap.py"]
    ordinary = sorted(set(nodes) - set(roots))
    selected = (set() if mode == "none" else set(roots[:1]) if mode == "one-root"
                else set(ordinary[:1]) if mode == "ordinary" else set(nodes) if mode == "all"
                else set(roots))
    keys = {_key(node) for node in selected}
    message = ("compiler or filesystem prerequisite unavailable" if mode == "wrong-reason"
               else "root-owned original input prerequisite; never elevate")

    def change(suite):
        for case in suite:
            if (case.get("classname"), case.get("name")) in keys:
                ET.SubElement(case, "skipped", type="pytest.xfail" if mode == "wrong-type" else "pytest.skip",
                              message=message)
        suite.set("skipped", str(len(selected)))

    _xml_change(evidence, role, change)
    path, summary = _summary(evidence, role)
    summary.update(skipped=len(selected), skipped_elements=len(selected))
    _json(path, summary)
    if allowed:
        result = _run(evidence)
        group = next(group for group in result["groups"] if group["id"] == "native-fixed-u-input-bootstrap")
        assert group["tests"] == 87 and len(group["skipped"]) == len(selected)
        assert len(ordinary) == 51 and len(roots) == 36
    else:
        with pytest.raises(gate.GateError, match="ordinary or unrecognized skip refused"):
            _run(evidence)


@pytest.mark.parametrize("evidence", ["root-inventory-drift"], indirect=True)
def test_fixed_u_root_inventory_cannot_be_replaced_by_another_same_count_case(evidence):
    with pytest.raises(gate.GateError, match="root/ordinary inventory differs"):
        _run(evidence)


@pytest.mark.parametrize("field,value", [
    ("id", "renamed"),
    ("files", ["tests/test_other.py"]), ("expected_tests", 86), ("zero_skips", True),
])
def test_fixed_u_bootstrap_manifest_rule_cannot_change_its_count_or_skip_domain(evidence, field, value):
    manifest = json.loads(evidence["manifest"])
    manifest["groups"][81].update(id="native-fixed-u-input-bootstrap",
                                  files=["tests/test_native_fixed_u_input_bootstrap.py"], expected_tests=87)
    manifest["groups"][81][field] = value
    with pytest.raises(gate.GateError, match="Invalid fixed-U bootstrap rule"):
        gate._manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize("delta", [-1, 1])
def test_exact_manifest_group_count_cannot_be_relaxed(evidence, delta):
    manifest = json.loads(evidence["manifest"])
    if delta < 0:
        manifest["groups"].pop()
    else:
        extra = dict(manifest["groups"][-1], id="extra", files=["tests/test_extra.py"])
        manifest["groups"].append(extra)
    with pytest.raises(gate.GateError, match="Expected 83 focused groups"):
        gate._manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize("placement", ["suite", "nested", "duplicate"])
def test_skip_elements_cannot_hide_outside_a_unique_direct_testcase_status(evidence, placement):
    def change(suite):
        parent = suite if placement == "suite" else suite[0]
        if placement == "nested":
            parent = ET.SubElement(parent, "properties")
        ET.SubElement(parent, "skipped", message="Hidden skip")
        if placement == "duplicate":
            ET.SubElement(parent, "skipped", message="Duplicate skip")
        suite.set("skipped", "2" if placement == "duplicate" else "1")
    _xml_change(evidence, "current-0", change)
    path, summary = _summary(evidence)
    count = 2 if placement == "duplicate" else 1
    summary.update(skipped=count, skipped_elements=count)
    _json(path, summary)
    with pytest.raises(gate.GateError, match="case shape"):
        _run(evidence)


def test_focused_file_missing_from_full_inventory_refuses(evidence):
    manifest = json.loads(evidence["manifest"])
    manifest["groups"][-1]["files"] = ["tests/test_absent.py"]
    evidence["manifest"] = json.dumps(manifest).encode()
    with pytest.raises(gate.GateError, match="Focused file missing"):
        _run(evidence)


def test_real_manifest_and_workflow_preserve_coverage_without_pytest_reexecution():
    groups = gate._manifest(gate.MANIFEST.read_bytes())
    assert len(groups) == 83 and sum(group["zero_skips"] for group in groups) == 65
    assert sum(group["expected_tests"] or 0 for group in groups) == 7419
    assert all((_ROOT / filename).is_file() for group in groups for filename in group["files"])
    for identity, expected in (("rsi-python-scheduler-inputs", 97), ("independent-guardian", 101)):
        group = next(group for group in groups if group["id"] == identity)
        assert group["expected_tests"] == expected
    ready = next(group for group in groups if group["id"] == "rsi-ready-capsule-scalars")
    assert ready["expected_tests"] == 203
    assert "tests/test_rsi_flow_payload_scalar_validation.py" in ready["files"]
    native = next(group for group in groups if group["id"] == "native-original-whole-scope")
    assert {"tests/test_native_whole_scope_successor.py",
            "tests/test_native_whole_scope_successor_bootstrap.py",
            "tests/test_native_whole_scope_successor_ownership.py",
            "tests/test_native_whole_scope_successor_resources.py",
            "tests/test_native_whole_scope_stdio.py",
            "tests/test_external_worker_whole_scope_vault.py",
            "tests/test_external_worker_whole_scope_successor_vault.py",
            "tests/test_external_worker_whole_scope_successor_bridge.py",
            "tests/test_external_worker_whole_scope_bridge.py",
            "tests/test_external_worker_native_vault.py",
            "tests/test_external_worker_guardian_vault.py"}.issubset(native["files"])
    idle = next(group for group in groups if group["id"] == "brs-idle-history-observation")
    assert (native["expected_tests"], native["zero_skips"]) == (530, False)
    build = next(group for group in groups if group["id"] == "python-build-inputs")
    assert (build["expected_tests"], build["zero_skips"]) == (147, True)
    assert "tests/test_static_python_podman_helper_inputs.py" in build["files"]
    assert (idle["expected_tests"], idle["zero_skips"]) == (27, True)
    assert "tests/test_rsi_brs_owner_scope_cost.py" in idle["files"]
    fixed = next(group for group in groups if group["id"] == "native-fixed-u-input-contracts")
    assert (fixed["expected_tests"], fixed["zero_skips"]) == (42, True)
    assert set(fixed["files"]) == {"tests/test_native_fixed_u_inputs.py",
                                  "tests/test_native_fixed_u_attempt_inputs.py"}
    bootstrap = next(group for group in groups if group["id"] == "native-fixed-u-input-bootstrap")
    assert (bootstrap["expected_tests"], bootstrap["zero_skips"]) == (87, False)
    assert bootstrap["files"] == ["tests/test_native_fixed_u_input_bootstrap.py"]
    assert gate._FIXED_U_ROOT_NODES == _fixed_u_root_nodes()
    assert len(gate._FIXED_U_ROOT_NODES) == 36
    custody = next(group for group in groups if group["id"] == "native-whole-scope-custody")
    assert (custody["expected_tests"], custody["zero_skips"]) == (203, True)
    assert custody["files"] == ["tests/test_native_whole_scope_custody.py",
                               "tests/test_native_whole_scope_abnormal.py",
                               "tests/test_native_whole_scope_creator_custody.py",
                               "tests/test_native_whole_scope_creator_transport.py"]
    recipe = next(group for group in groups if group["id"] == "python-rsi-launch-source")
    assert (recipe["expected_tests"], recipe["zero_skips"]) == (680, True)
    assert "tests/test_static_python_zig_lld_capture.py" in recipe["files"]
    assert {"tests/test_static_python_source_data_backend.py",
            "tests/test_static_python_source_data_graph.py",
            "tests/test_static_python_source_data_consumer.py"}.issubset(recipe["files"])
    assert {"tests/test_static_python_podman_vfs_root.py",
            "tests/test_static_python_source_data_vfs_custody.py",
            "tests/test_static_python_source_data_vfs_backend.py",
            "tests/test_static_python_source_data_vfs_consumer.py"}.issubset(recipe["files"])
    assert {"tests/test_static_python_vfs_snapshots.py",
            "tests/test_static_python_retained_runtime_spec.py",
            "tests/test_static_python_source_data_vfs_retained_backend.py",
            "tests/test_static_python_source_data_vfs_retained_consumer.py",
            "tests/test_static_python_source_data_vfs_retained_custody.py"}.issubset(recipe["files"])
    assert "tests/test_static_python_dependency_profile_selection.py" in recipe["files"]
    assert {"tests/test_static_python_configuration_generation.py",
            "tests/test_static_python_configuration_review.py"}.issubset(recipe["files"])
    workflow = (_ROOT / ".github/workflows/test.yml").read_text()
    assert 'role: ["current-0"' in workflow and '"history"]' in workflow
    matrix = next(line.strip().partition("role: ")[2] for line in workflow.splitlines()
                  if line.strip().startswith("role: ["))
    provenance = next(line.strip().partition("roles = ")[2] for line in workflow.splitlines()
                      if line.strip().startswith("roles = {"))
    expected_roles = {*gate.ROLES, "history"}
    assert set(ast.literal_eval(matrix)) == ast.literal_eval(provenance) == expected_roles
    assert gate.ROLES[-7:] == tuple(f"heavy-{index}" for index in range(7))
    dependency_root = ".lunar-evolution/ci-dependencies/"
    assert "mkdir -p .lunar-evolution/ci-dependencies" in workflow
    assert "--output-file " + dependency_root + "ci-locked-requirements.txt" in workflow
    assert "--python .venv/bin/python " + dependency_root + "ci-locked-requirements.txt" in workflow
    assert "--output-file " + dependency_root + "ci-registry-metadata.txt" in workflow
    assert ".lunar-evolution/test-results/ci-locked-requirements.txt" not in workflow
    assert ".lunar-evolution/test-results/ci-registry-metadata.txt" not in workflow
    assert "needs: test" in workflow and "if: ${{ always() }}" in workflow
    assert "${{ needs.test.result }}" in workflow
    assert "python -m pytest" not in workflow
    assert "Annotate historical test failures" in workflow
    assert "--archive-retry .lunar-evolution/test-results/archived.retry1.xml" in workflow


@pytest.mark.parametrize("field,value", [
    ("heavy_count", 3), ("shard_algorithm", "sha256-path-utf8-mod-six-explicit-heavy-v2"),
])
def test_legacy_three_node_heavy_evidence_is_refused(evidence, field, value):
    path, record = _summary(evidence, "heavy-3")
    record[field] = value
    _json(path, record)
    with pytest.raises(gate.GateError):
        _run(evidence)
