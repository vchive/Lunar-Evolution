"""Independent v1 encoding oracle and portable bounded parsing, never live material."""

from __future__ import annotations

import base64
import builtins
import hashlib
import json
import os
import struct
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from lunar_evolution import _python_runtime_material_format as fmt


@pytest.fixture
def vector():
    return json.loads(
        (
            Path(__file__).parents[1] / "specs/188-sealed-runtime-material/wire-v1-example.json"
        ).read_text()
    )


def canonical(value):
    # Independent oracle; do not derive expected encodings through the implementation.
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def table(vector):
    return fmt.parse_table(vector["table_utf8"].encode("utf-8"))


def descriptor(vector):
    return fmt.descriptor_from_table(
        table(vector),
        vector["table_size"],
        vector["table_sha256"],
        vector["payload_sha256"],
        vector["frame_sha256"],
    )


def refused(callback):
    with pytest.raises(fmt.PythonRuntimeMaterialError) as error:
        callback()
    assert error.value.code.startswith("python_runtime_material_")
    return error.value.code


def test_independent_header_table_payload_frame_vector(vector):
    header = bytes.fromhex(vector["header_hex"])
    assert header == b"LUNARPYMAT" + b"\x00" * 5 + b"\x01" + struct.pack(">QQ", 925, 6)
    assert fmt.pack_header(925, 6) == header
    assert fmt.unpack_header(header, 963) == (925, 6)
    raw = vector["table_utf8"].encode()
    payload = base64.b64decode(vector["payload_base64"])
    frame = base64.b64decode(vector["frame_base64"])
    assert header + raw + payload == frame
    for name, data in (("table", raw), ("payload", payload), ("frame", frame)):
        assert len(data) == vector[name + "_size"]
        assert hashlib.sha256(data).hexdigest() == vector[name + "_sha256"]
    observed = table(vector)
    assert observed.to_json() == raw == canonical(observed.to_dict())
    assert observed.directories[1].children == ()
    assert observed.files[1].size == 0 and observed.files[1].offset == 6
    assert observed.payload_size == 6


