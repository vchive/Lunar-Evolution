"""Candidate source receipt stays detached and source-only."""

from __future__ import annotations

import hashlib
import json

import pytest

from tools.static_python_fixture import candidate_build_source, source_patches


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _staging(policy: dict, archive_digest: str) -> tuple[bytes, str]:
    root = "Python-" + policy["source_version"]
    entries = []
    directories = set()
    source_files = []
    for patch in policy["files"]:
        path = root + "/" + patch["path"]
        parent = path.rpartition("/")[0]
        while parent != root:
            directories.add(parent)
            parent = parent.rpartition("/")[0]
        entries.append({
            "path": path, "kind": "file", "implicit": False,
            "source_sha256": patch["before_sha256"], "staged_sha256": patch["after_sha256"],
            "archive_mode": 0o644, "device": 1, "inode": len(entries) + 2,
            "mode": 0o600, "nlink": 1, "size": patch["after_size"],
            "mtime_ns": 1, "ctime_ns": 1,
        })
        source_files.append({
            "path": path, "mode": 0o644, "size": patch["before_size"],
            "sha256": patch["before_sha256"],
        })
    unchanged = b"parser"
    unchanged_path = root + "/Parser/parser.c"
    directories.add(root + "/Parser")
    unchanged_sha = hashlib.sha256(unchanged).hexdigest()
    entries.append({
        "path": unchanged_path, "kind": "file", "implicit": False,
        "source_sha256": unchanged_sha, "staged_sha256": unchanged_sha,
        "archive_mode": 0o644, "device": 1, "inode": len(entries) + 2,
        "mode": 0o600, "nlink": 1, "size": len(unchanged),
        "mtime_ns": 1, "ctime_ns": 1,
    })
    source_files.append({
        "path": unchanged_path, "mode": 0o644, "size": len(unchanged),
        "sha256": unchanged_sha,
    })
    for index, path in enumerate(sorted(directories), start=100):
        entries.append({
            "path": path, "kind": "directory", "implicit": True,
            "source_sha256": None, "staged_sha256": None, "archive_mode": None,
            "device": 1, "inode": index, "mode": 0o700, "nlink": 1, "size": 0,
            "mtime_ns": 1, "ctime_ns": 1,
        })
    entries.append({
        "path": root, "kind": "directory", "implicit": False,
        "source_sha256": None, "staged_sha256": None, "archive_mode": 0o755,
        "device": 1, "inode": 99, "mode": 0o700, "nlink": 2, "size": 1,
        "mtime_ns": 1, "ctime_ns": 1,
    })
    entries.sort(key=lambda item: item["path"])
    source_tree = {
        "schema": "lunar-static-python-source-tree-v1", "archive": "cpython",
        "root": root, "version": policy["source_version"],
        "files": sorted(source_files, key=lambda item: item["path"]),
    }
    source_tree_digest = hashlib.sha256(_canonical(source_tree)).hexdigest()
    value = {
        "schema": "lunar-static-python-source-staging-v1", "destination": "/tmp/staged",
        "root": root, "root_directory": "/tmp/staged/" + root,
        "archive": "cpython", "archive_sha256": archive_digest, "snapshot_sha256": archive_digest,
        "manifest_sha256": "c" * 64, "projection_sha256": "d" * 64,
        "policy_sha256": hashlib.sha256(_canonical(policy)).hexdigest(),
        "patch_set_sha256": policy["patch_set_sha256"],
        "profile_pin_verified": True, "metadata_validation": "validated",
        "source_preimages_checked": True, "signature_verification": "not-performed",
        "tree_identity": {"device": 1, "inode": 1, "raw_mode": 0o40700,
                          "nlink": 2, "size": 1, "mtime_ns": 1, "ctime_ns": 1},
        "ancestor_identities": [{"device": 1, "inode": 1}, {"device": 1, "inode": 2}],
        "entries": entries,
        "extraction_performed": True, "fixed_patches_staged": True, "release_verified": False,
        "source_execution_performed": False, "build_performed": False,
        "frozen_headers_generated": False, "runtime_execution_performed": False,
        "runtime_load_protection": False, "production_admission": False,
        "general_code_origin_protection": False,
    }
    return _canonical(value), source_tree_digest


def _profile(archive_digest: str, tree_digest: str, patch_digest: str, policy: dict) -> bytes:
    return _canonical({
        "schema": candidate_build_source.SOURCE_PROFILE_SCHEMA, "profile": "rsi-marker-launch-v1",
        "source_version": policy["source_version"], "source_commit": policy["source_commit"],
        "source_archive_sha256": archive_digest, "source_tree_sha256": tree_digest,
        "patch_set_sha256": patch_digest, "claims": dict.fromkeys(candidate_build_source._CLAIMS, False),
    })


def _inputs() -> tuple[bytes, str, bytes, str, bytes, str, str, str]:
    policy = source_patches.source_patch_manifest()
    files = _canonical(policy["files"])
    patch_digest = hashlib.sha256(files).hexdigest()
    assert patch_digest == policy["patch_set_sha256"]
    archive_digest = "1" * 64
    staging, source_tree_digest = _staging(policy, archive_digest)
    tree_projection = [{name: staging_value[name] for name in ("path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode", "size")} for staging_value in json.loads(staging)["entries"]]
    tree_digest = hashlib.sha256(_canonical(tree_projection)).hexdigest()
    profile = _profile(archive_digest, source_tree_digest, patch_digest, policy)
    return staging, hashlib.sha256(staging).hexdigest(), _canonical(policy), patch_digest, profile, hashlib.sha256(profile).hexdigest(), tree_digest, source_tree_digest


