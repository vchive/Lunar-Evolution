"""Provider-free replay of the static-Python two-input report composition.

This joins the original create-only RSI input descriptor, its two exact grant
proposals, the source-level input-report fixture and the detached input/result
cross-pin parser.  It deliberately does not claim that a sealed runtime ran or
that either input was consumed by an authoritative producer.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Self

import pytest

from lunar_evolution.native_grant_inputs import original_native_grant_inputs
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_inputs import prepare_native_rsi_inputs
from lunar_evolution.static_python_input_result import (
    INPUT_REPORT_SCHEMA,
    INPUT_RESULT_SCHEMA,
    StaticPythonInputResultError,
    parse_static_python_input_result,
)

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "tools/static_python_rsi_fixture/assets/input_read_report.py"
_COMPARATOR = _ROOT / "tools/static_python_rsi_fixture/input_read_report.py"
_REQUEST_PATH = "../.rsi-input/request.json"
_MEMORY_PATH = "../.rsi-input/memory.json"
_READ_SIZE = 128 * 1024 + 1


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _report_api():
    name = "lunar_static_python_input_read_report_fixture"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, _COMPARATOR)
        if spec is None or spec.loader is None:
            raise RuntimeError("static input report comparator unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


class _GrantFile:
    def __init__(self, path: str, content: bytes, events: list[tuple[str, str, int]]) -> None:
        self.path = path
        self.content = content
        self.events = events

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def read(self, size: int) -> bytes:
        assert type(size) is int and size == _READ_SIZE
        self.events.append(("read", self.path, size))
        return self.content

    def close(self) -> None:
        self.events.append(("close", self.path, 0))


def _run_source_report(manifest_sha256: str, request: bytes, memory: bytes) -> tuple[bytes, list]:
    """Run only the inert report source with `open` routed to retained grant bytes."""
    tree = ast.parse(_SOURCE.read_bytes())
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    materials = {_REQUEST_PATH: request, _MEMORY_PATH: memory}
    events: list[tuple[str, str, int]] = []

    def grant_open(path: object, mode: object, *args: object, **kwargs: object) -> _GrantFile:
        assert type(path) is str and path in materials
        assert mode == "rb" and not args and not kwargs
        if any(kind == "open" and opened == path for kind, opened, _size in events):
            raise AssertionError("the report source may consume each original grant once")
        events.append(("open", path, 0))
        return _GrantFile(path, materials[path], events)

    safe_builtins = dict(vars(builtins))
    safe_builtins.update({
        "open": grant_open,
        "__import__": lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("the source report must not import modules")
        ),
        "compile": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
        "eval": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
        "exec": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
        "input": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
        "print": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    })
    namespace = {"__builtins__": safe_builtins}
    exec(compile(tree, "<inert-static-input-report>", "exec"), namespace)  # noqa: S102
    result = namespace["read_input_report"](manifest_sha256)
    assert type(result) is bytes
    return result, events


@pytest.fixture
def original_inputs(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = EMPTY_MEMORY_SNAPSHOT
    request = SolverRequest.build(
        episode_id="input-result-replay-episode",
        contract_sha256=_sha("contract"), evaluator_sha256=_sha("evaluator"),
        environment_sha256=_sha("environment"), memory_snapshot_sha256=memory.digest(),
        solver_id="native_population", solver_settings={"width": 1},
    )
    descriptor = prepare_native_rsi_inputs(
        workspace, journal_id="input-result-replay", request=request, memory=memory,
    )
    grants = original_native_grant_inputs(descriptor)
    return descriptor, request, memory, grants


def _result_wire(descriptor, match) -> tuple[bytes, dict[str, object]]:
    pins: dict[str, object] = {
        "expected_startup_sha256": _sha("detached-startup-fixture"),
        "expected_build_closure_sha256": _sha("detached-build-fixture"),
        "expected_binding_sha256": _sha("detached-binding-fixture"),
        "expected_launch_intent_sha256": _sha("detached-launch-intent-fixture"),
        "expected_manifest_sha256": descriptor.manifest_sha256,
        "expected_report_sha256": match.report_sha256,
        "expected_request_sha256": match.request_sha256,
        "expected_memory_sha256": match.memory_sha256,
        "expected_request_size": match.request_size,
        "expected_memory_size": match.memory_size,
    }
    payload = {
        "schema": INPUT_RESULT_SCHEMA,
        "startup_sha256": pins["expected_startup_sha256"],
        "build_closure_sha256": pins["expected_build_closure_sha256"],
        "binding_sha256": pins["expected_binding_sha256"],
        "launch_intent_sha256": pins["expected_launch_intent_sha256"],
        "input_report_schema": INPUT_REPORT_SCHEMA,
        "manifest_sha256": pins["expected_manifest_sha256"],
        "report_sha256": pins["expected_report_sha256"],
        "request_sha256": pins["expected_request_sha256"],
        "memory_sha256": pins["expected_memory_sha256"],
        "request_size": pins["expected_request_size"],
        "memory_size": pins["expected_memory_size"],
        "computed": 285,
        "claims": {
            "input_authority_verified": False,
            "runtime_execution_verified": False,
            "solver_result_accepted": False,
            "memory_use_verified": False,
            "production_admission": False,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return raw, pins


def test_two_original_grants_replay_into_digest_only_cross_pin_projection(original_inputs):
    descriptor, request, memory, grants = original_inputs
    assert tuple(Path(item.path).name for item in grants.requests) == ("request.json", "memory.json")
    assert tuple(item.path for item in grants.requests) == tuple(
        str(path) for path in descriptor.read_paths
    )
    assert tuple(item.content for item in grants.materials) == (
        descriptor.request_json, descriptor.memory_json,
    )
    assert descriptor.request.digest() == request.digest()
    assert descriptor.memory.digest() == memory.digest()

    report_api = _report_api()
    raw_report, events = _run_source_report(
        descriptor.manifest_sha256,
        grants.materials[0].content,
        grants.materials[1].content,
    )
    assert [(kind, path) for kind, path, _size in events if kind == "open"] == [
        ("open", _REQUEST_PATH), ("open", _MEMORY_PATH),
    ]
    assert [(path, size) for kind, path, size in events if kind == "read"] == [
        (_REQUEST_PATH, _READ_SIZE), (_MEMORY_PATH, _READ_SIZE),
    ]
    assert _COMPARATOR.is_file()
    matched = report_api.compare_input_read_report(
        raw_report, expected_manifest_sha256=descriptor.manifest_sha256,
        expected_request=grants.materials[0].content,
        expected_memory=grants.materials[1].content,
    )
    result_raw, expected = _result_wire(descriptor, matched)
    result = parse_static_python_input_result(result_raw, **expected)

    assert result.report_sha256 == hashlib.sha256(raw_report).hexdigest()
    assert result.request_sha256 == request.digest()
    assert result.memory_sha256 == memory.digest()
    assert result.request_size == len(descriptor.request_json)
    assert result.memory_size == len(descriptor.memory_json)
    assert result.computed == 285
    assert all(value is False for value in result.to_dict()["claims"].values())
    assert not any(hasattr(result, name) for name in ("request", "memory", "solver_result"))


@pytest.mark.parametrize("mutation", ["marker", "request_bytes", "memory_bytes"])
def test_report_replay_refuses_marker_or_original_grant_drift(original_inputs, mutation):
    descriptor, _request, _memory, grants = original_inputs
    report_api = _report_api()
    request = grants.materials[0].content
    memory = grants.materials[1].content
    marker = descriptor.manifest_sha256
    if mutation == "marker":
        marker = _sha("foreign-marker")
    elif mutation == "request_bytes":
        request += b" "
    else:
        memory += b" "
    raw_report, _events = _run_source_report(marker, request, memory)
    with pytest.raises(report_api.InputReadReportError):
        report_api.compare_input_read_report(
            raw_report, expected_manifest_sha256=descriptor.manifest_sha256,
            expected_request=grants.materials[0].content,
            expected_memory=grants.materials[1].content,
        )


def test_cross_pin_parser_refuses_request_digest_changed_after_report_match(original_inputs):
    descriptor, _request, _memory, grants = original_inputs
    report_api = _report_api()
    raw_report, _events = _run_source_report(
        descriptor.manifest_sha256, grants.materials[0].content, grants.materials[1].content,
    )
    matched = report_api.compare_input_read_report(
        raw_report, expected_manifest_sha256=descriptor.manifest_sha256,
        expected_request=grants.materials[0].content,
        expected_memory=grants.materials[1].content,
    )
    raw, expected = _result_wire(descriptor, matched)
    payload = json.loads(raw)
    payload["request_sha256"] = _sha("foreign-request")
    forged = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(StaticPythonInputResultError, match="cross_pin"):
        parse_static_python_input_result(forged, **expected)