def test_descriptor_is_detached_exact_false_capabilities_not_live_authority(vector):
    observed = descriptor(vector)
    raw = observed.to_json()
    assert fmt.parse_python_runtime_material_descriptor(raw) == observed
    assert fmt.parse_python_runtime_material_descriptor(raw.decode()) == observed
    assert observed.to_dict() == json.loads(raw)
    assert observed.frame_size == 963 and observed.table_size == 925
    assert observed.root_count == 1 and observed.directory_count == observed.file_count == 2
    assert all(observed.to_dict()[field] is False for field in fmt._CAPABILITIES)
    assert not {"fd", "owner", "material_bytes_immutable"}.intersection(observed.to_dict())
    with pytest.raises(FrozenInstanceError):
        observed.frame_size = 1
    detached = observed.to_dict()
    detached["target"]["platform"] = "darwin"
    assert observed.target.platform == "linux"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "missing",
        "schema",
        "protocol",
        "roots-order",
        "roots-duplicate",
        "roots-empty",
        "root-missing",
        "unknown-label",
        "parent-missing",
        "child-extra",
        "child-missing",
        "child-duplicate",
        "child-order",
        "dir-duplicate",
        "file-duplicate",
        "file-dir-alias",
        "files-order",
        "dirs-order",
        "gap",
        "overlap",
        "first-offset",
        "offset-overflow",
        "size-overflow",
        "size-bool",
        "offset-bool",
        "role",
        "sha",
        "target-extra",
        "target-version",
        "file-extra",
        "dir-extra",
        "version-empty",
        "version-unicode",
    ],
)
def test_table_graph_shapes_roles_and_contiguous_ranges_refuse(vector, mutation):
    body = json.loads(vector["table_utf8"])
    if mutation == "unknown":
        body["fd"] = 3
    elif mutation == "missing":
        del body["tree_sha256"]
    elif mutation == "schema":
        body["schema_version"] = 1
    elif mutation == "protocol":
        body["protocol"] = "unknown"
    elif mutation == "roots-order":
        body["roots"] = ["z", "app"]
    elif mutation == "roots-duplicate":
        body["roots"] *= 2
    elif mutation == "roots-empty":
        body["roots"] = []
    elif mutation == "root-missing":
        body["directories"] = body["directories"][1:]
    elif mutation == "unknown-label":
        body["files"][0]["root_label"] = "foreign"
    elif mutation == "parent-missing":
        body["files"][0]["relative_path"] = "missing/image.bin"
    elif mutation == "child-extra":
        body["directories"][0]["children"].append("z-extra")
    elif mutation == "child-missing":
        body["directories"][0]["children"].pop()
    elif mutation == "child-duplicate":
        body["directories"][0]["children"].append("zero.dat")
    elif mutation == "child-order":
        body["directories"][0]["children"].reverse()
    elif mutation == "dir-duplicate":
        body["directories"].append(body["directories"][1])
    elif mutation == "file-duplicate":
        body["files"].append(body["files"][1])
    elif mutation == "file-dir-alias":
        body["files"][0]["relative_path"] = "empty"
    elif mutation == "files-order":
        body["files"].reverse()
    elif mutation == "dirs-order":
        body["directories"].reverse()
    elif mutation == "gap":
        body["files"][1]["offset"] = 7
    elif mutation == "overlap":
        body["files"][1]["offset"] = 5
    elif mutation == "first-offset":
        body["files"][0]["offset"] = 1
    elif mutation == "offset-overflow":
        body["files"][1]["offset"] = 2**64
    elif mutation == "size-overflow":
        body["files"][0]["size"] = fmt.MAX_FILE_BYTES + 1
    elif mutation == "size-bool":
        body["files"][0]["size"] = True
    elif mutation == "offset-bool":
        body["files"][0]["offset"] = False
    elif mutation == "role":
        body["files"][0]["role"] = "new-authority"
    elif mutation == "sha":
        body["files"][0]["sha256"] = "A" * 64
    elif mutation == "target-extra":
        body["target"]["fd"] = 3
    elif mutation == "target-version":
        body["target"]["python_version"] = "3.99"
    elif mutation == "file-extra":
        body["files"][0]["fd"] = 3
    elif mutation == "dir-extra":
        body["directories"][0]["inode"] = 1
    elif mutation == "version-empty":
        body["material_version"] = ""
    elif mutation == "version-unicode":
        body["material_version"] = "版本"
    refused(lambda: fmt.parse_table(canonical(body)))


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "..",
        "../image.bin",
        "/image.bin",
        "a//b",
        "a/./b",
        "a/../b",
        "a/",
        "a\\b",
        "a\x00b",
        "a\nb",
        "a\rb",
        "é" * 4096,
        "/".join(["a"] * 65),
    ],
)
def test_unsafe_or_oversized_relative_paths_refuse(vector, path):
    body = json.loads(vector["table_utf8"])
    body["files"][0]["relative_path"] = path
    refused(lambda: fmt.parse_table(canonical(body)))


