"""Actual inert shell processes, not CPython configure/build acceptance.

The fixture replaces the separately pinned configure source and complete Zig
inventory explicitly. Only the retained process/readback/dispatch mechanics are
exercised; no compiler, host Python, freezer or target is executed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import pytest

from tests.test_static_python_concrete_recipe import (
    concrete_inputs,  # noqa: F401 - shared pytest fixture
)
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import configuration_generation as generation
from tools.static_python_rsi_fixture.runtime_closure import canonical


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory(root):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            rows.append({"path": path.relative_to(root).as_posix(), "size": len(raw),
                         "sha256": sha(raw), "executable": bool(path.stat().st_mode & 0o111)})
    return canonical(rows)


@pytest.fixture
def configure_case(tmp_path, monkeypatch):
    script = b"set -eu\n"
    for name in generation.OUTPUTS:
        script += ("printf '%s\\n' 'inert-" + name + "' > '" + name + "'\n").encode()
    source, helpers, zig = (tmp_path / name for name in ("input-source", "input-helpers", "input-zig"))
    for root in (source, helpers, zig):
        root.mkdir()
    (source / "configure").write_bytes(script)
    (helpers / "bin").mkdir()
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("actual inert shell mechanism requires sh")
    for name in generation.HELPER_PROGRAMS:
        path = helpers / "bin" / name
        path.write_bytes(Path(shell).read_bytes() if name == "sh" else b"unused-inert-helper\n")
        path.chmod(0o700)
    (zig / "zig").write_bytes(b"unused-inert-zig\n")
    (zig / "zig").chmod(0o700)
    (zig / "lib").mkdir()
    (zig / "lib/resource").write_bytes(b"inert-lib\n")
    monkeypatch.setattr(generation, "CONFIGURE_BYTES", len(script))
    monkeypatch.setattr(generation, "CONFIGURE_SHA256", sha(script))
    monkeypatch.setattr(generation, "complete_zig_inventory", lambda _: json.loads(inventory(zig)))
    source_inventory, helper_inventory = inventory(source), inventory(helpers)
    return {"source_root": source, "helper_root": helpers, "toolchain_root": zig,
            "workspace": tmp_path / "attempt", "source_inventory_bytes": source_inventory,
            "expected_source_inventory_sha256": sha(source_inventory),
            "helper_inventory_bytes": helper_inventory,
            "expected_helper_inventory_sha256": sha(helper_inventory),
            "zig_manifest_bytes": b"explicit synthetic manifest", "deadline": time.monotonic() + 30}


def test_actual_inert_configure_process_and_original_output_readback(configure_case):
    result = generation.run_cpython_configuration(**configure_case)
    assert result.configuration_header == b"inert-pyconfig.h\n"
    assert result.makefile == b"inert-Makefile\n"
    observation = json.loads(result.observation_bytes)
    root = configure_case["workspace"]
    assert observation["status"] == "observed" and observation["reason"] is None
    assert (root / "observation.json").read_bytes() == result.observation_bytes
    assert observation["command"]["direct_child_reaped"] is True
    assert observation["command"]["descendant_cleanup_verified"] is False
    assert {row["path"] for row in observation["outputs"]} == set(generation.OUTPUTS)
    assert all(observation[key] is False for key in generation._FALSE)
    assert not result.production_admission and not result.configured_closure_verified
    assert not (root / "work/.zig-global-cache").exists()


def test_fixed_environment_does_not_inherit_ambient_flags(configure_case, monkeypatch):
    for name in ("CFLAGS", "CPPFLAGS", "CC", "PYTHONPATH", "ZIG_LIB_DIR", "CONFIG_SITE"):
        monkeypatch.setenv(name, "ambient-must-not-arrive")
    result = generation.run_cpython_configuration(**configure_case)
    wire = json.loads(result.observation_bytes)
    environment = wire["environment"]
    assert "ambient-must-not-arrive" not in str(environment)
    assert "PYTHONPATH" not in environment
    assert environment["ZIG_LIB_DIR"].endswith("/toolchain/lib")
    assert environment["PKG_CONFIG"].endswith("/helpers/bin/false")
    assert environment["CXX"].endswith("/helpers/bin/false")
    assert environment["PYTHONHOME"].endswith("/helpers")
    assert all("--zig-lib-dir" not in (configure_case["workspace"] / "work" / name).read_text()
               for name in ("cc", "ar", "ranlib"))
    assert wire["argv"][:2] == [str(configure_case["workspace"] / "helpers/bin/sh"),
                               str(configure_case["workspace"] / "source/configure")]
    assert "--disable-ipv6" in wire["argv"]
    assert not any("make" == Path(word).name for word in wire["argv"])


@pytest.mark.parametrize("field", ["source_inventory_bytes", "helper_inventory_bytes"])
def test_independent_inventory_pin_refused_before_workspace(configure_case, field):
    configure_case[field] += b" "
    with pytest.raises(generation.ConfigurationGenerationError, match="configuration_inventory"):
        generation.run_cpython_configuration(**configure_case)
    assert not configure_case["workspace"].exists()


def test_pinned_configure_source_cannot_be_replaced(configure_case, monkeypatch):
    monkeypatch.setattr(generation, "CONFIGURE_SHA256", "a" * 64)
    with pytest.raises(generation.ConfigurationGenerationError, match="configure_source"):
        generation.run_cpython_configuration(**configure_case)
    assert not configure_case["workspace"].exists()


@pytest.mark.parametrize("kind", ["missing", "nonexecutable", "make", "preconfigured"])
def test_helper_closure_and_fresh_source_gates(configure_case, kind):
    helpers, source = configure_case["helper_root"], configure_case["source_root"]
    if kind == "missing":
        (helpers / "bin/sed").unlink()
    elif kind == "nonexecutable":
        (helpers / "bin/sed").chmod(0o600)
    elif kind == "make":
        (helpers / "bin/make").write_bytes(b"refused\n")
    else:
        (source / "pyconfig.h").write_bytes(b"prior-configuration\n")
    for name, root in (("source", source), ("helper", helpers)):
        raw = inventory(root)
        configure_case[name + "_inventory_bytes"] = raw
        configure_case["expected_" + name + "_inventory_sha256"] = sha(raw)
    with pytest.raises(generation.ConfigurationGenerationError):
        generation.run_cpython_configuration(**configure_case)
    assert not configure_case["workspace"].exists()


def test_first_failed_process_is_retained_and_workspace_cannot_be_reused(configure_case, monkeypatch):
    script = b"printf 'first-configure-failure\\n' >&2\nexit 23\n"
    (configure_case["source_root"] / "configure").write_bytes(script)
    raw = inventory(configure_case["source_root"])
    configure_case.update(source_inventory_bytes=raw, expected_source_inventory_sha256=sha(raw))
    monkeypatch.setattr(generation, "CONFIGURE_BYTES", len(script))
    monkeypatch.setattr(generation, "CONFIGURE_SHA256", sha(script))
    with pytest.raises(generation.ConfigurationGenerationError, match="command_failed"):
        generation.run_cpython_configuration(**configure_case)
    root = configure_case["workspace"]
    original = (root / "observation.json").read_bytes()
    assert (root / "logs/stderr.log").read_bytes() == b"first-configure-failure\n"
    assert json.loads(original)["command"]["returncode"] == 23
    with pytest.raises(generation.ConfigurationGenerationError, match="workspace_not_fresh"):
        generation.run_cpython_configuration(**configure_case)
    assert (root / "observation.json").read_bytes() == original


@pytest.mark.parametrize("control", ["deadline", "interrupted"])
def test_absolute_controls_refuse_before_workspace(configure_case, control):
    configure_case[control] = (time.monotonic() - 1) if control == "deadline" else lambda: True
    with pytest.raises(generation.ConfigurationGenerationError, match=control):
        generation.run_cpython_configuration(**configure_case)
    assert not configure_case["workspace"].exists()


@pytest.mark.parametrize("control", ["deadline", "interrupted"])
def test_original_running_process_control_reason_and_reap_are_retained(configure_case, monkeypatch, control):
    script = b"printf 'running-configure\\n' > running-marker\nprintf 'running-configure\\n' >&2\nwhile :; do :; done\n"
    (configure_case["source_root"] / "configure").write_bytes(script)
    raw = inventory(configure_case["source_root"])
    configure_case.update(source_inventory_bytes=raw, expected_source_inventory_sha256=sha(raw))
    monkeypatch.setattr(generation, "CONFIGURE_BYTES", len(script))
    monkeypatch.setattr(generation, "CONFIGURE_SHA256", sha(script))
    marker = configure_case["workspace"] / "work/running-marker"
    if control == "deadline":
        configure_case["deadline"] = time.monotonic() + 5
    else:
        configure_case["interrupted"] = lambda: marker.is_file() and b"running-configure" in marker.read_bytes()
    with pytest.raises(generation.ConfigurationGenerationError, match=control):
        generation.run_cpython_configuration(**configure_case)
    assert marker.read_bytes() == b"running-configure\n"
    command = json.loads((configure_case["workspace"] / "observation.json").read_bytes())["command"]
    assert command["status"] == "partial" and command["reason"] == control
    assert command["direct_child_reaped"] is True


def test_generated_header_can_reach_existing_recipe_with_separate_pin(configure_case, concrete_inputs):  # noqa: F811
    result = generation.run_cpython_configuration(**configure_case)
    prep, args = concrete_inputs
    # This fixed test digest is independent of the process's observation; it is
    # not a production review. The recipe still independently requires a pin.
    args.update(configuration_header=result.configuration_header,
                expected_configuration_sha256=sha(b"inert-pyconfig.h\n"))
    generated = concrete.prepare_cpython_build_recipe(prep, **args)
    assert dict(generated.sources)["configuration/pyconfig.h"] == b"inert-pyconfig.h\n"
    assert json.loads(generated.manifest_bytes)["configured_closure_verified"] is False
    args["expected_configuration_sha256"] = sha(b"different-independent-expected-config\n")
    with pytest.raises(concrete.ConcreteRecipeError, match="input_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args)
