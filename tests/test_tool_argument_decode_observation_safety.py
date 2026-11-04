"""Untrusted optional decode observations cannot affect terminal failure evidence."""

import json
import logging
from enum import Enum

import pytest
from test_runtime_tool_call_validation import call

import lunar_evolution.model_request_logging as logs
import lunar_evolution.runtime as rt
from lunar_evolution.http_transport import MAX_BODY_BYTES

PRIVATE = "DECODE-OBSERVATION-PRIVATE-ARGUMENT-EXCEPTION-AND-METADATA"
ORIGINAL_LOADS = json.loads
POSITION_FIELDS = {"position", "line", "column"}


def observation():
    return rt.ToolArgumentDecodeObservation(
        decoder_category=rt.ToolArgumentDecoderCategory.JSON_SYNTAX,
        argument_characters=10,
        position=5,
        line=2,
        column=3,
        finish_reason_category=rt.ToolArgumentFinishReasonCategory.TOOL_CALLS,
    )


def failure(detail):
    error = rt.ModelRequestFailure(
        PRIVATE, "invalid_tool_calls", 200,
        tool_call_error_category=rt.ToolCallErrorCategory.ARGUMENTS_INVALID_JSON,
    )
    error.tool_argument_observation = detail
    error.request_fingerprint = rt.ModelRequestFingerprint(11, "1" * 64)
    return error


def terminal(caplog, error, *, outcome="failed"):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    caplog.clear()
    log = logs.ModelRequestLog(timeout=2, bounded=True)
    log.finish(outcome, failure=error)
    events = [ORIGINAL_LOADS(record.getMessage()) for record in caplog.records
              if record.name == logs.LOGGER_NAME]
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_" + outcome,
    ]
    assert PRIVATE not in json.dumps(events)
    if outcome == "failed":
        assert events[-1]["reason"] == "invalid_tool_calls"
        assert events[-1]["response_status"] == 200
        assert events[-1]["request_fingerprint"] == {
            "body_bytes": 11, "body_sha256": "1" * 64,
        }
    return events[-1]


class ForeignDecoderCategory(Enum):
    JSON_SYNTAX = "json_syntax"


class ForeignFinishCategory(Enum):
    TOOL_CALLS = "tool_calls"


class Hostile:
    def __init__(self, callbacks):
        self.callbacks = callbacks

    @property
    def value(self):
        self.callbacks.append("value")
        raise AssertionError(PRIVATE)

    def __str__(self):
        self.callbacks.append("str")
        raise AssertionError(PRIVATE)

    def __eq__(self, _other):
        self.callbacks.append("eq")
        raise AssertionError(PRIVATE)

    def __int__(self):
        self.callbacks.append("int")
        raise AssertionError(PRIVATE)

    def __hash__(self):
        self.callbacks.append("hash")
        raise AssertionError(PRIVATE)


@pytest.mark.parametrize("field,value", [
    ("argument_characters", True),
    ("argument_characters", -1),
    ("argument_characters", MAX_BODY_BYTES + 1),
    ("argument_characters", 10.0),
    ("argument_characters", "10"),
    ("position", True),
    ("position", -1),
    ("position", 11),
    ("position", 5.0),
    ("position", None),
    ("line", True),
    ("line", 0),
    ("line", 12),
    ("line", None),
    ("column", True),
    ("column", 0),
    ("column", 12),
    ("column", None),
])
def test_invalid_numbers_omit_only_affected_numeric_detail(caplog, field, value):
    detail = observation()
    object.__setattr__(detail, field, value)
    projected = terminal(caplog, failure(detail))["tool_argument_decode"]
    assert projected["decoder_category"] == "json_syntax"
    assert projected["finish_reason_category"] == "tool_calls"
    assert not POSITION_FIELDS.intersection(projected)
    if field == "argument_characters":
        assert "argument_characters" not in projected
    else:
        assert projected["argument_characters"] == 10


