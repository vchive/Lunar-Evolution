from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_adapter import (
    _installation_inputs,
    _observation,
    _supported_chain,
    _terminal,
)
from test_python_producer_binding_exports import _shinka_run

from lunar_evolution import openevolve_handoff as openevolve
from lunar_evolution import shinka_handoff as shinka
from lunar_evolution.producer_handoff import ProducerMaterial, ProducerResultEnvelope
from lunar_evolution.python_producer_adapter import build_python_producer_adapter_envelope
from lunar_evolution.python_producer_export import (
    PythonProducerExportError,
    read_python_producer_adapter_export,
)


def _fixture(tmp_path, producer):
    binding, terminal, observation, original = _supported_chain(tmp_path / "evidence", producer)
    root = tmp_path / "completed"
    root.mkdir()
    code = b"answer = 1\n"
    if producer == "openevolve":
        path = "candidate.py"
        (root / path).write_bytes(code)
        evaluation = {"combined_score": 10000}
        (root / "result.json").write_text(json.dumps({"candidate_path": path, "evaluation": evaluation}))
        evidence = evaluation
    else:
        _shinka_run(root, code.decode())
        path = "gen_0/main.py"
        evidence = {"correct": True, "generation": 0, "program_id": "program", "combined_score": 1.0}
    material = ProducerMaterial(kind="candidate_source", path=path, size=len(code),
                                sha256=hashlib.sha256(code).hexdigest(), external_evidence=evidence)
    result = ProducerResultEnvelope(
        schema_version="1", producer_id=producer, producer_fingerprint=binding.producer_fingerprint,
        producer_run_id=binding.run_id, status="completed", contract_sha256=binding.contract_sha256,
        budget=original.budget, materials=(material,),
    )
    args = {
        "producer_id": producer, "binding": binding, "terminal": terminal,
        "observation": observation, "result": result,
        "binding_sha256": binding.binding_sha256, "terminal_sha256": terminal.terminal_sha256,
        "observation_sha256": observation.observation_sha256, "result_sha256": result.envelope_sha256,
        **_installation_inputs(binding),
    }
    return root, args


def _inventory(root: Path):
    return [(path.relative_to(root).as_posix(), path.read_bytes(),
             (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_ctime_ns, path.stat().st_mode))
            for path in sorted(root.rglob("*")) if path.is_file()]


def _no_source_io(monkeypatch):
    monkeypatch.setattr(openevolve, "_external_root", lambda *_args: pytest.fail("source I/O before preflight"))
    monkeypatch.setattr(shinka, "_root", lambda *_args: pytest.fail("source I/O before preflight"))


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_reads_actual_local_outputs_into_existing_adapter_without_writes(tmp_path, monkeypatch, producer):
    root, args = _fixture(tmp_path, producer)
    original = _inventory(tmp_path)
    monkeypatch.setattr(openevolve, "admit_seed_manifest",
                        lambda *_args, **_kwargs: pytest.fail("read-only composition cannot evaluate"))
    monkeypatch.setattr(shinka, "_prepare_export_root",
                        lambda *_args, **_kwargs: pytest.fail("read-only composition cannot write an export"))
    exported = read_python_producer_adapter_export(root, **args)
    assert exported.to_json() == build_python_producer_adapter_envelope(
        args["binding"], args["terminal"], args["observation"], args["result"],
        **_installation_inputs(args["binding"]),
    ).to_json()
    assert exported.production_admission is False
    assert exported.result.materials[0].path == args["result"].materials[0].path
    assert exported.result.materials[0].external_evidence["score_present"] is True
    assert _inventory(tmp_path) == original
    assert not any(root.glob("programs.sqlite-*"))


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
@pytest.mark.parametrize("field", [
    "binding_sha256", "terminal_sha256", "observation_sha256", "result_sha256",
    "installation_descriptor_sha256", "initialization_profile_sha256",
])
@pytest.mark.parametrize("value", [None, "0" * 64, "f" * 64])
def test_all_retained_pin_refusals_precede_source_io(tmp_path, monkeypatch, producer, field, value):
    root, args = _fixture(tmp_path, producer)
    _no_source_io(monkeypatch)
    with pytest.raises(PythonProducerExportError):
        read_python_producer_adapter_export(root, **{**args, field: value})


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
@pytest.mark.parametrize("field", ["binding", "terminal", "observation", "result", "installation_descriptor"])
def test_missing_original_evidence_refuses_before_source_io(tmp_path, monkeypatch, producer, field):
    root, args = _fixture(tmp_path, producer)
    _no_source_io(monkeypatch)
    with pytest.raises(PythonProducerExportError, match="evidence_invalid"):
        read_python_producer_adapter_export(root, **{**args, field: None})


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
@pytest.mark.parametrize("state", ["unknown", "failed", "cancelled"])
def test_noncompleted_terminal_refuses_before_source_io(tmp_path, monkeypatch, producer, state):
    root, args = _fixture(tmp_path, producer)
    terminal = _terminal(args["terminal"], status=state)
    _no_source_io(monkeypatch)
    with pytest.raises(PythonProducerExportError, match="evidence_invalid"):
        read_python_producer_adapter_export(root, **{**args, "terminal": terminal,
                                                    "terminal_sha256": terminal.terminal_sha256})


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_producer_mismatch_refuses_before_source_io(tmp_path, monkeypatch, producer):
    root, args = _fixture(tmp_path, producer)
    _no_source_io(monkeypatch)
    opposite = "shinka" if producer == "openevolve" else "openevolve"
    with pytest.raises(PythonProducerExportError, match="producer_mismatch"):
        read_python_producer_adapter_export(root, **{**args, "producer_id": opposite})


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
@pytest.mark.parametrize("field,value", [("installation_version", "different"), ("installation_version", None),
                                        ("abi_profile", "cp313-foreign"), ("argv", ("foreign",))])
