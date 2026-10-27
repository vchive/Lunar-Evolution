from __future__ import annotations

import copy
import hashlib
import json
import time

import pytest

# Explicit re-exports register reused pytest fixtures and avoid parameter-shadow lint.
from tests.test_static_python_rsi_execution_backend_v2 import (
    inert_v2_tool as inert_v2_tool,  # noqa: PLC0414
)
from tests.test_static_python_rsi_execution_backend_v2 import (
    v2_fixture as v2_fixture,  # noqa: PLC0414
)
from tools.static_python_rsi_fixture.execution_backend import (
    MAX_RECIPE_BYTES,
    MAX_V3_RECIPE_BYTES,
    RECIPE_SCHEMA,
    RECIPE_V2_SCHEMA,
    RECIPE_V3_SCHEMA,
    BuildExecutionError,
    _recipe,
    run_pinned_build,
    run_pinned_build_v3,
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def checked(payload, *, version3=True):
    raw = canonical(payload)
    return _recipe(raw, hashlib.sha256(raw).hexdigest(), version3=version3)


def v3_payload(fixture):
    payload = copy.deepcopy(fixture[4])
    payload["schema"] = RECIPE_V3_SCHEMA
    return payload


def test_v3_same_mechanism_executes_only_inert_helper_with_private_cache_environment(v2_fixture):
    prep, source, tools, workspace, _ = v2_fixture
    payload = v3_payload(v2_fixture)
    raw = canonical(payload)
    report = run_pinned_build_v3(
        prep, recipe_bytes=raw, expected_recipe_sha256=hashlib.sha256(raw).hexdigest(),
        source_root=source, toolchain_root=tools, workspace=workspace, deadline=time.monotonic() + 10,
    )
    assert report.completed_stages == ("configure", "freeze", "compile", "link")
    assert json.loads((workspace / "report.json").read_bytes())["schema"].endswith("-v3")
    assert (workspace / "work/image.out").read_bytes() == b"#define LUNAR_TINY_FIXTURE 1\n"
    assert not any((report.configured_closure_verified, report.installation_accepted,
                    report.runtime_execution_performed, report.production_admission))


def test_legacy_public_entrypoint_refuses_v3_before_workspace(v2_fixture):
    prep, source, tools, workspace, _ = v2_fixture
    raw = canonical(v3_payload(v2_fixture))
    with pytest.raises(BuildExecutionError, match="recipe_shape_invalid"):
        run_pinned_build(prep, recipe_bytes=raw, expected_recipe_sha256=hashlib.sha256(raw).hexdigest(),
                         source_root=source, toolchain_root=tools, workspace=workspace,
                         deadline=time.monotonic() + 10)
    assert not workspace.exists()


@pytest.mark.parametrize("schema", [RECIPE_SCHEMA, RECIPE_V2_SCHEMA])
def test_v3_public_entrypoint_cannot_implicitly_accept_old_wire(v2_fixture, schema):
    payload = v3_payload(v2_fixture)
    payload["schema"] = schema
    with pytest.raises(BuildExecutionError, match="recipe_shape_invalid"):
        checked(payload)


def test_full_zig_sized_inventory_is_within_v3_only(v2_fixture):
    payload = v3_payload(v2_fixture)
    original = payload["inputs"]["toolchain"][0]
    payload["inputs"]["toolchain"] += [
        {"path": f"lib/complete-input-{i:05d}", "size": 1, "sha256": hashlib.sha256(b"x").hexdigest(),
         "executable": False} for i in range(19545)
    ]
    payload["inputs"]["toolchain"].sort(key=lambda r: r["path"])
    raw = canonical(payload)
    assert MAX_RECIPE_BYTES < len(raw) < MAX_V3_RECIPE_BYTES
    assert len(checked(payload)["inputs"]["toolchain"]) == 19546
    assert original in payload["inputs"]["toolchain"]
    payload["schema"] = RECIPE_V2_SCHEMA
    with pytest.raises(BuildExecutionError, match="recipe_pin_mismatch"):
        checked(payload, version3=False)


@pytest.mark.parametrize("schema", [RECIPE_SCHEMA, RECIPE_V2_SCHEMA, RECIPE_V3_SCHEMA])
def test_inventory_bound_is_schema_specific_without_changing_old_count_gate(v2_fixture, schema):
    payload = v3_payload(v2_fixture)
    payload["schema"] = schema
    payload["inputs"]["source"] = [None] * (32769 if schema == RECIPE_V3_SCHEMA else 16385)
    with pytest.raises(BuildExecutionError, match="input_inventory_invalid"):
        checked(payload, version3=schema == RECIPE_V3_SCHEMA)


@pytest.mark.parametrize("reference", ["@source-dir/../escape", "@source-dir/missing",
                                         "@work-dir/future", "@toolchain-dir/."])
def test_directory_reference_is_canonical_and_declared(v2_fixture, reference):
    payload = v3_payload(v2_fixture)
    payload["stages"][0]["commands"][0]["argv"].append(reference)
    with pytest.raises(BuildExecutionError):
        checked(payload)


def test_declared_input_and_prior_work_directories_are_explicit_v3_refs(v2_fixture):
    payload = v3_payload(v2_fixture)
    payload["inputs"]["source"].append({"path": "include/header.h", "size": 1,
                                        "sha256": hashlib.sha256(b"x").hexdigest(), "executable": False})
    payload["inputs"]["source"].sort(key=lambda r: r["path"])
    payload["stages"][0]["commands"][0]["argv"] += ["-I", "@source-dir/include"]
    payload["stages"][2]["commands"][0]["argv"] += ["-I", "@work-dir/generated-sources/Python"]
    checked(payload)
    payload["schema"] = RECIPE_V2_SCHEMA
    with pytest.raises(BuildExecutionError, match="reference_invalid"):
        checked(payload, version3=False)


def test_directories_are_not_executable_authority(v2_fixture):
    payload = v3_payload(v2_fixture)
    payload["inputs"]["toolchain"].append({"path": "lib/input", "size": 1,
                                           "sha256": hashlib.sha256(b"x").hexdigest(), "executable": False})
    payload["inputs"]["toolchain"].sort(key=lambda r: r["path"])
    payload["stages"][0]["commands"][0]["argv"][0] = "@toolchain-dir/lib"
    with pytest.raises(BuildExecutionError, match="executable_not_pinned"):
        checked(payload)


def test_v3_command_bound_accommodates_real_freezer_graph(v2_fixture):
    payload = v3_payload(v2_fixture)
    prototype = payload["stages"][0]["commands"][0]
    commands = []
    for i in range(257):
        command = copy.deepcopy(prototype)
        path = f"configuration/probe-{i}.o"
        command["argv"][-1] = "@work/" + path
        command["outputs"][0]["path"] = path
        commands.append(command)
    payload["stages"][0]["commands"] = commands
    checked(payload)
    payload["schema"] = RECIPE_V2_SCHEMA
    with pytest.raises(BuildExecutionError, match="commands_invalid"):
        checked(payload, version3=False)


@pytest.mark.parametrize("key", ["ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR", "ZIG_LIB_DIR"])
def test_no_new_caller_selected_zig_or_model_environment(v2_fixture, key):
    payload = v3_payload(v2_fixture)
    payload["environment"][key] = "/ambient/cache"
    with pytest.raises(BuildExecutionError, match="environment_invalid"):
        checked(payload)


def test_original_v3_dispatch_owns_resource_root_and_ignores_ambient_override(v2_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    prep, source, tools, workspace, _ = v2_fixture
    monkeypatch.setenv("ZIG_LIB_DIR", "/ambient/unapproved-resource-root")
    original = execution_backend._command
    dispatched = []

    def observe(argv, **kwargs):
        dispatched.append(dict(kwargs["environment"]))
        return original(argv, **kwargs)

    monkeypatch.setattr(execution_backend, "_command", observe)
    raw = canonical(v3_payload(v2_fixture))
    report = run_pinned_build_v3(
        prep, recipe_bytes=raw, expected_recipe_sha256=hashlib.sha256(raw).hexdigest(),
        source_root=source, toolchain_root=tools, workspace=workspace, deadline=time.monotonic() + 10,
    )
    assert report.status == "complete" and dispatched
    assert all(row["ZIG_LIB_DIR"] == str(workspace / "toolchain/lib") for row in dispatched)