def test_non_ascii_paths_preserve_original_utf8_spelling(vector):
    body = json.loads(vector["table_utf8"])
    body["files"][0]["relative_path"] = "é.bin"
    body["files"].reverse()
    body["files"][0]["offset"] = 0
    body["files"][1]["offset"] = 0
    body["directories"][0]["children"] = ["empty", "zero.dat", "é.bin"]
    raw = canonical(body)
    assert fmt.parse_table(raw).to_json() == raw and b"\xc3\xa9" in raw
    refused(
        lambda: fmt.parse_table(
            json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        )
    )


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "whitespace",
        "trailing",
        "utf8",
        "bom",
        "nan",
        "deep",
        "surrogate",
        "wrong-type",
        "too-large",
        "unknown-target-long",
    ],
)
def test_json_bounds_and_canonical_encoding_refuse(vector, kind):
    raw = vector["table_utf8"].encode()
    if kind == "duplicate":
        raw = raw.replace(b'"roots":["app"]', b'"roots":["app"],"roots":["app"]')
    elif kind == "whitespace":
        raw = b" " + raw
    elif kind == "trailing":
        raw += b"\n"
    elif kind == "utf8":
        raw = b"\xff"
    elif kind == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif kind == "nan":
        raw = raw.replace(b'"size":6', b'"size":NaN')
    elif kind == "deep":
        raw = b"[" * 2000 + b"0" + b"]" * 2000
    elif kind == "surrogate":
        raw = raw.replace(b"image.bin", b"\\ud800")
    elif kind == "wrong-type":
        raw = raw.decode()
    elif kind == "too-large":
        raw = b"x" * (fmt.MAX_TABLE_BYTES + 1)
    elif kind == "unknown-target-long":
        raw = raw.replace(b'"platform":"linux"', b'"platform":"' + b"x" * 10000 + b'"')
    refused(lambda: fmt.parse_table(raw))


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "missing",
        "capability",
        "bool-count",
        "bool-size",
        "root-dir-count",
        "entry-count",
        "file-payload-bound",
        "frame-size",
        "table-bound",
        "payload-bound",
        "sha",
        "version",
        "binding",
        "target",
        "duplicate",
        "noncanonical",
        "byte-cap",
    ],
)
def test_descriptor_shape_consistency_and_detached_claims_refuse(vector, mutation):
    body = descriptor(vector).to_dict()
    if mutation == "unknown":
        body["material_bytes_immutable"] = True
    elif mutation == "missing":
        del body["frame_sha256"]
    elif mutation == "capability":
        body["runtime_load_protection"] = True
    elif mutation == "bool-count":
        body["root_count"] = True
    elif mutation == "bool-size":
        body["payload_size"] = False
    elif mutation == "root-dir-count":
        body["root_count"] = 3
    elif mutation == "entry-count":
        body["directory_count"] = 8192
    elif mutation == "file-payload-bound":
        body["file_count"] = 1
        body["payload_size"] = fmt.MAX_FILE_BYTES + 1
        body["frame_size"] = 32 + body["table_size"] + body["payload_size"]
    elif mutation == "frame-size":
        body["frame_size"] += 1
    elif mutation == "table-bound":
        body["table_size"] = fmt.MAX_TABLE_BYTES + 1
    elif mutation == "payload-bound":
        body["payload_size"] = fmt.MAX_PAYLOAD_BYTES + 1
    elif mutation == "sha":
        body["frame_sha256"] = "A" * 64
    elif mutation == "version":
        body["material_version"] = ""
    elif mutation == "binding":
        body["binding"] = "ordinary-file"
    elif mutation == "target":
        body["target"]["abi_tag"] = "cp311"
    raw = canonical(body)
    if mutation == "duplicate":
        raw = raw.replace(b'"root_count":1', b'"root_count":1,"root_count":1')
    elif mutation == "noncanonical":
        raw += b"\n"
    elif mutation == "byte-cap":
        raw = b"x" * (fmt.MAX_DESCRIPTOR_BYTES + 1)
    refused(lambda: fmt.parse_python_runtime_material_descriptor(raw))


@pytest.mark.parametrize(
    "mutation",
    [
        "magic",
        "version",
        "padding",
        "short",
        "long",
        "table-zero",
        "table-max",
        "payload-max",
        "size-short",
        "size-tail",
        "bool",
        "foreign-type",
    ],
)
def test_exact_header_bounds_without_table_allocation(vector, mutation):
    header, size = bytes.fromhex(vector["header_hex"]), vector["frame_size"]
    if mutation == "magic":
        header = b"X" + header[1:]
    elif mutation == "version":
        header = header[:15] + b"\x02" + header[16:]
    elif mutation == "padding":
        header = header[:10] + b"X" + header[11:]
    elif mutation == "short":
        header = header[:-1]
    elif mutation == "long":
        header += b"x"
    elif mutation == "table-zero":
        header = struct.pack(">16sQQ", fmt.MAGIC, 0, 6)
    elif mutation == "table-max":
        header = struct.pack(">16sQQ", fmt.MAGIC, fmt.MAX_TABLE_BYTES + 1, 6)
    elif mutation == "payload-max":
        header = struct.pack(">16sQQ", fmt.MAGIC, 925, 2**64 - 1)
    elif mutation == "size-short":
        size -= 1
    elif mutation == "size-tail":
        size += 1
    elif mutation == "bool":
        size = True
    elif mutation == "foreign-type":
        header = memoryview(header)
    refused(lambda: fmt.unpack_header(header, size))


