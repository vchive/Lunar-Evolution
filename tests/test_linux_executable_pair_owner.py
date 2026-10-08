from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import replace

import pytest
from test_trusted_bootstrap_binding import _fixture, _prepare

from lunar_evolution import trusted_bootstrap_binding as binding
from lunar_evolution.linux_executable_binding import LinuxExecutableBindingError
from lunar_evolution.producer_process import ProducerExecutableSnapshot

linux = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux sealed executable pair")


def test_detached_pair_has_no_live_owner():
    snapshot = ProducerExecutableSnapshot(None, "a" * 64, 1, "linux-sealed-memfd")
    pair = binding.TrustedExecutablePair(
        binding.BoundExecutable("/proc/self/fd/30", snapshot, 30),
        binding.BoundExecutable("/proc/self/fd/31", snapshot, 31),
    )
    with pytest.raises(binding.TrustedBootstrapBindingError, match="^trusted_binding_owner_invalid$"):
        binding._validate_original_linux_executable_pair(pair)


@linux
def test_pair_validates_held_images_after_sources_disappear(tmp_path):
    values = _fixture(tmp_path)
    with _prepare(values) as pair:
        values[0].unlink()
        values[1].unlink()
        binding._validate_original_linux_executable_pair(pair)
        with pytest.raises(binding.TrustedBootstrapBindingError, match="owner_invalid"):
            binding._validate_original_linux_executable_pair(replace(pair))
    with pytest.raises(binding.TrustedBootstrapBindingError, match="owner_invalid"):
        binding._validate_original_linux_executable_pair(pair)


@linux
@pytest.mark.parametrize("role", ["bootstrap", "target"])
@pytest.mark.parametrize("field", ["executable", "pass_fd", "snapshot", "sha256", "size", "binding"])
def test_forced_pair_projection_mutation_never_redirects_cleanup(tmp_path, role, field):
    values = _fixture(tmp_path)
    foreign = os.open(tmp_path / "foreign", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        with _prepare(values) as pair:
            originals = pair.pass_fds
            bound = getattr(pair, role)
            if field == "snapshot":
                object.__setattr__(bound, field, replace(bound.snapshot))
            elif field == "executable":
                object.__setattr__(bound, field, f"/proc/self/fd/{foreign}")
            elif field == "pass_fd":
                object.__setattr__(bound, field, foreign)
            else:
                changed = {"sha256": "b" * 64, "size": bound.snapshot.size + 1, "binding": "foreign"}
                object.__setattr__(bound.snapshot, field, changed[field])
            with pytest.raises(binding.TrustedBootstrapBindingError, match="owner_invalid"):
                binding._validate_original_linux_executable_pair(pair)
        os.fstat(foreign)
        for fd in originals:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        os.close(foreign)


@linux
@pytest.mark.parametrize("role", ["bootstrap", "target"])
def test_pair_known_foreign_reuse_is_not_closed(tmp_path, role):
    values = _fixture(tmp_path)
    foreign = os.open(tmp_path / "foreign", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    reused = None
    try:
        with (
            pytest.raises(binding.TrustedBootstrapBindingError, match="^trusted_binding_cleanup_unknown$"),
            _prepare(values) as pair,
        ):
            reused = getattr(pair, role).pass_fd
            os.dup2(foreign, reused, inheritable=False)
            with pytest.raises(binding.TrustedBootstrapBindingError, match="linux_execution_binding_invalid"):
                binding._validate_original_linux_executable_pair(pair)
        assert os.fstat(reused).st_ino == os.fstat(foreign).st_ino
        other = pair.target if role == "bootstrap" else pair.bootstrap
        with pytest.raises(OSError):
            os.fstat(other.pass_fd)
    finally:
        if reused is not None:
            os.close(reused)
        os.close(foreign)


@linux
@pytest.mark.parametrize("primary", [RuntimeError("fixed"), KeyboardInterrupt(), SystemExit(2),
                                    LinuxExecutableBindingError("caller-owned-error")])
def test_pair_cleanup_preserves_the_same_body_exception(tmp_path, primary):
    values = _fixture(tmp_path)
    with pytest.raises(type(primary)) as caught, _prepare(values) as pair:
        os.close(pair.target.pass_fd)
        raise primary
    assert caught.value is primary
    assert "linux_execution_cleanup_unknown" in primary.__notes__
    with pytest.raises(OSError):
        os.fstat(pair.bootstrap.pass_fd)


@linux
def test_second_preparation_failure_releases_first_owner(tmp_path, monkeypatch):
    values = _fixture(tmp_path)
    first = []
    real = binding.sealed_linux_executable
    @contextmanager
    def fail_second(*args, **kwargs):
        if first:
            raise LinuxExecutableBindingError("linux_execution_source_changed")
        with real(*args, **kwargs) as live:
            first.append(live.fd)
            yield live

    monkeypatch.setattr(binding, "sealed_linux_executable", fail_second)
    with (
        pytest.raises(binding.TrustedBootstrapBindingError, match="^trusted_binding_source_changed$"),
        _prepare(values),
    ):
        pytest.fail("second preparation must refuse")
    with pytest.raises(OSError):
        os.fstat(first[0])


@linux
def test_pair_distinguishes_clean_body_refusal_from_secondary_exit_error(tmp_path, monkeypatch):
    values = _fixture(tmp_path)
    primary = LinuxExecutableBindingError("caller-owned-refusal")
    with pytest.raises(LinuxExecutableBindingError) as caught, _prepare(values):
        raise primary
    assert caught.value is primary and not getattr(primary, "__notes__", ())

    real = binding.sealed_linux_executable
    acquired = []

    @contextmanager
    def secondary_exit(*args, **kwargs):
        try:
            with real(*args, **kwargs) as live:
                acquired.append(live.fd)
                yield live
        finally:
            raise LinuxExecutableBindingError("linux_execution_cleanup_unknown")

    monkeypatch.setattr(binding, "sealed_linux_executable", secondary_exit)
    interrupt = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as caught, _prepare(values):
        raise interrupt
    assert caught.value is interrupt
    assert interrupt.__notes__ == ["linux_execution_cleanup_unknown"]
    assert len(acquired) == 2
    for fd in acquired:
        with pytest.raises(OSError):
            os.fstat(fd)
