"""Original committed proposal formats are evidence, never candidate evaluation."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace

import pytest
from test_static_python_producer_completion_source import _namespace, _sources

from lunar_evolution import static_python_fixed_producer_evidence as evidence
from lunar_evolution.producer_handoff import ProducerMaterial, ProducerResultEnvelope

SOURCE = b"def solve(x):\n    return x\n"


def _envelope(solver):
    material = ProducerMaterial(
        kind="candidate_source", path="candidate.py" if solver == "openevolve" else "gen_0/main.py",
        size=len(SOURCE), sha256=hashlib.sha256(SOURCE).hexdigest(), lineage=(),
        external_evidence=({"present": False, "score_present": False, "payload_sha256": None}
                           if solver == "openevolve" else
                           {"correct": False, "generation": 0, "program_id": "proposal"}),
    )
    return ProducerResultEnvelope(
        schema_version="1", producer_id=solver, producer_fingerprint="b" * 64,
        producer_run_id="fixture-original", status="completed", contract_sha256="a" * 64,
        budget={"requests": 1}, materials=(material,),
    )


def _artifacts(solver, committed):
    paths = ("candidate.py", "result.json") if solver == "openevolve" else ("gen_0/main.py", "programs.sqlite")
    return ((paths[0], SOURCE, ()), (paths[1], committed, ()))


@pytest.fixture(scope="module")
def snapshot():
    # Execute only the reviewed fixed snapshot writer, with upstream solver
    # imports removed by the shared artificial fixture. No candidate is run.
    return _namespace("shinka", _sources("shinka"))["_snapshot"](SOURCE)


@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_real_fixed_commit_format_matches_unevaluated_envelope(snapshot, solver):
    committed = b'{"candidate_path":"candidate.py"}' if solver == "openevolve" else snapshot
    envelope = _envelope(solver)
    material = evidence._completion_source_material(solver, _artifacts(solver, committed), envelope)
    assert material == envelope.materials[0]
    assert not material.external_evidence.get("correct", False)
    assert "score" not in material.external_evidence


@pytest.mark.parametrize("committed", (
    b'{"candidate_path":"other.py"}',
    b'{"candidate_path":"candidate.py","evaluation":{"score":1}}',
    b'{"candidate_path":"candidate.py","candidate_path":"other.py"}',
))
def test_wrapper_path_and_added_evaluation_cannot_authenticate_original_proposal(committed):
    with pytest.raises(ValueError):
        evidence._completion_source_material("openevolve", _artifacts("openevolve", committed), _envelope("openevolve"))


@pytest.mark.parametrize("sql", (
    "UPDATE programs SET correct=1",
    "UPDATE programs SET combined_score=9",
    "UPDATE programs SET code='different source'",
    "UPDATE programs SET parent_id='different parent'",
    "UPDATE programs SET generation=1",
    "UPDATE programs SET id='different-program'",
    "UPDATE programs SET language='bash'",
    "DELETE FROM programs",
    "INSERT INTO programs (id,code,language,parent_id,generation,combined_score,correct) SELECT 'second',code,language,parent_id,generation,combined_score,correct FROM programs",
    "CREATE TABLE unexpected (x)",
    "CREATE VIEW unexpected AS SELECT * FROM programs",
))
def test_database_row_schema_and_evaluation_drift_refuses(snapshot, sql):
    with sqlite3.connect(":memory:") as connection:
        connection.deserialize(snapshot)
        connection.execute(sql)
        connection.commit()
        committed = connection.serialize()
    with pytest.raises(ValueError):
        evidence._completion_source_material("shinka", _artifacts("shinka", committed), _envelope("shinka"))


@pytest.mark.parametrize("raw", (b"", b"not a database", b"x" * (256 * 1024 + 1)), ids=("empty", "invalid", "oversize"))
def test_invalid_or_unbounded_database_refuses(raw):
    with pytest.raises(ValueError):
        evidence._completion_source_material("shinka", _artifacts("shinka", raw), _envelope("shinka"))


@pytest.mark.parametrize("field,value", (("size", 1), ("sha256", "f" * 64), ("path", "other.py"),
                                         ("external_evidence", {"correct": True})))
def test_captured_envelope_must_match_actual_committed_material(snapshot, field, value):
    envelope = _envelope("shinka")
    changed = replace(envelope, materials=(replace(envelope.materials[0], **{field: value}),))
    with pytest.raises(ValueError):
        evidence._completion_source_material("shinka", _artifacts("shinka", snapshot), changed)


def test_sqlite_api_replacement_is_refused_before_foreign_callable(monkeypatch):
    called = []
    monkeypatch.setattr(evidence.sqlite3, "connect", lambda *_args, **_kwargs: called.append(True))
    with pytest.raises(ValueError):
        evidence._sqlite_api_pin()
    assert called == []
