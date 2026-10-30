"""Source-only preparation fixtures; no upstream import, build or execution.

Synthetic tar data exercises malformed-member cases. The real retained archive
is inspected once separately; normal CI neither requires nor downloads it.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from tools.shinka_fixed_profile import __main__ as cli
from tools.shinka_fixed_profile import prepare

ROOT = Path(__file__).resolve().parents[1]


def _archive(members, *, file_mode=0o644):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, raw, kind in members:
            member = tarfile.TarInfo(name)
            member.mode = 0o775 if kind == tarfile.DIRTYPE else file_mode
            member.type = kind
            member.size = len(raw)
            member.linkname = "unused-link"
            archive.addfile(member, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
    return stream.getvalue()


def _member(path, raw=b"x", kind=tarfile.REGTYPE):
    return prepare.ARCHIVE_ROOT + "/" + path, raw, kind


def _current_sources():
    return (
        (ROOT / "src/lunar_evolution/producer_broker_ipc.py").read_bytes(),
        (ROOT / "src/lunar_evolution/http_transport.py").read_bytes(),
    )


@pytest.fixture
def synthetic_profile(monkeypatch):
    # Pin a completely synthetic archive inside this fixture only. The public
    # preparer's production constants remain exact retained upstream byte pins.
    originals = {
        path: (b'"""synthetic source data only"""\n' if path.endswith(".py") else b"fixture license")
        for path in prepare._ORIGINAL_PINS
    }
    archive = _archive([_member(path, data) for path, data in originals.items()])
    monkeypatch.setattr(prepare, "ARCHIVE_BYTES", len(archive))
    monkeypatch.setattr(prepare, "ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(prepare, "ARCHIVE_FILES", len(originals))
    monkeypatch.setattr(prepare, "ARCHIVE_CONTENT_BYTES", sum(map(len, originals.values())))
    monkeypatch.setattr(prepare, "_ORIGINAL_PINS", {
        path: (len(raw), hashlib.sha256(raw).hexdigest()) for path, raw in originals.items()
    })
    broker, transport = _current_sources()
    result = prepare.prepare_shinka_sources(
        archive, broker_source_bytes=broker, transport_source_bytes=transport,
    )
    return result, originals, archive


@pytest.mark.parametrize("raw", [b"", b"not an archive", b"x" * prepare.ARCHIVE_BYTES],
                         ids=["empty", "invalid-tar", "wrong-content-at-archive-size"])
def test_wrong_archive_pin_refused_before_tar_processing(raw, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unverified tar decoded")

    monkeypatch.setattr(prepare, "_read_archive_members", forbidden)
    with pytest.raises(prepare.ShinkaPreparationError, match="archive_pin_mismatch"):
        prepare.prepare_shinka_sources(raw, broker_source_bytes=b"", transport_source_bytes=b"")


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../escape", "a//b", "a\\b", "./x"])
def test_unsafe_archive_paths_are_not_extracted(path):
    raw = _archive([_member(path)])
    with pytest.raises(prepare.ShinkaPreparationError, match="archive_path_invalid"):
        prepare._read_archive_members(raw, expected_files=1, expected_bytes=1, selected=set())


def test_foreign_archive_root_refused():
    raw = _archive([("foreign/file.py", b"x", tarfile.REGTYPE)])
    with pytest.raises(prepare.ShinkaPreparationError, match="archive_path_invalid"):
        prepare._read_archive_members(raw, expected_files=1, expected_bytes=1, selected=set())


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_special_archive_members_refused(kind):
    raw = _archive([_member("file", b"", kind)])
    with pytest.raises(prepare.ShinkaPreparationError, match="archive_member_invalid"):
        prepare._read_archive_members(raw, expected_files=0, expected_bytes=0, selected=set())


def test_duplicate_archive_member_refused():
    raw = _archive([_member("file"), _member("file")])
    with pytest.raises(prepare.ShinkaPreparationError, match="archive_path_invalid"):
        prepare._read_archive_members(raw, expected_files=2, expected_bytes=2, selected={"file"})


@pytest.mark.parametrize("files,size,selected", [(0, 1, set()), (1, 0, set()), (2, 2, set()), (1, 1, {"absent"})])
def test_archive_inventory_and_bounds_refused(files, size, selected):
    raw = _archive([_member("file")])
    with pytest.raises(prepare.ShinkaPreparationError):
        prepare._read_archive_members(raw, expected_files=files, expected_bytes=size, selected=selected)


def test_all_archive_members_checked_beyond_selected_files():
    raw = _archive([_member("selected"), _member("hidden", b"", tarfile.SYMTYPE)])
    with pytest.raises(prepare.ShinkaPreparationError, match="archive_member_invalid"):
        prepare._read_archive_members(raw, expected_files=1, expected_bytes=1, selected={"selected"})


def test_original_mode_0775_directories_and_selected_data_are_accepted():
    raw = _archive([
        (prepare.ARCHIVE_ROOT + "/", b"", tarfile.DIRTYPE),
        _member("package", b"", tarfile.DIRTYPE), _member("package/data.py", b"data"),
    ])
    assert prepare._read_archive_members(
        raw, expected_files=1, expected_bytes=4, selected={"package/data.py"},
    ) == {"package/data.py": b"data"}


@pytest.mark.parametrize("mode", [0o664, 0o775])
def test_retained_github_regular_file_modes_are_accepted(mode):
    raw = _archive([_member("module.py", b"data")], file_mode=mode)
    assert prepare._read_archive_members(
        raw, expected_files=1, expected_bytes=4, selected={"module.py"},
    ) == {"module.py": b"data"}


@pytest.mark.parametrize("source", ["broker", "transport"])
def test_full_current_source_drift_refused(source, synthetic_profile):
    _profile, _original, archive = synthetic_profile
    broker, transport = _current_sources()
    if source == "broker":
        broker += b"\n"
    else:
        transport += b"\n"
    with pytest.raises(prepare.ShinkaPreparationError, match="broker_source_drift"):
        prepare.prepare_shinka_sources(archive, broker_source_bytes=broker, transport_source_bytes=transport)


def test_reuses_existing_pinned_broker_generator_byte_for_byte(synthetic_profile):
    from tools.openevolve_fixed_profile.prepare import generate_target_broker

    profile, _original, _archive = synthetic_profile
    expected, records = generate_target_broker(*_current_sources())
    observed = {source.path: source.data for source in profile.sources}
    assert observed["shinka/lunar_fixed_broker.py"] == expected
    manifest = json.loads(profile.manifest)
    assert manifest["broker"]["segments"] == list(records)
    assert manifest["broker"]["generator"] == "tools.openevolve_fixed_profile.prepare.generate_target_broker"
    assert b"lunar_evolution" not in expected


@pytest.mark.parametrize("mutation", ["memory_field", "region_check", "read_mode"])
def test_shared_boundary_guard_refuses_unchecked_validation_divergence(mutation):
    raw = (ROOT / "tools/shinka_fixed_profile/assets/fixed_entrypoint.py").read_bytes()
    if mutation == "memory_field":
        raw = raw.replace(b'"failure_boundary"', b'"unreviewed_boundary"')
    elif mutation == "region_check":
        raw = raw.replace(b"    _region(program)\n", b"")
    else:
        raw = raw.replace(b"stat.S_IMODE(before.st_mode) != 0o400", b"stat.S_IMODE(before.st_mode) != 0o600")
    with pytest.raises(prepare.ShinkaPreparationError, match="shared_boundary_drift"):
        prepare._shared_boundary_guard(raw)


def test_preparation_has_exact_finite_tree_and_canonical_unaccepted_claims(synthetic_profile):
    result, original, _archive_raw = synthetic_profile
    observed = {source.path: source.data for source in result.sources}
    assert set(observed) == prepare.PREPARED_PATHS
    assert observed["LICENSE"] == original["LICENSE"]
    assert observed["LICENSE.lunar"] == (ROOT / "LICENSE").read_bytes()
    for path in ("shinka/prompts/prompts_diff.py", "shinka/edit/apply_diff.py", "shinka/edit/marker_validation.py", "shinka/utils/languages.py"):
        assert observed[path] == original[path]
    manifest = json.loads(result.manifest)
    assert result.manifest == json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    assert result.manifest_sha256 == hashlib.sha256(result.manifest).hexdigest()
    assert manifest["license"]["upstream"]["spdx"] == "Apache-2.0"
    assert manifest["license"]["lunar"]["spdx"] == "MIT"
    assert manifest["license"]["lunar"]["result"]["sha256"] == hashlib.sha256(observed["LICENSE.lunar"]).hexdigest()
    assert len(manifest["sources"]) == 10
    assert {row["module"] for row in manifest["sources"]} == {
        "shinka", "shinka.lunar_fixed", "shinka.lunar_fixed_broker", "shinka.edit",
        "shinka.edit.apply_diff", "shinka.edit.marker_validation", "shinka.prompts",
        "shinka.prompts.prompts_diff", "shinka.utils", "shinka.utils.languages",
    }
    assert {row["module"] for row in manifest["sources"] if row["package"]} == {
        "shinka", "shinka.edit", "shinka.prompts", "shinka.utils",
    }
    assert manifest["entrypoint"]["shared_boundary"]["ast_equivalent"] is True
    assert manifest["entrypoint"]["sqlite"] == {
        "required": True, "serialization_required": True, "runtime_accepted": False,
    }
    assert manifest["entrypoint"]["selection"] == {"program_ids": ["proposal"], "top_k": None}
    assert manifest["entrypoint"]["correct"] is False
    assert manifest["entrypoint"]["combined_score"] is None
    assert manifest["entrypoint"]["evaluation_performed"] is False
    assert manifest["claims"] == {
        "source_only": True, "closure_verified": False, "upstream_imported": False,
        "source_execution_performed": False, "build_performed": False,
        "runtime_execution_performed": False, "production_admission": False, "online_publication": False,
    }
    assert manifest["entrypoint"]["inputs"] == ["request.json", "memory.json"]
    assert manifest["entrypoint"]["new_grants"] == []
    assert manifest["entrypoint"]["max_requests"] == 1
    assert manifest["resources"] == []
    assert "marker_validation" not in manifest["stdlib_direct_imports"]
    for row in manifest["sources"]:
        assert row["result"] == {
            "bytes": len(observed[row["path"]]), "sha256": hashlib.sha256(observed[row["path"]]).hexdigest(),
        }
        if row["original"] is not None:
            assert row["original"]["sha256"] == hashlib.sha256(original[row["path"]]).hexdigest()


def test_preparation_does_not_import_lunar_host_or_upstream(synthetic_profile, monkeypatch):
    _profile, _original, archive = synthetic_profile
    broker, transport = _current_sources()
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith(("shinka", "lunar_evolution")):
            raise AssertionError("source-only preparation attempted a project import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = prepare.prepare_shinka_sources(
        archive, broker_source_bytes=broker, transport_source_bytes=transport,
    )
    assert len(result.sources) == 12


def test_writer_creates_finite_sources_and_manifest_last_create_only(synthetic_profile, tmp_path, monkeypatch):
    profile, _original, _archive_raw = synthetic_profile
    destination = tmp_path / "prepared"
    order = []
    write = cli._write_file

    def observed(directory, name, raw):
        order.append(name)
        return write(directory, name, raw)

    monkeypatch.setattr(cli, "_write_file", observed)
    cli._write_prepared_profile(profile, destination)
    assert order[-1] == "source-manifest.json"
    assert (destination / "source-manifest.json").read_bytes() == profile.manifest
    assert {str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()} == (
        prepare.PREPARED_PATHS | {"source-manifest.json"}
    )
    with pytest.raises(FileExistsError):
        cli._write_prepared_profile(profile, destination)
    assert (destination / "LICENSE").read_bytes() == {
        source.path: source.data for source in profile.sources
    }["LICENSE"]


def test_writer_failure_retains_partial_without_completion_manifest(synthetic_profile, tmp_path, monkeypatch):
    profile, _original, _archive_raw = synthetic_profile
    destination = tmp_path / "partial"
    write = cli._write_file

    def interrupted(directory, name, raw):
        if name == "source-manifest.json":
            raise OSError("synthetic write interruption")
        return write(directory, name, raw)

    monkeypatch.setattr(cli, "_write_file", interrupted)
    with pytest.raises(OSError):
        cli._write_prepared_profile(profile, destination)
    assert (destination / "LICENSE").exists()
    assert not (destination / "source-manifest.json").exists()


@pytest.mark.parametrize("kind", ["empty", "oversize", "symlink", "fifo"])
def test_cli_input_is_bounded_nofollow_regular_file(tmp_path, kind):
    path = tmp_path / "input"
    path.write_bytes(b"x")
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "oversize":
        path.write_bytes(b"xx")
    elif kind == "symlink":
        original = tmp_path / "original"
        path.rename(original)
        path.symlink_to(original)
    else:
        path.unlink()
        os.mkfifo(path)
    with pytest.raises((OSError, prepare.ShinkaPreparationError)):
        cli._read_regular(path, 1)


@pytest.mark.parametrize("kind", ["argument", "missing_file", "nul_path"])
def test_cli_errors_are_fixed_codes_without_raw_paths_or_args(tmp_path, capsys, kind):
    private = "private-source-prose-do-not-print"
    if kind == "argument":
        arguments = ["--archive", private, "--unexpected", private]
    else:
        arguments = ["--archive", str(tmp_path / private), "--destination", str(tmp_path / "out")]
        if kind == "nul_path":
            arguments[1] += "\x00"
    assert cli.main(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert private not in output.err
    assert str(tmp_path) not in output.err
    assert output.err in {
        "shinka_source_arguments_invalid\n", "shinka_source_io_failed\n",
    }