@pytest.mark.parametrize("position,line,column", [
    (5, 1, 3),  # First line requires column == position + 1.
    (0, 2, 1),  # A later line needs an earlier newline.
    (5, 5, 4),  # Newline count and column cannot exceed the consumed prefix.
    (1, 4, 1),
])
def test_inconsistent_position_group_is_wholly_omitted(caplog, position, line, column):
    detail = observation()
    for key, value in {"position": position, "line": line, "column": column}.items():
        object.__setattr__(detail, key, value)
    projected = terminal(caplog, failure(detail))["tool_argument_decode"]
    assert projected == {
        "decoder_category": "json_syntax", "argument_characters": 10,
        "finish_reason_category": "tool_calls",
    }


@pytest.mark.parametrize("field,kind", [
    ("decoder_category", "string"), ("decoder_category", "foreign_enum"),
    ("decoder_category", "unregistered_owned"), ("decoder_category", "hostile"),
    ("finish_reason_category", "string"), ("finish_reason_category", "foreign_enum"),
    ("finish_reason_category", "unregistered_owned"), ("finish_reason_category", "hostile"),
    ("argument_characters", "hostile"), ("position", "hostile"),
    ("line", "hostile"), ("column", "hostile"),
])
def test_unknown_typed_fields_do_not_invoke_remote_callbacks(caplog, field, kind):
    callbacks = []
    detail = observation()
    decoder = field == "decoder_category"
    if kind == "string":
        value = "json_syntax" if decoder else "tool_calls"
    elif kind == "foreign_enum":
        value = ForeignDecoderCategory.JSON_SYNTAX if decoder else ForeignFinishCategory.TOOL_CALLS
    elif kind == "unregistered_owned":
        value = object.__new__(rt.ToolArgumentDecoderCategory if decoder
                               else rt.ToolArgumentFinishReasonCategory)
    else:
        value = Hostile(callbacks)
    object.__setattr__(detail, field, value)
    projected = terminal(caplog, failure(detail))["tool_argument_decode"]
    assert field not in projected
    if field != "finish_reason_category":
        assert not POSITION_FIELDS.intersection(projected)
    else:
        assert POSITION_FIELDS.issubset(projected)
    assert callbacks == []


@pytest.mark.parametrize("category", ["VALUE_ERROR", "RECURSION_ERROR"])
def test_position_is_not_accepted_for_a_non_syntax_decoder(caplog, category):
    detail = observation()
    object.__setattr__(detail, "decoder_category", getattr(rt.ToolArgumentDecoderCategory, category))
    projected = terminal(caplog, failure(detail))["tool_argument_decode"]
    assert projected["decoder_category"] == category.lower()
    assert not POSITION_FIELDS.intersection(projected)


@pytest.mark.parametrize("mutation", [
    "missing", "none", "dict", "foreign_type", "foreign_dictionary",
    "foreign_key", "oversized_storage", "hostile_object", "property",
])
def test_invalid_observation_storage_omits_detail_and_preserves_terminal_fields(
    monkeypatch, caplog, mutation,
):
    callbacks = []
    detail = observation()
    error = failure(detail)

    class ForeignObservation(rt.ToolArgumentDecodeObservation):
        pass

    class ForeignDict(dict):
        def get(self, *_args):
            callbacks.append("dict_get")
            raise AssertionError(PRIVATE)

        def __iter__(self):
            callbacks.append("dict_iter")
            raise AssertionError(PRIVATE)

    class ForeignKey(str):
        def __hash__(self):
            callbacks.append("key_hash")
            return hash("decoder_category")

        def __eq__(self, _other):
            callbacks.append("key_eq")
            raise AssertionError(PRIVATE)

    if mutation == "missing":
        del error.tool_argument_observation
    elif mutation == "none":
        error.tool_argument_observation = None
    elif mutation == "dict":
        error.tool_argument_observation = {"decoder_category": PRIVATE}
    elif mutation == "foreign_type":
        error.tool_argument_observation = ForeignObservation()
    elif mutation == "foreign_dictionary":
        object.__setattr__(detail, "__dict__", ForeignDict(detail.__dict__))
    elif mutation == "foreign_key":
        stored = {ForeignKey(PRIVATE): PRIVATE}
        stored.update({key: value for key, value in detail.__dict__.items()
                       if key != "decoder_category"})
        object.__setattr__(detail, "__dict__", stored)
        callbacks.clear()
    elif mutation == "oversized_storage":
        detail.__dict__.update({f"extra-{index}": PRIVATE for index in range(17)})
    elif mutation == "hostile_object":
        error.tool_argument_observation = Hostile(callbacks)
    elif mutation == "property":
        del error.tool_argument_observation

        def unreadable(_self):
            callbacks.append("observation_property")
            raise AssertionError(PRIVATE)

        monkeypatch.setattr(rt.ModelRequestFailure, "tool_argument_observation",
                            property(unreadable), raising=False)
    assert "tool_argument_decode" not in terminal(caplog, error)
    assert callbacks == []


