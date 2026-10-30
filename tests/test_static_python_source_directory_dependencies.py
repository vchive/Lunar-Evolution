"""Fixed source-owned depfile aliases; doubles establish no build acceptance.

The twelve spellings below are an independent oracle transcribed from the
retained 202 original compiler depfiles and pinned-directory proof. They are
not generated from the product's alias table. Existing recipe/capture factories
remain active; only native execution and OCI observation use existing doubles.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests import test_static_python_source_data_consumer as source_transport
from tests import test_static_python_source_data_vfs_retained_consumer as retained_transport
from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tests.test_static_python_source_data_graph import _comparison
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import dependency_capture as compiler
from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture.runtime_closure import canonical

PROFILE = "source-inventory-directories-v1"
BACKEND = "podman-snapshots-source-data-vfs-retained-v1"
legacy_transport = source_transport.transport
transport = retained_transport.transport

# These literal directory sequences preserve every traversal step, including
# repeated parents and the separately bound source root after Python/..
ALIAS_CASES = (
    ("Modules/_hacl/internal/../Hacl_Hash_SHA2.h", "Modules/_hacl/Hacl_Hash_SHA2.h",
     ("@source/Modules", "@source/Modules/_hacl", "@source/Modules/_hacl/internal", "@source/Modules/_hacl")),
    ("Modules/_hacl/internal/../Hacl_Streaming_Types.h", "Modules/_hacl/Hacl_Streaming_Types.h",
     ("@source/Modules", "@source/Modules/_hacl", "@source/Modules/_hacl/internal", "@source/Modules/_hacl")),
    ("Modules/_hacl/internal/../python_hacl_namespaces.h", "Modules/_hacl/python_hacl_namespaces.h",
     ("@source/Modules", "@source/Modules/_hacl", "@source/Modules/_hacl/internal", "@source/Modules/_hacl")),
    ("Parser/lexer/../tokenizer/../lexer/state.h", "Parser/lexer/state.h",
     ("@source/Parser", "@source/Parser/lexer", "@source/Parser", "@source/Parser/tokenizer",
      "@source/Parser", "@source/Parser/lexer")),
    ("Parser/lexer/../tokenizer/helpers.h", "Parser/tokenizer/helpers.h",
     ("@source/Parser", "@source/Parser/lexer", "@source/Parser", "@source/Parser/tokenizer")),
    ("Parser/tokenizer/../lexer/buffer.h", "Parser/lexer/buffer.h",
     ("@source/Parser", "@source/Parser/tokenizer", "@source/Parser", "@source/Parser/lexer")),
    ("Parser/tokenizer/../lexer/lexer.h", "Parser/lexer/lexer.h",
     ("@source/Parser", "@source/Parser/tokenizer", "@source/Parser", "@source/Parser/lexer")),
    ("Parser/tokenizer/../lexer/state.h", "Parser/lexer/state.h",
     ("@source/Parser", "@source/Parser/tokenizer", "@source/Parser", "@source/Parser/lexer")),
    ("Python/../Parser/lexer/lexer.h", "Parser/lexer/lexer.h",
     ("@source/Python", "@source", "@source/Parser", "@source/Parser/lexer")),
    ("Python/../Parser/lexer/state.h", "Parser/lexer/state.h",
     ("@source/Python", "@source", "@source/Parser", "@source/Parser/lexer")),
    ("Python/../Parser/pegen.h", "Parser/pegen.h", ("@source/Python", "@source", "@source/Parser")),
    ("Python/../Parser/tokenizer/tokenizer.h", "Parser/tokenizer/tokenizer.h",
     ("@source/Python", "@source", "@source/Parser", "@source/Parser/tokenizer")),
)


def _generate(monkeypatch, *, removed=(), extra=()):
    names = {"unit.c", "Modules/_hacl/internal/anchor.h", "Python/anchor.h"}
    names.update(case[1] for case in ALIAS_CASES)
    names.difference_update(removed)
    sources = [record(name, ("inert " + name).encode()) for name in sorted(names)]
    sources.extend(extra)
    sources.sort(key=lambda row: row["path"])
    base = base_recipe(sha(b"prep"), sources,
                       [record("lib/crt.o"), record("zig", executable=True)])
    legacy = instrument(monkeypatch, base)
    return capture._data_source_capture_successor(
        legacy, original_source_inventory_sha256=sha(canonical(sources)))


@pytest.fixture
def vector(monkeypatch):
    generated = _generate(monkeypatch)
    kwargs, artifacts, _ = _comparison(generated)
    return generated, kwargs, artifacts


def _append_paths(vector, paths, *, depfile=None):
    _generated, kwargs, artifacts = vector
    name = next(iter(artifacts)) if depfile is None else depfile
    artifacts[name] = artifacts[name].rstrip(b"\n") + b" " + " ".join(paths).encode() + b"\n"
    rows = json.loads(kwargs["output_inventory_bytes"])
    next(row for row in rows if row["path"] == name).update(
        size=len(artifacts[name]), sha256=sha(artifacts[name]))
    kwargs.update(output_inventory_bytes=canonical(rows), expected_output_inventory_sha256=sha(canonical(rows)))


def _compare(vector):
    generated, kwargs, artifacts = vector
    return compiler.compare_compiler_dependencies_v4_source_directories(
        generated.recipe_bytes, **kwargs, dependency_artifacts=artifacts).to_dict()


@pytest.mark.parametrize("alias,canonical_path,directories", ALIAS_CASES)
def test_only_fixed_observed_source_aliases_bind_inventory_directories(
        vector, alias, canonical_path, directories):
    _append_paths(vector, ["/attempt/source/" + alias])
    result = _compare(vector)
    assert result["schema"] == "lunar-cpython-compiler-dependency-comparison-v3"
    assert result["dependency_path_profile"] == PROFILE
    assert result["source_directory_aliases"] == [{
        "reference": "@source/" + alias, "canonical_reference": "@source/" + canonical_path,
        "directories": list(directories)}]
    assert "@source/" + canonical_path in result["compilations"][0]["dependencies"]
    assert "@source/" + alias not in result["compilations"][0]["dependencies"]
    assert result["production_admission"] is False


def test_alias_receipt_is_unique_sorted_and_keeps_original_depfile_pin(vector):
    paths = ["/attempt/source/" + case[0] for case in reversed(ALIAS_CASES)]
    first, second, *_ = vector[2]
    _append_paths(vector, paths, depfile=first)
    _append_paths(vector, [paths[0]], depfile=second)
    result = _compare(vector)
    assert result["source_directory_aliases"] == [{
        "reference": "@source/" + alias, "canonical_reference": "@source/" + member,
        "directories": list(directories)} for alias, member, directories in ALIAS_CASES]
    assert result["compilations"][0]["depfile_sha256"] == sha(next(iter(vector[2].values())))
    assert b"/attempt/" not in canonical(result)


def test_explicit_profile_without_aliases_still_has_distinct_receipt(vector):
    result = _compare(vector)
    assert result["dependency_path_profile"] == PROFILE and result["source_directory_aliases"] == []
    assert result["schema"] == "lunar-cpython-compiler-dependency-comparison-v3"


@pytest.mark.parametrize("case", [ALIAS_CASES[0], ALIAS_CASES[4], ALIAS_CASES[-1]])
def test_original_v4_comparator_still_refuses_the_same_fixed_alias(vector, case):
    _append_paths(vector, ["/attempt/source/" + case[0]])
    generated, kwargs, artifacts = vector
    with pytest.raises(compiler.CompilerDependencyError, match="dependency_path"):
        compiler.compare_compiler_dependencies_v4(
            generated.recipe_bytes, **kwargs, dependency_artifacts=artifacts)


@pytest.mark.parametrize("path", [
    "/attempt/source/Parser/lexer/./../tokenizer/helpers.h",
    "/attempt/source/Parser/lexer//../tokenizer/helpers.h",
    "/attempt/source/Parser/tokenizer/../tokenizer/helpers.h",
    "/attempt/source/Parser/lexer/../tokenizer/unknown.h",
    "/attempt/source/Parser/lexer/../tokenizer/helpers.h/..",
    "/attempt/source/../../source/unit.c",
    "/attempt/source/Parser/lexer/../../Python/../Parser/tokenizer/helpers.h",
    "/attempt/toolchain/Parser/lexer/../tokenizer/helpers.h",
    "/attempt/work/objects/../probe.o",
    "/attempt/source-lookalike/Parser/lexer/../tokenizer/helpers.h",
    "Parser/lexer/../tokenizer/helpers.h",
    "/etc/../etc/hosts",
])
def test_profile_does_not_generalize_to_other_dot_paths_roots_or_spellings(vector, path):
    _append_paths(vector, [path])
    with pytest.raises(compiler.CompilerDependencyError):
        _compare(vector)


@pytest.mark.parametrize("removed", [
    ("Modules/_hacl/internal/anchor.h",),
    ("Modules/_hacl/Hacl_Hash_SHA2.h",),
])
def test_fixed_alias_requires_both_traversed_directory_and_canonical_member(monkeypatch, removed):
    generated = _generate(monkeypatch, removed=removed)
    kwargs, artifacts, _ = _comparison(generated)
    vector = generated, kwargs, artifacts
    _append_paths(vector, ["/attempt/source/" + ALIAS_CASES[0][0]])
    with pytest.raises(compiler.CompilerDependencyError):
        _compare(vector)


def test_inventory_regular_file_is_never_a_traversable_alias_directory(monkeypatch):
    generated = _generate(monkeypatch, extra=[record("Modules/_hacl/internal", b"regular file")])
    kwargs, artifacts, _ = _comparison(generated)
    vector = generated, kwargs, artifacts
    _append_paths(vector, ["/attempt/source/" + ALIAS_CASES[0][0]])
    with pytest.raises(compiler.CompilerDependencyError):
        _compare(vector)


def test_canonical_member_cannot_also_be_a_declared_directory(monkeypatch):
    generated = _generate(monkeypatch, extra=[
        record("Modules/_hacl/Hacl_Hash_SHA2.h/child", b"inert conflicting child"),
    ])
    kwargs, artifacts, _ = _comparison(generated)
    _append_paths((generated, kwargs, artifacts), ["/attempt/source/" + ALIAS_CASES[0][0]])
    with pytest.raises(compiler.CompilerDependencyError, match="dependency_path"):
        _compare((generated, kwargs, artifacts))


def test_profile_keeps_original_artifact_pin_refusal(vector):
    vector[2][next(iter(vector[2]))] += b" "
    with pytest.raises(compiler.CompilerDependencyError, match="artifact_pin"):
        _compare(vector)


def test_source_alias_comparison_does_not_read_filesystem(vector, monkeypatch):
    _append_paths(vector, ["/attempt/source/" + ALIAS_CASES[-1][0]])

    def refuse(*_args, **_kwargs):
        pytest.fail("pure alias comparator performed filesystem I/O")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", refuse)
        patch.setattr(os, "open", refuse)
        result = _compare(vector)
    assert result["dependency_path_profile"] == PROFILE


def test_named_retained_entry_binds_new_comparison_and_preserves_original_report(transport):
    kwargs, _wire, controls, _observed = transport
    result = consumer.run_dependency_checked_build_v4_vfs_retained_source_directories(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    comparison_raw = (kwargs["workspace"] / "compiler-dependency-comparison.json").read_bytes()
    comparison = json.loads(comparison_raw)
    report_raw = (kwargs["workspace"] / "report.json").read_bytes()
    report = json.loads(report_raw)
    assert controls["calls"] == 1
    assert evidence["schema"] == "lunar-actual-build-dependency-consumer-v5"
    assert evidence["dependency_path_profile"] == comparison["dependency_path_profile"] == PROFILE
    assert comparison["source_directory_aliases"] == []
    assert evidence["compiler_comparison_sha256"] == sha(comparison_raw) == result.compiler_comparison_sha256
    assert evidence["execution_report_sha256"] == sha(report_raw)
    assert report["schema"] == "lunar-static-python-build-execution-report-v6"
    assert report["custody_backend"] == BACKEND
    assert "dependency_path_profile" not in report
    assert "source_directory_aliases" not in evidence
    for key in ("immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
                "installation_accepted", "production_admission", "online_publication"):
        assert evidence[key] is False and getattr(result, key) is False


def test_original_retained_entry_keeps_original_receipt_without_profile(transport):
    kwargs, _wire, controls, _observed = transport
    consumer.run_dependency_checked_build_v4_vfs_retained(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    comparison = json.loads((kwargs["workspace"] / "compiler-dependency-comparison.json").read_bytes())
    assert controls["calls"] == 1 and evidence["schema"] == "lunar-actual-build-dependency-consumer-v4"
    assert "dependency_path_profile" not in evidence and "dependency_path_profile" not in comparison


@pytest.mark.parametrize("backend", [None, "podman", "host", "podman-snapshots-v1",
                                     "podman-snapshots-source-data-vfs-v1", True])
def test_named_profile_never_changes_backend_or_uses_fallback_before_runner(transport, backend):
    kwargs, _wire, controls, _observed = transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend"):
        consumer.run_dependency_checked_build_v4_vfs_retained_source_directories(
            object(), **kwargs, custody_backend=backend)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


@pytest.mark.parametrize("drift,reason", [
    ("report", "file_pin"), ("source_mode", "file_pin"), ("output", "file_pin"),
    ("deadline", "deadline_expired"), ("interrupt", "interrupted"),
])
def test_named_profile_keeps_original_file_pins_budget_and_failure_report(transport, drift, reason):
    kwargs, _wire, controls, _observed = transport
    controls["drift"] = drift
    with pytest.raises(consumer.BuildDependencyError, match=reason) as failure:
        consumer.run_dependency_checked_build_v4_vfs_retained_source_directories(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert (kwargs["workspace"] / "report.json").is_file()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


def test_named_profile_has_no_arbitrary_profile_override(transport):
    kwargs, _wire, controls, _observed = transport
    with pytest.raises(TypeError):
        consumer.run_dependency_checked_build_v4_vfs_retained_source_directories(
            object(), **kwargs, dependency_path_profile="arbitrary-dot-path-policy")
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()
