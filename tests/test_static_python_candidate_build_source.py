"""Candidate source receipt stays detached and source-only."""

from __future__ import annotations

import hashlib
import json

import pytest

from tools.static_python_fixture import candidate_build_source, source_patches


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _staging(patch_digest: str, archive_digest: str) -> bytes:
    entry = {
        "path": "Python-3.13.12/Parser/parser.c", "kind": "file", "implicit": False,
        "source_sha256": "a" * 64, "staged_sha256": "b" * 64, "archive_mode": 0o644,
        "device": 1, "inode": 2, "mode": 0o600, "nlink": 1, "size": 1,
        "mtime_ns": 1, "ctime_ns": 1,
    }
    value = {
        "schema": "lunar-static-python-source-staging-v1", "destination": "/tmp/staged",
        "root": "Python-3.13.12", "root_directory": "/tmp/staged/Python-3.13.12",
        "archive": "cpython", "archive_sha256": archive_digest, "snapshot_sha256": archive_digest,
        "manifest_sha256": "c" * 64, "projection_sha256": "d" * 64,
        "policy_sha256": "e" * 64, "patch_set_sha256": patch_digest,
        "profile_pin_verified": True, "metadata_validation": "validated",
        "source_preimages_checked": True, "signature_verification": "not-performed",
        "tree_identity": {}, "ancestor_identities": [], "entries": [entry],
        "extraction_performed": True, "fixed_patches_staged": True, "release_verified": False,
        "source_execution_performed": False, "build_performed": False,
        "frozen_headers_generated": False, "runtime_execution_performed": False,
        "runtime_load_protection": False, "production_admission": False,
        "general_code_origin_protection": False,
    }
    return _canonical(value)


def _profile(archive_digest: str, tree_digest: str, patch_digest: str, policy: dict) -> bytes:
    return _canonical({
        "schema": candidate_build_source.SOURCE_PROFILE_SCHEMA, "profile": "rsi-marker-launch-v1",
        "source_version": policy["source_version"], "source_commit": policy["source_commit"],
        "source_archive_sha256": archive_digest, "source_tree_sha256": tree_digest,
        "patch_set_sha256": patch_digest, "claims": dict.fromkeys(candidate_build_source._CLAIMS, False),
    })


def _inputs() -> tuple[bytes, str, bytes, str, bytes, str, str]:
    policy = source_patches.source_patch_manifest()
    files = _canonical(policy["files"])
    patch_digest = hashlib.sha256(files).hexdigest()
    assert patch_digest == policy["patch_set_sha256"]
    archive_digest = "1" * 64
    staging = _staging(patch_digest, archive_digest)
    tree_projection = [{name: staging_value[name] for name in ("path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode", "size")} for staging_value in json.loads(staging)["entries"]]
    tree_digest = hashlib.sha256(_canonical(tree_projection)).hexdigest()
    profile = _profile(archive_digest, "2" * 64, patch_digest, policy)
    return staging, hashlib.sha256(staging).hexdigest(), files if False else _canonical(policy), patch_digest, profile, hashlib.sha256(profile).hexdigest(), tree_digest


def test_receipt_binds_staged_tree_patch_and_profile() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin = _inputs()
    receipt = candidate_build_source.build_candidate_build_source_receipt(
        staging, expected_staging_manifest_sha256=staging_pin, expected_staged_tree_sha256=tree_pin,
        patch_set=policy, expected_patch_set_sha256=patch_pin, source_profile=profile,
        expected_source_profile_sha256=profile_pin, expected_source_tree_sha256="2" * 64,
    )
    assert receipt.to_dict()["status"] == "source-only"
    assert all(value is False for value in receipt.to_dict()["claims"].values())
    parsed = candidate_build_source.validate_candidate_build_source_receipt(
        receipt.to_json(), expected_sha256=receipt.receipt_sha256,
    )
    assert parsed.receipt_sha256 == receipt.receipt_sha256


def test_staging_tree_drift_refuses_before_receipt() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin = _inputs()
    altered = json.loads(staging)
    altered["entries"][0]["staged_sha256"] = "f" * 64
    altered_raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="staging_pin_mismatch"):
        candidate_build_source.build_candidate_build_source_receipt(
            altered_raw, expected_staging_manifest_sha256=staging_pin, expected_staged_tree_sha256=tree_pin,
            patch_set=policy, expected_patch_set_sha256=patch_pin, source_profile=profile,
            expected_source_profile_sha256=profile_pin, expected_source_tree_sha256="2" * 64,
        )


def test_receipt_claim_or_patch_profile_drift_refuses() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin = _inputs()
    receipt = candidate_build_source.build_candidate_build_source_receipt(
        staging, expected_staging_manifest_sha256=staging_pin, expected_staged_tree_sha256=tree_pin,
        patch_set=policy, expected_patch_set_sha256=patch_pin, source_profile=profile,
        expected_source_profile_sha256=profile_pin, expected_source_tree_sha256="2" * 64,
    )
    altered = receipt.to_dict()
    altered["claims"]["build_performed"] = True
    raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="receipt_claim_invalid"):
        candidate_build_source.validate_candidate_build_source_receipt(raw, expected_sha256=hashlib.sha256(raw).hexdigest())

    altered = receipt.to_dict()
    altered["patch_set"]["source_commit"] = "different-source"
    raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="receipt_patch_profile_mismatch"):
        candidate_build_source.validate_candidate_build_source_receipt(
            raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
        )
