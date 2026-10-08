from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
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


def test_build_driver_stays_plan_only_without_explicit_opt_in(tmp_path: Path):
    plan = emit_build_plan(tmp_path / "plan")
    result = subprocess.run(
        ["/bin/sh", str(plan / "build.sh")], cwd=tmp_path,
        env={"PATH": os.defpath}, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 78
    assert b"PLAN ONLY" in result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == ["plan"]


def test_emitted_freeze_commands_expand_exact_paths_without_building_python(tmp_path: Path):
    # Disposable shell stubs exercise the emitted driver only: no source archive,
    # compiler, target interpreter or real CPython build is used.
    plan = emit_build_plan(tmp_path / "plan 'quoted' $lunar_literal")
    source = tmp_path / "source with spaces"
    zig = tmp_path / "zig with spaces"
    output = tmp_path / "out with spaces"
    (source / "Programs").mkdir(parents=True)
    zig.mkdir()
    for path in (source / "configure", zig / "zig"):
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o700)
    freezer = source / "Programs" / "_freeze_module"
    freezer.write_text('#!/bin/sh\nprintf "%s\\0" "$@" >> "$PWD/freeze-argv.bin"\n')
    freezer.chmod(0o700)
    (source / "Makefile").write_text("Programs/_freeze_module:\n\t@true\n")
    result = subprocess.run(
        ["/bin/sh", str(plan / "build.sh")], cwd=tmp_path,
        env={"PATH": os.defpath, "LUNAR_STATIC_EXECUTE": "1",
             "LUNAR_STATIC_SOURCE": str(source), "LUNAR_STATIC_ZIG": str(zig),
             "LUNAR_STATIC_OUT": str(output)},
        capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 78, result.stderr
    actual = (source / "freeze-argv.bin").read_bytes().split(b"\0")
    expected = []
    for name, generator_id, relative_source, _package in FROZEN:
        input_path = plan / "assets/frozen_main.py" if name == "_lunar_static_main" else source / relative_source
        expected.extend(str(item).encode() for item in (
            generator_id, input_path, output / "generated" / (generator_id + ".h"),
        ))
    assert actual == [*expected, b""]
    assert list((output / "generated").iterdir()) == []


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
