"""Feature191 durable binding sidecar publication and retained-pin checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import (
    PYTHON_BINDING_SIDECAR_NAME,
    PythonProducerBindingStoreError,
    persist_python_producer_binding,
    read_python_producer_binding_sidecar,
)


def _binding(tmp_path: Path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest,
        runtime_tree=tree,
        intent=intent,
        attestation=attestation,
        deadline_unix=4102444800.0,
        budget=budget,
    )
    batch = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id
    batch.mkdir(parents=True)
    batch.chmod(0o700)
    return binding, batch


def test_sidecar_roundtrip_pin_captures_published_single_link(tmp_path: Path) -> None:
    binding, batch = _binding(tmp_path)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    path = batch / PYTHON_BINDING_SIDECAR_NAME
    info = path.stat()
    assert info.st_nlink == 1
    assert info.st_mode & 0o777 == 0o600
    assert sidecar.file_nlink == 1
    assert sidecar.file_mode == 0o600
    assert read_python_producer_binding_sidecar(
        tmp_path, binding=binding, expected_sidecar=sidecar,
    ) == sidecar


def test_sidecar_create_only_failure_leaves_no_temporary_file(tmp_path: Path) -> None:
    binding, batch = _binding(tmp_path)
    persist_python_producer_binding(tmp_path, binding=binding)
    with pytest.raises(PythonProducerBindingStoreError, match="already_exists"):
        persist_python_producer_binding(tmp_path, binding=binding)
    assert not tuple(batch.glob(".python-binding-*"))


def test_malformed_retained_pin_is_rejected_before_workspace_io(tmp_path: Path) -> None:
    binding, _batch = _binding(tmp_path)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    tampered = replace(sidecar, raw_sha256="g" * 64)
    # A missing workspace would otherwise produce a filesystem error.  The retained
    # pin gate is required to run before selecting or opening the batch directory.
    with pytest.raises(PythonProducerBindingStoreError, match="expected_pin_invalid"):
        read_python_producer_binding_sidecar(
            tmp_path / "missing", binding=binding, expected_sidecar=tampered,
        )


@pytest.mark.parametrize("field", ["raw_sha256", "file_device", "file_inode"])
def test_zero_retained_pin_identity_is_rejected_before_workspace_io(
    tmp_path: Path, field: str,
) -> None:
    binding, _batch = _binding(tmp_path)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    tampered = replace(sidecar, **{field: "0" * 64 if field == "raw_sha256" else 0})
    with pytest.raises(PythonProducerBindingStoreError, match="expected_pin_invalid"):
        read_python_producer_binding_sidecar(
            tmp_path / "missing", binding=binding, expected_sidecar=tampered,
        )


def test_invalid_binding_is_normalized_before_workspace_io(tmp_path: Path) -> None:
    binding, _batch = _binding(tmp_path)
    object.__setattr__(binding, "intent", object())
    with pytest.raises(PythonProducerBindingStoreError, match="binding_invalid"):
        persist_python_producer_binding(tmp_path / "missing", binding=binding)


def test_missing_batch_is_a_fixed_missing_binding_error(tmp_path: Path) -> None:
    binding, batch = _binding(tmp_path)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    for path in sorted(batch.iterdir(), reverse=True):
        path.unlink()
    batch.rmdir()
    with pytest.raises(PythonProducerBindingStoreError) as caught:
        read_python_producer_binding_sidecar(
            tmp_path, binding=binding, expected_sidecar=sidecar,
        )
    assert caught.value.code == "python_producer_binding_store_batch_missing"


def test_missing_sidecar_is_distinct_from_missing_batch(tmp_path: Path) -> None:
    binding, batch = _binding(tmp_path)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    (batch / PYTHON_BINDING_SIDECAR_NAME).unlink()
    with pytest.raises(PythonProducerBindingStoreError) as caught:
        read_python_producer_binding_sidecar(
            tmp_path, binding=binding, expected_sidecar=sidecar,
        )
    assert caught.value.code == "python_producer_binding_store_missing"


def test_persist_missing_batch_has_a_fixed_missing_error(tmp_path: Path) -> None:
    binding, batch = _binding(tmp_path)
    for path in sorted(batch.iterdir(), reverse=True):
        path.unlink()
    batch.rmdir()
    with pytest.raises(PythonProducerBindingStoreError) as caught:
        persist_python_producer_binding(tmp_path, binding=binding)
    assert caught.value.code == "python_producer_binding_store_batch_missing"
