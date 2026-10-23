"""Content-based extraction reuse never caches live configuration or authority."""

from __future__ import annotations

import importlib.util
import inspect
import linecache
import os
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import ModuleType

import pytest

from lunar_evolution import rsi_identity as identity


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    identity._SOURCE_CACHE.clear()
    yield
    identity._SOURCE_CACHE.clear()


def _module(tmp_path, monkeypatch, source="class Component:\n    value = 1\n"):
    path = tmp_path / "source_component.py"
    path.write_text(source)
    name = "source_cache_fixture_" + tmp_path.name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module, path


def _count_extractions(monkeypatch):
    calls = []
    original = identity._extract_fresh_source

    def extract(*args):
        calls.append(args[1])
        return original(*args)

    monkeypatch.setattr(identity, "_extract_fresh_source", extract)
    return calls


def _code(value):
    return identity.component_identity(value, config={}).code


def _assert_cache_accounting():
    with identity._SOURCE_CACHE_LOCK:
        cache = identity._SOURCE_CACHE
        references = {}
        for key in cache:
            raw = key[1]
            assert type(raw) is bytes
            canonical, count = cache._raw_sources[raw]
            assert raw is canonical
            assert count > 0
            references[raw] = references.get(raw, 0) + 1
        assert {raw: value[1] for raw, value in cache._raw_sources.items()} == references
        assert cache.retained_bytes == (
            sum(len(raw) for raw in references)
            + sum(len(value[0].encode("utf-8")) for value in cache.values())
        )
        assert cache.retained_bytes <= identity._MAX_SOURCE_CACHE_BYTES
        assert len(cache) <= identity._MAX_SOURCE_CACHE_ENTRIES


def test_repeated_content_reuses_extraction_without_caching_final_identity(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch)
    calls = _count_extractions(monkeypatch)
    assert identity.component_fingerprint(module.Component, config={"setting": 1}) != (
        identity.component_fingerprint(module.Component, config={"setting": 2})
    )
    assert len(calls) == 1 and len(identity._SOURCE_CACHE) == 1


def test_hundreds_of_small_components_reuse_extraction_but_still_read_fresh_twice(
    tmp_path, monkeypatch,
):
    count = 613
    module, path = _module(tmp_path, monkeypatch, "".join(
        f"def component_{index}():\n    return {index}\n" for index in range(count)
    ))
    targets = [getattr(module, f"component_{index}") for index in range(count)]
    extractions = _count_extractions(monkeypatch)
    original = identity._fresh_source_bytes
    reads = 0

    def fresh(filename):
        nonlocal reads
        assert filename == str(path)
        reads += 1
        return original(filename)

    monkeypatch.setattr(identity, "_fresh_source_bytes", fresh)
    baseline = [identity.component_fingerprint(target) for target in targets]
    assert [identity.component_fingerprint(target) for target in targets] == baseline
    assert len(extractions) == len(identity._SOURCE_CACHE) == count
    assert reads == 4 * count


def test_utf8_byte_budget_evicts_lru_without_changing_fingerprints(tmp_path, monkeypatch):
    module, path = _module(tmp_path, monkeypatch, "".join(
        f"def {name}():\n    return '界'\n" for name in ("alpha", "bravo", "cello")
    ))
    targets = (module.alpha, module.bravo, module.cello)
    expected = {target: identity.component_fingerprint(target) for target in targets}
    source_bytes = len(inspect.getsource(module.alpha).encode("utf-8"))
    raw_bytes = len(path.read_bytes())
    budget = raw_bytes + 2 * source_bytes
    monkeypatch.setattr(identity, "_MAX_SOURCE_CACHE_BYTES", budget)
    identity._SOURCE_CACHE.clear()
    calls = _count_extractions(monkeypatch)

    for target in (module.alpha, module.bravo, module.alpha, module.bravo, module.alpha):
        assert identity.component_fingerprint(target) == expected[target]
    assert len(calls) == 2
    assert identity.component_fingerprint(module.cello) == expected[module.cello]
    assert identity.component_fingerprint(module.alpha) == expected[module.alpha]
    assert len(calls) == 3
    assert identity.component_fingerprint(module.bravo) == expected[module.bravo]
    assert len(calls) == 4
    assert raw_bytes + sum(len(value[0].encode("utf-8")) for value in identity._SOURCE_CACHE.values()) == (
        identity._SOURCE_CACHE.retained_bytes
    ) == budget
    _assert_cache_accounting()

    identity._SOURCE_CACHE.clear()
    for target in (module.alpha, module.bravo, module.alpha, module.bravo):
        assert identity.component_fingerprint(target) == expected[target]
    assert len(calls) == 6 and identity._SOURCE_CACHE.retained_bytes == budget
    _assert_cache_accounting()


