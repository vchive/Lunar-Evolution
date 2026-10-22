"""Pure installation descriptor tests; no filesystem, build or runtime launch."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution import static_python_installation as installation


@pytest.fixture
def vector():
    return json.loads(
        (Path(__file__).parents[1] / "specs/189-static-python-fixture/wire-v1-example.json").read_text()
    )


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def parse(vector, payload=None, **pins):
    payload = vector["descriptor"] if payload is None else payload
    defaults = {
        "expected_descriptor_sha256": hashlib.sha256(encode(payload)).hexdigest(),
        "expected_installation_version": payload["installation_version"],
        "expected_artifact_sha256": payload.get("artifact_sha256", vector["descriptor"]["artifact_sha256"]),
    }
    defaults.update(pins)
    return installation.parse_static_python_installation_descriptor(encode(payload), **defaults)


def refused(callback, reason):
    with pytest.raises(installation.StaticPythonInstallationError) as caught:
        callback()
    assert caught.value.reason == "static_python_installation_" + reason
    assert str(caught.value) == caught.value.reason


def test_vector_is_detached_and_external_pins_are_mandatory(vector):
    observed = parse(vector)
    assert observed.descriptor_sha256 == vector["descriptor_sha256"]
    assert observed.artifact_size == 256
    assert observed.to_json() == encode(vector["descriptor"])
    detached = observed.to_dict()
    detached["production_admission"] = True
    assert observed.to_dict()["production_admission"] is False
    with pytest.raises(installation.StaticPythonInstallationError):
        parse(vector, expected_descriptor_sha256="0" * 64)
    with pytest.raises(installation.StaticPythonInstallationError):
        parse(vector, expected_installation_version="other-v1")
    with pytest.raises(installation.StaticPythonInstallationError):
        parse(vector, expected_artifact_sha256="f" * 64)


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p.update({"unknown": 1}), "schema"),
    (lambda p: p.pop("artifact_sha256"), "schema"),
    (lambda p: p.update({"execution_performed": True}), "claims"),
    (lambda p: p.update({"artifact_mode": 0o755}), "artifact_mode"),
    (lambda p: p.update({"artifact_size": 0}), "integer"),
    (lambda p: p.update({"source_commit": "1"}), "profile"),
    (lambda p: p["toolchain"].update({"target": "x86_64-linux-gnu"}), "toolchain"),
    (lambda p: p["recipe"]["environment"].append({"name": "HOME", "value": "/tmp"}), "environment"),
    (lambda p: p["embedded_startup_arrays"].append({}), "startup_arrays"),
    (lambda p: p["initialization_profile"]["config"].update({"use_environment": 1}), "initialization"),
    (lambda p: p["elf_profile"].update({"has_pt_interp": True}), "elf_profile"),
    (lambda p: p["frozen_modules"].reverse(), "frozen_inventory"),
])
def test_profile_mutations_refuse_before_any_external_effect(vector, mutation, reason):
    payload = copy.deepcopy(vector["descriptor"])
    mutation(payload)
    refused(lambda: parse(vector, payload), reason)


def test_manifest_digest_is_bound_to_canonical_nested_bytes(vector):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_flags"].append("-fvisibility=hidden")
    refused(lambda: parse(vector, payload), "manifest_pin")


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"{\"x\":1}", b"{\"schema_version\":1}"])
def test_wire_shapes_refuse(raw):
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            raw,
            expected_descriptor_sha256="a" * 64,
            expected_installation_version="v1",
            expected_artifact_sha256="b" * 64,
        ),
        "wire" if raw == b"" else "json_type" if raw == b"null" else "schema",
    )


def test_duplicate_json_keys_and_noncanonical_bytes_refuse(vector):
    raw = encode(vector["descriptor"]) + b" "
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            raw,
            expected_descriptor_sha256=hashlib.sha256(raw).hexdigest(),
            expected_installation_version="synthetic-v1",
            expected_artifact_sha256=vector["descriptor"]["artifact_sha256"],
        ),
        "canonical",
    )
    duplicate = b'{"schema_version":"1","schema_version":"1"}'
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            duplicate,
            expected_descriptor_sha256="a" * 64,
            expected_installation_version="v1",
            expected_artifact_sha256="b" * 64,
        ),
        "duplicate_key",
    )


def test_descriptor_overflow_is_rejected_before_json_parse(monkeypatch):
    monkeypatch.setattr(installation, "_scan", lambda _value: pytest.fail("scan must not run"))
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            b"{" + b" " * installation.MAX_DESCRIPTOR_BYTES,
            expected_descriptor_sha256="a" * 64,
            expected_installation_version="v1",
            expected_artifact_sha256="b" * 64,
        ),
        "wire",
    )

@pytest.mark.parametrize("section,flag", [
    ("configure_flags", "--enable-shared"),
    ("configure_flags", "--with-dynamic-loading"),
    ("compile_flags", "-fPIC"),
    ("compile_flags", "-fPIE"),
    ("link_flags", "-shared"),
    ("link_flags", "-pie"),
    ("link_flags", "-static-pie"),
    ("link_flags", "-ldl"),
    ("link_flags", "-Wl,-Bdynamic"),
    ("link_flags", "-Wl,-rpath=/tmp"),
])
def test_no_dynamic_recipe_rejects_loader_or_position_independent_escape(vector, section, flag):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"][section].append(flag)
    refused(lambda: parse(vector, payload), "recipe")


@pytest.mark.parametrize("flags", [
    ("-Wl,-rpath,/tmp",),
    ("-Wl,--rpath,/tmp",),
    ("-Wl,-rpath=/tmp",),
    ("-Wl,--dynamic-linker,/lib/ld-linux-x86-64.so.2",),
    ("-Wl,-dynamic-linker,/lib/ld-linux-x86-64.so.2",),
    ("-Wl,-Bdynamic,-ldl",),
    ("-Wl,--enable-new-dtags,-rpath,/tmp",),
    ("-Wl,-rpath-link,/tmp",),
    ("-Wl,-R,/tmp",),
    ("-Wl,-R/tmp",),
    ("-rpath", "/tmp"),
    ("--dynamic-linker", "/lib/ld-linux-x86-64.so.2"),
    ("-l:libdl.so.2",),
    ("-llibc.so",),
    ("-L/usr/lib",),
    ("--library=dl",),
    ("--library-path=/usr/lib",),
    ("-Xlinker=-rpath",),
    ("-Xlinker=--dynamic-linker",),
    ("-Wl,-I,/lib/ld-linux-x86-64.so.2",),
    ("-Wl,-I/lib/ld-linux-x86-64.so.2",),
    ("-I", "/lib/ld-linux-x86-64.so.2"),
    ("-I/lib/ld-linux-x86-64.so.2",),
    ("-Irelative-loader",),
    ("-Xlinker=-I", "-Xlinker=/lib/ld-linux-x86-64.so.2"),
    ("-Xlinker", "-I"),
    ("-dy",),
    ("-Wl,-dy",),
    ("-Xlinker=-dy",),
    ("-Bshareable",),
    ("-Wl,-Bshareable",),
    ("-Xlinker=-Bshareable",),
    ("-call_shared",),
    ("-Wl,-call_shared",),
    ("-Xlinker=-call_shared",),
    ("-G",),
    ("-Wl,-G",),
    ("-Xlinker=-G",),
    ("-E",),
    ("-Wl,-E",),
    ("-Xlinker=-E",),
    ("-frtlib-add-rpath",),
    ("-shared-libsan",),
    ("-shared-libasan",),
    ("-shared-libubsan",),
    ("-shared-libtsan",),
    ("-shared-libgcc",),
    ("--script=/tmp/ld.script",),
    ("--script", "/tmp/ld.script"),
    ("-flinker-output=dyn",),
    ("-fopenmp",),
    ("-fsanitize=address",),
    ("-z", "execstack"),
    ("-R", "/tmp/rpath"),
    ("-R/tmp/rpath",),
])
def test_no_dynamic_recipe_rejects_forwarded_linker_escape_forms(vector, flags):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_flags"].extend(flags)
    payload["recipe_sha256"] = hashlib.sha256(encode(payload["recipe"])).hexdigest()
    refused(lambda: parse(vector, payload), "recipe")


@pytest.mark.parametrize("field", ("configure_flags", "compile_flags", "link_flags"))
@pytest.mark.parametrize("flag", (
    "-Wl,--gc-sections", "-Xlinker=--gc-sections", "@/tmp/link.rsp", "@response-file",
    "-specs=/tmp/driver.specs", "-B/tmp/toolchain/", "-wrapper=/tmp/wrapper",
    "-fuse-ld=lld", "--ld-path=/tmp/ld", "--config=/tmp/clang.cfg",
    "--gcc-toolchain=/tmp/toolchain", "--gcc-install-dir=/tmp/toolchain", "-Xclang",
    "-fplugin=/tmp/plugin.so", "-fpass-plugin=/tmp/plugin.so", "-mllvm=-load=/tmp/plugin.so",
    "-Xoffload-linkerx86_64-linux-gnu", "-Xoffload-linker", "-T", "-T/tmp/linker.ld",
    "-R", "-R/tmp/rpath",
    "-foffload-options=nvptx-none=-Wl,-dynamic-linker,/lib/ld.so",
    "-Xopenmp-target=x86_64-linux-gnu", "-Xopenmp-target", "-fopenmp-targets=x86_64-linux-gnu",
    "--offload-arch=x86_64", "--offload-arch-tool=/tmp/tool", "--offload-link",
    "--cuda-path=/tmp/cuda", "--rocm-path=/tmp/rocm", "--hip-path=/tmp/hip",
    "--target=x86_64-unknown-linux-gnu", "-target=x86_64-unknown-linux-gnu",
    "--sysroot=/tmp/sysroot", "-isysroot=/tmp/sysroot", "--resource-dir=/tmp/clang-resource",
    "-resource-dir=/tmp/clang-resource",
))
def test_no_dynamic_recipe_rejects_driver_and_response_file_escape_in_every_flag_vector(
    vector, field, flag
):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"][field].append(flag)
    payload["recipe_sha256"] = hashlib.sha256(encode(payload["recipe"])).hexdigest()
    refused(lambda: parse(vector, payload), "recipe")


@pytest.mark.parametrize("field", ("configure_flags", "compile_flags", "link_flags"))
@pytest.mark.parametrize("flag", (
    "-l:libdl.so.2", "-llibc.so", "-L/usr/lib", "--library=dl", "--library-path=/usr/lib",
))
def test_no_dynamic_recipe_rejects_unpinned_library_search_in_every_flag_vector(
    vector, field, flag
):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"][field].append(flag)
    payload["recipe_sha256"] = hashlib.sha256(encode(payload["recipe"])).hexdigest()
    refused(lambda: parse(vector, payload), "recipe")


@pytest.mark.parametrize("name", ("CFLAGS", "CPPFLAGS", "LDFLAGS"))
@pytest.mark.parametrize("value", (
    "-shared", "-fPIC", "-L/usr/lib", "-l:libdl.so.2", "-Wl", "-B/tmp/toolchain",
    "-zexecstack", "-fsanitize", "-fopenmp", "-flinker-output", "-R/tmp/rpath", "-R",
))
def test_no_dynamic_recipe_rejects_unsafe_flag_environment_values(vector, name, value):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["environment"].append({"name": name, "value": value})
    payload["recipe"]["environment"].sort(key=lambda item: item["name"])
    payload["recipe_sha256"] = hashlib.sha256(encode(payload["recipe"])).hexdigest()
    refused(lambda: parse(vector, payload), "recipe")


def test_no_dynamic_recipe_requires_static_and_non_pie_link(vector):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_flags"].remove("-static")
    refused(lambda: parse(vector, payload), "recipe")
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_flags"].remove("-no-pie")
    refused(lambda: parse(vector, payload), "recipe")


def test_no_dynamic_recipe_rejects_shared_link_inputs(vector):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_inputs"][0]["path"] = "objects/libpython.so"
    refused(lambda: parse(vector, payload), "recipe")
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_inputs"][0]["path"] = "objects/libpython.dylib"
    refused(lambda: parse(vector, payload), "recipe")


def test_no_dynamic_recipe_rejects_shell_like_environment_values(vector):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["environment"][0]["value"] = "C;touch-pwned"
    refused(lambda: parse(vector, payload), "environment")


def test_no_dynamic_recipe_keeps_non_pie_flags_allowed(vector):
    observed = parse(vector)
    recipe = observed.to_dict()["recipe"]
    assert "-fno-PIE" in recipe["compile_flags"]
    assert "-no-pie" in recipe["link_flags"]
    assert "-pie" not in recipe["link_flags"]