def test_projection_reads_owned_storage_without_field_properties(monkeypatch, caplog):
    callbacks = []
    detail = observation()
    detail.__dict__.pop("decoder_category")

    def unreadable(_self):
        callbacks.append("decoder_property")
        raise AssertionError(PRIVATE)

    monkeypatch.setattr(rt.ToolArgumentDecodeObservation, "decoder_category",
                        property(unreadable), raising=False)
    projected = terminal(caplog, failure(detail))["tool_argument_decode"]
    assert "decoder_category" not in projected
    assert not POSITION_FIELDS.intersection(projected)
    assert projected["argument_characters"] == 10
    assert projected["finish_reason_category"] == "tool_calls"
    assert callbacks == []


def test_registered_enum_identity_ignores_mutated_value_and_name(monkeypatch, caplog):
    detail = observation()
    for category in (detail.decoder_category, detail.finish_reason_category):
        monkeypatch.setattr(category, "_value_", PRIVATE)
        monkeypatch.setattr(category, "_name_", PRIVATE)
    assert terminal(caplog, failure(detail))["tool_argument_decode"] == {
        "decoder_category": "json_syntax", "argument_characters": 10,
        "position": 5, "line": 2, "column": 3, "finish_reason_category": "tool_calls",
    }


@pytest.mark.parametrize("where", ["wrong_reason", "wrong_category", "completed"])
def test_argument_specific_details_are_not_projected_for_other_outcomes(caplog, where):
    error = failure(observation())
    if where == "wrong_reason":
        error.evidence = rt.ModelFailureEvidence("invalid_json", 200)
    elif where == "wrong_category":
        error.tool_call_error_category = rt.ToolCallErrorCategory.DUPLICATE_CALL_ID
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    log = logs.ModelRequestLog(timeout=2, bounded=True)
    log.finish("completed" if where == "completed" else "failed", failure=error)
    events = [ORIGINAL_LOADS(record.getMessage()) for record in caplog.records
              if record.name == logs.LOGGER_NAME]
    assert "tool_argument_decode" not in events[-1]
    assert PRIVATE not in json.dumps(events)


def test_legacy_failure_without_new_attribute_and_old_finish_signature(caplog):
    error = failure(None)
    del error.tool_argument_observation
    assert "tool_argument_decode" not in terminal(caplog, error)
    caplog.clear()
    log = logs.ModelRequestLog(timeout=None, bounded=False)
    log.finish("failed", response_status=503)
    events = [ORIGINAL_LOADS(record.getMessage()) for record in caplog.records
              if record.name == logs.LOGGER_NAME]
    assert events[-1]["reason"] == "local_error"
    assert events[-1]["response_status"] == 503
    assert "tool_argument_decode" not in events[-1]