def test_source_larger_than_cache_byte_budget_is_valid_but_never_retained(tmp_path, monkeypatch):
    module, path = _module(tmp_path, monkeypatch, (
        "def small():\n    return 1\n"
        "def larger():\n    return 'this valid source exceeds the cache byte budget'\n"
    ))
    budget = len(path.read_bytes()) + len(inspect.getsource(module.small).encode("utf-8"))
    monkeypatch.setattr(identity, "_MAX_SOURCE_CACHE_BYTES", budget)
    calls = _count_extractions(monkeypatch)
    small = identity.component_fingerprint(module.small)
    baseline = identity.component_fingerprint(module.larger)
    assert identity.component_fingerprint(module.larger) == baseline
    assert identity.component_fingerprint(module.small) == small
    assert len(calls) == 3 and len(identity._SOURCE_CACHE) == 1
    assert identity._SOURCE_CACHE.retained_bytes == budget
    _assert_cache_accounting()


def test_source_cache_key_retains_complete_fresh_file_bytes(tmp_path, monkeypatch):
    module, path = _module(tmp_path, monkeypatch, (
        "# bytes outside the extracted range also belong to the key: \u754c\n"
        "class Component:\n    value = 1\n"
    ))
    expected = path.read_bytes()
    _code(module.Component)
    key = next(iter(identity._SOURCE_CACHE))
    assert key[0] == str(path)
    assert type(key[1]) is bytes and key[1] == expected
    assert len(key[1]) == len(expected)
    _assert_cache_accounting()


def test_equal_file_bytes_share_one_retained_object_across_locators_and_paths(tmp_path, monkeypatch):
    source = "def alpha():\n    return 1\ndef bravo():\n    return 2\n"
    modules = []
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        module, _path = _module(directory, monkeypatch, source)
        modules.append(module)
    for module in modules:
        for target in (module.alpha, module.bravo):
            _code(target)
    cache = identity._SOURCE_CACHE
    assert len(cache) == 4
    assert len(cache._raw_sources) == 1
    canonical, references = next(iter(cache._raw_sources.values()))
    assert canonical == source.encode("utf-8") and references == 4
    assert all(key[1] is canonical for key in cache)
    _assert_cache_accounting()


def test_lru_releases_raw_source_only_after_its_last_reference(tmp_path, monkeypatch):
    module, path = _module(tmp_path, monkeypatch, (
        "def alpha():\n    return 1\ndef bravo():\n    return 2\n"
    ))
    raw = path.read_bytes()
    monkeypatch.setattr(identity, "_MAX_SOURCE_CACHE_ENTRIES", 2)
    _code(module.alpha)
    _code(module.bravo)
    replacement = tmp_path / "different"
    replacement.mkdir()
    other, other_path = _module(replacement, monkeypatch, "class Component:\n    value = 2\n")
    _code(other.Component)
    cache = identity._SOURCE_CACHE
    assert cache._raw_sources[raw][1] == 1
    _assert_cache_accounting()

    # A second locator for the other file evicts the last entry retaining the original bytes.
    with identity._SOURCE_CACHE_LOCK:
        other_key = next(key for key in cache if key[0] == str(other_path))
        cache.retain((*other_key, "another-locator"), cache[other_key], len(cache[other_key][0].encode("utf-8")))
    assert raw not in cache._raw_sources
    assert cache._raw_sources[other_path.read_bytes()][1] == 2
    _assert_cache_accounting()
    cache.clear()
    assert not cache and not cache._raw_sources and cache.retained_bytes == 0


