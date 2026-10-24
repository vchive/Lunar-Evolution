"""Unsupported class metadata cannot run callbacks at admission type gates."""

from dataclasses import dataclass

import pytest

import lunar_evolution.rsi_python_admission as admission


@pytest.mark.parametrize("placement", ["root", "list", "tuple", "dict"])
@pytest.mark.parametrize("unhashable", [False, True])
def test_shape_refuses_custom_metaclass_without_hash_or_equality(placement, unhashable):
    calls = []

    class Meta(type):
        def __hash__(cls):
            calls.append("hash")
            raise AssertionError("type gate called untrusted hash")

        def __eq__(cls, other):
            calls.append("equality")
            raise AssertionError("type gate called untrusted equality")

    if unhashable:
        Meta.__hash__ = None

    class Trap(metaclass=Meta):
        def __getattribute__(self, name):
            calls.append("attribute")
            raise AssertionError("type gate read untrusted attribute")

    value = Trap()
    value = {"root": value, "list": [value], "tuple": (value,), "dict": {"value": value}}[placement]
    with pytest.raises(admission.RSIPythonAdmissionError) as error:
        admission.validate_rsi_python_admission_shapes(value)
    assert error.value.code == "rsi_python_admission_shape_invalid"
    assert calls == []


@pytest.mark.parametrize("base", [str, bytes, list, tuple, dict, int, float])
def test_builtin_subclass_is_not_a_builtin_even_with_spoofed_class_equality(base):
    calls = []

    class Meta(type):
        def __hash__(cls):
            calls.append("hash")
            return hash(str)

        def __eq__(cls, other):
            calls.append("equality")
            return True

    class Trap(base, metaclass=Meta):
        pass

    with pytest.raises(admission.RSIPythonAdmissionError, match="shape_invalid"):
        admission.validate_rsi_python_admission_shapes(Trap())
    assert calls == []


def test_dto_allowlist_compares_class_identity_without_metaclass_equality():
    calls = []

    @dataclass
    class Allowed:
        value: object

    class Meta(type):
        def __hash__(cls):
            calls.append("hash")
            return 0

        def __eq__(cls, other):
            calls.append("equality")
            return True

    class Trap(Allowed, metaclass=Meta):
        def __getattribute__(self, name):
            calls.append("attribute")
            raise AssertionError("unapproved DTO was inspected")

    admission.validate_rsi_python_admission_shapes(Allowed({"finite": 0.375}), dto_types=(Allowed,))
    with pytest.raises(admission.RSIPythonAdmissionError, match="shape_invalid"):
        admission.validate_rsi_python_admission_shapes(Trap(None), dto_types=(Allowed,))
    assert calls == []


@pytest.mark.parametrize("entry", ["strict_json", "record"])
@pytest.mark.parametrize("base", [object, str, bytes])
def test_wire_entry_refuses_custom_metaclass_without_type_callbacks(entry, base):
    calls = []

    class Meta(type):
        def __hash__(cls):
            calls.append("hash")
            raise AssertionError("wire gate called untrusted hash")

        def __eq__(cls, other):
            calls.append("equality")
            raise AssertionError("wire gate called untrusted equality")

    class Trap(base, metaclass=Meta):
        pass

    function = admission._strict_json if entry == "strict_json" else admission.parse_rsi_python_admission_record
    with pytest.raises(admission.RSIPythonAdmissionError) as error:
        function(Trap())
    expected = "json_invalid" if entry == "strict_json" else "schema_invalid"
    assert error.value.code == "rsi_python_admission_" + expected
    assert calls == []


@pytest.mark.parametrize("value", [None, True, 1, 0.375, "text", [], (), {}])
def test_exact_builtin_shapes_remain_valid(value):
    admission.validate_rsi_python_admission_shapes(value)


@pytest.mark.parametrize("entry", ["record", "from_dict", "reference"])
def test_fieldset_checks_refuse_string_subclass_keys_before_equality(entry):
    calls = []

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            calls.append("equality")
            raise AssertionError("fieldset compared an untrusted key")

    names = admission._REFERENCE_FIELDS if entry == "reference" else admission._FIELDS
    wire = {name: None for name in names}
    name = next(iter(names))
    del wire[name]
    wire[Key(name)] = None
    function = {
        "record": admission.parse_rsi_python_admission_record,
        "from_dict": admission.RSIPythonAdmissionRecord.from_dict,
        "reference": admission.parse_rsi_python_admission_reference,
    }[entry]
    with pytest.raises(admission.RSIPythonAdmissionError, match="shape_invalid"):
        function(wire)
    assert calls == []
