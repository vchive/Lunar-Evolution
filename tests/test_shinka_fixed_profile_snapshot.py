"""New adapter SQLite output reaches the real local read-only Shinka boundary.

All proposal edits are artificial doubles. Actual upstream helpers, model calls,
evaluators and candidates remain unexecuted; SQLite itself is host stdlib fixture
behavior and does not establish a sealed SQLite runtime dependency.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import replace

import pytest
from test_shinka_fixed_profile_entrypoint import (
    CHANGED,
    ORIGINAL,
    canonical,
    install_artificial_diff_doubles,
    reply,
)
from test_shinka_fixed_profile_entrypoint import (
    adapter as adapter,  # noqa: PLC0414 - imported pytest fixture
)
from test_shinka_fixed_profile_entrypoint import (
    wires as wires,  # noqa: PLC0414 - imported pytest fixture
)

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.shinka_handoff import (
    SHINKA_NO_CORRECT_PROGRAMS,
    ShinkaHandoffError,
    _read_shinka_snapshot,
)


def _database(raw):
    connection = sqlite3.connect(":memory:")
    connection.deserialize(raw)
    return connection


def _grants(tmp_path, request, memory):
    (tmp_path / "work").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / ".rsi-input").mkdir()
    for name, value in (("request.json", request), ("memory.json", memory)):
        path = tmp_path / ".rsi-input" / name
        path.write_bytes(canonical(value))
        path.chmod(0o400)


def test_snapshot_is_one_closed_unevaluated_row_with_exact_original_schema(adapter):
    raw = adapter["_snapshot"](CHANGED.encode())
    connection = _database(raw)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(programs)")]
        assert columns == ["id", "code", "language", "parent_id", "generation", "combined_score", "correct"]
        assert connection.execute("SELECT * FROM programs").fetchall() == [
            ("proposal", CHANGED, "python", None, 0, None, 0),
        ]
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    finally:
        connection.close()


def test_artificial_one_request_proposal_returns_existing_sqlite_shape(adapter, wires):
    request, memory = wires
    upstream_order = install_artificial_diff_doubles(adapter)
    requests = []

    def post(request_id, body, *, deadline_ns):
        requests.append((request_id, json.loads(body), deadline_ns))
        return 200, reply()

    candidate, raw = adapter["propose"](
        canonical(request), canonical(memory), deadline_ns=time.monotonic_ns() + 10**9, post=post,
    )
    assert candidate == CHANGED.encode()
    assert len(requests) == 1 and requests[0][0] == "req-1"
    assert [item[0] for item in upstream_order] == ["apply", "validate"]
    connection = _database(raw)
    try:
        assert connection.execute("SELECT correct, combined_score FROM programs").fetchall() == [(0, None)]
    finally:
        connection.close()


def test_fixed_main_writes_source_then_closed_database_last_and_existing_reader_accepts_explicit_id(
    adapter, wires, tmp_path, monkeypatch,
):
    request, memory = wires
    _grants(tmp_path, request, memory)
    install_artificial_diff_doubles(adapter)
    adapter["brokered_producer_post"] = lambda *_args, **_kwargs: (200, reply())
    order = []
    original_write = adapter["_write_at"]

    def observed(directory, name, raw):
        order.append(name)
        return original_write(directory, name, raw)

    adapter["_write_at"] = observed
    monkeypatch.chdir(tmp_path / "work")
    adapter["main"](["--lunar-rsi-input-v1", "e" * 64])
    assert order == ["main.py", "programs.sqlite"]
    output = tmp_path / "output"
    assert (output / "gen_0/main.py").read_bytes() == CHANGED.encode()
    assert {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()} == {
        "gen_0/main.py", "programs.sqlite",
    }
    before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    prepared = _read_shinka_snapshot(output, None, ["proposal"])
    assert len(prepared) == 1
    row, lineage, source, origin = prepared[0]
    assert row.program_id == "proposal" and row.correct is False
    assert row.combined_score is None and row.generation == 0
    assert lineage == () and source == CHANGED.encode() and origin == "gen_0/main.py"
    with pytest.raises(ShinkaHandoffError, match=SHINKA_NO_CORRECT_PROGRAMS):
        _read_shinka_snapshot(output, None, None)
    assert {str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()} == before
    assert not any(path.name.endswith(("-wal", "-shm", "-journal")) for path in tmp_path.rglob("*"))


def test_main_database_write_failure_retains_source_without_completed_snapshot(adapter, wires, tmp_path, monkeypatch):
    request, memory = wires
    _grants(tmp_path, request, memory)
    install_artificial_diff_doubles(adapter)
    adapter["brokered_producer_post"] = lambda *_args, **_kwargs: (200, reply())
    original_write = adapter["_write_at"]

    def interrupted(directory, name, raw):
        if name == "programs.sqlite":
            raise OSError("synthetic output failure")
        return original_write(directory, name, raw)

    adapter["_write_at"] = interrupted
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(OSError):
        adapter["main"](["--lunar-rsi-input-v1", "e" * 64])
    assert (tmp_path / "output/gen_0/main.py").read_bytes() == CHANGED.encode()
    assert not (tmp_path / "output/programs.sqlite").exists()


def test_main_collision_never_overwrites_existing_generation_or_database(adapter, wires, tmp_path, monkeypatch):
    request, memory = wires
    _grants(tmp_path, request, memory)
    install_artificial_diff_doubles(adapter)
    adapter["brokered_producer_post"] = lambda *_args, **_kwargs: (200, reply())
    generation = tmp_path / "output/gen_0"
    generation.mkdir()
    (generation / "main.py").write_bytes(b"caller owned")
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(FileExistsError):
        adapter["main"](["--lunar-rsi-input-v1", "e" * 64])
    assert (generation / "main.py").read_bytes() == b"caller owned"
    assert not (tmp_path / "output/programs.sqlite").exists()


@pytest.mark.parametrize("generation", ["current", "legacy"])
def test_real_current_and_legacy_memory_dtos_use_the_same_guarded_projection(adapter, generation):
    first = MemoryItem(
        memory_id="memory-original", problem_family="integer", trigger="Legacy condition",
        strategy="Legacy action", expected_result="Legacy observation", failure_boundary="Legacy applicability",
        compatible_contracts=("a" * 64,), compatible_solvers=("shinka",), verifier_outcome="pass",
        receipt_sha256="d" * 64, episode_id="episode-source", condition="Current condition",
        action="Current action", observed_result="Current observation", applicability="Current applicability",
    )
    foreign = replace(first, memory_id="foreign", compatible_solvers=("openevolve",))
    snapshot = MemorySnapshot("snapshot-original", None, (first, foreign))
    if generation == "legacy":
        wire = snapshot.to_dict()
        for item in wire["items"]:
            for name in ("condition", "action", "observed_result", "applicability"):
                item.pop(name)
        snapshot = MemorySnapshot.from_dict(wire)
    raw = snapshot.to_bytes()
    request = SolverRequest.build(
        episode_id="episode-original", contract_sha256="a" * 64, evaluator_sha256="b" * 64,
        environment_sha256="c" * 64, memory_snapshot_sha256=hashlib.sha256(raw).hexdigest(),
        solver_id="shinka", solver_settings={"model": "fixture-model", "initial_program": ORIGINAL, "task": "Preserve results."},
        budget={"deadline_unix": 2_000_000_000}, practice_charter={},
    )
    decoded_request, decoded_memory = adapter["_inputs"](canonical(request.to_dict()), raw)
    prefix = "Current" if generation == "current" else "Legacy"
    assert json.loads(adapter["_memory_history"](decoded_request, decoded_memory)) == [{
        "condition": prefix + " condition", "action": prefix + " action",
        "observed_result": prefix + " observation", "applicability": prefix + " applicability",
    }]


def test_late_broker_response_refused_before_any_upstream_diff_execution(adapter, wires):
    from types import SimpleNamespace

    request, memory = wires
    clock = {"now": 1}
    adapter["time"] = SimpleNamespace(monotonic_ns=lambda: clock["now"], time=lambda: 1)

    def late_response(*_args, **_kwargs):
        clock["now"] = 101
        return 200, reply()

    with pytest.raises(adapter["FixedProfileError"], match="deadline_expired"):
        adapter["propose"](canonical(request), canonical(memory), deadline_ns=100, post=late_response)


def test_snapshot_preparation_does_not_extend_original_deadline(adapter, wires):
    from types import SimpleNamespace

    request, memory = wires
    clock = {"now": 1}
    adapter["time"] = SimpleNamespace(monotonic_ns=lambda: clock["now"], time=lambda: 1)
    install_artificial_diff_doubles(adapter)
    original_snapshot = adapter["_snapshot"]

    def late_snapshot(candidate):
        raw = original_snapshot(candidate)
        clock["now"] = 101
        return raw

    adapter["_snapshot"] = late_snapshot
    with pytest.raises(adapter["FixedProfileError"], match="deadline_expired"):
        adapter["propose"](
            canonical(request), canonical(memory), deadline_ns=100,
            post=lambda *_args, **_kwargs: (200, reply()),
        )