def test_replacing_entry_balances_source_cost_and_shared_raw_references():
    cache = identity._SOURCE_CACHE
    raw = b"a shared complete source file\n"
    first, second = ("first.py", raw, "alpha"), ("second.py", bytes(bytearray(raw)), "bravo")
    owner = object()
    with identity._SOURCE_CACHE_LOCK:
        for key in (first, second):
            cache.retain(key, ("small", owner, None), len(b"small"))
        for source in ("\u754c", "replacement source", "small"):
            # Each hit/replacement releases the old entry before retaining one new reference.
            cache.retain(first, (source, owner, None), len(source.encode("utf-8")))
            assert cache[first][0] == source
            assert cache._raw_sources[raw][1] == 2
            _assert_cache_accounting()
    cache.clear()
    assert not cache._raw_sources and cache.retained_bytes == 0


def test_large_raw_file_with_small_extracted_source_is_not_retained(tmp_path, monkeypatch):
    module, path = _module(tmp_path, monkeypatch, (
        "# " + "large unrelated source content " * 200 + "\n"
        "class Component:\n    value = 1\n"
    ))
    source_bytes = len(inspect.getsource(module.Component).encode("utf-8"))
    monkeypatch.setattr(identity, "_MAX_SOURCE_CACHE_BYTES", len(path.read_bytes()) + source_bytes - 1)
    calls = _count_extractions(monkeypatch)
    baseline = _code(module.Component)
    assert _code(module.Component) == baseline
    assert len(calls) == 2
    assert not identity._SOURCE_CACHE and not identity._SOURCE_CACHE._raw_sources
    assert identity._SOURCE_CACHE.retained_bytes == 0


def test_concurrent_clear_and_insert_keep_shared_raw_accounting_consistent(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, (
        "def alpha():\n    return 1\ndef bravo():\n    return 2\n"
    ))
    targets = (module.alpha, module.bravo)
    expected = [_code(target) for target in targets]
    barrier = Barrier(4)

    def insert():
        barrier.wait()
        for _ in range(24):
            assert [_code(target) for target in targets] == expected
            _assert_cache_accounting()

    def clear():
        barrier.wait()
        for _ in range(24):
            identity._SOURCE_CACHE.clear()
            _assert_cache_accounting()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(insert) for _ in range(3)] + [pool.submit(clear)]
        for future in futures:
            future.result()
    _assert_cache_accounting()
    for target in targets:
        _code(target)
    assert len(identity._SOURCE_CACHE) == 2
    assert len(identity._SOURCE_CACHE._raw_sources) == 1
    assert next(iter(identity._SOURCE_CACHE._raw_sources.values()))[1] == 2
    _assert_cache_accounting()


@pytest.mark.parametrize("change", ["same_metadata", "replace", "stale_linecache"])
def test_file_content_is_fresh_despite_metadata_or_linecache(tmp_path, monkeypatch, change):
    module, path = _module(tmp_path, monkeypatch)
    original = path.read_bytes()
    before = path.stat()
    baseline = _code(module.Component)
    changed = original.replace(b"value = 1", b"value = 2")
    if change == "replace":
        replacement = path.with_name("replacement.py")
        replacement.write_bytes(changed)
        replacement.replace(path)
    else:
        path.write_bytes(changed)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    if change == "stale_linecache":
        monkeypatch.setitem(linecache.cache, str(path), (
            len(original), path.stat().st_mtime, original.decode().splitlines(keepends=True), str(path),
        ))
        assert "value = 1" in "".join(linecache.getlines(str(path)))
    assert _code(module.Component) != baseline
    assert "value = 2" in _code(module.Component)


def test_equal_bytes_replacement_reuses_only_the_pure_source_result(tmp_path, monkeypatch):
    module, path = _module(tmp_path, monkeypatch)
    calls = _count_extractions(monkeypatch)
    baseline = _code(module.Component)
    inode = path.stat().st_ino
    replacement = path.with_name("replacement.py")
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    assert path.stat().st_ino != inode
    assert _code(module.Component) == baseline
    assert len(calls) == 1