@pytest.mark.parametrize("mutation", [
    "other_document", "bool_position", "negative_position", "oversized_position",
    "spoofed_line_column",
])
def test_decoder_position_requires_original_document_and_derives_its_own_coordinates(
    monkeypatch, caplog, mutation,
):
    callbacks = []
    damaged = '{\n "' + PRIVATE + '":}'
    position = len(damaged) - 1
    cause = json.JSONDecodeError(PRIVATE, damaged, position)
    if mutation == "other_document":
        other = damaged.encode().decode()
        assert other == damaged and other is not damaged
        cause.doc = other
    elif mutation == "bool_position":
        cause.pos = True
    elif mutation == "negative_position":
        cause.pos = -1
    elif mutation == "oversized_position":
        cause.pos = len(damaged) + 1
    elif mutation == "spoofed_line_column":
        cause.lineno = Hostile(callbacks)
        cause.colno = Hostile(callbacks)

    def rejected(value, *_args, **_kwargs):
        assert value is damaged
        raise cause

    monkeypatch.setattr(rt.json, "loads", rejected)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._parse_tool_calls([call("fixture", "fixture", damaged)])
    error = caught.value
    assert error.__cause__ is cause
    error.request_fingerprint = rt.ModelRequestFingerprint(11, "1" * 64)
    # Direct parser callers may omit status; the logging assertion below observes
    # the same failure after its local status has been explicitly supplied.
    error.evidence = rt.ModelFailureEvidence("invalid_tool_calls", 200)
    projected = terminal(caplog, error)["tool_argument_decode"]
    assert projected["decoder_category"] == "json_syntax"
    assert projected["argument_characters"] == len(damaged)
    if mutation == "spoofed_line_column":
        assert {key: projected[key] for key in POSITION_FIELDS} == {
            "position": position, "line": 2, "column": position - 1,
        }
    else:
        assert not POSITION_FIELDS.intersection(projected)
    assert callbacks == []


def test_decoder_subclass_does_not_supply_category_or_access_exception_properties(
    monkeypatch, caplog,
):
    callbacks = []
    damaged = "{" + PRIVATE

    class ForeignDecodeError(ValueError):
        @property
        def doc(self):
            callbacks.append("doc")
            raise AssertionError(PRIVATE)

        @property
        def pos(self):
            callbacks.append("pos")
            raise AssertionError(PRIVATE)

        def __str__(self):
            callbacks.append("str")
            raise AssertionError(PRIVATE)

    cause = ForeignDecodeError(PRIVATE)

    def rejected(value, *_args, **_kwargs):
        assert value is damaged
        raise cause

    monkeypatch.setattr(rt.json, "loads", rejected)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._parse_tool_calls(
            [call("fixture", "fixture", damaged)], response_status=200,
        )
    error = caught.value
    assert error.__cause__ is cause
    error.request_fingerprint = rt.ModelRequestFingerprint(11, "1" * 64)
    assert terminal(caplog, error)["tool_argument_decode"] == {
        "argument_characters": len(damaged),
    }
    assert callbacks == []


def test_string_subclass_is_not_inspected_for_argument_size_or_coordinates(monkeypatch, caplog):
    callbacks = []

    class ForeignText(str):
        def __len__(self):
            callbacks.append("length")
            raise AssertionError(PRIVATE)

        def count(self, *_args):
            callbacks.append("count")
            raise AssertionError(PRIVATE)

        def rfind(self, *_args):
            callbacks.append("rfind")
            raise AssertionError(PRIVATE)

    damaged = ForeignText("{" + PRIVATE)
    cause = json.JSONDecodeError(PRIVATE, "{", 1)
    cause.doc = damaged

    def rejected(value, *_args, **_kwargs):
        assert value is damaged
        raise cause

    monkeypatch.setattr(rt.json, "loads", rejected)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._parse_tool_calls(
            [call("fixture", "fixture", damaged)], response_status=200,
        )
    error = caught.value
    assert error.__cause__ is cause
    error.request_fingerprint = rt.ModelRequestFingerprint(11, "1" * 64)
    assert terminal(caplog, error)["tool_argument_decode"] == {"decoder_category": "json_syntax"}
    assert callbacks == []


