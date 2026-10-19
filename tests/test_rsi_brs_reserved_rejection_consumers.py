"""Private whole-prefix consumer observations; these fixtures confer no authority."""
from __future__ import annotations

import itertools
from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_rsi_brs_reserved_rejection as wires
from test_rsi_brs_rejection_capacity import _file, _table

from lunar_evolution import rsi_brs_rejection_capacity as capacity
from lunar_evolution import rsi_brs_rejection_provenance as provenance
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
)
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_rejection import MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES


def _fixture(monkeypatch, outcomes):
    # Supply unique physical observations, preserving the genuine distinct v1/v2
    # descriptors and full original prefix produced by the shared pure fixture.
    sequence = itertools.count(20_000)
    original_pin, original_p = wires._pin, wires._p
    with monkeypatch.context() as patch:
        patch.setattr(wires, "_pin", lambda name, raw=b"", inode=None:
                      original_pin(name, raw, inode=next(sequence) if inode is None else inode))

        def p():
            value = original_p()
            value["file_pin"]["inode"] = next(sequence)
            return value

        patch.setattr(wires, "_p", p)
        before, c1, c2, options = wires._fixture(outcomes)
    rejected, published = {}, {}
    for entry in c1["batches"]:
        journal = entry["journal_id"]
        if entry["state"] == "rejected":
            rejected[journal] = {candidate: _table([
                _file(f"evolution/native/{journal}/{candidate}/output", next(sequence), 31),
                _file(f"evolution/native/{journal}/{candidate}/empty", next(sequence), 0),
            ]) for candidate in entry["rejected"]["candidate_ids"]}
        else:
            item = _file(f"evolution/native/{journal}/published-receipt", next(sequence), 71)
            published[journal] = {item.pop("path"): {**item, "mode": 0o400, "nlink": 1}}
    return before, c1, c2, options, rejected, published


def _count(state, wire, rejected, published, options):
    return capacity._retained_reserved_brs_c1_evidence_bytes(state, wire, rejected, published, **options)


def _expected(wire, rejected, published):
    total = 0
    for entry in wire["batches"]:
        total += sum(pin["size"] for pin in entry["snapshots"].values())
        total += sum(entry[kind + "_file_pin"]["size"] for kind in ("before", "staged", "terminal", "rejected")
                     if kind + "_file_pin" in entry)
        total += sum(pin["size"] for pin in entry["evidence_pins"].values())
        if entry["state"] == "rejected":
            total += sum(item["size"] for table in rejected[entry["journal_id"]].values()
                         for item in table["entries"] if item["kind"] == "file")
            if entry.get("rejection_provenance") is not None:
                total += entry["rejection_provenance"]["file_pin"]["size"]
        else:
            total += sum(item["size"] for item in published[entry["journal_id"]].values())
    return total


@pytest.mark.parametrize("outcomes", [(), ("all_rejected",), ("published",),
    ("all_rejected", "all_rejected"), ("published", "all_rejected"),
    ("all_rejected", "published", "all_rejected"), ("published", "all_rejected", "published")])
def test_complete_mixed_prefix_capacity_preserves_original_wire_and_native_modes(monkeypatch, outcomes):
    _before, c1, c2, options, rejected, published = _fixture(monkeypatch, outcomes)
    saved = deepcopy((c1, c2, rejected, published))
    state = {"producer_publication_lineage": c1}
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: pytest.fail("pure counter read disk"))
    assert _count(state, c1, rejected, published, options) == _expected(c1, rejected, published)
    assert capacity._retained_reserved_brs_c2_evidence_bytes(state, c2, rejected, published, **options) == \
        _expected(c2, rejected, published)
    assert (c1, c2, rejected, published) == saved
    if outcomes:
        with pytest.raises(RSILearningError):
            capacity.retained_brs_c1_evidence_bytes(state, c1, rejected[c1["batches"][-1]["journal_id"]])


@pytest.mark.parametrize("fault", ["missing_rejected", "missing_published", "extra_journal", "journal_order",
    "candidate_order", "old_head", "old_batch", "old_index", "missing_original", "prefix_hook"])
