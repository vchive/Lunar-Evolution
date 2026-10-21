"""Source-only readiness receipt tests; no archive/build/runtime side effects."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.static_python_fixture import source_readiness
from tools.static_python_rsi_fixture.recipe import emit_rsi_launch_source_plan


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _toolchain() -> bytes:
    payload = {
        "schema": source_readiness.TOOLCHAIN_INVENTORY_SCHEMA,
        "profile": "zig-0.16.0-linux-x86_64-musl", "archive": "zig",
        "url": "https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz",
        "root": "zig-x86_64-linux-0.16.0", "version": "0.16.0",
        "archive_size": 55478392,
        "archive_sha256": "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00",
        "target": "x86_64-linux-musl", "llvm_version": "21.1.0",
        "libc": "Zig bundled musl 1.2.5 with backports and Zig replacements",
        "evidence_status": "unverified",
        "files": [{
            "path": "zig-x86_64-linux-0.16.0/bin/zig", "kind": "file", "size": 1,
            "mode": 0o755, "sha256": hashlib.sha256(b"z").hexdigest(),
        }],
        "claims": {
            "archive_bytes_verified": False, "file_bytes_verified": False,
            "signature_verified": False, "build_authorized": False,
            "production_admission": False,
        },
    }
    return _canonical(payload)


def _source_plan(tmp_path: Path) -> tuple[bytes, dict[str, bytes]]:
    path = emit_rsi_launch_source_plan(tmp_path / "source-plan")
    return path.read_bytes(), {
        item.name: (path.parent / "assets" / item.name).read_bytes()
        for item in (path.parent / "assets").iterdir()
    }


def test_source_plan_and_expanded_main_are_bound_to_all_six_assets(tmp_path: Path) -> None:
    plan, assets = _source_plan(tmp_path)
    result = source_readiness._source_plan(plan, assets, hashlib.sha256(plan).hexdigest())
    assert {item["path"] for item in result[1]} == {
        "assets/launcher.c", "assets/pipe.c", "assets/profile.c", "assets/getpath.c",
        "assets/lunar_fixture_profile.h", "assets/frozen_main.py",
    }
    expanded = result[2]
    assert expanded["size"] == len(assets["frozen_main.py"])
    assert expanded["sha256"] == hashlib.sha256(assets["frozen_main.py"]).hexdigest()


def test_source_plan_asset_drift_refuses_before_any_receipt_claim(tmp_path: Path) -> None:
    plan, assets = _source_plan(tmp_path)
    assets["frozen_main.py"] += b"drift"
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError) as caught:
        source_readiness._source_plan(plan, assets, hashlib.sha256(plan).hexdigest())
    assert caught.value.reason == "static_python_source_readiness_source_asset_digest_mismatch"


def test_toolchain_inventory_requires_unverified_explicit_file_manifest() -> None:
    raw = _toolchain()
    value = source_readiness._toolchain_inventory(raw, hashlib.sha256(raw).hexdigest())
    assert value["evidence_status"] == "unverified"
    assert value["files"][0]["kind"] == "file"
    altered = json.loads(raw)
    altered["files"][0]["path"] = "zig-x86_64-linux-0.16.0/../bin/zig"
    altered_raw = _canonical(altered)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError) as caught:
        source_readiness._toolchain_inventory(altered_raw, hashlib.sha256(altered_raw).hexdigest())
    assert caught.value.reason == "static_python_source_readiness_toolchain_inventory_path_invalid"

    altered = json.loads(raw)
    altered["files"][0]["path"] = altered["root"]
    altered_raw = _canonical(altered)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError) as caught:
        source_readiness._toolchain_inventory(altered_raw, hashlib.sha256(altered_raw).hexdigest())
    assert caught.value.reason == "static_python_source_readiness_toolchain_inventory_file_invalid"

    altered = json.loads(raw)
    altered["files"] = [
        {**altered["files"][0], "path": "zig-x86_64-linux-0.16.0/bin"},
        {**altered["files"][0], "path": "zig-x86_64-linux-0.16.0/bin/zig"},
    ]
    altered_raw = _canonical(altered)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError) as caught:
        source_readiness._toolchain_inventory(altered_raw, hashlib.sha256(altered_raw).hexdigest())
    assert caught.value.reason == "static_python_source_readiness_toolchain_inventory_file_invalid"


def test_persisted_receipt_rejects_missing_fields_and_true_claims() -> None:
    toolchain = _toolchain()
    assets = [{"path": "assets/" + name, "size": 1, "sha256": "a" * 64}
              for name in sorted(source_readiness._ASSET_NAMES)]
    receipt = {
        "schema": source_readiness.SOURCE_READINESS_SCHEMA, "status": "source-only",
        "archive_receipt_sha256": "a" * 64, "archive": "cpython", "root": "Python-3.13.12",
        "version": "3.13.12", "archive_size": 22926488,
        "archive_sha256": "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593",
        "snapshot_sha256": "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593",
        "manifest_sha256": "c" * 64, "source_tree_sha256": "d" * 64,
        "staging_sha256": "e" * 64, "patch_set_sha256": "1" * 64,
        "policy_sha256": "2" * 64, "projection_sha256": "3" * 64,
        "declared_signature_verification": "verified",
        "observed_signature_verification": "not-performed",
        "source_plan_sha256": "4" * 64, "source_assets": assets,
        "expanded_frozen_main": next(item for item in assets if item["path"] == "assets/frozen_main.py"),
        "toolchain_inventory_sha256": hashlib.sha256(toolchain).hexdigest(),
        "toolchain": json.loads(toolchain),
        "claims": dict.fromkeys(source_readiness._RECEIPT_CLAIMS, False),
    }
    raw = _canonical(receipt)
    result = source_readiness.validate_static_python_source_readiness_receipt(
        raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
    )
    assert result.to_dict()["status"] == "source-only"
    missing = dict(receipt)
    del missing["source_tree_sha256"]
    missing_raw = _canonical(missing)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError, match="receipt_schema_invalid"):
        source_readiness.validate_static_python_source_readiness_receipt(
            missing_raw, expected_sha256=hashlib.sha256(missing_raw).hexdigest(),
        )
    forged = json.loads(raw)
    forged["source_assets"][0]["path"] = forged["source_assets"][0]["path"].removeprefix("assets/")
    forged_raw = _canonical(forged)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError, match="receipt_asset_path_invalid"):
        source_readiness.validate_static_python_source_readiness_receipt(
            forged_raw, expected_sha256=hashlib.sha256(forged_raw).hexdigest(),
        )
    forged = json.loads(raw)
    forged["claims"]["production_admission"] = True
    forged_raw = _canonical(forged)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError, match="receipt_claim_invalid"):
        source_readiness.validate_static_python_source_readiness_receipt(
            forged_raw, expected_sha256=hashlib.sha256(forged_raw).hexdigest(),
        )
    forged = json.loads(raw)
    forged["expanded_frozen_main"] = {**forged["expanded_frozen_main"], "size": 2}
    forged_raw = _canonical(forged)
    with pytest.raises(source_readiness.StaticPythonSourceReadinessError,
                       match="receipt_expanded_main_mismatch"):
        source_readiness.validate_static_python_source_readiness_receipt(
            forged_raw, expected_sha256=hashlib.sha256(forged_raw).hexdigest(),
        )
