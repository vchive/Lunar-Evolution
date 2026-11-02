"""Opt-in subject stderr diagnostics with inert adapters and no model/evaluator calls."""

import argparse
import json
import logging
import re

import pytest

from lunar_evolution import cli
from lunar_evolution.model_request_logging import ModelRequestLog


def _logger_state(logger):
    return (logger.level, logger.disabled, logger.propagate,
            tuple(logger.handlers), tuple(logger.filters))


@pytest.fixture
def isolated_request_logger():
    logger = logging.getLogger("lunar_evolution.model_requests")
    original = _logger_state(logger)
    logger.setLevel(logging.WARNING)
    logger.disabled = False
    logger.propagate = False
    logger.handlers = [logging.NullHandler()]
    logger.filters = []
    try:
        yield logger
    finally:
        level, disabled, propagate, handlers, filters = original
        logger.setLevel(level)
        logger.disabled = disabled
        logger.propagate = propagate
        logger.handlers = list(handlers)
        logger.filters = list(filters)


def _completed_request():
    request_log = ModelRequestLog(timeout=1, bounded=True)
    request_log.finish("completed")


def _assert_request_lines(stderr, enabled):
    lines = stderr.splitlines()
    if not enabled:
        assert lines == []
        return
    records = [json.loads(line) for line in lines]
    assert [record["event"] for record in records] == [
        "model_request_started", "model_request_completed",
    ]
    request_ids = {record["request_id"] for record in records}
    assert len(request_ids) == 1
    assert re.fullmatch(r"[0-9a-f]{32}", request_ids.pop())
    for record in records:
        assert record["schema_version"] == "1"
        assert record["transport"] == "bounded"
        assert record["request_timeout_ms"] == 1000
        assert type(record["elapsed_ms"]) is int and record["elapsed_ms"] >= 0


def test_model_request_log_flag_defaults_off_and_is_subject_only():
    parser = cli.build_parser()
    assert parser.parse_args(["effect-subject", "request.json"]).model_request_log is False
    assert parser.parse_args([
        "effect-subject", "request.json", "--model-request-log",
    ]).model_request_log is True
    commands = next(action for action in parser._actions
                    if isinstance(action, argparse._SubParsersAction)).choices
    assert {name for name, command in commands.items()
            if "--model-request-log" in command._option_string_actions} == {"effect-subject"}


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_subject_request_logs_preserve_stdout_protocol_and_logger_configuration(
    tmp_path, monkeypatch, capsys, isolated_request_logger, enabled, json_mode,
):
    logger = isolated_request_logger
    before = _logger_state(logger)
    root_before = _logger_state(logging.getLogger())
    request = tmp_path / "unread-request.json"
    payload = {"status": "completed", "interaction_turns": 1}
    calls = []
    endpoint = "https://private-endpoint.invalid/CLI-ENDPOINT-SENTINEL"
    model = "CLI-MODEL-SENTINEL"
    api_key = "CLI-API-KEY-SENTINEL"

    def adapter(request_path, **kwargs):
        calls.append((request_path, kwargs))
        _completed_request()
        return payload

    monkeypatch.setattr(cli, "run_subject_adapter", adapter)
    arguments = [
        "effect-subject", str(request), "--endpoint", endpoint,
        "--model", model, "--api-key", api_key, "--no-exec",
    ]
    if enabled:
        arguments.append("--model-request-log")
    if json_mode:
        arguments.append("--json")
    assert cli.main(arguments) == 0
    captured = capsys.readouterr()
    expected = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" if json_mode
                else "status: completed\ninteraction_turns: 1\n")
    assert captured.out == expected
    _assert_request_lines(captured.err, enabled)
    assert calls == [(request, {
        "endpoint": endpoint, "model": model, "api_key": api_key, "max_steps": 100,
        "allow_exec": False, "timeout": None, "model_profile": None,
        "workflow_config": None, "session_history": False,
    })]
    assert not request.exists()
    assert all(secret not in captured.out + captured.err for secret in (endpoint, model, api_key))
    assert _logger_state(logger) == before
    assert _logger_state(logging.getLogger()) == root_before
    logger.info("AFTER-CONTEXT-SENTINEL")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("enabled", [False, True])
def test_subject_adapter_exception_restores_logger_and_preserves_original_cause(
    tmp_path, monkeypatch, capsys, isolated_request_logger, enabled,
):
    logger = isolated_request_logger
    before = _logger_state(logger)
    root_before = _logger_state(logging.getLogger())
    cause = OSError("PRIVATE-CAUSE-SENTINEL")
    original = RuntimeError("PRIVATE-ADAPTER-ERROR-SENTINEL")

    def adapter(*args, **kwargs):
        _completed_request()
        raise original from cause

    monkeypatch.setattr(cli, "run_subject_adapter", adapter)
    arguments = ["effect-subject", str(tmp_path / "unread-request.json"), "--json"]
    if enabled:
        arguments.append("--model-request-log")
    with pytest.raises(RuntimeError) as caught:
        cli.main(arguments)
    assert caught.value is original and caught.value.__cause__ is cause
    captured = capsys.readouterr()
    assert captured.out == ""
    _assert_request_lines(captured.err, enabled)
    assert "PRIVATE-CAUSE-SENTINEL" not in captured.err
    assert "PRIVATE-ADAPTER-ERROR-SENTINEL" not in captured.err
    assert _logger_state(logger) == before
    assert _logger_state(logging.getLogger()) == root_before