def test_reserved_capacity_requires_complete_original_domain_and_never_calls_foreign_hooks(monkeypatch, fault):
    _before, c1, _c2, options, rejected, published = _fixture(monkeypatch, ("published", "all_rejected"))
    called = []
    if fault == "missing_rejected":
        rejected.pop(next(iter(rejected)))
    elif fault == "missing_published":
        published.clear()
    elif fault == "extra_journal":
        published["foreign"] = {}
    elif fault == "journal_order":
        rejected = dict(reversed(tuple(rejected.items())))
    elif fault == "candidate_order":
        rejected[c1["batches"][-1]["journal_id"]]["foreign"] = _table([_file("evolution/foreign", 5555)])
    elif fault == "old_head":
        c1["head"] = None
    elif fault == "old_batch":
        c1["batches"][0]["terminal_file_pin"]["inode"] += 1
    elif fault == "old_index":
        c1["rejections"] = c1["rejections"][-1:]
    elif fault == "missing_original":
        options["original_lineage_bytes"] = None
    else:
        class Hook:
            def __eq__(self, other):
                called.append(other)
                return True
        object.__setattr__(options["prefix"], "batch_bytes", (Hook(),))
    with pytest.raises(RSILearningError):
        _count({}, c1, rejected, published, options)
    assert called == []


@pytest.mark.parametrize("fault", ["published_alias", "old_rejection_alias", "shared_path_drift"])
def test_native_material_alias_or_refresh_is_refused_across_prefix_outcomes(monkeypatch, fault):
    _before, c1, _c2, options, rejected, published = _fixture(monkeypatch, ("published", "all_rejected"))
    active = rejected[c1["batches"][-1]["journal_id"]]
    candidate = next(iter(active))
    entries = active[candidate]["entries"]
    original = next(item for item in entries if item["size"] == 31)
    if fault == "published_alias":
        record = next(iter(next(iter(published.values())).values()))
        original["device"], original["inode"] = record["device"], record["inode"]
    elif fault == "old_rejection_alias":
        record = next(item for item in next(iter(next(iter(rejected.values())).values()))["entries"] if item["size"] == 31)
        original["device"], original["inode"] = record["device"], record["inode"]
    else:
        journal = c1["batches"][-1]["journal_id"]
        pin = c1["batches"][-1]["evidence_pins"]["journal.prepared.json"]
        original.update(path=f"evolution/producer-batches/{journal}/journal.prepared.json",
                        device=pin["device"], inode=pin["inode"], size=pin["size"] + 1)
    active[candidate] = _table(entries)
    with pytest.raises(RSILearningError, match="material_alias|material_drift"):
        _count({}, c1, rejected, published, options)


@pytest.mark.parametrize("fault", ["record_type", "missing_identity", "foreign_field", "bool_mode", "bad_path",
                                    "bad_size", "callback"])
def test_published_native_records_keep_exact_plain_shape_and_native_file_domain(monkeypatch, fault):
    _before, c1, _c2, options, rejected, published = _fixture(monkeypatch, ("published",))
    table = next(iter(published.values()))
    path, record = next(iter(table.items()))
    touched = []
    if fault == "record_type":
        table[path] = []
    elif fault == "missing_identity":
        record.pop("inode")
    elif fault == "foreign_field":
        record["unexpected"] = 1
    elif fault == "bool_mode":
        record["mode"] = True
    elif fault == "bad_path":
        table["../outside"] = table.pop(path)
    elif fault == "bad_size":
        record["size"] = -1
    else:
        class Hook:
            def __eq__(self, other):
                touched.append(other)
                return True
        record["inode"] = Hook()
    with pytest.raises((RSILearningError, ValueError)):
        _count({}, c1, rejected, published, options)
    assert touched == []


def test_history_and_future_provenance_reservation_share_the_exact_aggregate_bound(monkeypatch):
    _before, c1, _c2, options, rejected, published = _fixture(monkeypatch, ("published", "all_rejected"))
    candidate_tables = rejected[c1["batches"][-1]["journal_id"]]
    candidate = next(iter(candidate_tables))
    entries = candidate_tables[candidate]["entries"]
    remaining = (MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES
                 - _expected(c1, rejected, published))
    index = 0
    while remaining:
        size = min(remaining, MAX_LINEAGE_SNAPSHOT_BYTES)
        entries.append(_file(f"evolution/large/{index}", 70000 + index, size))
        remaining -= size
        index += 1
    candidate_tables[candidate] = _table(entries)
    assert _count({}, c1, rejected, published, options) == \
        MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES
    entries[-1]["size"] += 1
    candidate_tables[candidate] = _table(entries)
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        _count({}, c1, rejected, published, options)


@pytest.mark.parametrize("outcomes", [("all_rejected",), ("published", "all_rejected"),
                                      ("published", "all_rejected", "published")])
