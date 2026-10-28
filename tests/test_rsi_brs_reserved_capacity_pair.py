"""Historical C1/C2 counting shares only its adjacent pure material walk."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
from test_rsi_brs_rejection_capacity import _file, _table
from test_rsi_brs_reserved_rejection_consumers import _expected, _fixture

from lunar_evolution import rsi_brs_rejection_capacity as capacity
from lunar_evolution import rsi_brs_reserved_rejection as rejection
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
)
from lunar_evolution.rsi_learning import RSILearningError


def _case(monkeypatch, outcomes=("published", "all_rejected")):
    _before, c1, c2, options, rejected, published = _fixture(monkeypatch, outcomes)
    return {"producer_publication_lineage": c1}, c1, c2, options, rejected, published


def _pair(case):
    state, c1, c2, options, rejected, published = case
    return capacity._retained_reserved_brs_c1_c2_evidence_bytes(
        state, c1, c2, rejected, published, **options,
    )


def _separate(case):
    state, c1, c2, options, rejected, published = case
    return (
        capacity._retained_reserved_brs_c1_evidence_bytes(state, c1, rejected, published, **options),
        capacity._retained_reserved_brs_c2_evidence_bytes(state, c2, rejected, published, **options),
    )


def _profile(call):
    # Count real original computations without substituting any parser/kernel.
    functions = (capacity._retained_reserved_brs_materials, capacity._validate_retained_evidence,
                 capacity.retained_ready_capsule_bytes, rejection._prefix)
    codes = {function.__code__: function.__name__ for function in functions}
    counts = Counter()

    def observe(frame, event, _arg):
        if event == "call" and frame.f_code in codes:
            counts[codes[frame.f_code]] += 1

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        result = call()
    finally:
        sys.setprofile(previous)
    return result, counts


@pytest.mark.parametrize("outcomes", [(), ("all_rejected",), ("published",),
    ("published", "all_rejected"), ("all_rejected", "published", "all_rejected"),
    ("all_rejected", "published") * 3 + ("published",)])
def test_historical_pair_keeps_complete_mixed_domain_and_halves_material_walk(monkeypatch, outcomes):
    case = _case(monkeypatch, outcomes)
    state, c1, c2, _options, rejected, published = case
    saved = deepcopy((state, c1, c2, rejected, published))
    expected = (_expected(c1, rejected, published), _expected(c2, rejected, published))
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: pytest.fail("pure counter read disk"))
    separate, old = _profile(lambda: _separate(case))
    together, new = _profile(lambda: _pair(case))
    assert separate == together == expected
    assert old["_retained_reserved_brs_materials"] == 2
    assert new["_retained_reserved_brs_materials"] == 1
    assert old["_validate_retained_evidence"] == 2 * new["_validate_retained_evidence"]
    assert old["retained_ready_capsule_bytes"] == 2
    assert new["retained_ready_capsule_bytes"] == 1
    # C2 retains its complete independent transition/prefix observation.
    assert old["_prefix"] == 3 and new["_prefix"] == 2
    assert (state, c1, c2, rejected, published) == saved


@pytest.mark.parametrize("fault", ["c2_delta", "old_prefix", "active_p_alias", "published_alias",
    "table_drift", "missing_table", "foreign_pin", "prefix_noncanonical", "oversized_c2"])
def test_pair_keeps_standalone_refusal_for_drift_alias_shape_and_bounds(monkeypatch, fault):
    case = _case(monkeypatch)
    _state, c1, c2, options, rejected, published = case
    if fault == "c2_delta":
        c2["batches"][-1]["episode_id"] += "-foreign"
    elif fault == "old_prefix":
        c2["batches"][0]["terminal_file_pin"]["inode"] += 1
    elif fault == "active_p_alias":
        pin = c2["batches"][-1]["rejection_provenance"]["file_pin"]
        held = c1["batches"][-1]["rejected_file_pin"]
        pin["device"], pin["inode"] = held["device"], held["inode"]
    elif fault == "published_alias":
        old = next(iter(next(iter(published.values())).values()))
        table = next(iter(rejected[c1["batches"][-1]["journal_id"]].values()))
        table["entries"][0].update(device=old["device"], inode=old["inode"])
        table.update(_table(table["entries"]))
    elif fault == "table_drift":
        table = next(iter(rejected[c1["batches"][-1]["journal_id"]].values()))
        table["entries"][0]["size"] += 1
    elif fault == "missing_table":
        published.clear()
    elif fault == "foreign_pin":
        c2["batches"][-1]["rejection_provenance"]["file_pin"]["inode"] = True
    elif fault == "prefix_noncanonical":
        prefix = options["prefix"]
        object.__setattr__(prefix, "canonical_bytes", prefix.canonical_bytes + b"\n")
    else:
        c2["batches"][-1]["rejection_provenance"]["provenance_sha256"] = "x" * (128 * 1024 + 1)
    with pytest.raises((RSILearningError, ValueError)) as original:
        _separate(case)
    with pytest.raises(type(original.value)) as shared:
        _pair(case)
    assert str(shared.value) == str(original.value)


def test_pair_reobserves_inputs_on_each_call_and_rejects_foreign_callbacks(monkeypatch):
    case = _case(monkeypatch)
    _pair(case)
    _state, _c1, c2, _options, _rejected, _published = case
    calls = []

    class ForeignInt(int):
        def __eq__(self, other):
            calls.append(other)
            pytest.fail("capacity compared a foreign integer")

    pin = c2["batches"][-1]["rejection_provenance"]["file_pin"]
    original = pin["inode"]
    pin["inode"] = ForeignInt(original)
    with pytest.raises(RSILearningError):
        _pair(case)
    assert calls == []
    pin["inode"] = original
    assert _pair(case) == _separate(case)


def test_pair_keeps_future_p_reservation_and_exact_aggregate_cap(monkeypatch):
    case = _case(monkeypatch)
    _state, c1, c2, _options, rejected, published = case
    reference = c2["batches"][-1]["rejection_provenance"]["file_pin"]
    reference["size"] = capacity.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES
    active = rejected[c1["batches"][-1]["journal_id"]]
    candidate = next(iter(active))
    entries = active[candidate]["entries"]
    remaining = (MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
                 - capacity.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES - _expected(c1, rejected, published))
    index = 0
    while remaining:
        size = min(remaining, MAX_LINEAGE_SNAPSHOT_BYTES)
        entries.append(_file(f"evolution/pair-large/{index}", 90000 + index, size))
        remaining -= size
        index += 1
    active[candidate] = _table(entries)
    assert _pair(case) == _separate(case) == (
        MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - capacity.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES,
        MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    )
    entries[-1]["size"] += 1
    active[candidate] = _table(entries)
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        _pair(case)


def test_pair_binds_the_accumulated_wire_to_the_captured_c1_state(monkeypatch):
    case = _case(monkeypatch)
    state, _c1, _c2, _options, _rejected, _published = case
    state["producer_publication_lineage"] = deepcopy(state["producer_publication_lineage"])
    state["producer_publication_lineage"]["head"] = None
    with pytest.raises(RSILearningError, match="^rsi_brs_rejection_capacity_captured_c1_drift$"):
        _pair(case)


@pytest.mark.parametrize("fault", ["replace", "code", "kwdefault"])
def test_pair_helper_is_part_of_the_original_reserved_fingerprint(tmp_path, fault):
    # The original graph is intentionally a process-lifetime capture, including
    # aliases substituted by the separate inert process fixture. Exercise its
    # mutation gate in a fresh interpreter; never reset its original closure,
    # inner latch, outer capture or a preceding test's graph in this worker.
    source = Path(__file__).resolve().parents[1] / "src"
    expected = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(source.rglob("*.py"))}
    graph = sys.modules.get("lunar_evolution.rsi_brs_reserved_policy")
    owner = sys.modules.get("lunar_evolution.rsi_brs_publication_lineage")
    held_project = getattr(graph, "_PROJECT", None)
    held_capture = getattr(owner, "_ORIGINAL_RESERVED_PROJECT_CAPTURE", None)
    script = r'''
import hashlib
import json
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve(strict=True)
expected = json.loads(sys.argv[2])
fault = sys.argv[3]
assert fault in {"replace", "code", "kwdefault"}
sys.path.insert(0, str(source))

def no_execution(event, args):
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "socket.connect"}:
        raise AssertionError("policy-only child attempted execution or network: " + event)

sys.addaudithook(no_execution)

from lunar_evolution import rsi_brs_publication_lineage as owner
from lunar_evolution import rsi_brs_rejection_capacity as capacity
from lunar_evolution.rsi_learning import RSILearningError

def check_sources():
    count = 0
    for name, module in tuple(sys.modules.items()):
        if name != "lunar_evolution" and not name.startswith("lunar_evolution."):
            continue
        path = Path(module.__file__).resolve(strict=True)
        relative = path.relative_to(source).as_posix()
        assert relative in expected and hashlib.sha256(path.read_bytes()).hexdigest() == expected[relative]
        count += 1
    assert count > 0
    return count

check_sources()
original = owner._policy()
assert original["production_admission"] is False and original["online_publication"] is False
helper = capacity._retained_reserved_brs_c1_c2_evidence_bytes

def foreign(*args, **kwargs):
    raise AssertionError("policy executed a replacement capacity helper")

if fault == "replace":
    capacity._retained_reserved_brs_c1_c2_evidence_bytes = foreign
elif fault == "code":
    helper.__code__ = helper.__code__.replace(co_consts=(*helper.__code__.co_consts, "foreign"))
else:
    helper.__kwdefaults__ = {"prefix": None}
try:
    owner._policy()
except RSILearningError as exc:
    assert str(exc) == "rsi_brs_reserved_policy_drift"
else:
    raise AssertionError("original policy accepted a changed capacity helper")
count = check_sources()
print(json.dumps({"fault": fault, "original_policy_drift": True, "source_modules_checked": count}))
'''
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source), json.dumps(expected), fault],
        cwd=tmp_path, env={"PATH": os.defpath, "LC_ALL": "C"},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["fault"] == fault and observed["original_policy_drift"] is True
    assert observed["source_modules_checked"] > 0
    assert sys.modules.get("lunar_evolution.rsi_brs_reserved_policy") is graph
    assert sys.modules.get("lunar_evolution.rsi_brs_publication_lineage") is owner
    assert getattr(graph, "_PROJECT", None) is held_project
    assert getattr(owner, "_ORIGINAL_RESERVED_PROJECT_CAPTURE", None) is held_capture
