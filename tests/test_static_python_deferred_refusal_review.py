"""Independent callback regressions for five fixed source-only refusals.

Only repository-owned replacement bodies run in synthetic namespaces. Parsing
the prepared external module never executes its archived CPython definitions.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.static_python_fixture import source_patches

_FIXTURES = Path(__file__).parent / "fixtures/static_python_source"
_MESSAGE = "lunar_static_external_loader_refused"
_ENTRIES = (
    ("FileLoader", "get_resource_reader"),
    ("NamespaceLoader", "get_resource_reader"),
    ("PathFinder", "invalidate_caches"),
    ("PathFinder", "find_distributions"),
    (None, "decode_source"),
)
_IDS = tuple(f"{owner}.{name}" if owner else name for owner, name in _ENTRIES)


@pytest.fixture
def prepared_tree():
    inputs = {
        path: (_FIXTURES / (path + ".source")).read_bytes()
        for path in source_patches.SOURCE_PATHS
    }
    prepared, _ = source_patches.prepare_static_python_sources(inputs)
    return ast.parse(prepared["Lib/importlib/_bootstrap_external.py"])


def _entry(tree, owner, name):
    body = tree.body
    if owner is not None:
        body = next(node.body for node in body
                    if isinstance(node, ast.ClassDef) and node.name == owner)
    return next(node for node in body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _fixed_raise(node):
    expected = ast.parse(f"raise ImportError({_MESSAGE!r})").body[0]
    assert len(node.body) == 1
    assert ast.dump(node.body[0]) == ast.dump(expected)


def _trap(events, label):
    def forbidden(*_args, **_kwargs):
        events.append(label)
        raise AssertionError("candidate invoked a caller callback")

    return forbidden


def _opaque(events):
    hooks = (
        "__getattribute__", "__eq__", "__ne__", "__repr__", "__str__",
        "__bytes__", "__bool__", "__iter__", "__len__", "__getitem__",
        "__hash__", "decode",
    )
    return type("CallerOwned", (), {hook: _trap(events, hook) for hook in hooks})()


def _replacement(tree, owner, name, events, **globals_):
    """Compile only the fixed new snippet and link it to the prepared AST.

    In particular, do not clear decorators on the prepared method: a surviving
    name guard must fail this review instead of disappearing in a test helper.
    """
    actual = _entry(tree, owner, name)
    _fixed_raise(actual)
    expected_decorators = [ast.Name(id="staticmethod", ctx=ast.Load())] if (
        owner == "PathFinder"
    ) else []
    assert [ast.dump(node) for node in actual.decorator_list] == [
        ast.dump(node) for node in expected_decorators
    ]
    label = f"{owner}.{name}" if owner else name
    profile = next(profile for profile in source_patches._PROFILES
                   if profile.path == "Lib/importlib/_bootstrap_external.py")
    snippets = [snippet for snippet in profile.snippets if snippet.label == label]
    assert len(snippets) == 1
    replacement = ast.parse(textwrap.dedent(snippets[0].new.decode("utf-8")))
    assert len(replacement.body) == 1
    node = replacement.body[0]
    assert isinstance(node, ast.FunctionDef)
    _fixed_raise(node)
    # Staticmethod may remain outside the snippet's byte range; its actual
    # prepared AST above is authoritative. Never remove a parsed decorator.
    assert [ast.dump(decorator) for decorator in node.decorator_list] in (
        [], [ast.dump(decorator) for decorator in expected_decorators],
    )
    assert ast.dump(node.args) == ast.dump(actual.args)
    assert ast.dump(node.body[0]) == ast.dump(actual.body[0])
    namespace = {
        "__builtins__": {"ImportError": ImportError, "staticmethod": staticmethod,
                         "__import__": _trap(events, "import")},
        "sys": _opaque(events), "_io": _opaque(events),
        "tokenize": _opaque(events), "_NamespacePath": _opaque(events),
        "_path_isabs": _trap(events, "path-isabs"),
        **globals_,
    }
    exec(compile(replacement, "<fixed-deferred-refusal>", "exec"), namespace)  # noqa: S102
    return namespace[name]


def _refuses(function, *args, **kwargs):
    with pytest.raises(ImportError) as raised:
        function(*args, **kwargs)
    assert type(raised.value) is ImportError
    assert raised.value.args == (_MESSAGE,)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("owner,name", _ENTRIES, ids=_IDS)
def test_complete_prepared_entry_is_only_the_fixed_refusal(prepared_tree, owner, name):
    _fixed_raise(_entry(prepared_tree, owner, name))


def test_file_reader_does_not_retain_the_name_guard_decorator(prepared_tree):
    method = _entry(prepared_tree, "FileLoader", "get_resource_reader")
    # The ordinary extracted-method helper strips decorators and cannot catch
    # this regression. Inspect the real prepared method before any extraction.
    assert method.decorator_list == []


@pytest.mark.parametrize("name", ["invalidate_caches", "find_distributions"])
def test_metadata_entry_keeps_staticmethod_and_its_argument_domain(prepared_tree, name):
    method = _entry(prepared_tree, "PathFinder", name)
    assert len(method.decorator_list) == 1
    decorator = method.decorator_list[0]
    assert isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
    assert method.args.posonlyargs == method.args.args == method.args.kwonlyargs == []
    assert method.args.defaults == method.args.kw_defaults == []
    if name == "invalidate_caches":
        assert method.args.vararg is method.args.kwarg is None
    else:
        assert method.args.vararg.arg == "args"
        assert method.args.kwarg.arg == "kwargs"


@pytest.mark.parametrize("owner,name", _ENTRIES, ids=_IDS)
def test_entry_does_not_inspect_callers_or_resolve_deferred_imports(prepared_tree, owner, name):
    events = []
    function = _replacement(prepared_tree, owner, name, events)
    if owner in {"FileLoader", "NamespaceLoader"}:
        arguments = (_opaque(events), _opaque(events))
    elif name in {"decode_source", "find_distributions"}:
        arguments = (_opaque(events),)
    else:
        arguments = ()
    _refuses(function, *arguments)
    assert events == []


@pytest.mark.parametrize("class_name", ["SourceFileLoader", "SourcelessFileLoader"])
def test_inherited_file_reader_refuses_before_name_comparison_or_formatting(
    prepared_tree, class_name,
):
    events = []
    actual_class = next(node for node in prepared_tree.body
                        if isinstance(node, ast.ClassDef) and node.name == class_name)
    assert isinstance(actual_class.bases[0], ast.Name)
    assert actual_class.bases[0].id == "FileLoader"
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "get_resource_reader"
                   for node in actual_class.body)
    function = _replacement(prepared_tree, "FileLoader", "get_resource_reader", events)
    base = type("SyntheticFileLoader", (), {"get_resource_reader": function})
    # Avoid all archived constructors. If a name check returns, even comparing
    # or formatting this name is forbidden rather than hidden by a benign str.
    derived = type(class_name, (base,), {"name": _opaque(events)})
    _refuses(derived().get_resource_reader, _opaque(events))
    assert events == []


@pytest.mark.parametrize("shape", ["empty", "positional", "keyword", "mixed"])
def test_distribution_arguments_remain_uninspected(prepared_tree, shape):
    events = []
    function = _replacement(prepared_tree, "PathFinder", "find_distributions", events)
    opaque = _opaque(events)
    arguments, keywords = {
        "empty": ((), {}),
        "positional": ((opaque, opaque), {}),
        "keyword": ((), {"context": opaque, "unrecognized": opaque}),
        "mixed": ((opaque,), {"context": opaque}),
    }[shape]
    _refuses(function, *arguments, **keywords)
    assert events == []


def test_cache_invalidation_keeps_cache_epoch_finders_and_modules_untouched(prepared_tree):
    events = []

    class Finder:
        invalidate_caches = staticmethod(_trap(events, "finder-invalidate"))

    class Cache(dict):
        items = _trap(events, "cache-items")
        __delitem__ = _trap(events, "cache-delete")
        __setitem__ = _trap(events, "cache-write")

    finder = Finder()
    cache = Cache({"relative": None, "/absolute": finder})
    modules = {"_frozen_importlib_external": object()}
    sys = SimpleNamespace(path_importer_cache=cache, modules=modules)
    namespace_path = SimpleNamespace(_epoch=73)
    before_cache = tuple(dict.items(cache))
    before_modules = tuple(modules.items())
    function = _replacement(
        prepared_tree, "PathFinder", "invalidate_caches", events,
        sys=sys, _NamespacePath=namespace_path,
    )
    _refuses(function)
    assert tuple(dict.items(cache)) == before_cache
    assert all(value is before for (_key, value), (_old_key, before)
               in zip(dict.items(cache), before_cache, strict=True))
    assert namespace_path._epoch == 73
    assert tuple(modules.items()) == before_modules
    assert events == []


def test_source_decoding_never_constructs_a_stream_or_decodes_caller_bytes(prepared_tree):
    events = []

    class CallerBytes(bytes):
        decode = _trap(events, "bytes-decode")
        __bytes__ = _trap(events, "bytes-conversion")
        __iter__ = _trap(events, "bytes-iteration")

    function = _replacement(
        prepared_tree, None, "decode_source", events,
        _io=SimpleNamespace(BytesIO=_trap(events, "bytes-stream"),
                            IncrementalNewlineDecoder=_trap(events, "newline-decoder")),
        tokenize=SimpleNamespace(detect_encoding=_trap(events, "encoding-detection")),
    )
    _refuses(function, CallerBytes(b"# coding: caller-selected\n"))
    assert events == []


def test_namespace_reader_never_observes_the_callers_path_property(prepared_tree):
    events = []
    holder = type("NamespaceOwner", (), {"_path": property(_trap(events, "namespace-path"))})
    function = _replacement(prepared_tree, "NamespaceLoader", "get_resource_reader", events)
    _refuses(function, holder(), _opaque(events))
    assert events == []
