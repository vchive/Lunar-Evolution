"""Caller-owned binding DTOs cannot run callbacks while building cache tokens."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from lunar_evolution import producer_launcher as launcher
from lunar_evolution import producer_python_runtime as runtime
from lunar_evolution import producer_python_runtime_tree as closed
from lunar_evolution import python_producer_binding as binding

DEADLINE = 4102444800.0


@pytest.fixture(autouse=True)
def _isolated_caches_and_forbidden_observation(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("pure binding validation attempted filesystem observation")

    for name in ("_observe_directory", "_observe_file", "_observe_snapshot", "DirectoryChain"):
        monkeypatch.setattr(runtime, name, forbidden)
    monkeypatch.setattr(closed, "DirectoryChain", forbidden)
    for name in ("_stat_file", "_root", "_confined_file"):
        monkeypatch.setattr(launcher, name, forbidden)
    _clear_caches()
    yield
    _clear_caches()


def _clear_caches():
    with binding._VALIDATION_CACHE_LOCK:
        binding._RUNTIME_VALIDATION_CACHE.clear()
        binding._TREE_VALIDATION_CACHE.clear()


def _pure_material():
    """Build valid declarations using inert numbers, without observing a tree."""
    target = runtime.PythonRuntimeTarget("linux", "x86_64", "3.11", "cp311")
    pins = (
        runtime.PythonRuntimeDirectory("/", 1, 1, 0o755),
        runtime.PythonRuntimeDirectory("/inert", 1, 2, 0o755),
    )
    root = runtime.PythonRuntimeRoot("root", "/inert", 1, 2, 0o755, pins)
    files = tuple(sorted((
        runtime.PythonRuntimeFile("root", "python", "interpreter", 1, "1" * 64, 1, 3, 0o755, 0, 0),
        runtime.PythonRuntimeFile("root", "stdlib.py", "stdlib", 1, "2" * 64, 1, 4, 0o644, 0, 0),
        runtime.PythonRuntimeFile("root", "lock.txt", "dependency_lock", 1, "3" * 64, 1, 5, 0o644, 0, 0),
        runtime.PythonRuntimeFile("root", "main.py", "project_source", 1, "4" * 64, 1, 6, 0o644, 0, 0),
    ), key=lambda item: (item.root_label, item.relative_path)))
    entrypoint = runtime.PythonRuntimeFileDeclaration("root", "main.py", "project_source")
    values = {
        "target": target, "roots": (root,), "files": files, "import_roots": (),
        "entrypoint": entrypoint, **runtime._slot_digests(files), "manifest_sha256": "a" * 64,
    }
    prototype = object.__new__(runtime.PythonRuntimeManifest)
    for name, value in values.items():
        object.__setattr__(prototype, name, value)
    body = prototype.to_dict()
    body.pop("manifest_sha256")
    manifest = runtime.PythonRuntimeManifest(**{**values, "manifest_sha256": runtime._digest(body)})
    directory = closed.PythonRuntimeTreeDirectory(
        "root", ".", 1, 2, 0o755, 0, 0, tuple(sorted(item.relative_path for item in files)),
    )
    prototype = object.__new__(closed.PythonRuntimeTreeManifest)
    for name, value in {"declared_manifest": manifest, "directories": (directory,),
                        "tree_sha256": "a" * 64}.items():
        object.__setattr__(prototype, name, value)
    body = prototype.to_dict()
    body.pop("tree_sha256")
    tree = closed.PythonRuntimeTreeManifest(manifest, (directory,), closed._digest(body))
    return manifest, tree


def _pure_binding():
    manifest, tree = _pure_material()
    argv = ("python", "-I", "-S", "-B", "main.py")
    intent = launcher.ProducerLaunchIntent(
        launch_id="launch-1", journal_id="journal-1", run_id="run-1", parent_task_id="parent-1",
        task_id="task-1", contract_sha256="a" * 64, evaluator_kind="local",
        evaluator_fingerprint="b" * 64, runner_fingerprint="c" * 64,
        generator_fingerprint="d" * 64, dependency_sha256="e" * 64,
        environment_sha256="f" * 64, producer_id="fixture", producer_fingerprint="a" * 64,
        executable_root_label="root", executable_relative="python", executable_sha256="1" * 64,
        executable_size=1, executable_device=1, executable_inode=3,
        executable_mtime_ns=0, executable_ctime_ns=0, argv=argv,
        argv_sha256=hashlib.sha256(binding._canonical(list(argv))).hexdigest(),
        working_directory="work", output_directory="output", envelope_path="output/producer-result.json",
        request_timeout_seconds=5, max_requests=3, output_max_bytes=4096, wall_timeout_seconds=10,
    )
    intent = replace(intent, intent_sha256=intent.digest())
    attestation = launcher.build_producer_launch_attestation(intent, "nonce-1")
    return binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=DEADLINE, budget={"deadline_unix": DEADLINE, "max_solver_invocations": 3},
    )


def _construct_again(item, **overrides):
    values = {
        name: getattr(item, name) for name in (
            "runtime_manifest", "runtime_tree", "intent", "attestation", "fixture_case",
            "deadline_unix", "request_budget", "output_max_bytes", "wall_timeout_seconds",
            "broker_policy", "binding_sha256", "schema_version", "protocol",
        )
    }
    return binding.PythonProducerBinding(**{**values, **overrides})


def _foreign(events, mode):
    class Meta(type):
        def __hash__(cls):
            events.append("metaclass-hash")
            if mode == "hash":
                raise AssertionError("foreign metaclass hash")
            return hash(str)

        def __eq__(cls, other):
            events.append("metaclass-equality")
            raise AssertionError("foreign metaclass equality")

    class Foreign(metaclass=Meta):
        def __getattribute__(self, name):
            events.append("attribute")
            raise AssertionError("foreign attribute access")

        def __iter__(self):
            events.append("iterate")
            raise AssertionError("foreign iteration")

        def __str__(self):
            events.append("string")
            raise AssertionError("foreign string conversion")

        def __float__(self):
            events.append("float")
            raise AssertionError("foreign float conversion")

    return Foreign()


def test_valid_pure_binding_tokens_and_public_roundtrip_remain_stable():
    item = _pure_binding()
    other = _pure_binding()
    for name in ("runtime_manifest", "runtime_tree"):
        source = getattr(item, name)
        token = binding._safe_validation_token(source)
        assert token is not None
        assert token == binding._safe_validation_token(source)
        assert token == binding._safe_validation_token(getattr(other, name))
    wire = item.to_json()
    assert binding.parse_python_producer_binding(wire) == item
    assert item.to_json() == wire
    assert item.digest() == item.binding_sha256


def test_valid_binding_with_no_token_reparses_without_reading_or_populating_cache(monkeypatch):
    item = _pure_binding()
    wire = item.to_json()
    digest = item.digest()
    calls = []
    runtime_parser = binding.parse_python_runtime_manifest
    tree_parser = binding.parse_python_runtime_tree_manifest

    def parse_runtime(value):
        calls.append("runtime")
        return runtime_parser(value)

    def parse_tree(value):
        calls.append("tree")
        return tree_parser(value)

    monkeypatch.setattr(binding, "_safe_validation_token", lambda _value: None)
    monkeypatch.setattr(binding, "parse_python_runtime_manifest", parse_runtime)
    monkeypatch.setattr(binding, "parse_python_runtime_tree_manifest", parse_tree)
    for populated in (True, False):
        if not populated:
            _clear_caches()
        before = [dict(cache) for cache in (
            binding._RUNTIME_VALIDATION_CACHE, binding._TREE_VALIDATION_CACHE,
        )]
        assert all(bool(cache) is populated for cache in before)
        calls.clear()
        assert item.to_json() == wire
        assert item.digest() == digest
        assert calls == ["runtime", "tree", "runtime", "tree"]
        for cache, original in zip((binding._RUNTIME_VALIDATION_CACHE, binding._TREE_VALIDATION_CACHE),
                                   before, strict=True):
            assert cache.keys() == original.keys()
            assert all(cache[key] is entry for key, entry in original.items())


@pytest.mark.parametrize("target", ["runtime", "tree"])
@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("entry", ["constructor", "to_json"])
@pytest.mark.parametrize("mode", ["hash", "hash-collision"])
def test_tampered_dto_refuses_without_foreign_callbacks_or_stale_cache(target, warm, entry, mode):
    item = _pure_binding()
    if warm:
        item.to_json()
    else:
        _clear_caches()
    events = []
    foreign = _foreign(events, mode)
    source = item.runtime_manifest if target == "runtime" else item.runtime_tree
    field = "target" if target == "runtime" else "declared_manifest"
    cache = binding._RUNTIME_VALIDATION_CACHE if target == "runtime" else binding._TREE_VALIDATION_CACHE
    before = cache.get(id(source))
    object.__setattr__(source, field, foreign)
    assert binding._safe_validation_token(source) is None
    with pytest.raises(binding.PythonProducerBindingError, match=f"^python_producer_binding_runtime_{'manifest' if target == 'runtime' else 'tree'}_invalid$"):
        _construct_again(item) if entry == "constructor" else item.to_json()
    assert cache.get(id(source)) is before
    assert events == []


@pytest.mark.parametrize("target", ["runtime", "tree"])
@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("entry", ["constructor", "to_json"])
def test_cyclic_tampered_dto_falls_back_to_fixed_public_refusal(target, warm, entry):
    item = _pure_binding()
    if warm:
        item.to_json()
    else:
        _clear_caches()
    source = item.runtime_manifest if target == "runtime" else item.runtime_tree
    field = "target" if target == "runtime" else "declared_manifest"
    object.__setattr__(source, field, source)
    assert binding._safe_validation_token(source) is None
    with pytest.raises(binding.PythonProducerBindingError, match=f"^python_producer_binding_runtime_{'manifest' if target == 'runtime' else 'tree'}_invalid$"):
        _construct_again(item) if entry == "constructor" else item.to_json()


@pytest.mark.parametrize("depth,accepted", [(48, True), (49, False)])
@pytest.mark.parametrize("leaf", [None, ()])
def test_private_token_depth_bound_includes_scalar_and_empty_tuple(depth, accepted, leaf):
    value = leaf
    for _ in range(depth):
        value = (value,)
    assert (binding._safe_validation_token(value) is not None) is accepted


@pytest.mark.parametrize("children,accepted", [(99_999, True), (100_000, False)])
def test_private_token_node_bound_counts_root_and_each_scalar(children, accepted):
    assert (binding._safe_validation_token((None,) * children) is not None) is accepted


@pytest.mark.parametrize("copies,accepted", [(999, True), (1000, False)])
def test_private_token_counts_shared_subtree_at_every_occurrence(copies, accepted):
    shared = (None,) * 99
    # Root plus copies of (one tuple + 99 scalar leaves): 99,901 / 100,001 nodes.
    assert (binding._safe_validation_token((shared,) * copies) is not None) is accepted


@pytest.mark.parametrize("base", [str, int, float, bytes, tuple])
def test_private_token_subclasses_are_not_tokenizable(base):
    class Child(base):
        def __iter__(self):
            raise AssertionError("subclass iteration")

    assert binding._safe_validation_token(Child()) is None


@pytest.mark.parametrize("boundary", ["wire", "deadline", "budget"])
@pytest.mark.parametrize("mode", ["hash", "hash-collision"])
def test_public_wire_deadline_and_budget_reject_foreign_types_before_callbacks(boundary, mode):
    item = _pure_binding()
    events = []
    foreign = _foreign(events, mode)
    expected = {"wire": "json_invalid", "deadline": "deadline_invalid", "budget": "budget_shape_invalid"}
    with pytest.raises(binding.PythonProducerBindingError, match="^python_producer_binding_" + expected[boundary] + "$"):
        if boundary == "wire":
            binding.parse_python_producer_binding(foreign)
        elif boundary == "deadline":
            _construct_again(item, deadline_unix=foreign)
        else:
            binding.build_python_producer_binding(
                runtime_manifest=item.runtime_manifest, runtime_tree=item.runtime_tree,
                intent=item.intent, attestation=item.attestation, deadline_unix=DEADLINE,
                budget={"deadline_unix": DEADLINE, "max_solver_invocations": foreign},
            )
    assert events == []


@pytest.mark.parametrize("boundary", ["wire", "deadline", "budget"])
def test_public_wire_deadline_and_budget_keep_bool_refusal(boundary):
    item = _pure_binding()
    expected = {"wire": "json_invalid", "deadline": "deadline_invalid", "budget": "budget_shape_invalid"}
    with pytest.raises(binding.PythonProducerBindingError, match="^python_producer_binding_" + expected[boundary] + "$"):
        if boundary == "wire":
            binding.parse_python_producer_binding(True)
        elif boundary == "deadline":
            _construct_again(item, deadline_unix=True)
        else:
            binding.build_python_producer_binding(
                runtime_manifest=item.runtime_manifest, runtime_tree=item.runtime_tree,
                intent=item.intent, attestation=item.attestation, deadline_unix=DEADLINE,
                budget={"deadline_unix": DEADLINE, "max_solver_invocations": True},
            )