@pytest.mark.parametrize("source", [
    "class Component:\n    value = 1\n",
    "def decorate(cls):\n    return cls\n@decorate\nclass Component:\n    value = 1\n",
    "class Outer:\n    class Component:\n        value = 1\nComponent = Outer.Component\n",
    "def make():\n    class Component:\n        value = 1\n    return Component\nComponent = make()\n",
    "if False:\n    class Component:\n        value = 1\nelse:\n    class Component:\n        value = 2\n",
])
def test_class_source_range_matches_the_installed_inspector(tmp_path, monkeypatch, source):
    module, _path = _module(tmp_path, monkeypatch, source)
    expected = textwrap.dedent(inspect.getsource(module.Component)).strip()
    assert _code(module.Component) == expected
    assert _code(module.Component) == expected


def test_function_defaults_kwdefaults_and_closure_remain_live(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, (
        "def make():\n    captured = 1\n    def component(value=1, *, named=1):\n"
        "        return captured + value + named\n    return component\ncomponent = make()\n"
    ))
    calls = _count_extractions(monkeypatch)
    component = module.component
    fingerprints = [identity.component_fingerprint(component)]
    component.__defaults__ = (2,)
    fingerprints.append(identity.component_fingerprint(component))
    component.__kwdefaults__["named"] = 2
    fingerprints.append(identity.component_fingerprint(component))
    component.__closure__[0].cell_contents = 2
    fingerprints.append(identity.component_fingerprint(component))
    assert len(set(fingerprints)) == 4 and len(calls) == 1


def test_config_and_explicit_code_hooks_are_invoked_on_every_call(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, (
        "class Component:\n    calls = 0\n    setting = 1\n    source = 'explicit-one'\n"
        "    def rsi_fingerprint_config(self):\n        self.calls += 1\n        return {'setting': self.setting}\n"
        "    def rsi_fingerprint_code(self):\n        self.calls += 1\n        return self.source\n"
    ))
    value = module.Component()
    fingerprints = [identity.component_fingerprint(value)]
    value.setting = 2
    fingerprints.append(identity.component_fingerprint(value))
    value.source = "explicit-two"
    fingerprints.append(identity.component_fingerprint(value))
    assert len(set(fingerprints)) == 3 and value.calls == 6
    assert not identity._SOURCE_CACHE


@pytest.mark.parametrize("change", ["code", "wrapped"])
def test_function_code_and_unwrapped_target_reassignment_are_visible(tmp_path, monkeypatch, change):
    module, _path = _module(tmp_path, monkeypatch, (
        "def one():\n    return 1\ndef two():\n    return 2\ndef wrapper():\n    pass\n"
    ))
    if change == "code":
        target = module.one
        baseline = _code(target)
        target.__code__ = module.two.__code__
    else:
        target = module.wrapper
        target.__wrapped__ = module.one
        baseline = _code(target)
        target.__wrapped__ = module.two
    assert _code(target) != baseline and "return 2" in _code(target)


def test_class_source_file_reassignment_is_visible(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch)
    baseline = _code(module.Component)
    other = tmp_path / "another.py"
    other.write_text("class Component:\n    value = 2\n")
    module.__file__ = str(other)
    assert _code(module.Component) != baseline


def test_inspector_monkeypatch_is_observed_even_with_a_warm_cache(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch)
    _code(module.Component)
    calls = []

    def getsource(target):
        calls.append(target)
        return "replacement-source"

    monkeypatch.setattr(inspect, "getsource", getsource)
    assert _code(module.Component) == "replacement-source"
    assert _code(module.Component) == "replacement-source"
    assert calls == [module.Component, module.Component]


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("change", ["content", "ownership"])
def test_source_or_ownership_change_during_observation_refuses_without_caching(
    tmp_path, monkeypatch, warm, change,
):
    module, path = _module(tmp_path, monkeypatch)
    other = path.with_name("different.py")
    other.write_bytes(path.read_bytes())
    if warm:
        _code(module.Component)
    original = identity._fresh_source_bytes
    calls = 0

    def read(filename):
        nonlocal calls
        raw = original(filename)
        calls += 1
        if calls == 1:
            if change == "content":
                path.write_bytes(raw.replace(b"value = 1", b"value = 2"))
            else:
                module.__file__ = str(other)
        return raw

    monkeypatch.setattr(identity, "_fresh_source_bytes", read)
    before = tuple(identity._SOURCE_CACHE)
    # Cold extraction can notice reassociation before the final cache-boundary
    # check; both paths must refuse instead of reusing another source's result.
    refusal = "code_hook_required" if change == "ownership" and not warm else "code_unavailable"
    with pytest.raises(identity.RSIIdentityError, match=refusal):
        _code(module.Component)
    assert tuple(identity._SOURCE_CACHE) == before