def test_provenance_capture_and_c2_wire_use_the_actual_ordinal_without_truncating_history(monkeypatch, outcomes):
    _before, c1, c2, options, _rejected, _published = _fixture(monkeypatch, outcomes)
    state = {"producer_publication_lineage": c1}
    raw = canonical_json(state)
    owner = SimpleNamespace(_ordinal=len(outcomes), _reserved_prefix=options["prefix"],
        _reserved_lineage_bytes=options["original_lineage_bytes"],
        _reserved_original_checkpoint=("a" * 64, b"{}"), _reserved_capture_bytes=options["prefix"].canonical_bytes,
        _plan=SimpleNamespace(plan_sha256=options["native_plan_sha256"]),
        _controller=SimpleNamespace(_python_admission_flow_payload=canonical_json),
        _rejection_c1_capture=("b" * 64, raw), _phase="rejected", _head="b" * 64,
        _payload=raw, _state=state, _rejection_provenance_c2_capture=None,
        _rejection_file_pin=LineageSnapshotPin.from_dict(c1["batches"][-1]["rejected_file_pin"]),
        _policy_bytes=canonical_json({"rejection_provenance_schema": "lunar-rsi-brs-rejection-provenance-c2-v1"}))
    observed_state, observed_wire = provenance._capture(owner)
    reference = c2["batches"][-1]["rejection_provenance"]
    from lunar_evolution.rsi_native_rejection import NativeRSIRejectionFilePin
    actual = provenance._wire(owner, reference["provenance_sha256"],
                              NativeRSIRejectionFilePin.from_dict(reference["file_pin"]))
    assert observed_state == state and observed_wire == c1
    assert actual == c2 and actual["batches"][:-1] == c1["batches"][:-1]
    assert canonical_json(state) == raw


@pytest.fixture
def original_native_rejection(monkeypatch, request):
    """Use the existing sealed, inert original-owner native C1/P/C2 fixture."""
    import test_rsi_brs_rejection_c1 as c1
    import test_rsi_brs_rejection_provenance as native

    # The sealed-launch fixture is a regular pytest fixture dependency, requested
    # explicitly here so the pure comparison tests do not acquire native owners.
    request.getfixturevalue("sealed_launch")
    request.getfixturevalue("inert_only")
    return c1, native


# Expose only the existing provider-free fixture functions to pytest.
from test_rsi_brs_rejection_c1 import inert_only  # noqa: F401
from test_rsi_brs_rejection_provenance import sealed_launch  # noqa: F401


@pytest.mark.parametrize("fault", [None, "native-inode", "metadata-inode"])
def test_physical_inventory_reads_real_native_p_and_refuses_equal_byte_replacements(
    tmp_path, monkeypatch, original_native_rejection, fault,
):
    from lunar_evolution import rsi_brs_rejection_owner as reader
    from lunar_evolution.rsi_native_rejection import read_native_rsi_rejection_provenance

    c1_fixture, _native = original_native_rejection
    with c1_fixture._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        value.owner.retain_rejection_provenance()
        wire = value.wave.state["producer_publication_lineage"]
        entry = wire["batches"][0]
        # This is a physical-reader fixture only: it deliberately does not claim
        # controller settlement or construct a reserved owner/selection permit.
        batch = {"episode_id": entry["episode_id"], "native_plan_sha256": entry["native_plan_sha256"],
                 "snapshots": deepcopy(entry["snapshots"]), "outcome": "all_rejected"}
        observed, by_episode = reader.read_reserved_brs_material_inventory(value.workspace, wire, prefix_batches=(batch,))
        records = dict(observed)
        evidence = read_native_rsi_rejection_provenance(value.batch,
            expected_file_pin=value.owner._rejection_provenance_file_pin)
        provenance_path = value.batch.relative_to(value.workspace).as_posix() + "/native-rsi.rejection-provenance.json"
        assert records[provenance_path]["mode"] == 0o400
        assert sum(record["size"] for record in records.values() if record["kind"] == "file") == \
            evidence.lineage.retained_bytes + records[provenance_path]["size"]
        assert by_episode[entry["episode_id"]] == tuple(sorted(
            {record["sha256"] for record in records.values() if record["kind"] == "file"}))
        if fault is None:
            return
        if fault == "metadata-inode":
            path = value.batch / "lineage" / "rejected.json"
        else:
            path = next(value.workspace / relative for relative, record in observed
                        if record["kind"] == "file" and "/bundle-attempts/" in relative)
        raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
        replacement = path.with_name(path.name + ".replacement")
        replacement.write_bytes(raw)
        replacement.chmod(mode)
        replacement.replace(path)
        with pytest.raises(ValueError):
            reader.read_reserved_brs_material_inventory(value.workspace, wire, prefix_batches=(batch,))


