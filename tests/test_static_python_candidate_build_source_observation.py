"""Read-only staged-source observation against an actual disposable tree."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path

import pytest
import test_static_python_source_staging as staging_fixtures

from tools.static_python_fixture import candidate_build_source_observation as observation
from tools.static_python_fixture import source_patches
from tools.static_python_fixture.source_tree_observation import SOURCE_TREE_SCHEMA


@pytest.fixture
def sources():
    fixture = staging_fixtures.FIXTURE
    return {path: (fixture / (path + ".source")).read_bytes()
            for path in source_patches.SOURCE_PATHS}


@pytest.fixture
def tmp_path(tmp_path):
    # The staging contract rejects symlinked ancestors (notably macOS /var).
    return tmp_path.resolve()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _with_entry_update(inputs, path: str, **updates):
    manifest = json.loads(inputs["staging_raw"])
    entry = next(item for item in manifest["entries"] if item["path"] == path)
    entry.update(updates)
    raw = _canonical(manifest)
    return {
        **inputs,
        "staging_raw": raw,
        "staging_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _source_tree_pin(entries: list[tuple[object, bytes | None]]) -> str:
    files = []
    for member, raw in entries:
        if member.isdir():
            continue
        assert member.isfile() and raw is not None
        files.append({
            "path": member.name,
            "mode": member.mode & 0o777,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    tree = {
        "schema": SOURCE_TREE_SCHEMA,
        "archive": "cpython",
        "root": staging_fixtures.ROOT,
        "version": staging_fixtures.ROOT.removeprefix("Python-"),
        "files": sorted(files, key=lambda item: item["path"]),
    }
    return hashlib.sha256(_canonical(tree)).hexdigest()


@pytest.fixture
def staged_inputs(sources, tmp_path):
    entries = staging_fixtures._entries(sources)
    bundle = staging_fixtures._bundle(entries)
    staged = staging_fixtures._stage(bundle, tmp_path / "stage")
    policy = source_patches.source_patch_manifest()
    policy_raw = _canonical(policy)
    return {
        "destination": tmp_path / "stage",
        "staging_raw": staged.canonical_json,
        "staging_sha256": staged.staging_sha256,
        "policy_raw": policy_raw,
        "patch_set_sha256": policy["patch_set_sha256"],
        "source_tree_sha256": _source_tree_pin(entries),
    }


def _observe(inputs, *, monotonic=time.monotonic, deadline=None):
    return observation.observe_staged_candidate_source_tree(
        inputs["staging_raw"],
        expected_staging_manifest_sha256=inputs["staging_sha256"],
        patch_policy=inputs["policy_raw"],
        expected_patch_set_sha256=inputs["patch_set_sha256"],
        expected_source_tree_sha256=inputs["source_tree_sha256"],
        deadline=time.monotonic() + 30.0 if deadline is None else deadline,
        monotonic=monotonic,
    )


def _refused(call):
    with pytest.raises(ValueError) as caught:
        call()
    reason = getattr(caught.value, "reason", str(caught.value))
    assert type(reason) is str and reason
    assert str(caught.value) == reason
    assert "stage" not in reason and "/" not in reason
    return reason


def _tree_snapshot(root: Path) -> dict[str, tuple[tuple[int, ...], bytes | None]]:
    result = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in sorted(directories + files):
            path = current_path / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            identity = (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                        info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            result[relative] = (identity, path.read_bytes() if path.is_file() and not path.is_symlink() else None)
    return result


def test_observation_reads_staged_tree_without_mutation(staged_inputs):
    root = staged_inputs["destination"] / staging_fixtures.ROOT
    before = _tree_snapshot(staged_inputs["destination"])
    result = _observe(staged_inputs)
    after = _tree_snapshot(staged_inputs["destination"])

    assert before == after
    assert result.source_tree_sha256 == staged_inputs["source_tree_sha256"]
    assert result.staging_manifest_sha256 == staged_inputs["staging_sha256"]
    assert result.patch_set_sha256 == staged_inputs["patch_set_sha256"]
    record = result.to_dict()
    assert record["status"] == "staged-source-observed"
    assert record["source_tree_sha256"] == staged_inputs["source_tree_sha256"]
    assert record["staging_manifest_sha256"] == staged_inputs["staging_sha256"]
    assert record["patch_set_sha256"] == staged_inputs["patch_set_sha256"]
    assert record["claims"]["production_admission"] is False
    assert record["claims"]["build_performed"] is False
    assert result.observation_sha256 == hashlib.sha256(result.canonical_json).hexdigest()
    assert (root / "Lib/abc.py").is_file()


def test_observation_accepts_space_and_utf8_paths(sources, tmp_path):
    entries = staging_fixtures._entries(sources) + [
        staging_fixtures._file(
            f"{staging_fixtures.ROOT}/Mac/Icons/Disk Image.icns", b"fixture-space-name",
        ),
        staging_fixtures._file(
            f"{staging_fixtures.ROOT}/Mac/Icons/图标.icns", b"fixture-utf8-name",
        ),
    ]
    bundle = staging_fixtures._bundle(entries)
    staged = staging_fixtures._stage(bundle, tmp_path / "stage")
    policy = source_patches.source_patch_manifest()
    inputs = {
        "destination": tmp_path / "stage",
        "staging_raw": staged.canonical_json,
        "staging_sha256": staged.staging_sha256,
        "policy_raw": _canonical(policy),
        "patch_set_sha256": policy["patch_set_sha256"],
        "source_tree_sha256": _source_tree_pin(entries),
    }

    result = _observe(inputs)

    assert result.file_count == len(sources) + 4
    root = inputs["destination"] / staging_fixtures.ROOT
    assert (root / "Mac/Icons/Disk Image.icns").read_bytes() == b"fixture-space-name"
    assert (root / "Mac/Icons/图标.icns").read_bytes() == b"fixture-utf8-name"


@pytest.mark.parametrize("drift", ["content", "mode"])
def test_observation_refuses_changed_staged_file(staged_inputs, drift):
    target = staged_inputs["destination"] / staging_fixtures.ROOT / "Lib/abc.py"
    if drift == "content":
        target.write_bytes(target.read_bytes() + b"# late drift\n")
    else:
        target.chmod(0o644)
    reason = _refused(lambda: _observe(staged_inputs))
    assert any(part in reason for part in ("drift", "identity", "stat", "changed"))


def test_observation_refuses_unmanifested_extra_file(staged_inputs):
    extra = staged_inputs["destination"] / staging_fixtures.ROOT / "unmanifested-extra"
    extra.write_bytes(b"unexpected")
    reason = _refused(lambda: _observe(staged_inputs))
    assert any(part in reason for part in ("extra", "inventory", "entry", "drift"))


def test_observation_refuses_extra_destination_sibling(staged_inputs):
    sibling = staged_inputs["destination"] / "unmanifested-sibling"
    sibling.mkdir()
    manifest = json.loads(staged_inputs["staging_raw"])
    info = staged_inputs["destination"].stat(follow_symlinks=False)
    manifest["tree_identity"] = {
        "device": info.st_dev, "inode": info.st_ino, "raw_mode": info.st_mode,
        "nlink": info.st_nlink, "size": info.st_size,
        "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }
    staging_raw = _canonical(manifest)
    updated_inputs = {
        **staged_inputs,
        "staging_raw": staging_raw,
        "staging_sha256": hashlib.sha256(staging_raw).hexdigest(),
    }
    reason = _refused(lambda: _observe(updated_inputs))
    assert "inventory" in reason


def test_observation_rechecks_empty_directory_after_late_entry(staged_inputs, monkeypatch):
    target = staged_inputs["destination"] / staging_fixtures.ROOT / "explicit-empty"
    expected_identity = target.stat(follow_symlinks=False)
    original = observation._list_children
    injected = False

    def inject_after_scan(fd, expected, *, deadline, monotonic, reason):
        nonlocal injected
        result = original(
            fd, expected, deadline=deadline, monotonic=monotonic, reason=reason,
        )
        current = os.fstat(fd)
        if (not injected and reason == "directory_changed_after_read"
                and stat.S_ISDIR(current.st_mode)
                and (current.st_dev, current.st_ino)
                == (expected_identity.st_dev, expected_identity.st_ino)):
            unexpected = os.open(
                "late-extra", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                dir_fd=fd,
            )
            os.close(unexpected)
            injected = True
        return result

    monkeypatch.setattr(observation, "_list_children", inject_after_scan)
    reason = _refused(lambda: _observe(staged_inputs))
    assert injected
    assert any(part in reason for part in ("directory_changed", "directory_identity", "inventory")), reason


def test_observation_rechecks_directory_stat_after_last_inventory_scan(staged_inputs, monkeypatch):
    target = staged_inputs["destination"] / staging_fixtures.ROOT / "explicit-empty"
    expected_identity = target.stat(follow_symlinks=False)
    original = observation._list_children
    injected = False

    def inject_after_final_scan(fd, expected, *, deadline, monotonic, reason):
        nonlocal injected
        result = original(
            fd, expected, deadline=deadline, monotonic=monotonic, reason=reason,
        )
        current = os.fstat(fd)
        if (not injected and reason == "directory_changed_after_read"
                and stat.S_ISDIR(current.st_mode)
                and (current.st_dev, current.st_ino)
                == (expected_identity.st_dev, expected_identity.st_ino)):
            unexpected = os.open(
                "late-extra", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                dir_fd=fd,
            )
            os.close(unexpected)
            injected = True
        return result

    monkeypatch.setattr(observation, "_list_children", inject_after_final_scan)
    reason = _refused(lambda: _observe(staged_inputs))
    assert injected
    assert "directory_changed_after_read" in reason


def test_observation_refuses_missing_staged_file(staged_inputs):
    target = staged_inputs["destination"] / staging_fixtures.ROOT / "Lib/abc.py"
    target.unlink()
    reason = _refused(lambda: _observe(staged_inputs))
    assert any(part in reason for part in ("missing", "inventory", "entry", "drift"))


def test_observation_refuses_patched_postimage_not_bound_to_fixed_patch(staged_inputs):
    """A self-consistent staging DTO cannot substitute an arbitrary postimage."""
    target = staged_inputs["destination"] / staging_fixtures.ROOT / "Lib/abc.py"
    target.write_bytes(target.read_bytes() + b"# arbitrary postimage\n")
    info = target.stat(follow_symlinks=False)
    manifest = json.loads(staged_inputs["staging_raw"])
    entry = next(item for item in manifest["entries"] if item["path"] == f"{staging_fixtures.ROOT}/Lib/abc.py")
    entry.update({
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "staged_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    })
    staging_raw = _canonical(manifest)
    forged_inputs = {
        **staged_inputs,
        "staging_raw": staging_raw,
        "staging_sha256": hashlib.sha256(staging_raw).hexdigest(),
    }
    reason = _refused(lambda: _observe(forged_inputs))
    assert "patch_image" in reason


@pytest.mark.parametrize("mutation", ["source_preimage", "staged_postimage", "postimage_size", "unpatched_source"])
def test_observation_binds_manifest_entries_to_fixed_patch_vector(staged_inputs, mutation):
    patch_path = source_patches.source_patch_manifest()["files"][0]["path"]
    fake_digest = hashlib.sha256(b"fixed patch binding regression").hexdigest()
    if mutation == "source_preimage":
        path = f"{staging_fixtures.ROOT}/{patch_path}"
        forged = _with_entry_update(staged_inputs, path, source_sha256=fake_digest)
    elif mutation == "staged_postimage":
        path = f"{staging_fixtures.ROOT}/{patch_path}"
        forged = _with_entry_update(staged_inputs, path, staged_sha256=fake_digest)
    elif mutation == "postimage_size":
        path = f"{staging_fixtures.ROOT}/{patch_path}"
        manifest = json.loads(staged_inputs["staging_raw"])
        entry = next(item for item in manifest["entries"] if item["path"] == path)
        forged = _with_entry_update(staged_inputs, path, size=entry["size"] + 1)
    else:
        path = f"{staging_fixtures.ROOT}/extra/unchanged.bin"
        forged = _with_entry_update(staged_inputs, path, source_sha256=fake_digest)

    reason = _refused(lambda: _observe(forged))
    assert any(part in reason for part in ("patch_image", "unpatched_file")), reason


def test_observation_refuses_symlink_instead_of_following_it(staged_inputs, tmp_path):
    root = staged_inputs["destination"] / staging_fixtures.ROOT
    target = root / "Lib/abc.py"
    retained = tmp_path / "retained-abc.py"
    target.rename(retained)
    target.symlink_to(retained)
    reason = _refused(lambda: _observe(staged_inputs))
    assert any(part in reason for part in ("symlink", "file", "type", "drift", "identity"))
    assert retained.is_file()


def test_observation_uses_one_original_deadline(staged_inputs):
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return 0.5 if calls == 1 else 1.0

    reason = _refused(lambda: _observe(staged_inputs, monotonic=clock, deadline=1.0))
    assert "deadline" in reason or "timeout" in reason
    assert calls >= 2