class Forbidden:
    def __len__(self):
        raise AssertionError("caller length callback")

    def __iter__(self):
        raise AssertionError("caller iteration callback")

    def __getitem__(self, key):
        raise AssertionError("caller indexing callback")

    def __hash__(self):
        raise AssertionError("caller hash callback")

    def __str__(self):
        raise AssertionError("caller text callback")


class ForbiddenText(str):
    def __len__(self):
        raise AssertionError("caller string length callback")

    def __hash__(self):
        raise AssertionError("caller string hash callback")

    def encode(self, *args, **kwargs):
        raise AssertionError("caller string encoding callback")


@pytest.mark.parametrize(
    "field",
    [
        "roots",
        "directories",
        "files",
        "children",
        "file-path",
        "role",
        "offset",
        "sha",
        "target",
        "target-text",
        "version",
        "descriptor-size",
        "descriptor-target",
    ],
)
def test_forced_frozen_mutations_refuse_before_callbacks_or_encoding(vector, monkeypatch, field):
    observed = table(vector)
    evidence = descriptor(vector)
    callback = observed.to_json
    if field in {"roots", "directories", "files"}:
        object.__setattr__(observed, field, Forbidden())
    elif field == "children":
        object.__setattr__(observed.directories[0], "children", Forbidden())
    elif field == "file-path":
        object.__setattr__(observed.files[0], "relative_path", ForbiddenText("image.bin"))
    elif field == "role":
        object.__setattr__(observed.files[0], "role", ForbiddenText("interpreter"))
    elif field == "offset":
        object.__setattr__(observed.files[0], "offset", Forbidden())
    elif field == "sha":
        object.__setattr__(observed.files[0], "sha256", ForbiddenText("a" * 64))
    elif field == "target":
        object.__setattr__(observed, "target", Forbidden())
    elif field == "target-text":
        object.__setattr__(observed.target, "platform", ForbiddenText("linux"))
    elif field == "version":
        object.__setattr__(observed, "material_version", ForbiddenText("fixture-v1"))
    elif field == "descriptor-size":
        object.__setattr__(evidence, "frame_size", Forbidden())
        callback = evidence.to_json
    elif field == "descriptor-target":
        object.__setattr__(evidence.target, "platform", ForbiddenText("linux"))
        callback = evidence.to_json

    def forbidden(*args, **kwargs):
        pytest.fail("serialization before exact DTO validation")

    monkeypatch.setattr(fmt, "_canonical", forbidden)
    refused(callback)


@pytest.mark.parametrize(
    "bound",
    [
        "MAX_ROOTS",
        "MAX_FILES",
        "MAX_ENTRIES",
        "MAX_MEMBERSHIP_EDGES",
        "MAX_DEPTH",
        "MAX_FILE_BYTES",
        "MAX_PAYLOAD_BYTES",
        "MAX_TABLE_BYTES",
        "MAX_PATH_BYTES",
        "MAX_LABEL_LENGTH",
    ],
)
def test_retained_independent_bounds_checked_without_payload(vector, monkeypatch, bound):
    raw = vector["table_utf8"].encode()
    monkeypatch.setattr(fmt, bound, 0)
    refused(lambda: fmt.parse_table(raw))


@pytest.mark.parametrize("bound", ["roots", "files", "directories", "combined", "aggregate-edges"])
def test_count_limits_precede_member_callbacks_and_digest_or_encoding_work(
    vector, monkeypatch, bound
):
    value = table(vector)
    if bound == "roots":
        monkeypatch.setattr(fmt, "MAX_ROOTS", 0)
        object.__setattr__(value, "roots", (ForbiddenText("app"),))
    elif bound == "files":
        monkeypatch.setattr(fmt, "MAX_FILES", 1)
        object.__setattr__(value, "files", (Forbidden(), Forbidden()))
    elif bound == "directories":
        monkeypatch.setattr(fmt, "MAX_ENTRIES", 1)
        object.__setattr__(value, "directories", (Forbidden(), Forbidden()))
    elif bound == "combined":
        monkeypatch.setattr(fmt, "MAX_ENTRIES", 3)
        object.__setattr__(value.directories[0], "root_label", ForbiddenText("app"))
    else:
        monkeypatch.setattr(fmt, "MAX_MEMBERSHIP_EDGES", 3)
        object.__setattr__(value.directories[1], "children", (Forbidden(),))

    def forbidden(*args, **kwargs):
        pytest.fail("count bounds were checked after digest validation or encoding")

    monkeypatch.setattr(fmt, "_sha", forbidden)
    monkeypatch.setattr(fmt, "_canonical", forbidden)
    code = refused(value.to_json)
    suffix = (
        "entries_exceeded" if bound in {"combined", "aggregate-edges"} else "collection_invalid"
    )
    assert code == "python_runtime_material_" + suffix


