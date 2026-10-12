"""Source integrity and create-only refusal checks without a Python runtime build."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.static_python_rsi_fixture import recipe


@pytest.fixture
def isolated_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source_root = tmp_path / "source-root"
    for name, _, _ in recipe._SOURCE_PINS:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((recipe._ROOT / name).read_bytes())
    monkeypatch.setattr(recipe, "_ROOT", source_root)
    return source_root


@pytest.mark.parametrize("source", [item[0] for item in recipe._SOURCE_PINS])
@pytest.mark.parametrize("mutation", ["missing", "drift"])
def test_every_reviewed_source_refuses_mutation_before_destination_creation(
    isolated_sources: Path, tmp_path: Path, source: str, mutation: str,
):
    changed = isolated_sources / source
    if mutation == "missing":
        changed.unlink()
    else:
        changed.write_bytes(changed.read_bytes() + b"\nsource drift\n")
    destination = tmp_path / "must-not-exist"
    with pytest.raises(recipe.RSILaunchSourceError, match="source_(missing|drift)"):
        recipe.emit_rsi_launch_source_plan(destination)
    assert not destination.exists()


def test_source_symlink_refuses_before_output(
    isolated_sources: Path, tmp_path: Path,
):
    source = isolated_sources / recipe._SOURCE_PINS[-1][0]
    referent = tmp_path / "same-bytes-outside-source-root"
    referent.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(referent)
    destination = tmp_path / "must-not-exist"
    with pytest.raises(recipe.RSILaunchSourceError, match="symlink"):
        recipe.emit_rsi_launch_source_plan(destination)
    assert not destination.exists()


@pytest.mark.parametrize("payload", ["raise RuntimeError('must not execute')\n", "side-effect"])
def test_drifted_profile_code_refuses_without_executing_its_top_level(
    isolated_sources: Path, tmp_path: Path, payload: str,
):
    sentinel = tmp_path / "must-not-be-written"
    if payload == "side-effect":
        payload = f"__import__('pathlib').Path({str(sentinel)!r}).write_text('executed')\n"
    profile = isolated_sources / "tools/static_python_fixture/profile.py"
    profile.write_bytes(profile.read_bytes() + payload.encode("utf-8"))
    destination = tmp_path / "must-not-exist"
    with pytest.raises(recipe.RSILaunchSourceError, match="source_drift"):
        recipe.emit_rsi_launch_source_plan(destination)
    assert not sentinel.exists()
    assert not destination.exists()


@pytest.mark.parametrize("symlink_location", ["destination", "ancestor"])
def test_destination_or_ancestor_symlink_cannot_select_output(
    isolated_sources: Path, tmp_path: Path, symlink_location: str,
):
    referent = tmp_path / "outside-output"
    referent.mkdir()
    selected = tmp_path / "selected"
    selected.symlink_to(referent, target_is_directory=True)
    destination = selected if symlink_location == "destination" else selected / "nested"
    with pytest.raises(recipe.RSILaunchSourceError, match="symlink"):
        recipe.emit_rsi_launch_source_plan(destination)
    assert list(referent.iterdir()) == []


@pytest.mark.parametrize("corrupt_relative", ["assets/launcher.c", "manifest.json"])
def test_persisted_output_corruption_refuses_and_retains_partial_without_replay_overwrite(
    isolated_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    corrupt_relative: str,
):
    destination = tmp_path / "prepared"
    original_write = recipe._write_readback

    def corrupt_after_readback(path: Path, raw: bytes) -> None:
        original_write(path, raw)
        if path == destination / corrupt_relative:
            path.chmod(0o644)
            path.write_bytes(raw + b"corrupted-output")

    monkeypatch.setattr(recipe, "_write_readback", corrupt_after_readback)
    with pytest.raises(recipe.RSILaunchSourceError, match="readback_drift"):
        recipe.emit_rsi_launch_source_plan(destination)
    retained = {item.relative_to(destination).as_posix(): item.read_bytes()
                for item in destination.rglob("*") if item.is_file()}
    assert retained[corrupt_relative].endswith(b"corrupted-output")
    with pytest.raises(recipe.RSILaunchSourceError, match="destination_exists"):
        recipe.emit_rsi_launch_source_plan(destination)
    assert {item.relative_to(destination).as_posix(): item.read_bytes()
            for item in destination.rglob("*") if item.is_file()} == retained


def test_readback_disagreement_refuses_and_preserves_bytes_already_written(
    isolated_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    destination = tmp_path / "prepared"
    original_read = Path.read_bytes

    def disagree(path: Path) -> bytes:
        raw = original_read(path)
        return raw + b"readback-disagreement" if path == destination / "assets/launcher.c" else raw

    monkeypatch.setattr(Path, "read_bytes", disagree)
    with pytest.raises(recipe.RSILaunchSourceError, match="readback_drift"):
        recipe.emit_rsi_launch_source_plan(destination)
    retained = destination / "assets/launcher.c"
    assert retained.is_file()
    assert original_read(retained) == original_read(
        isolated_sources / "tools/static_python_rsi_fixture/assets/launcher.c"
    )
    assert not (destination / "manifest.json").exists()


def test_original_frozen_encoder_prefix_retains_original_source_expansion(
    isolated_sources: Path, tmp_path: Path,
):
    from tools.static_python_fixture.profile import (
        BUILTINS,
        EXPECTED_STARTUP_MODULES,
        FROZEN,
    )

    source = (isolated_sources / "tools/static_python_fixture/assets/frozen_main.py").read_text()
    expected = source.replace("__LUNAR_EXPECTED_BUILTINS__", repr(list(BUILTINS)))
    expected = expected.replace("__LUNAR_EXPECTED_FROZEN__", repr([item[0] for item in FROZEN]))
    expected = expected.replace("__LUNAR_EXPECTED_MODULES__", repr(list(EXPECTED_STARTUP_MODULES)))
    path = recipe.emit_rsi_launch_source_plan(tmp_path / "prepared")
    record = json.loads(path.read_bytes())
    emitted = (path.parent / "assets/frozen_main.py").read_bytes()
    wrapper = (isolated_sources / "tools/static_python_rsi_fixture/assets/frozen_main.py").read_bytes()
    assert emitted == expected.encode() + b"\n" + wrapper
    assert record["claims"]["input_consumption_verified"] is False
