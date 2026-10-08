from __future__ import annotations

import hashlib
import json
import stat
import tarfile
from pathlib import Path

import pytest

from tools.static_python_fixture.profile import CONFIG, FROZEN, PRECONFIG
from tools.static_python_fixture.recipe import (
    ExactPatch,
    RecipeError,
    apply_exact_patch,
    emit_build_plan,
    extract_source,
)


def test_plan_emits_explicit_profile_and_never_claims_build(tmp_path: Path):
    plan = emit_build_plan(tmp_path / "plan")
    manifest = json.loads((plan / "manifest.json").read_text())
    assert manifest["preconfig"] == PRECONFIG
    assert manifest["config"] == CONFIG
    assert manifest["artifact_state"] == "pending-builder"
    assert manifest["startup_state"] == "not-executed"
    assert manifest["max_image_bytes"] == 134217728
    assert (stat.S_IMODE((plan / "build.sh").stat().st_mode)) == 0o555
    assert "exec env -i" in (plan / "build.sh").read_text()
    assert "regen-frozen" not in (plan / "build.sh").read_text()
    assert "PLAN ONLY" in (plan / "linux-build-commands.sh").read_text()
    assert len(manifest["frozen"]) == len(FROZEN) == 9


def test_exact_patch_checks_hash_and_occurrence(tmp_path: Path):
    source = tmp_path / "source.c"
    source.write_bytes(b"one\nneedle\ntwo\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    output = apply_exact_patch(tmp_path, ExactPatch("source.c", digest, b"needle", b"patched"))
    assert output == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.read_bytes() == b"one\npatched\ntwo\n"
    with pytest.raises(RecipeError, match="preimage hash"):
        apply_exact_patch(tmp_path, ExactPatch("source.c", "0" * 64, b"patched", b"bad"))
    source.write_bytes(b"needle needle")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(RecipeError, match="occurrence"):
        apply_exact_patch(tmp_path, ExactPatch("source.c", digest, b"needle", b"bad"))


def _archive(path: Path, *, member_name: str = "Python-3.13.12/file.txt", symlink: bool = False):
    with tarfile.open(path, "w:xz") as archive:
        root = tarfile.TarInfo("Python-3.13.12")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo(member_name)
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
        else:
            member.size = 3
        archive.addfile(member, None if symlink else __import__("io").BytesIO(b"abc"))


def test_extract_source_rejects_links_and_contains_members(tmp_path: Path):
    archive = tmp_path / "source.tar.xz"
    _archive(archive)
    pin = {"size": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
           "url": "fixture", "root": "Python-3.13.12"}
    root = extract_source(archive, tmp_path / "out", pin)
    assert (root / "file.txt").read_bytes() == b"abc"
    linked = tmp_path / "linked.tar.xz"
    _archive(linked, member_name="Python-3.13.12/link", symlink=True)
    linked_pin = dict(pin, size=linked.stat().st_size,
                      sha256=hashlib.sha256(linked.read_bytes()).hexdigest())
    with pytest.raises(RecipeError, match="links"):
        extract_source(linked, tmp_path / "linked-out", linked_pin)