@pytest.mark.parametrize(
    "position,value",
    [
        (0, False),
        (0, 0),
        (0, -1),
        (0, fmt.MAX_TABLE_BYTES + 1),
        (1, True),
        (1, -1),
        (1, fmt.MAX_PAYLOAD_BYTES + 1),
    ],
)
def test_header_builder_refuses_exact_integer_and_length_defects(position, value):
    sizes = [925, 6]
    sizes[position] = value
    refused(lambda: fmt.pack_header(*sizes))


def test_header_and_detached_metadata_can_represent_maximum_lengths_without_payload(vector):
    header = fmt.pack_header(fmt.MAX_TABLE_BYTES, fmt.MAX_PAYLOAD_BYTES)
    assert fmt.unpack_header(header, fmt.MAX_FRAME_BYTES) == (
        fmt.MAX_TABLE_BYTES,
        fmt.MAX_PAYLOAD_BYTES,
    )
    evidence = replace(
        descriptor(vector),
        table_size=fmt.MAX_TABLE_BYTES,
        payload_size=fmt.MAX_PAYLOAD_BYTES,
        frame_size=fmt.MAX_FRAME_BYTES,
        root_count=16,
        file_count=4096,
        directory_count=4096,
    )
    assert fmt.parse_python_runtime_material_descriptor(evidence.to_json()) == evidence


def test_source_conversion_is_pure_and_targets_do_not_share_mutable_dto_authority(
    tmp_path, monkeypatch
):
    from test_producer_python_runtime_tree import fixture

    source = fixture(tmp_path).closed

    def forbidden(*args, **kwargs):
        pytest.fail("pure conversion/parser performed filesystem IO")

    for name in ("open", "stat", "fstat", "scandir", "read", "write"):
        monkeypatch.setattr(os, name, forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    observed = fmt.table_from_tree(source, "original-v1")
    raw = observed.to_json()
    assert fmt.parse_table(raw) == observed
    assert observed.declared_manifest_sha256 == source.declared_manifest.manifest_sha256
    assert observed.tree_sha256 == source.tree_sha256
    assert (
        observed.target == source.declared_manifest.target
        and observed.target is not source.declared_manifest.target
    )
    offset = 0
    for actual, original in zip(observed.files, source.declared_manifest.files, strict=True):
        assert (
            actual.root_label,
            actual.relative_path,
            actual.role,
            actual.size,
            actual.sha256,
        ) == (
            original.root_label,
            original.relative_path,
            original.role,
            original.size,
            original.sha256,
        )
        assert actual.offset == offset
        offset += original.size
    assert observed.payload_size == offset
    object.__setattr__(source.declared_manifest.target, "platform", "darwin")
    assert observed.target.platform == "linux"


def test_descriptor_factory_requires_independent_canonical_table_pin(vector):
    value = table(vector)
    for size, digest in (
        (vector["table_size"] + 1, vector["table_sha256"]),
        (vector["table_size"], "f" * 64),
    ):
        refused(
            lambda size=size, digest=digest: fmt.descriptor_from_table(
                value, size, digest, vector["payload_sha256"], vector["frame_sha256"]
            )
        )
    observed = descriptor(vector)
    other = replace(observed, target=replace(observed.target, platform="darwin"))
    assert other.target.platform == "darwin"
    assert fmt.parse_python_runtime_material_descriptor(other.to_json()).target.platform == "darwin"
    # Detached digest spelling can be valid without any corresponding live frame.
    asserted = replace(observed, frame_sha256="f" * 64)
    assert fmt.parse_python_runtime_material_descriptor(asserted.to_json()) == asserted
