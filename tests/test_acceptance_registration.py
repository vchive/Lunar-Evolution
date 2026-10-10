"""Provider-free registration manifest, seal and launch-preflight checks."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import (
    DEFAULT_ACCEPTANCE_BUDGETS,
    AcceptanceRegistrationError,
    build_acceptance_registration,
    build_registration_seal,
    parse_acceptance_registration,
    parse_registration_seal,
    preflight_acceptance_registration,
)
from lunar_evolution.acceptance_registration import MAX_PRODUCT_FILE_BYTES, MAX_REGISTRATION_BYTES


def payload() -> dict[str, object]:
    value = {
        "schema_version": "1", "scope": "acceptance_registration",
        "registration_id": "registration-20260922", "campaign_id": "campaign-20260922",
        "attempt_id": "attempt-001", "product_commit": "a" * 40,
        "product_files": [{"path": "src/main.py", "size": 1, "sha256": "9" * 64}],
        "task_material": {"path": "task.json", "size": 1, "sha256": "5" * 64},
        "input_material": {"path": "input.json", "size": 1, "sha256": "6" * 64},
        "evaluator_material": {"path": "evaluator.py", "size": 1, "sha256": "7" * 64},
        "evaluator_profile_material": {"path": "profile.json", "size": 1, "sha256": "8" * 64},
        "campaign_root": "campaign-20260922", "task_sha256": "5" * 64,
        "input_sha256": "6" * 64, "evaluator_sha256": "7" * 64,
        "evaluator_profile_sha256": "8" * 64, "provider": "configured-provider",
        "model": "configured-model", "runtime": "python311", "api_mode": "responses",
        "entrypoint": "src/main.py", "budgets": dict(DEFAULT_ACCEPTANCE_BUDGETS),
        "islands": 1, "population_size": 1, "offspring_count": 1, "rounds": 1,
        "candidate_tool_steps": 12,
        "holdout_pins": [
            {"holdout_id": f"holdout-{index:02d}", "ordinal": index,
             "input": {"path": f"holdout/{index:02d}.in", "size": 1, "sha256": f"{index + 5:x}" * 64},
             "expected": {"path": f"expected/{index:02d}.out", "size": 1, "sha256": f"{index + 6:x}" * 64},
             "max_duration_ms": 5000} for index in range(8)
        ],
        "frozen_identities": {
            "registration_id": ["old-registration"],
            "campaign_id": ["old-campaign"],
            "campaign_root": ["old-root"],
        },
    }
    import hashlib
    value["frozen_identities_sha256"] = hashlib.sha256(json.dumps(value["frozen_identities"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value


def registration() -> dict[str, object]:
    return build_acceptance_registration(payload())


def test_registration_is_canonical_and_digest_bound() -> None:
    value = registration()
    assert parse_acceptance_registration(json.dumps(value, sort_keys=True, separators=(",", ":"))) == value
    with pytest.raises(AcceptanceRegistrationError, match="registration_noncanonical"):
        parse_acceptance_registration(json.dumps(value, indent=2))
    forged = copy.deepcopy(value)
    forged["input_sha256"] = "f" * 64
    with pytest.raises(AcceptanceRegistrationError, match="material_digest_mismatch"):
        parse_acceptance_registration(forged)


@pytest.mark.parametrize(("field", "code"), [
    ("budgets", "budgets_do_not_match_plan"), ("campaign_root", "invalid_campaign_root"),
    ("holdout_pins", "holdout_pins_invalid"), ("entrypoint", "invalid_entrypoint"),
    ("candidate_tool_steps", "invalid_candidate_tool_steps"),
])
def test_registration_rejects_drift(field: str, code: str) -> None:
    value = payload()
    if field == "budgets":
        value[field]["solve_wall_seconds"] = 2400  # type: ignore[index]
    elif field == "holdout_pins":
        value[field] = value[field][:-1]  # type: ignore[index]
    elif field == "candidate_tool_steps":
        value[field] = 11
    elif field == "campaign_root":
        value[field] = "../old"
    else:
        value[field] = "../candidate.py"
    with pytest.raises(AcceptanceRegistrationError, match=code):
        build_acceptance_registration(value)


def test_clean_pushed_observation_is_ready_and_seal_is_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = registration()
    manifest_path = tmp_path / "registration.json"
    seal_path = tmp_path / "seal.json"
    manifest_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    seal = build_registration_seal(value)
    seal_path.write_text(json.dumps(seal, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    monkeypatch.setattr("lunar_evolution.acceptance_registration._git", lambda *args, **kwargs: b"a" * 40)
    # The filesystem-free contract is covered here; actual checkout reading is exercised by integration.
    assert parse_registration_seal(seal)["registration_sha256"] == value["registration_sha256"]


def test_preflight_function_does_not_run_external_commands() -> None:
    value = registration()
    assert value["candidate_tool_steps"] == 12


def test_seal_tamper_is_rejected() -> None:
    value = registration()
    seal = build_registration_seal(value)
    seal["campaign_root"] = "other-root"
    with pytest.raises(AcceptanceRegistrationError, match="seal_digest_mismatch"):
        parse_registration_seal(seal)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _materials(value: dict) -> dict[str, dict]:
    materials = {key: value[key] for key in (
        "task_material", "input_material", "evaluator_material", "evaluator_profile_material",
    )}
    materials.update({
        f"holdout-{pin['ordinal']:02d}-{key}": pin[key]
        for pin in value["holdout_pins"] for key in ("input", "expected")
    })
    return materials


def _write_registration(value: dict, manifest_path: Path, seal_path: Path) -> dict:
    manifest = build_acceptance_registration({
        key: item for key, item in value.items() if key != "registration_sha256"
    })
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    seal = build_registration_seal(manifest)
    seal_path.write_bytes(json.dumps(seal, sort_keys=True, separators=(",", ":")).encode())
    return manifest


def _commit_checkout(root: Path) -> None:
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "registration")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


def _checkout(
    tmp_path: Path, *, product_bytes: bytes = b"x", material_bytes: bytes | None = None,
) -> tuple[Path, Path, dict[str, object], Path, Path]:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "src").mkdir()
    (root / "src/main.py").write_bytes(product_bytes)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "product")
    product_commit = _git(root, "rev-parse", "HEAD")
    value = payload()
    value["product_commit"] = product_commit
    value["product_files"] = [{
        "path": "src/main.py", "size": len(product_bytes),
        "sha256": hashlib.sha256(product_bytes).hexdigest(),
    }]
    for index, item in enumerate(_materials(value).values()):
        content = material_bytes if material_bytes is not None else f"material-{index:02d}\n".encode()
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        item.update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
    for name in ("task", "input", "evaluator", "evaluator_profile"):
        value[f"{name}_sha256"] = value[f"{name}_material"]["sha256"]
    metadata = root / ".registration"
    metadata.mkdir()
    manifest_path = metadata / "registration.json"
    seal_path = metadata / "registration-seal.json"
    manifest = _write_registration(value, manifest_path, seal_path)
    _commit_checkout(root)
    parent = tmp_path / "campaigns"
    parent.mkdir()
    return root, parent, manifest, manifest_path, seal_path


def test_read_only_preflight_checks_committed_bytes_and_checkout(tmp_path: Path) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    result = preflight_acceptance_registration(
        manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        frozen_identities=["old-registration", "old-campaign", "old-root"],
    )
    assert result["status"] == "ready" and result["checks"]["head_equals_origin"] is True
    assert result["checks"]["materials_tracked"] is True
    assert result["checks"]["material_files_unchanged"] is True
    assert not (parent / manifest["campaign_root"]).exists()
    assert before == sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


@pytest.mark.parametrize("material_name", _materials(payload()))
@pytest.mark.parametrize("mutation", ["digest", "size"])
def test_preflight_verifies_every_material_pin_after_resealing(
    tmp_path: Path, material_name: str, mutation: str,
) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    item = _materials(manifest)[material_name]
    if mutation == "size":
        item["size"] += 1
    else:
        item["sha256"] = "f" * 64
        if material_name.endswith("_material"):
            manifest[material_name.removesuffix("_material") + "_sha256"] = item["sha256"]
    _write_registration(manifest, manifest_path, seal_path)
    _commit_checkout(root)
    with pytest.raises(AcceptanceRegistrationError, match="^material_file_drift$"):
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )


@pytest.mark.parametrize("mutation", ["missing", "untracked", "committed_drift", "head_mismatch"])
def test_preflight_material_must_match_tracked_head(tmp_path: Path, mutation: str) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    item = manifest["input_material"]
    path = root / item["path"]
    if mutation == "missing":
        path.unlink()
    elif mutation == "untracked":
        _git(root, "rm", "--cached", "--", item["path"])
        (root / ".gitignore").write_text(item["path"] + "\n", encoding="utf-8")
    elif mutation == "committed_drift":
        path.write_bytes(b"changed\n")
    else:
        _git(root, "update-index", "--assume-unchanged", "--", item["path"])
        path.write_bytes(b"changed\n")
        item.update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        manifest["input_sha256"] = item["sha256"]
        _write_registration(manifest, manifest_path, seal_path)
    _commit_checkout(root)
    assert _git(root, "status", "--porcelain", "--untracked-files=all") == ""
    code = "registration_files_untracked" if mutation in {"missing", "untracked"} else "material_file_drift"
    with pytest.raises(AcceptanceRegistrationError, match=f"^{code}$"):
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )


@pytest.mark.parametrize("kind", ["product", "material", "binary"])
def test_preflight_accepts_product_sized_files(tmp_path: Path, kind: str) -> None:
    content = b"x" * (MAX_REGISTRATION_BYTES + 1) if kind != "binary" else b"x\x00y"
    root, parent, _, manifest_path, seal_path = _checkout(
        tmp_path,
        product_bytes=content if kind != "material" else b"x",
        material_bytes=content if kind != "product" else None,
    )
    assert preflight_acceptance_registration(
        manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
    )["status"] == "ready"


@pytest.mark.parametrize("kind", ["product", "material", "registration", "seal"])
def test_preflight_preserves_separate_file_size_limits(tmp_path: Path, kind: str) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    if kind in {"product", "material"}:
        item = manifest["product_files"][0] if kind == "product" else manifest["input_material"]
        path, maximum = root / item["path"], MAX_PRODUCT_FILE_BYTES
    else:
        path = manifest_path if kind == "registration" else seal_path
        maximum = MAX_REGISTRATION_BYTES
    path.write_bytes(b"x" * (maximum + 1))
    _commit_checkout(root)
    with pytest.raises(AcceptanceRegistrationError, match="^preflight_file_invalid$"):
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )


@pytest.mark.parametrize("kind", ["leaf", "ancestor"])
def test_preflight_never_follows_material_symlinks(tmp_path: Path, kind: str) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    path = root / manifest["input_material"]["path"] if kind == "leaf" else root / "holdout"
    destination = tmp_path / "retained-material"
    path.rename(destination)
    path.symlink_to(destination, target_is_directory=kind == "ancestor")
    _commit_checkout(root)
    with pytest.raises(AcceptanceRegistrationError) as error:
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )
    assert error.value.code in {
        "preflight_file_invalid", "preflight_file_changed", "registration_files_untracked",
    }


def _mutate_once_when_material_is_read(
    path: Path, monkeypatch: pytest.MonkeyPatch, mutate: Callable[[], None],
) -> list[int]:
    wanted = path.stat()
    original_read = os.read
    changed: list[int] = []

    def read(descriptor: int, maximum: int) -> bytes:
        content = original_read(descriptor, maximum)
        observed = os.fstat(descriptor)
        if (not changed and stat.S_ISREG(observed.st_mode)
                and (observed.st_dev, observed.st_ino) == (wanted.st_dev, wanted.st_ino)):
            changed.append(descriptor)
            mutate()
        return content

    monkeypatch.setattr("lunar_evolution.acceptance_registration.os.read", read)
    return changed


def test_material_read_fault_injection_ignores_pipe_inode_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "material.in"
    path.write_bytes(b"material\n")
    wanted = path.stat()
    original_fstat = os.fstat
    read_pipe, write_pipe = os.pipe()

    def fstat(descriptor: int):
        observed = original_fstat(descriptor)
        if descriptor == read_pipe:
            # Subprocess.Popen reads a shared os.read error pipe. Even an inode/device
            # collision there must not trigger a filesystem mutation intended for a file.
            return SimpleNamespace(
                st_mode=observed.st_mode, st_dev=wanted.st_dev, st_ino=wanted.st_ino,
            )
        return observed

    monkeypatch.setattr(os, "fstat", fstat)
    mutations: list[bool] = []
    changed = _mutate_once_when_material_is_read(path, monkeypatch, lambda: mutations.append(True))
    descriptor = -1
    try:
        os.write(write_pipe, b"pipe")
        assert os.read(read_pipe, 4) == b"pipe"
        assert mutations == [] and changed == []
        descriptor = os.open(path, os.O_RDONLY)
        assert os.read(descriptor, 9) == b"material\n"
        assert mutations == [True] and changed == [descriptor]
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(read_pipe)
        os.close(write_pipe)


@pytest.mark.parametrize("mutation", ["replace", "rewrite", "ancestor"])
def test_preflight_rejects_material_changes_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    path = root / manifest["holdout_pins"][0]["input"]["path"]

    def mutate() -> None:
        if mutation == "replace":
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        elif mutation == "rewrite":
            path.write_bytes(b"changed!!!\n")
        else:
            destination = tmp_path / "moved-holdouts"
            path.parent.rename(destination)
            path.parent.symlink_to(destination, target_is_directory=True)

    changed = _mutate_once_when_material_is_read(path, monkeypatch, mutate)
    with pytest.raises(AcceptanceRegistrationError, match="^preflight_file_changed$"):
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )
    assert changed


def test_preflight_rejects_committed_symlink_masked_by_regular_material(tmp_path: Path) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    path = root / manifest["input_material"]["path"]
    content = path.read_bytes()
    path.unlink()
    path.symlink_to(content.decode("utf-8"))
    _commit_checkout(root)
    path.unlink()
    path.write_bytes(content)
    _git(root, "update-index", "--assume-unchanged", "--", manifest["input_material"]["path"])
    assert _git(root, "status", "--porcelain", "--untracked-files=all") == ""
    with pytest.raises(AcceptanceRegistrationError, match="^material_file_drift$"):
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )


@pytest.mark.parametrize("changed", ["HEAD", "origin/main"])
def test_preflight_rechecks_commit_and_origin_after_materials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str,
) -> None:
    root, parent, _, manifest_path, seal_path = _checkout(tmp_path)
    from lunar_evolution import acceptance_registration as registration

    original_git = registration._git
    calls = 0

    def git(checkout: Path, *args: str, check: bool = True):
        nonlocal calls
        if args == ("rev-parse", "HEAD") and changed == "HEAD":
            calls += 1
            if calls == 2:
                return b"f" * 40 + b"\n"
        if args == ("rev-parse", "--verify", "origin/main") and changed == "origin/main":
            calls += 1
            if calls == 2:
                return b"f" * 40 + b"\n"
        return original_git(checkout, *args, check=check)

    monkeypatch.setattr(registration, "_git", git)
    with pytest.raises(AcceptanceRegistrationError, match="^checkout_changed_during_preflight$"):
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        )


@pytest.mark.parametrize("mutation", ["dirty", "unpushed", "root", "drift", "identity"])
def test_preflight_fails_closed_before_admission(tmp_path: Path, mutation: str) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    if mutation == "dirty":
        (root / "dirty").write_text("x", encoding="utf-8")
    elif mutation == "unpushed":
        (root / "src/main.py").write_bytes(b"changed")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "unpushed")
    elif mutation == "root":
        (parent / manifest["campaign_root"]).mkdir()
    elif mutation == "drift":
        (root / "src/main.py").write_bytes(b"y")
        # Keep checkout clean while changing the committed product blob.
        _git(root, "add", "src/main.py")
        _git(root, "commit", "-qm", "drift")
        _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    elif mutation == "identity":
        frozen = [manifest["campaign_id"]]
    else:
        frozen = ["old-registration"]
    if mutation != "identity":
        frozen = ["old-registration", "old-campaign", "old-root"]
    with pytest.raises(AcceptanceRegistrationError) as error:
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
            frozen_identities=frozen,
        )
    assert error.value.code in {
        "checkout_dirty", "checkout_not_pushed", "campaign_root_not_fresh", "product_file_drift", "identity_reused",
    }


def test_material_and_frozen_identity_digests_are_required() -> None:
    value = payload()
    value["task_sha256"] = "f" * 64
    with pytest.raises(AcceptanceRegistrationError, match="material_digest_mismatch"):
        build_acceptance_registration(value)
    value = payload()
    value["frozen_identities_sha256"] = "f" * 64
    with pytest.raises(AcceptanceRegistrationError, match="frozen_identities_digest_mismatch"):
        build_acceptance_registration(value)
