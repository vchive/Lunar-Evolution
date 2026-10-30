"""One ordered pure walk must match independently encoded original prefixes."""
from __future__ import annotations

from copy import deepcopy

import pytest
from test_rsi_brs_lineage_prefix import _extra, _sha, _wave

from lunar_evolution import rsi_brs_lineage_prefix as prefix_module
from lunar_evolution.rsi_learning import RSILearningError


def _separate_prefixes(domain, batches):
    return tuple(prefix_module.validate_brs_reserved_prefix(**domain, batches=batches[:ordinal])
                 for ordinal in range(len(batches) + 1))


def _result(call):
    try:
        return "return", call()
    except (RSILearningError, TypeError, ValueError, RecursionError) as error:
        return type(error), str(error)


@pytest.mark.parametrize("count", range(1, 9))
@pytest.mark.parametrize("pattern", ("published", "all_rejected", "mixed"))
def test_all_original_prefix_bytes_match_one_ordered_walk_and_detach_inputs(count, pattern):
    outcomes = tuple(("published" if ordinal % 2 == 0 else "all_rejected")
                     if pattern == "mixed" else pattern for ordinal in range(count))
    domain, batches = _wave(outcomes)
    saved = deepcopy(batches)
    root_identities = tuple(id(batch["root_checkpoint"][1]) for batch in batches)
    expected = _separate_prefixes(domain, batches)
    actual = prefix_module._validate_brs_reserved_prefixes(**domain, batches=batches)
    assert actual == expected
    assert len(actual) == count + 1
    assert all(actual[ordinal].batch_bytes == expected[ordinal].batch_bytes
               for ordinal in range(count + 1))
    assert batches == saved
    assert tuple(id(batch["root_checkpoint"][1]) for batch in batches) == root_identities
    retained = tuple(item.canonical_bytes for item in actual)
    batches[0]["root_checkpoint"][1]["phase"] = "foreign"
    assert tuple(item.canonical_bytes for item in actual) == retained
    assert _result(lambda: prefix_module._validate_brs_reserved_prefixes(**domain, batches=batches)) == \
        _result(lambda: _separate_prefixes(domain, batches))


def test_empty_prefix_still_encodes_original_whole_domain():
    domain, _batches = _wave(("published",) * 8)
    assert prefix_module._validate_brs_reserved_prefixes(**domain, batches=()) == \
        (prefix_module.validate_brs_reserved_prefix(**domain, batches=()),)


@pytest.mark.parametrize("fault", (
    "bool_ordinal", "entry_head", "root_head", "claim", "root_execution", "physical_alias",
    "missing_original", "root_depth", "descriptor_capacity", "prefix_capacity_before_later_fault",
))
def test_ordered_walk_preserves_first_refusal_and_capacity_before_later_batch(fault):
    domain, batches = _wave(("published", "all_rejected", "published"))
    if fault == "bool_ordinal":
        batches[1]["ordinal"] = True
    elif fault == "entry_head":
        batches[1]["entry_checkpoint_sha256"] = _sha("foreign")
    elif fault == "root_head":
        batches[1]["root_checkpoint"] = (batches[0]["root_checkpoint"][0], batches[1]["root_checkpoint"][1])
    elif fault == "claim":
        batches[1]["claim"]["status"] = "started"
    elif fault == "root_execution":
        batches[1]["root_checkpoint"][1]["executions"][domain["episode_ids"][0]]["result"]["trace_digest"] = _sha("foreign")
    elif fault == "physical_alias":
        old = batches[0]["materials"][0]
        batches[1]["materials"] += ({"relative_path": "retained/" + old["file_pin"]["name"],
                                    "file_pin": deepcopy(old["file_pin"])},)
    elif fault == "missing_original":
        batches[1]["materials"] = batches[1]["materials"][1:]
    elif fault == "root_depth":
        nested = None
        for _ in range(34):
            nested = {"nested": nested}
        batches[0]["root_checkpoint"][1]["extra"] = nested
    elif fault == "descriptor_capacity":
        batches[0]["before"]["descriptor"]["extra"] = "x" * (32 * 1024)
    else:
        batches[0]["materials"] = _extra(batches[0], [1] * 500)
        batches[1]["ordinal"] = True
    expected = _result(lambda: _separate_prefixes(domain, batches))
    assert expected[0] != "return"
    assert _result(lambda: prefix_module._validate_brs_reserved_prefixes(**domain, batches=batches)) == expected
    if fault == "prefix_capacity_before_later_fault":
        assert "capacity_exhausted" in expected[1]


def test_each_heavy_batch_normalization_occurs_once_while_every_prefix_is_encoded(monkeypatch):
    domain, batches = _wave(("published", "all_rejected") * 4)
    expected = _separate_prefixes(domain, batches)
    executions, roots, encodings = [], [], []
    original_execution, original_root = prefix_module._execution, prefix_module._root
    original_projection = prefix_module._project_brs_reserved_prefix

    def execution(raw, **kwargs):
        executions.append(kwargs["ordinal"])
        return original_execution(raw, **kwargs)

    def root(raw, **kwargs):
        roots.append(kwargs["ordinal"])
        return original_root(raw, **kwargs)

    def projection(*args):
        encodings.append(len(args[1]))
        return original_projection(*args)

    monkeypatch.setattr(prefix_module, "_execution", execution)
    monkeypatch.setattr(prefix_module, "_root", root)
    monkeypatch.setattr(prefix_module, "_project_brs_reserved_prefix", projection)
    assert prefix_module._validate_brs_reserved_prefixes(**domain, batches=batches) == expected
    assert executions == roots == list(range(8))
    assert encodings == list(range(9))


def test_walk_has_no_io_and_foreign_batch_cannot_invoke_mapping_hooks(monkeypatch):
    import builtins
    import sqlite3

    domain, batches = _wave(("all_rejected",))

    def forbidden(*_args, **_kwargs):
        pytest.fail("ordered pure prefix walk attempted IO or a foreign hook")

    class Foreign(dict):
        items = values = __iter__ = forbidden

    with pytest.raises(RSILearningError, match="batch_invalid"):
        prefix_module._validate_brs_reserved_prefixes(**domain, batches=(Foreign(batches[0]),))
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert len(prefix_module._validate_brs_reserved_prefixes(**domain, batches=batches)) == 2