def test_failed_extraction_is_never_cached(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch)
    calls = []

    def unavailable(*args):
        calls.append(args)
        raise OSError("no source")

    monkeypatch.setattr(identity, "_extract_fresh_source", unavailable)
    for _ in range(2):
        with pytest.raises(OSError):
            identity._source_with_content_cache(module.Component)
    assert len(calls) == 2 and not identity._SOURCE_CACHE


def test_generated_linecache_source_remains_uncached_and_live(monkeypatch):
    filename = "<rsi-source-cache-generated>"
    module = ModuleType("rsi_source_cache_generated")
    module.__file__ = filename
    monkeypatch.setitem(sys.modules, module.__name__, module)
    source = "def component():\n    return 1\n"
    exec(compile(source, filename, "exec"), module.__dict__)  # noqa: S102 - inert identity fixture declaration
    monkeypatch.setitem(linecache.cache, filename, (len(source), None, source.splitlines(keepends=True), filename))
    assert "return 1" in _code(module.component)
    changed = source.replace("return 1", "return 2")
    monkeypatch.setitem(linecache.cache, filename, (len(changed), None, changed.splitlines(keepends=True), filename))
    assert "return 2" in _code(module.component)
    assert not identity._SOURCE_CACHE


def test_unwrap_cycles_keep_the_original_refusal(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, "def component():\n    pass\n")
    module.component.__wrapped__ = module.component
    with pytest.raises(ValueError, match="wrapper loop"):
        _code(module.component)
    assert not identity._SOURCE_CACHE


def test_source_cache_eviction_is_bounded_and_reextracts_old_entries(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, "class A:\n    pass\nclass B:\n    pass\nclass C:\n    pass\n")
    monkeypatch.setattr(identity, "_MAX_SOURCE_CACHE_ENTRIES", 2)
    calls = _count_extractions(monkeypatch)
    for target in (module.A, module.B, module.C, module.A):
        _code(target)
    assert len(identity._SOURCE_CACHE) == 2 and len(calls) == 4


def test_bound_method_source_matches_inspect(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, (
        "class Component:\n    def rsi_fingerprint_config(self):\n        return {}\n"
        "    def method(self):\n        return 1\n"
    ))
    method = module.Component().method
    assert identity.component_identity(method).code == textwrap.dedent(inspect.getsource(method)).strip()


def test_inspector_code_and_unwrap_changes_are_not_hidden_by_cache(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, "class Component:\n    pass\nclass Other:\n    value = 2\n")
    _code(module.Component)
    original_unwrap = inspect.unwrap

    def redirect(target, *, stop=None):
        return module.Other if target is module.Component else original_unwrap(target, stop=stop)

    with monkeypatch.context() as patch:
        patch.setattr(inspect, "unwrap", redirect)
        assert "class Other" in _code(module.Component)

    def replacement(_target):
        return "changed-inspector-code"

    monkeypatch.setattr(inspect.getsource, "__code__", replacement.__code__)
    assert _code(module.Component) == "changed-inspector-code"


def test_custom_loader_and_generated_bytecode_keep_the_original_path(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch, "def component():\n    return 1\n")
    module.__loader__ = object()
    assert _code(module.component) == textwrap.dedent(inspect.getsource(module.component)).strip()
    assert not identity._SOURCE_CACHE
    filename = "<rsi-source-cache-bytecode>"
    source = "def component():\n    return 2\n"
    exec(compile(source, filename, "exec"), module.__dict__)  # noqa: S102 - inert identity fixture declaration
    assert _code(module.component).startswith("bytecode-v2:")
    assert not identity._SOURCE_CACHE


def test_large_source_extraction_is_not_retained(tmp_path, monkeypatch):
    module, _path = _module(tmp_path, monkeypatch)
    monkeypatch.setattr(identity, "MAX_CODE_BYTES", 1)
    with pytest.raises(identity.RSIIdentityError, match="too_large"):
        _code(module.Component)
    assert not identity._SOURCE_CACHE