@pytest.mark.parametrize("mutation", ["foreign_dictionary", "foreign_key", "oversized_storage"])
def test_exception_storage_cannot_supply_callbacks_or_unbounded_position_metadata(
    monkeypatch, caplog, mutation,
):
    callbacks = []
    damaged = "{" + PRIVATE
    cause = json.JSONDecodeError(PRIVATE, damaged, 1)

    class ForeignDict(dict):
        def get(self, *_args):
            callbacks.append("dict_get")
            raise AssertionError(PRIVATE)

        def __iter__(self):
            callbacks.append("dict_iter")
            raise AssertionError(PRIVATE)

    class ForeignKey(str):
        def __hash__(self):
            callbacks.append("key_hash")
            return 1

        def __eq__(self, _other):
            callbacks.append("key_eq")
            raise AssertionError(PRIVATE)

    if mutation == "foreign_dictionary":
        cause.__dict__ = ForeignDict(cause.__dict__)
    elif mutation == "foreign_key":
        cause.__dict__[ForeignKey(PRIVATE)] = PRIVATE
        callbacks.clear()
    else:
        cause.__dict__.update({f"extra-{index}": PRIVATE for index in range(17)})

    def rejected(value, *_args, **_kwargs):
        assert value is damaged
        raise cause

    monkeypatch.setattr(rt.json, "loads", rejected)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._parse_tool_calls(
            [call("fixture", "fixture", damaged)], response_status=200,
        )
    error = caught.value
    assert error.__cause__ is cause
    error.request_fingerprint = rt.ModelRequestFingerprint(11, "1" * 64)
    assert terminal(caplog, error)["tool_argument_decode"] == {
        "decoder_category": "json_syntax", "argument_characters": len(damaged),
    }
    assert callbacks == []


@pytest.mark.parametrize("seam", ["capture", "finish", "log"])
def test_optional_helper_failure_preserves_original_failure_and_cause(monkeypatch, caplog, seam):
    damaged = "{" + PRIVATE
    cause = json.JSONDecodeError(PRIVATE, damaged, 1)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError(PRIVATE)

    if seam == "capture":
        monkeypatch.setattr(rt, "_tool_argument_decode_observation", unavailable)

        def rejected(value, *_args, **_kwargs):
            assert value is damaged
            raise cause

        monkeypatch.setattr(rt.json, "loads", rejected)
        with pytest.raises(rt.ModelRequestFailure) as caught:
            rt.OpenAICompatibleRuntime._parse_tool_calls(
                [call("fixture", "fixture", damaged)], response_status=200,
            )
        error = caught.value
    else:
        error = failure(observation())
        error.__cause__ = cause
        if seam == "finish":
            monkeypatch.setattr(rt, "_add_tool_argument_finish_reason", unavailable)

            def rejected(*_args, **_kwargs):
                raise error

            monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_tool_calls", staticmethod(rejected))
            with pytest.raises(rt.ModelRequestFailure) as caught:
                rt.OpenAICompatibleRuntime._extract_turn({"choices": [{
                    "message": {"content": None, "tool_calls": []}, "finish_reason": "stop",
                }]}, response_status=200)
            assert caught.value is error
        else:
            monkeypatch.setattr(logs, "_tool_argument_decode_fields", unavailable)
    assert error.__cause__ is cause
    error.request_fingerprint = rt.ModelRequestFingerprint(11, "1" * 64)
    projected = terminal(caplog, error)
    if seam in {"capture", "log"}:
        assert "tool_argument_decode" not in projected
    else:
        assert projected["tool_argument_decode"]["finish_reason_category"] == "tool_calls"
