"""Inert metadata fixtures: no archive acquisition, extraction or signature work."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from tools.static_python_fixture import verified_inputs as contract
from tools.static_python_fixture.source_patches import source_patch_manifest

_PROFILES = {
    "cpython": {
        "url": "https://www.python.org/ftp/python/3.13.12/Python-3.13.12.tar.xz",
        "size": 22926488,
        "sha256": "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593",
        "root": "Python-3.13.12", "version": "3.13.12",
        "identity": {"commit": "1cbe481834751b0125e006042ffbd8cd5eaec8a8", "tag": "v3.13.12"},
    },
    "zig": {
        "url": "https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz",
        "size": 55478392,
        "sha256": "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00",
        "root": "zig-x86_64-linux-0.16.0", "version": "0.16.0",
        "identity": {
            "target": "x86_64-linux-musl", "llvm_version": "21.1.0",
            "libc": "Zig bundled musl 1.2.5 with backports and Zig replacements",
        },
    },
}
_TEST_FILE_SHA = hashlib.sha256(b"inert test file\n").hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _receipt(archive="cpython", signature="not-performed"):
    return {
        "schema": "lunar-static-python-archive-receipt-v1", "archive": archive,
        **copy.deepcopy(_PROFILES[archive]), "signature_verification": signature,
    }


def _validate_receipt(value):
    raw = _canonical(value)
    return contract.validate_static_python_archive_receipt(raw, expected_sha256=_digest(raw))


def _directory(path, mode=0o755):
    return {"path": path, "kind": "directory", "size": 0, "mode": mode, "sha256": None}


def _file(path, size=16, mode=0o644, sha256=_TEST_FILE_SHA):
    return {"path": path, "kind": "file", "size": size, "mode": mode, "sha256": sha256}


def _manifest(archive="cpython"):
    profile = _PROFILES[archive]
    root = profile["root"]
    return {
        "schema": "lunar-static-python-extraction-manifest-v1", "archive": archive,
        "root": root, "archive_sha256": profile["sha256"],
        "members": [_file(root + "/file.txt"), _directory(root)],
    }


def _manifest_pin(value):
    detached = copy.deepcopy(value)
    detached["members"] = sorted(detached["members"], key=lambda member: member["path"])
    return _digest(_canonical(detached))


def _validate_manifest(value, *, require_source_preimages=False):
    return contract.validate_static_python_extraction_manifest(
        value, expected_sha256=_manifest_pin(value),
        require_source_preimages=require_source_preimages,
    )


def _refusal(reason):
    return pytest.raises(contract.StaticPythonVerifiedInputError,
                         match="^static_python_verified_input_" + reason + "$")


@pytest.mark.parametrize("archive", ["cpython", "zig"])
@pytest.mark.parametrize("signature", ["verified", "not-performed", "unavailable", "failed"])
def test_receipt_fixed_pins_canonical_digest_and_honest_signature_declaration(archive, signature):
    value = _receipt(archive, signature)
    original = copy.deepcopy(value)
    receipt = _validate_receipt(value)
    assert receipt.archive == archive
    assert receipt.signature_verification == signature
    assert receipt.canonical_json == _canonical(original)
    assert receipt.receipt_sha256 == _digest(receipt.canonical_json)
    assert receipt.identity == tuple(sorted(original["identity"].items()))
    assert receipt.version == _PROFILES[archive]["version"]
    assert not hasattr(receipt, "production_admission")
    value["identity"].clear()
    assert receipt.canonical_json == _canonical(original)
    with pytest.raises(FrozenInstanceError):
        receipt.signature_verification = "verified"


@pytest.mark.parametrize("value", [None, "{}", b"", bytearray(b"{}"), memoryview(b"{}")])
def test_receipt_requires_nonempty_exact_bounded_bytes(value):
    reason = "receipt_budget_exceeded" if value == b"" else "receipt_bytes_invalid"
    with _refusal(reason):
        contract.validate_static_python_archive_receipt(value, expected_sha256="1" * 64)


def test_receipt_raw_budget_precedes_json_parsing():
    with _refusal("receipt_budget_exceeded"):
        contract.validate_static_python_archive_receipt(
            b"x" * (contract.MAX_ARCHIVE_RECEIPT_BYTES + 1), expected_sha256="1" * 64,
        )


@pytest.mark.parametrize("raw", [
    b"[]", b"true", b"null", b"{}", b'{"schema":NaN}', b'{"schema":Infinity}',
    b"\xff", b"[" * 1100 + b"]" * 1100,
])
def test_receipt_malformed_shape_encoding_depth_and_nonfinite_fail_closed(raw):
    with pytest.raises(contract.StaticPythonVerifiedInputError):
        contract.validate_static_python_archive_receipt(raw, expected_sha256="1" * 64)


@pytest.mark.parametrize("nested", [False, True])
def test_receipt_rejects_duplicate_keys_even_if_values_are_equal(nested):
    raw = _canonical(_receipt())
    if nested:
        raw = raw.replace(b'"tag":"v3.13.12"', b'"tag":"v3.13.12","tag":"v3.13.12"')
    else:
        raw = raw.replace(b'"archive":"cpython"', b'"archive":"cpython","archive":"cpython"')
    with _refusal("duplicate_json_key"):
        contract.validate_static_python_archive_receipt(raw, expected_sha256=_digest(raw))


@pytest.mark.parametrize("style", ["newline", "whitespace", "order", "escaped"])
def test_receipt_rejects_noncanonical_json(style):
    value = _receipt()
    raw = _canonical(value)
    if style == "newline":
        raw += b"\n"
    elif style == "whitespace":
        raw = b" " + raw
    elif style == "order":
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    else:
        raw = raw.replace(b"cpython", b"cpyth\\u006fn")
    with _refusal("receipt_noncanonical_json"):
        contract.validate_static_python_archive_receipt(raw, expected_sha256=_digest(raw))


@pytest.mark.parametrize("field,value,reason", [
    ("schema", "other", "receipt_schema_invalid"),
    ("archive", "host-python", "archive_invalid"),
    ("archive", False, "archive_invalid"),
    ("url", "https://example.invalid/Python-3.13.12.tar.xz", "archive_pin_drift"),
    ("root", "Python-3.13.12/", "archive_pin_drift"),
    ("version", "3.13.11", "archive_pin_drift"),
    ("size", True, "archive_pin_drift"),
    ("size", 22926489, "archive_pin_drift"),
    ("sha256", "0" * 64, "archive_pin_drift"),
    ("sha256", "F" * 64, "archive_pin_drift"),
    ("identity", [], "archive_identity_drift"),
    ("identity", {"commit": "a" * 40, "tag": "v3.13.12"}, "archive_identity_drift"),
    ("identity", {"commit": "1cbe481834751b0125e006042ffbd8cd5eaec8a8"},
     "archive_identity_drift"),
    ("signature_verification", "VERIFIED", "signature_status_invalid"),
    ("signature_verification", True, "signature_status_invalid"),
    ("signature_verification", "\ud800", "signature_status_invalid"),
])
def test_receipt_pin_identity_and_signature_drift(field, value, reason):
    receipt = _receipt()
    receipt[field] = value
    # JSON can carry a surrogate through its escaped representation; canonical
    # UTF-8 metadata must still refuse it without leaking a codec exception.
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
           if field == "signature_verification" and value == "\ud800" else _canonical(receipt))
    with _refusal(reason):
        contract.validate_static_python_archive_receipt(raw, expected_sha256=_digest(raw))


@pytest.mark.parametrize("field", ["extra", "missing"])
def test_receipt_exact_field_set(field):
    receipt = _receipt()
    if field == "extra":
        receipt["production_admission"] = True
    else:
        del receipt["signature_verification"]
    with _refusal("receipt_shape_invalid"):
        _validate_receipt(receipt)


@pytest.mark.parametrize("expected", [None, False, 1, "", "0" * 64, "f" * 64, "F" * 64, "1" * 63])
def test_receipt_expected_pin_is_exact_nonplaceholder_lowercase_sha(expected):
    with _refusal("expected_digest_invalid"):
        contract.validate_static_python_archive_receipt(
            _canonical(_receipt()), expected_sha256=expected,
        )


def test_receipt_valid_claims_still_require_matching_external_metadata_pin():
    raw = _canonical(_receipt(signature="verified"))
    with _refusal("receipt_digest_drift"):
        contract.validate_static_python_archive_receipt(raw, expected_sha256="1" * 64)
    with pytest.raises(TypeError):
        contract.validate_static_python_archive_receipt(raw)


def test_changing_valid_signature_declaration_still_refuses_the_original_external_receipt_pin():
    value = _receipt(signature="not-performed")
    original_pin = _digest(_canonical(value))
    value["signature_verification"] = "verified"
    changed = _canonical(value)
    assert _digest(changed) != original_pin
    with _refusal("receipt_digest_drift"):
        contract.validate_static_python_archive_receipt(changed, expected_sha256=original_pin)


@pytest.mark.parametrize("archive", ["cpython", "zig"])
def test_manifest_sorted_canonical_detached_and_immutable(archive):
    value = _manifest(archive)
    original = copy.deepcopy(value)
    expected = _manifest_pin(value)
    result = contract.validate_static_python_extraction_manifest(value, expected_sha256=expected)
    assert value == original
    assert tuple(member.path for member in result.members) == tuple(sorted(
        member["path"] for member in original["members"]
    ))
    assert result.total_bytes == 16
    assert result.source_preimages_checked is False
    assert result.manifest_sha256 == expected == _digest(result.canonical_json)
    assert not hasattr(result, "production_admission")
    value["members"][0]["path"] = "changed"
    value["members"].clear()
    assert result.members[1].path == _PROFILES[archive]["root"] + "/file.txt"
    with pytest.raises(FrozenInstanceError):
        result.members[1].mode = 0o777
    with pytest.raises(FrozenInstanceError):
        result.members = ()


def test_manifest_order_does_not_change_external_canonical_pin():
    value = _manifest()
    first = _validate_manifest(value)
    value["members"].reverse()
    second = contract.validate_static_python_extraction_manifest(
        value, expected_sha256=first.manifest_sha256,
    )
    assert first == second


@pytest.mark.parametrize("expected", [None, False, 1, "", "0" * 64, "f" * 64, "F" * 64, "1" * 63])
def test_manifest_expected_pin_is_exact_nonplaceholder_lowercase_sha(expected):
    with _refusal("expected_digest_invalid"):
        contract.validate_static_python_extraction_manifest(_manifest(), expected_sha256=expected)


def test_manifest_valid_claims_still_require_matching_external_metadata_pin():
    with _refusal("manifest_digest_drift"):
        contract.validate_static_python_extraction_manifest(_manifest(), expected_sha256="1" * 64)
    with pytest.raises(TypeError):
        contract.validate_static_python_extraction_manifest(_manifest())


@pytest.mark.parametrize("field,changed", [("size", 17), ("mode", 0o755)])
def test_changing_valid_member_metadata_still_refuses_original_external_manifest_pin(field, changed):
    value = _manifest()
    original_pin = _manifest_pin(value)
    value["members"][0][field] = changed
    assert _manifest_pin(value) != original_pin
    with _refusal("manifest_digest_drift"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256=original_pin)


class _HostileDict(dict):
    def __len__(self):
        raise AssertionError("caller callback executed")

    def __iter__(self):
        raise AssertionError("caller callback executed")


class _HostileList(list):
    def __len__(self):
        raise AssertionError("caller callback executed")

    def __iter__(self):
        raise AssertionError("caller callback executed")


class _HostileText(str):
    def __hash__(self):
        raise AssertionError("caller callback executed")

    def __eq__(self, other):
        raise AssertionError("caller callback executed")


@pytest.mark.parametrize("surface", ["top", "members", "member", "path", "kind", "key"])
def test_manifest_callback_bearing_inputs_refuse_before_callbacks(surface):
    value = _manifest()
    if surface == "top":
        value = _HostileDict(value)
    elif surface == "members":
        value["members"] = _HostileList(value["members"])
    elif surface == "member":
        value["members"][0] = _HostileDict(value["members"][0])
    elif surface == "key":
        # Build the dictionary while hashing is allowed, then replace the key's
        # class behavior to prove validation does not hash or compare it again.
        class Key:
            pass
        key = Key()
        value.pop("root")
        value[key] = "Python-3.13.12"
        Key.__hash__ = lambda self: (_ for _ in ()).throw(AssertionError("key hash callback"))
        Key.__eq__ = lambda self, other: (_ for _ in ()).throw(AssertionError("key eq callback"))
    else:
        value["members"][0][surface] = _HostileText(value["members"][0][surface])
    with pytest.raises(contract.StaticPythonVerifiedInputError):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


@pytest.mark.parametrize("surface", ["schema", "root", "archive", "hash", "vector", "member"])
def test_manifest_shape_and_fixed_profile_drift(surface):
    value = _manifest()
    if surface == "schema":
        value["schema"] = "unknown"
    elif surface == "root":
        value["root"] = "Python-3.13.11"
    elif surface == "archive":
        value["archive"] = "host-python"
    elif surface == "hash":
        value["archive_sha256"] = "2" * 64
    elif surface == "vector":
        value["members"] = tuple(value["members"])
    else:
        value["members"][0]["link_target"] = "arbitrary"
    with pytest.raises(contract.StaticPythonVerifiedInputError):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


@pytest.mark.parametrize("path", [
    "/Python-3.13.12/file", "../file", "Python-3.13.12/../file",
    "Python-3.13.12/./file", "Python-3.13.12//file", "Python-3.13.12/file/",
    "Python-3.13.12\\file", "Python-3.13.12/C:stream", "other-root/file",
    "Python-3.13.12/\x00file", "Python-3.13.12/\nfile", "Python-3.13.12/\x7ffile",
    "Python-3.13.12/\x80file", "Python-3.13.12/\x9ffile", "Python-3.13.12/\ud800",
])
def test_manifest_traversal_ambiguous_and_control_member_paths_refuse(path):
    value = _manifest()
    value["members"][0]["path"] = path
    with _refusal("member_path_invalid"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


@pytest.mark.parametrize("field,bad,reason", [
    ("kind", "symlink", "member_kind_invalid"),
    ("kind", "hardlink", "member_kind_invalid"),
    ("kind", "fifo", "member_kind_invalid"),
    ("kind", "device", "member_kind_invalid"),
    ("kind", "sparse", "member_kind_invalid"),
    ("kind", True, "member_kind_invalid"),
    pytest.param("kind", "x" * (1024 * 1024), "member_kind_invalid", id="kind-too-long"),
    ("size", True, "member_size_invalid"),
    ("size", -1, "member_size_invalid"),
    ("size", 1.0, "member_size_invalid"),
    ("size", contract.MAX_EXTRACTION_MEMBER_BYTES + 1, "member_size_invalid"),
    ("mode", True, "member_mode_invalid"),
    ("mode", 0o100644, "member_mode_invalid"),
    ("mode", 0o4644, "member_mode_invalid"),
    ("mode", -1, "member_mode_invalid"),
    ("sha256", None, "member_digest_invalid"),
    ("sha256", "0" * 64, "member_digest_invalid"),
    ("sha256", "F" * 64, "member_digest_invalid"),
    ("sha256", "1" * 63, "member_digest_invalid"),
])
def test_regular_file_type_permissions_size_and_digest_contract(field, bad, reason):
    value = _manifest()
    value["members"][0][field] = bad
    with _refusal(reason):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


@pytest.mark.parametrize("field,bad", [("size", 1), ("sha256", _TEST_FILE_SHA)])
def test_directory_has_zero_size_and_null_digest(field, bad):
    value = _manifest()
    value["members"][1][field] = bad
    with _refusal("directory_metadata_invalid"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


@pytest.mark.parametrize("mode", [0, 0o644, 0o755, 0o777])
def test_permission_bits_are_metadata_only_with_no_special_or_type_bits(mode):
    value = _manifest()
    value["members"][0]["mode"] = mode
    assert _validate_manifest(value).members[1].mode == mode


@pytest.mark.parametrize("directory_collision", [False, True])
def test_duplicate_path_rejects_both_repeated_files_and_file_directory_collisions(directory_collision):
    value = _manifest()
    path = value["members"][0]["path"]
    value["members"].append(_directory(path) if directory_collision else _file(path))
    with _refusal("member_duplicate_path"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


@pytest.mark.parametrize("reverse", [False, True])
def test_file_ancestor_collisions_reject_in_either_input_order(reverse):
    value = _manifest()
    root = value["root"]
    # The intervening dash sibling catches an incorrect adjacent-sorted-only
    # detector, because it sorts between root/a and root/a/child.
    value["members"] = [_directory(root), _file(root + "/a"),
                        _file(root + "/a-sibling"), _file(root + "/a/child")]
    if reverse:
        value["members"].reverse()
    with _refusal("file_directory_collision"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


def test_directory_ancestors_and_similar_prefixes_are_valid():
    value = _manifest()
    root = value["root"]
    value["members"] = [_directory(root), _directory(root + "/a"),
                        _file(root + "/a/child"), _file(root + "/ab/implicit-parent")]
    assert _validate_manifest(value).total_bytes == 32


@pytest.mark.parametrize("style", ["missing", "file"])
def test_pinned_root_must_be_present_as_directory(style):
    value = _manifest()
    if style == "missing":
        value["members"].pop()
    else:
        value["members"][1] = _file(value["root"])
    with _refusal("root_directory_missing"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


def test_member_total_byte_limit_accepts_exact_boundary_and_refuses_one_more():
    value = _manifest()
    root = value["root"]
    value["members"] = [_directory(root)] + [
        _file(root + "/member" + str(index), size=contract.MAX_EXTRACTION_MEMBER_BYTES)
        for index in range(4)
    ]
    assert _validate_manifest(value).total_bytes == contract.MAX_EXTRACTION_TOTAL_BYTES
    value["members"].append(_file(root + "/tail", size=1))
    with _refusal("total_byte_budget_exceeded"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


def test_member_count_and_empty_inventory_refuse_before_member_callbacks():
    value = _manifest()
    for vector in ([], [object()] * (contract.MAX_EXTRACTION_MEMBERS + 1)):
        value["members"] = vector
        with _refusal("member_budget_exceeded"):
            contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


def test_path_utf8_byte_bound_and_segment_bound():
    value = _manifest()
    root = value["root"]
    path = root + "/" + "x" * (contract.MAX_EXTRACTION_PATH_BYTES - len(root) - 1)
    value["members"][0]["path"] = path
    assert _validate_manifest(value).members[1].path == path
    value["members"][0]["path"] += "x"
    with _refusal("member_path_invalid"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)
    # Character count alone is insufficient for non-ASCII UTF-8 paths.
    value["members"][0]["path"] = root + "/" + "界" * 400
    with _refusal("member_path_invalid"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)
    path = root + "/x" * (contract.MAX_EXTRACTION_PATH_SEGMENTS - 1)
    value["members"][0]["path"] = path
    assert _validate_manifest(value).members[1].path == path
    value["members"][0]["path"] += "/x"
    with _refusal("member_path_invalid"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


def test_aggregate_path_and_canonical_limits_apply_after_safe_shape_checks(monkeypatch):
    value = _manifest()
    path_bytes = sum(len(member["path"].encode("utf-8")) for member in value["members"])
    monkeypatch.setattr(contract, "MAX_EXTRACTION_TOTAL_PATH_BYTES", path_bytes)
    result = _validate_manifest(value)
    value["members"][0]["path"] += "x"
    with _refusal("total_path_budget_exceeded"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)
    value = _manifest()
    monkeypatch.setattr(contract, "MAX_EXTRACTION_MANIFEST_BYTES", len(result.canonical_json) - 1)
    with _refusal("canonical_budget_exceeded"):
        contract.validate_static_python_extraction_manifest(value, expected_sha256="1" * 64)


def _source_manifest():
    value = _manifest()
    root = value["root"]
    value["members"] = [_directory(root)] + [
        _file(root + "/" + source["path"], size=source["before_size"],
              sha256=source["before_sha256"])
        for source in source_patch_manifest()["files"]
    ]
    return value


def test_optional_preimage_gate_matches_reviewed_three_metadata_claims_only():
    value = _source_manifest()
    unchecked = _validate_manifest(value)
    checked = _validate_manifest(value, require_source_preimages=True)
    assert unchecked.source_preimages_checked is False
    assert checked.source_preimages_checked is True
    assert checked.manifest_sha256 == unchecked.manifest_sha256
    assert checked.canonical_json == unchecked.canonical_json
    assert checked.total_bytes == 235702


@pytest.mark.parametrize("drift", ["missing", "digest", "size", "directory"])
def test_preimage_missing_or_drift_refuses_even_with_matching_external_manifest_pin(drift):
    value = _source_manifest()
    if drift == "missing":
        value["members"].pop()
    elif drift == "digest":
        value["members"][1]["sha256"] = "1" * 64
    elif drift == "size":
        value["members"][1]["size"] += 1
    else:
        value["members"][1] = _directory(value["members"][1]["path"])
    with _refusal("source_preimage_drift"):
        _validate_manifest(value, require_source_preimages=True)


def test_preimage_gate_refuses_zig_and_nonbool_flag():
    with _refusal("source_preimages_archive_invalid"):
        _validate_manifest(_manifest("zig"), require_source_preimages=True)
    with _refusal("source_preimages_flag_invalid"):
        contract.validate_static_python_extraction_manifest(
            _source_manifest(), expected_sha256="1" * 64, require_source_preimages=1,
        )


def test_malformed_children_refuse_before_external_digest_format_is_considered():
    receipt = _receipt()
    receipt["size"] = True
    with _refusal("archive_pin_drift"):
        contract.validate_static_python_archive_receipt(_canonical(receipt), expected_sha256=None)
    manifest = _manifest()
    manifest["members"][0]["mode"] = True
    with _refusal("member_mode_invalid"):
        contract.validate_static_python_extraction_manifest(manifest, expected_sha256=None)


@pytest.mark.parametrize("surface", ["receipt", "manifest"])
def test_invalid_external_digest_shape_refuses_before_canonical_serialization(monkeypatch, surface):
    raw = _canonical(_receipt())

    def poisoned(*args, **kwargs):
        raise AssertionError("invalid expected pin reached canonical serialization")

    monkeypatch.setattr(contract, "_canonical", poisoned)
    with _refusal("expected_digest_invalid"):
        if surface == "receipt":
            contract.validate_static_python_archive_receipt(raw, expected_sha256="f" * 64)
        else:
            contract.validate_static_python_extraction_manifest(_manifest(), expected_sha256="f" * 64)


def test_valid_receipts_and_preimage_metadata_do_not_perform_io(monkeypatch):
    import builtins
    import os
    import socket
    import subprocess
    import tarfile
    import urllib.request
    from pathlib import Path

    receipt = _receipt()
    manifest = _source_manifest()

    def forbidden(*args, **kwargs):
        raise AssertionError("pure metadata validator attempted external IO")

    for owner, name in (
        (builtins, "open"), (os, "open"), (Path, "open"),
        (socket, "socket"), (subprocess, "run"), (subprocess, "Popen"),
        (tarfile, "open"), (urllib.request, "urlopen"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    assert _validate_receipt(receipt).archive == "cpython"
    assert _validate_manifest(manifest, require_source_preimages=True).source_preimages_checked is True