def _staged_tree_pin(staging: dict) -> str:
    projection = [{name: entry[name] for name in (
        "path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode", "size",
    )} for entry in staging["entries"]]
    return hashlib.sha256(_canonical(projection)).hexdigest()


def _build(staging: bytes, staging_pin: str, policy: bytes, patch_pin: str,
           profile: bytes, profile_pin: str, tree_pin: str, source_tree_pin: str):
    return candidate_build_source.build_candidate_build_source_receipt(
        staging, expected_staging_manifest_sha256=staging_pin,
        expected_staged_tree_sha256=tree_pin, patch_set=policy,
        expected_patch_set_sha256=patch_pin, source_profile=profile,
        expected_source_profile_sha256=profile_pin,
        expected_source_tree_sha256=source_tree_pin,
    )


def test_receipt_binds_staged_tree_patch_and_profile() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin, source_tree_pin = _inputs()
    receipt = candidate_build_source.build_candidate_build_source_receipt(
        staging, expected_staging_manifest_sha256=staging_pin, expected_staged_tree_sha256=tree_pin,
        patch_set=policy, expected_patch_set_sha256=patch_pin, source_profile=profile,
        expected_source_profile_sha256=profile_pin, expected_source_tree_sha256=source_tree_pin,
    )
    assert receipt.to_dict()["status"] == "source-only"
    assert all(value is False for value in receipt.to_dict()["claims"].values())
    parsed = candidate_build_source.validate_candidate_build_source_receipt(
        receipt.to_json(), expected_sha256=receipt.receipt_sha256,
    )
    assert parsed.receipt_sha256 == receipt.receipt_sha256


def test_staging_tree_drift_refuses_before_receipt() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin, source_tree_pin = _inputs()
    altered = json.loads(staging)
    altered["entries"][0]["staged_sha256"] = "f" * 64
    altered_raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="staging_pin_mismatch"):
        candidate_build_source.build_candidate_build_source_receipt(
            altered_raw, expected_staging_manifest_sha256=staging_pin, expected_staged_tree_sha256=tree_pin,
            patch_set=policy, expected_patch_set_sha256=patch_pin, source_profile=profile,
            expected_source_profile_sha256=profile_pin, expected_source_tree_sha256=source_tree_pin,
        )


def test_receipt_requires_every_fixed_patch_target_in_staged_tree() -> None:
    staging, _, policy, patch_pin, profile, profile_pin, _, source_tree_pin = _inputs()
    altered = json.loads(staging)
    target = "Python-3.13.12/Lib/abc.py"
    altered["entries"] = [entry for entry in altered["entries"] if entry["path"] != target]
    raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="staging_patch_inventory_mismatch"):
        _build(raw, hashlib.sha256(raw).hexdigest(), policy, patch_pin, profile,
               profile_pin, _staged_tree_pin(altered), source_tree_pin)


@pytest.mark.parametrize(("field", "changed"), [
    ("source_sha256", "9" * 64),
    ("staged_sha256", "9" * 64),
    ("size", 1),
])
def test_receipt_requires_patch_preimage_and_postimage_identity(field: str, changed: object) -> None:
    staging, _, policy, patch_pin, profile, profile_pin, _, source_tree_pin = _inputs()
    altered = json.loads(staging)
    target = next(entry for entry in altered["entries"]
                  if entry["path"].endswith("/Lib/abc.py"))
    target[field] = changed
    raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="staging_patch_image_mismatch"):
        _build(raw, hashlib.sha256(raw).hexdigest(), policy, patch_pin, profile,
               profile_pin, _staged_tree_pin(altered), source_tree_pin)


def test_receipt_requires_installation_owned_patch_policy() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin, source_tree_pin = _inputs()
    altered = json.loads(policy)
    altered["provenance"] = "caller-controlled"
    raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="patch_set_not_fixed"):
        _build(staging, staging_pin, raw, patch_pin, profile, profile_pin,
               tree_pin, source_tree_pin)


def test_receipt_claim_or_patch_profile_drift_refuses() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin, source_tree_pin = _inputs()
    receipt = candidate_build_source.build_candidate_build_source_receipt(
        staging, expected_staging_manifest_sha256=staging_pin, expected_staged_tree_sha256=tree_pin,
        patch_set=policy, expected_patch_set_sha256=patch_pin, source_profile=profile,
        expected_source_profile_sha256=profile_pin, expected_source_tree_sha256=source_tree_pin,
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


def test_retained_receipt_rejects_malformed_patch_file_vector() -> None:
    staging, staging_pin, policy, patch_pin, profile, profile_pin, tree_pin, source_tree_pin = _inputs()
    receipt = _build(staging, staging_pin, policy, patch_pin, profile, profile_pin,
                     tree_pin, source_tree_pin)
    altered = receipt.to_dict()
    malformed_files = ["not-a-patch-file"]
    malformed_patch_pin = hashlib.sha256(_canonical(malformed_files)).hexdigest()
    altered["patch_set"]["files"] = malformed_files
    altered["patch_set_sha256"] = malformed_patch_pin
    altered["source_profile"]["patch_set_sha256"] = malformed_patch_pin
    profile_raw = _canonical(altered["source_profile"])
    altered["source_profile_sha256"] = hashlib.sha256(profile_raw).hexdigest()
    raw = _canonical(altered)
    with pytest.raises(candidate_build_source.CandidateBuildSourceError, match="patch_set_file_invalid"):
        candidate_build_source.validate_candidate_build_source_receipt(
            raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
        )