def test_provenance_capture_rejects_ordinal_hooks_before_index_or_arithmetic():
    touched = []

    class Hook:
        def __index__(self):
            touched.append("index")
            return 0

        def __add__(self, other):
            touched.append("add")
            return other

    with pytest.raises(RSILearningError, match="original_ordinal_invalid"):
        provenance._capture(SimpleNamespace(_ordinal=Hook()))
    assert touched == []


def test_reserved_rejection_reader_is_readonly_and_compares_the_entire_original_c2(
    tmp_path, monkeypatch, original_native_rejection,
):
    from lunar_evolution.rsi_brs_lineage_prefix import validate_brs_reserved_prefix
    from lunar_evolution.rsi_gateway import SolverRequest

    c1_fixture, _native = original_native_rejection
    with c1_fixture._waiting(tmp_path, monkeypatch) as value:
        original_head = value.owner._head
        state = value.wave.state
        episodes = tuple(state["intents"])
        requests = tuple(SolverRequest.from_dict(state["intents"][key]["request"]) for key in episodes)
        prefix = validate_brs_reserved_prefix(run_id=value.binding.run_id, wave=0, episode_ids=episodes,
            request_sha256s=tuple(request.digest() for request in requests),
            root_snapshot_sha256=value.request.memory_snapshot_sha256,
            base_checkpoint_sha256=original_head, batches=())
        value.owner.retain_rejected_terminal(value.terminal)
        value.owner.retain_rejection_provenance()
        wire = deepcopy(state["producer_publication_lineage"])
        roots = value.ledger.controller_checkpoint_history(value.binding.run_id)
        binding = {"run_id": value.binding.run_id, "episode_id": value.episode_id,
            "selected_request_sha256": value.request.digest(), "native_plan_sha256": value.plan.plan_sha256,
            "native_claim_sha256": value.owner._claim.claim_sha256}
        publication = {"lineage": wire, "journal": value.terminal.to_dict(), "manifest": None}
        before = c1_fixture.owner_fixture._capture(value)
        # This reuses genuine original first-batch material as a reader fixture.
        # It constructs neither a reserved owner nor a dispatch/selection grant.
        assert provenance.verify_reserved_rejected_publication(value.workspace, publication, binding, roots,
            ledger=value.ledger, ordinal=0, prefix=prefix, original_lineage_bytes=None) == value.terminal.digest()
        c1_fixture.owner_fixture._unchanged(value, before)
        changed = deepcopy(publication)
        changed["lineage"]["foreign_metadata"] = "must-not-be-ignored"
        with pytest.raises(RSILearningError, match="historical_publication_binding_drift"):
            provenance.verify_reserved_rejected_publication(value.workspace, changed, binding, roots,
                ledger=value.ledger, ordinal=0, prefix=prefix, original_lineage_bytes=None)
        c1_fixture.owner_fixture._unchanged(value, before)
        c1_fixture._quiet(value)


def test_reserved_rejection_reader_refuses_foreign_ledger_before_a_context_hook():
    touched = []

    class Foreign:
        def read_only_observations(self):
            touched.append("context")
            raise AssertionError("foreign context executed")

    with pytest.raises(RSILearningError, match="historical_ledger_invalid"):
        provenance.verify_reserved_rejected_publication(None, {}, {}, [], ledger=Foreign(), ordinal=0,
                                                        prefix=None, original_lineage_bytes=None)
    assert touched == []


def test_reserved_rejection_material_reader_refuses_prefix_hooks_before_attribute_access(tmp_path):
    from lunar_evolution.rsi_store import RSILedger

    touched = []

    class Foreign:
        @property
        def batch_bytes(self):
            touched.append("prefix")
            raise AssertionError("foreign prefix executed")

    with pytest.raises(RSILearningError, match="historical_ordinal_drift"):
        provenance._verify_reserved_rejected_materials(tmp_path, {}, ledger=RSILedger(tmp_path / "ledger.sqlite3"),
            roots=[], ordinal=0, prefix=Foreign(), original_lineage_bytes=None)
    assert touched == []
