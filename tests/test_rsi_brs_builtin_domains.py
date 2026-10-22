"""Builtin observation covers distinct globals, including shared domains."""

import importlib

import pytest

from lunar_evolution import rsi_brs_reserved_policy as policy
from lunar_evolution.rsi_learning import RSILearningError


def _captures(function):
    return dict(zip(function.__code__.co_freevars, function.__closure__, strict=True))


@pytest.fixture(autouse=True)
def original_projection():
    policy.reserved_brs_policy_projection()


def test_each_function_globals_is_observed_once_and_all_function_pins_remain():
    captures = _captures(policy._PROJECT)
    functions = captures["functions"].cell_contents
    domains = captures["builtin_domains"].cell_contents
    expected = {id(pin[2]) for pin in functions}
    actual = [id(entry[0]) for entry in domains]
    assert len(functions) > len(expected)
    assert len(actual) == len(set(actual))
    assert set(actual) == expected
    assert all(function.__globals__ is namespace for function, _code, namespace, *_tail in functions)


def test_shared_builtin_domain_keeps_each_separate_namespace_shadow_vector():
    domains = _captures(policy._PROJECT)["builtin_domains"].cell_contents
    shared = {}
    for namespace, _alias, domain, _shadows in domains:
        shared.setdefault(id(domain), set()).add(id(namespace))
    assert any(len(namespaces) > 1 for namespaces in shared.values())


def test_every_distinct_held_builtin_domain_is_observed_once():
    captures = _captures(policy._PROJECT)
    expected = {id(entry[2]) for entry in captures["builtin_domains"].cell_contents}
    actual = captures["unique_builtin_domains"].cell_contents
    assert type(actual) is tuple
    assert all(type(domain) is dict for domain in actual)
    assert len(actual) == len(expected)
    assert {id(domain) for domain in actual} == expected


@pytest.mark.parametrize("domain_index", [0, 1])
@pytest.mark.parametrize("mutation", ["binding", "foreign_key", "overlength"])
def test_equal_private_builtin_domains_remain_separate_live_observations(monkeypatch, domain_index, mutation):
    copies = []
    for name in ("rsi_controller", "rsi_store"):
        namespace = vars(importlib.import_module("lunar_evolution." + name))
        original = namespace["__builtins__"]
        copied = dict(vars(original) if type(original) is not dict else original)
        monkeypatch.setitem(namespace, "__builtins__", copied)
        copies.append(copied)
    assert copies[0] == copies[1] and copies[0] is not copies[1]
    project = policy._build_reserved_brs_policy()
    monkeypatch.setattr(policy, "_PROJECT", project)
    project()
    actual = _captures(project)["unique_builtin_domains"].cell_contents
    assert all(any(domain is copied for domain in actual) for copied in copies)
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("foreign builtin executed")

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            calls.append("equality")
            raise AssertionError("foreign domain key compared")

    domain = copies[domain_index]
    if mutation == "binding":
        domain["len"] = forbidden
    elif mutation == "foreign_key":
        del domain["len"]
        domain[Key("len")] = len
    else:
        domain.update(("extra_" + str(index), None) for index in range(32769))
    calls.clear()
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        project()
    assert calls == []


@pytest.mark.parametrize("module_name", [
    "rsi_controller", "rsi_store", "rsi_native_scheduler", "rsi_producer_gateway",
])
@pytest.mark.parametrize("mutation", ["shadow", "builtins_alias"])
def test_each_external_namespace_still_refuses_drift_without_callbacks(module_name, mutation, monkeypatch):
    module = importlib.import_module("lunar_evolution." + module_name)
    namespace = vars(module)
    assert module_name not in policy._MODULE_NAMES
    domains = _captures(policy._PROJECT)["builtin_domains"].cell_contents
    assert any(entry[0] is namespace for entry in domains)
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("foreign builtin shadow executed")

    if mutation == "shadow":
        functions = _captures(policy._PROJECT)["functions"].cell_contents
        used = {name for pin in functions if pin[2] is namespace for name, _value, _container in pin[-1]}
        shadows = next(entry[3] for entry in domains if entry[0] is namespace)
        unused = next(name for name, _value in shadows if name not in used)
        monkeypatch.setitem(namespace, unused, forbidden)
    else:
        original = namespace["__builtins__"]
        copied = dict(vars(original) if type(original) is not dict else original)
        monkeypatch.setitem(namespace, "__builtins__", copied)
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        policy.reserved_brs_policy_projection()
    assert calls == []


@pytest.mark.parametrize("mutation", ["binding", "foreign_key"])
def test_private_copied_domain_keeps_binding_and_exact_key_checks(mutation, monkeypatch):
    module = importlib.import_module("lunar_evolution.rsi_controller")
    original = vars(module)["__builtins__"]
    copied = dict(vars(original) if type(original) is not dict else original)
    monkeypatch.setitem(vars(module), "__builtins__", copied)
    project = policy._build_reserved_brs_policy()
    monkeypatch.setattr(policy, "_PROJECT", project)
    project()
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("foreign builtin executed")

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            calls.append("equality")
            raise AssertionError("foreign builtin key compared")

    if mutation == "binding":
        copied["len"] = forbidden
    else:
        del copied["len"]
        copied[Key("len")] = len
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        project()
    assert calls == []
