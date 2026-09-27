"""Provider-free fresh campaign admission against an actual local Git origin."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from test_acceptance_registration import _checkout, _git

from lunar_evolution import AcceptanceRegistrationError, acceptance_launch
from lunar_evolution.acceptance_launch import prepare_acceptance_campaign


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _registered_origin(tmp_path: Path) -> tuple[Path, Path, dict, Path, Path, Path]:
    checkout, parent, manifest, registration_path, seal_path = _checkout(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True, capture_output=True)
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/main")
    return checkout, parent, manifest, registration_path, seal_path, origin


def _prepare(fixture: tuple[Path, Path, dict, Path, Path, Path]) -> dict:
    checkout, parent, _, registration_path, seal_path, _ = fixture
    return prepare_acceptance_campaign(
        registration_path, seal_path, checkout_root=checkout, campaign_parent=parent,
    )


def _snapshots(checkout: Path, manifest: dict, registration_path: Path, seal_path: Path) -> dict[str, bytes]:
    snapshots = {
        "registration.json": registration_path.read_bytes(),
        "registration-seal.json": seal_path.read_bytes(),
    }
    for source, target in (
        ("task_material", "task"), ("input_material", "input"),
        ("evaluator_material", "evaluator-criteria"), ("evaluator_profile_material", "profile-criteria"),
    ):
        snapshots[f"materials/{target}.bin"] = (checkout / manifest[source]["path"]).read_bytes()
    for pin in manifest["holdout_pins"]:
        for kind in ("input", "expected"):
            snapshots[f"materials/holdout-{pin['ordinal']:02d}-{kind}.bin"] = (checkout / pin[kind]["path"]).read_bytes()
    return snapshots


def test_admission_retains_exact_pins_and_private_directory(tmp_path: Path) -> None:
    fixture = _registered_origin(tmp_path)
    checkout, parent, manifest, registration_path, seal_path, _ = fixture
    checkout_names = sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*"))
    receipt = _prepare(fixture)
    root = parent / manifest["campaign_root"]
    assert receipt["status"] == "prepared"
    assert receipt["provider_started"] is False
    for key in ("registration_id", "campaign_id", "attempt_id", "product_commit", "campaign_root", "registration_sha256"):
        assert receipt[key] == manifest[key]
    seal = json.loads(seal_path.read_bytes())
    assert receipt["seal_sha256"] == seal["seal_sha256"]
    assert receipt["head_commit"] == receipt["remote_commit"] == _git(checkout, "rev-parse", "HEAD")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert (receipt["root_device"], receipt["root_inode"]) == (root.stat().st_dev, root.stat().st_ino)
    assert (receipt["parent_device"], receipt["parent_inode"]) == (parent.stat().st_dev, parent.stat().st_ino)
    retained = _snapshots(checkout, manifest, registration_path, seal_path)
    for name, content in retained.items():
        assert (root / name).read_bytes() == content
    preflight_bytes = (root / "preflight.json").read_bytes()
    preflight = json.loads(preflight_bytes)
    assert preflight["status"] == "ready"
    assert preflight["head_commit"] == receipt["head_commit"]
    assert preflight["registration_sha256"] == manifest["registration_sha256"]
    assert preflight_bytes == _canonical(preflight)
    remote_bytes = (root / "remote-main.json").read_bytes()
    remote = json.loads(remote_bytes)
    assert receipt["remote_commit"] in remote.values()
    assert remote_bytes == _canonical(remote)
    retained.update({"preflight.json": preflight_bytes, "remote-main.json": remote_bytes})
    expected_files = [
        {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in sorted(retained.items())
    ]
    assert receipt["files"] == expected_files
    assert json.loads((root / "admission.json").read_bytes()) == receipt
    assert (root / "admission.json").read_bytes() == _canonical(receipt)
    assert receipt["admission_sha256"] == hashlib.sha256(_canonical({
        key: value for key, value in receipt.items() if key != "admission_sha256"
    })).hexdigest()
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()) == sorted([*retained, "admission.json"])
    assert stat.S_IMODE((root / "materials").stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in root.rglob("*") if path.is_file())
    assert checkout_names == sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*"))
    assert _git(checkout, "status", "--porcelain", "--untracked-files=all") == ""


def test_admission_rejects_forged_local_tracking_ref_before_reservation(tmp_path: Path) -> None:
    fixture = _registered_origin(tmp_path)
    checkout, parent, manifest, _, _, origin = fixture
    assert _git(origin, "rev-parse", "refs/heads/main") == _git(checkout, "rev-parse", "HEAD")
    (checkout / "unrelated.txt").write_bytes(b"new commit not sent to origin\n")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "unpublished")
    _git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _git(checkout, "rev-parse", "origin/main") == _git(checkout, "rev-parse", "HEAD")
    with pytest.raises(AcceptanceRegistrationError, match="^remote_main_mismatch$"):
        _prepare(fixture)
    assert not os.path.lexists(parent / manifest["campaign_root"])


def test_admission_remote_unavailable_does_not_reserve_root_or_expose_origin(tmp_path: Path) -> None:
    fixture = _registered_origin(tmp_path)
    checkout, parent, manifest, _, _, _ = fixture
    private_origin = tmp_path / "private-token-origin-not-present.git"
    _git(checkout, "remote", "set-url", "origin", str(private_origin))
    with pytest.raises(AcceptanceRegistrationError, match="^remote_main_unavailable$") as caught:
        _prepare(fixture)
    assert "private-token" not in str(caught.value)
    assert not os.path.lexists(parent / manifest["campaign_root"])


def test_admission_missing_remote_main_ref_is_unavailable(tmp_path: Path) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, origin = fixture
    _git(origin, "update-ref", "-d", "refs/heads/main")
    with pytest.raises(AcceptanceRegistrationError, match="^remote_main_unavailable$"):
        _prepare(fixture)
    assert not os.path.lexists(parent / manifest["campaign_root"])


@pytest.mark.parametrize("existing", ["directory", "file", "symlink"])
def test_admission_never_reuses_existing_root(tmp_path: Path, existing: str) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    marker = b"reserved previous attempt\n"
    if existing == "directory":
        root.mkdir()
        (root / "marker").write_bytes(marker)
    elif existing == "file":
        root.write_bytes(marker)
    else:
        root.symlink_to("missing-target")
    before = root.lstat()
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)
    after = root.lstat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    if existing == "directory":
        assert (root / "marker").read_bytes() == marker
    elif existing == "file":
        assert root.read_bytes() == marker
    else:
        assert root.is_symlink() and os.readlink(root) == "missing-target"


def test_concurrent_admission_has_one_winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    barrier = Barrier(2)
    remote_main = acceptance_launch._remote_main

    def synchronized_remote_main(checkout: Path):
        result = remote_main(checkout)
        barrier.wait(timeout=30)
        return result

    monkeypatch.setattr(acceptance_launch, "_remote_main", synchronized_remote_main)

    def prepare_or_code():
        try:
            return _prepare(fixture)
        except AcceptanceRegistrationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: prepare_or_code(), range(2)))
    winners = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    assert len(winners) == 1
    assert outcomes.count("campaign_root_not_fresh") == 1
    root = parent / manifest["campaign_root"]
    assert json.loads((root / "admission.json").read_bytes()) == winners[0]


def test_admission_record_is_last_and_fsynced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    writes = []
    synced = []
    write_fresh = acceptance_launch._write_new
    fsync = os.fsync

    def record_write(directory_fd: int, name: str, content: bytes):
        writes.append(name)
        return write_fresh(directory_fd, name, content)

    def record_sync(fd: int):
        status = os.fstat(fd)
        synced.append((status.st_dev, status.st_ino))
        return fsync(fd)

    monkeypatch.setattr(acceptance_launch, "_write_new", record_write)
    monkeypatch.setattr(acceptance_launch.os, "fsync", record_sync)
    _prepare(fixture)
    assert writes[-1] == "admission.json"
    root = parent / manifest["campaign_root"]
    for path in [root, root / "materials", *[path for path in root.rglob("*") if path.is_file()]]:
        status = path.stat()
        assert (status.st_dev, status.st_ino) in synced


@pytest.mark.parametrize("failure_name", ["registration.json", "preflight.json", "admission.json"])
def test_write_failure_reserves_root_and_cannot_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_name: str,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    write_fresh = acceptance_launch._write_new

    def fail_write(directory_fd: int, name: str, content: bytes):
        if name == failure_name:
            raise OSError("private diagnostic must never be surfaced")
        return write_fresh(directory_fd, name, content)

    monkeypatch.setattr(acceptance_launch, "_write_new", fail_write)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_admission_incomplete$"):
        _prepare(fixture)
    assert root.is_dir()
    identity = (root.stat().st_dev, root.stat().st_ino)
    assert not (root / "admission.json").exists()
    files_before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(acceptance_launch, "_write_new", write_fresh)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)
    assert identity == (root.stat().st_dev, root.stat().st_ino)
    assert files_before == {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_fsync_failure_reserves_root_and_cannot_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    fsync = os.fsync

    def fail_sync(_fd: int):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(acceptance_launch.os, "fsync", fail_sync)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_admission_incomplete$"):
        _prepare(fixture)
    assert root.is_dir()
    identity = root.stat().st_ino
    monkeypatch.setattr(acceptance_launch.os, "fsync", fsync)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)
    assert root.stat().st_ino == identity


def test_second_preflight_identity_drift_rejects_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    preflight = acceptance_launch.preflight_acceptance_registration
    calls = 0

    def change_second_observation(*args, **kwargs):
        nonlocal calls
        calls += 1
        report = preflight(*args, **kwargs)
        if calls == 2:
            report["head_commit"] = "f" * 40
        return report

    monkeypatch.setattr(acceptance_launch, "preflight_acceptance_registration", change_second_observation)
    with pytest.raises(AcceptanceRegistrationError, match="^checkout_changed_during_admission$"):
        _prepare(fixture)
    assert calls == 2
    assert not os.path.lexists(parent / manifest["campaign_root"])


@pytest.mark.parametrize("output", [
    b"", b"not-a-commit\trefs/heads/main\n",
    b"a" * 40 + b"\trefs/heads/other\n",
    b"a" * 40 + b"\trefs/heads/main\n" + b"b" * 40 + b"\trefs/heads/main\n",
    b"a" * 40 + b"\trefs/heads/main\nprivate diagnostic",
])
def test_malformed_remote_observation_rejects_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: bytes,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    run = subprocess.run

    def replace_ls_remote(command, *args, **kwargs):
        if command[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(command, 0, output, b"private origin diagnostic")
        return run(command, *args, **kwargs)

    monkeypatch.setattr(acceptance_launch.subprocess, "run", replace_ls_remote)
    with pytest.raises(AcceptanceRegistrationError, match="^remote_main_invalid$"):
        _prepare(fixture)
    assert not os.path.lexists(parent / manifest["campaign_root"])


def test_remote_timeout_is_bounded_and_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    run = subprocess.run
    observations = []

    def timeout_ls_remote(command, *args, **kwargs):
        if command[:2] == ["git", "ls-remote"]:
            observations.append(kwargs)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"private origin diagnostic")
        return run(command, *args, **kwargs)

    monkeypatch.setattr(acceptance_launch.subprocess, "run", timeout_ls_remote)
    with pytest.raises(AcceptanceRegistrationError, match="^remote_main_unavailable$"):
        _prepare(fixture)
    assert len(observations) == 1
    assert 0 < observations[0]["timeout"] <= 10
    assert observations[0]["stdin"] is subprocess.DEVNULL
    assert observations[0]["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert not os.path.lexists(parent / manifest["campaign_root"])


def test_material_drift_after_remote_observation_rejects_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _registered_origin(tmp_path)
    checkout, parent, manifest, _, _, _ = fixture
    remote_main = acceptance_launch._remote_main
    material_path = checkout / manifest["input_material"]["path"]
    material_content = material_path.read_bytes()

    def mutate_material(checkout_root: Path):
        commit = remote_main(checkout_root)
        material_path.write_bytes(b"x" * len(material_content))
        return commit

    monkeypatch.setattr(acceptance_launch, "_remote_main", mutate_material)
    with pytest.raises(AcceptanceRegistrationError, match="^material_file_drift$"):
        _prepare(fixture)
    assert not os.path.lexists(parent / manifest["campaign_root"])


@pytest.mark.parametrize("mutation", ["content", "replacement", "same_content_replacement"])
def test_retained_evidence_modified_during_later_write_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    write_new = acceptance_launch._write_new
    changed = False

    def mutate_retained(directory_fd: int, name: str, content: bytes):
        nonlocal changed
        result = write_new(directory_fd, name, content)
        if name == "remote-main.json":
            retained = root / "preflight.json"
            previous = retained.read_bytes()
            replacement = previous if mutation == "same_content_replacement" else b"x" * len(previous)
            if mutation == "content":
                retained.write_bytes(replacement)
            else:
                fresh = parent / "evidence-replacement"
                fresh.write_bytes(replacement)
                os.chmod(fresh, 0o600)
                os.replace(fresh, retained)
            changed = True
        return result

    monkeypatch.setattr(acceptance_launch, "_write_new", mutate_retained)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_admission_incomplete$"):
        _prepare(fixture)
    assert changed and root.is_dir()
    assert not (root / "admission.json").exists()
    monkeypatch.setattr(acceptance_launch, "_write_new", write_new)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)


def test_materials_directory_replaced_before_publication_reserves_failed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    write_new = acceptance_launch._write_new
    changed = False

    def replace_materials(directory_fd: int, name: str, content: bytes):
        nonlocal changed
        result = write_new(directory_fd, name, content)
        if name == "remote-main.json":
            retained = root / "materials"
            retained.rename(root / "replaced-materials")
            retained.mkdir(mode=0o700)
            for source in (root / "replaced-materials").iterdir():
                target = retained / source.name
                target.write_bytes(source.read_bytes())
                os.chmod(target, 0o600)
            changed = True
        return result

    monkeypatch.setattr(acceptance_launch, "_write_new", replace_materials)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_admission_incomplete$"):
        _prepare(fixture)
    assert changed and root.is_dir()
    assert not (root / "admission.json").exists()
    monkeypatch.setattr(acceptance_launch, "_write_new", write_new)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)


@pytest.mark.parametrize("mutation", ["hardlink", "extra_root_file", "extra_material_file", "materials_chmod"])
def test_retained_evidence_links_inventory_and_permissions_are_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    write_new = acceptance_launch._write_new
    changed = False

    def mutate_evidence(directory_fd: int, name: str, content: bytes):
        nonlocal changed
        result = write_new(directory_fd, name, content)
        if name == "remote-main.json":
            if mutation == "hardlink":
                os.link(root / "preflight.json", parent / "preflight-alias")
                assert (root / "preflight.json").stat().st_nlink == 2
            elif mutation == "extra_root_file":
                (root / "unexpected.bin").write_bytes(b"extra evidence\n")
            elif mutation == "extra_material_file":
                (root / "materials/unexpected.bin").write_bytes(b"extra material\n")
            else:
                os.chmod(root / "materials", 0o755)
            changed = True
        return result

    monkeypatch.setattr(acceptance_launch, "_write_new", mutate_evidence)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_admission_incomplete$"):
        _prepare(fixture)
    assert changed and root.is_dir()
    assert not (root / "admission.json").exists()
    identity = (root.stat().st_dev, root.stat().st_ino)
    monkeypatch.setattr(acceptance_launch, "_write_new", write_new)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)
    assert (root.stat().st_dev, root.stat().st_ino) == identity


def test_old_evidence_changed_after_admission_write_never_returns_success_or_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _registered_origin(tmp_path)
    _, parent, manifest, _, _, _ = fixture
    root = parent / manifest["campaign_root"]
    write_new = acceptance_launch._write_new
    changed = False

    def mutate_after_admission(directory_fd: int, name: str, content: bytes):
        nonlocal changed
        result = write_new(directory_fd, name, content)
        if name == "admission.json":
            retained = root / "preflight.json"
            retained.write_bytes(b"x" * retained.stat().st_size)
            changed = True
        return result

    monkeypatch.setattr(acceptance_launch, "_write_new", mutate_after_admission)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_admission_incomplete$"):
        _prepare(fixture)
    assert changed and root.is_dir()
    assert (root / "admission.json").is_file()
    files_before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    identity = (root.stat().st_dev, root.stat().st_ino)
    monkeypatch.setattr(acceptance_launch, "_write_new", write_new)
    with pytest.raises(AcceptanceRegistrationError, match="^campaign_root_not_fresh$"):
        _prepare(fixture)
    assert (root.stat().st_dev, root.stat().st_ino) == identity
    assert files_before == {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