def test_runtime_or_installation_drift_refuses_before_source_io(tmp_path, monkeypatch, producer, field, value):
    root, args = _fixture(tmp_path, producer)
    if field in {"abi_profile", "argv"}:
        observation = _observation(args["observation"], **{field: value})
        args.update(observation=observation, observation_sha256=observation.observation_sha256)
    else:
        args[field] = value
    _no_source_io(monkeypatch)
    with pytest.raises(PythonProducerExportError, match="evidence_invalid"):
        read_python_producer_adapter_export(root, **args)


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_complete_result_identity_drift_refuses_before_source_io(tmp_path, monkeypatch, producer):
    root, args = _fixture(tmp_path, producer)
    result = replace(args["result"], producer_run_id="foreign-run")
    _no_source_io(monkeypatch)
    with pytest.raises(PythonProducerExportError, match="evidence_invalid"):
        read_python_producer_adapter_export(root, **{**args, "result": result,
                                                    "result_sha256": result.envelope_sha256})


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_source_drift_cannot_reuse_retained_result(tmp_path, producer):
    root, args = _fixture(tmp_path, producer)
    (root / args["result"].materials[0].path).write_bytes(b"answer = 2\n")
    if producer == "openevolve":
        with pytest.raises(PythonProducerExportError, match="result_mismatch"):
            read_python_producer_adapter_export(root, **args)
    else:
        with pytest.raises(shinka.ShinkaHandoffError, match="shinka_database_code_mismatch"):
            read_python_producer_adapter_export(root, **args)


def test_coherently_changed_shinka_database_and_source_still_refuse_retained_result(tmp_path):
    root, args = _fixture(tmp_path, "shinka")
    with sqlite3.connect(root / "programs.sqlite") as database:
        database.execute("UPDATE programs SET code = 'answer = 2\n'")
    (root / "gen_0/main.py").write_bytes(b"answer = 2\n")
    with pytest.raises(PythonProducerExportError, match="result_mismatch"):
        read_python_producer_adapter_export(root, **args)


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_external_score_drift_is_provenance_and_cannot_replace_retained_evidence(tmp_path, producer):
    root, args = _fixture(tmp_path, producer)
    if producer == "openevolve":
        (root / "result.json").write_text('{"candidate_path":"candidate.py","evaluation":{"combined_score":20000}}')
    else:
        with sqlite3.connect(root / "programs.sqlite") as database:
            database.execute("UPDATE programs SET combined_score = 99999")
    with pytest.raises(PythonProducerExportError, match="result_mismatch"):
        read_python_producer_adapter_export(root, **args)


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_caller_binding_mutation_during_source_read_refuses_without_writes(tmp_path, monkeypatch, producer):
    root, args = _fixture(tmp_path, producer)
    original = _inventory(tmp_path)
    module, name = ((openevolve, "_read_openevolve_snapshot") if producer == "openevolve"
                    else (shinka, "_read_shinka_snapshot"))
    reader = getattr(module, name)

    def mutate(*reader_args):
        value = reader(*reader_args)
        object.__setattr__(args["binding"], "binding_sha256", "f" * 64)
        return value

    monkeypatch.setattr(module, name, mutate)
    with pytest.raises(PythonProducerExportError, match="evidence_(invalid|drift)"):
        read_python_producer_adapter_export(root, **args)
    assert _inventory(tmp_path) == original


def test_explicit_shinka_selection_works_without_export_destination(tmp_path):
    root, args = _fixture(tmp_path, "shinka")
    result = read_python_producer_adapter_export(root, **args, program_ids=("program",))
    assert result.result == args["result"]
    assert sorted(path.name for path in root.iterdir()) == ["gen_0", "programs.sqlite"]


def test_shinka_database_sidecar_refuses_without_creating_export_tree(tmp_path):
    root, args = _fixture(tmp_path, "shinka")
    (root / "programs.sqlite-wal").write_bytes(b"inert-wal")
    original = _inventory(tmp_path)
    with pytest.raises(shinka.ShinkaHandoffError, match="shinka_database_wal_unsupported"):
        read_python_producer_adapter_export(root, **args)
    assert _inventory(tmp_path) == original
