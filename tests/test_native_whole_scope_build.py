"""Builder/installed-byte refusals, separate from privileged scope acceptance."""
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import replace

import pytest

from lunar_evolution import native_whole_scope_build as builder
from lunar_evolution.native_bootstrap import NativeBootstrapError


def test_unsupported_platform_refuses_before_creating_output(tmp_path, monkeypatch):
    monkeypatch.setattr(builder.platform, "system", lambda: "Darwin")
    output = tmp_path / "absent"
    with pytest.raises(NativeBootstrapError, match="native_whole_scope_platform_unsupported"):
        builder.build_native_whole_scope_artifact(output)
    assert not output.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux ELF developer build")
def test_actual_helper_build_binds_every_source_and_installed_bytes(tmp_path):
    artifact = builder.build_native_whole_scope_artifact(tmp_path / "build")
    assert artifact.path.read_bytes().startswith(b"\x7fELF")
    assert artifact.artifact_sha256 == hashlib.sha256(artifact.path.read_bytes()).hexdigest()
    assert artifact.descriptor.implementation_version == builder.WHOLE_SCOPE_IMPLEMENTATION
    assert builder.load_native_whole_scope_artifact(
        artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
    ).artifact_sha256 == artifact.artifact_sha256
    with pytest.raises(NativeBootstrapError, match="implementation_invalid"):
        builder.load_native_whole_scope_artifact(
            artifact.path, descriptor=replace(artifact.descriptor, implementation_version="old-native",
                                               descriptor_sha256=None),
            allowlist_id=artifact.allowlist_id,
        )
    with pytest.raises(NativeBootstrapError, match="output_exists"):
        builder.build_native_whole_scope_artifact(artifact.path.parent)
    artifact.path.write_bytes(artifact.path.read_bytes() + b"changed")
    with pytest.raises(NativeBootstrapError, match="artifact_changed"):
        builder.load_native_whole_scope_artifact(
            artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
        )


@pytest.mark.skipif(sys.platform != "linux", reason="explicit Linux builder prerequisite")
def test_nonprivate_output_directory_never_calls_compiler(tmp_path, monkeypatch):
    directory = tmp_path / "shared"
    directory.mkdir(mode=0o755)
    os.chmod(directory, 0o755)
    monkeypatch.setattr(builder.subprocess, "run", lambda *_a, **_kw: pytest.fail("compiler must not start"))
    with pytest.raises(NativeBootstrapError, match="output_invalid"):
        builder.build_native_whole_scope_artifact(directory)
