"""Fresh runtime reuse stays local and preserves the public revalidation gates."""

from __future__ import annotations

import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_python_producer_binding_parser_normalization import _wire

from lunar_evolution import producer_python_runtime as runtime
from lunar_evolution import python_producer_binding as binding


@contextmanager
def _runtime_calls(callback=None):
    """Observe execution without replacing any parser or validation helper."""
    calls = Counter()
    codes = {
        runtime.parse_python_runtime_manifest.__code__: "parse",
        binding._reparse_runtime.__code__: "reparse",
    }
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if event == "call" and frame.f_code in codes:
            calls[codes[frame.f_code]] += 1
        if callback is not None:
            callback(frame, event, arg)

    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
def test_fresh_runtime_avoids_only_the_redundant_parser_local_reparse(tmp_path, text):
    raw = _wire(tmp_path)
    with binding._VALIDATION_CACHE_LOCK:
        previous_cache_sources = tuple(binding._RUNTIME_VALIDATION_CACHE)
    with _runtime_calls() as calls:
        parsed = binding.parse_python_producer_binding(raw.decode() if text else raw)
    # The standalone manifest and the tree's declared manifest each still get a
    # real strict parse. Neither is promoted to cross-call validation authority.
    assert calls == {"parse": 2}
    with binding._VALIDATION_CACHE_LOCK:
        assert tuple(binding._RUNTIME_VALIDATION_CACHE) == previous_cache_sources
    assert parsed.runtime_manifest is not parsed.runtime_tree.declared_manifest
    assert parsed.to_json() == raw
    assert replace(parsed) == parsed


@pytest.mark.parametrize("seam", [
    "binding_parser", "module_parser", "helper", "shape", "type", "module",
    "parser_code", "validator_code", "serializer_code", "constructor_code", "helper_defaults",
    "function_pins", "value_pins", "class_pins", "role_mirror", "guard_defaults",
])
def test_fresh_runtime_changed_pure_seam_keeps_original_reparse(tmp_path, monkeypatch, seam):
    raw = _wire(tmp_path)

    def wrap(function):
        def unchanged(*args, **kwargs):
            return function(*args, **kwargs)

        return unchanged

    if seam == "binding_parser":
        monkeypatch.setattr(binding, "parse_python_runtime_manifest", wrap(binding.parse_python_runtime_manifest))
    elif seam == "module_parser":
        monkeypatch.setattr(runtime, "parse_python_runtime_manifest", wrap(runtime.parse_python_runtime_manifest))
    elif seam == "helper":
        monkeypatch.setattr(runtime, "_validate_manifest", wrap(runtime._validate_manifest))
    elif seam == "shape":
        monkeypatch.setattr(binding.closed_runtime, "_declared_shape", wrap(binding.closed_runtime._declared_shape))
    elif seam == "type":
        monkeypatch.setattr(binding, "PythonRuntimeTarget", type("DifferentTargetAlias", (), {}))
    elif seam == "module":
        monkeypatch.setattr(runtime, "json", SimpleNamespace(loads=runtime.json.loads, dumps=runtime.json.dumps))
    elif seam == "helper_defaults":
        monkeypatch.setattr(runtime._integer, "__kwdefaults__", dict(runtime._integer.__kwdefaults__))
    elif seam == "guard_defaults":
        monkeypatch.setattr(binding._fresh_runtime_helpers_current, "__defaults__", ())
    elif seam in {"function_pins", "value_pins", "class_pins", "role_mirror"}:
        name = {
            "function_pins": "_FRESH_RUNTIME_FUNCTION_PINS",
            "value_pins": "_FRESH_RUNTIME_VALUE_PINS",
            "class_pins": "_FRESH_RUNTIME_CLASS_PINS",
            "role_mirror": "_FRESH_RUNTIME_ROLE_SLOTS",
        }[seam]
        monkeypatch.setattr(binding, name, ())
    else:
        function = {
            "parser_code": runtime.parse_python_runtime_manifest,
            "validator_code": runtime.PythonRuntimeManifest.__post_init__,
            "serializer_code": runtime.PythonRuntimeManifest.to_dict,
            "constructor_code": runtime.PythonRuntimeManifest.__init__,
        }[seam]
        # Identical behavior with a distinct executable code object must still
        # select the compatibility path, including in-place function changes.
        monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed_pure_seam"))
    with _runtime_calls() as calls:
        parsed = binding.parse_python_producer_binding(raw)
    assert calls["reparse"] == 1
    assert parsed.to_json() == raw


def test_fresh_runtime_mutation_between_parsers_falls_back_before_callback(tmp_path):
    raw = _wire(tmp_path)
    observed, callbacks = [], []

    class SameItems(tuple):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

        def __len__(self):
            callbacks.append("len")
            return super().__len__()

    runtime_code = runtime.parse_python_runtime_manifest.__code__
    tree_code = binding.parse_python_runtime_tree_manifest.__code__

    def mutate(frame, event, arg):
        if event == "return" and frame.f_code is runtime_code and not observed:
            observed.append(arg)
        if event == "return" and frame.f_code is tree_code:
            manifest = observed[0]
            object.__setattr__(manifest, "files", SameItems(manifest.files))

    with _runtime_calls(mutate) as calls, pytest.raises(binding.PythonProducerBindingError) as caught:
        binding.parse_python_producer_binding(raw)
    assert calls["reparse"] == 1
    assert caught.value.code == "python_producer_binding_runtime_manifest_invalid"
    assert callbacks == []


@pytest.mark.parametrize("gate", ["constructor", "post_init", "to_dict", "to_json", "digest"])
@pytest.mark.parametrize("mutation", ["files", "digest"])
def test_fresh_runtime_public_gates_revalidate_caller_mutations(tmp_path, gate, mutation):
    parsed = binding.parse_python_producer_binding(_wire(tmp_path))
    callbacks = []

    class SameItems(tuple):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

        def __len__(self):
            callbacks.append("len")
            return super().__len__()

    if mutation == "files":
        object.__setattr__(parsed.runtime_manifest, "files", SameItems(parsed.runtime_manifest.files))
    else:
        object.__setattr__(parsed.runtime_manifest, "manifest_sha256", "1" * 64)
    with pytest.raises(binding.PythonProducerBindingError) as caught:
        if gate == "constructor":
            replace(parsed)
        else:
            getattr(parsed, "__post_init__" if gate == "post_init" else gate)()
    assert caught.value.code == "python_producer_binding_runtime_manifest_invalid"
    assert callbacks == []
