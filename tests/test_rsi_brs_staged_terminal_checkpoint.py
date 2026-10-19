"""Real BRS owner success CAS over synthetic retained files; no producer transaction.

The original native context and PopulationStrategy are genuine DTOs. Candidate,
preflight, manifest and terminal files are inert fixture bytes written explicitly;
the publication transaction, evaluator, subprocess and network boundaries refuse.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace

import pytest
import test_rsi_brs_publication_lineage_owner as fixture
import test_rsi_python_admission as admission
from test_algorithm import _contract
from test_rsi_python_scheduler_inputs import _inert_bootstrap

from lunar_evolution import RSILearningError
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution import rsi_python_scheduler_inputs as scheduler_inputs
from lunar_evolution.algorithm import AlgorithmProblemContract, EvaluationReport
from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import (
    Candidate,
    EvolutionConfig,
    EvolutionContext,
    PopulationStrategy,
)
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_lineage import (
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    persist_lineage_descriptor,
    persist_lineage_snapshot,
)
from lunar_evolution.producer_bundle_preflight import (
    compute_archive_prefix_digest,
    derive_producer_bundle_candidate_id,
    preflight_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_receipts import _collect_retained_evidence
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerContext
from lunar_evolution.rsi_producer_gateway import PythonProducerRSIExecutionConfig
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerInputContext


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("s")


def _forbidden(*_args, **_kwargs):
    pytest.fail("success checkpoint fixture invoked execution/publication")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    for module, names in (
        (subprocess, ("Popen", "run")), (socket, ("create_connection",)),
        (transaction, ("run_native_producer_bundle_publication_transaction",)),
        # Keep canonical stage/commit function identities bound for the policy
        # fingerprint while blocking any unexpected staging side effect below
        # their stable internal helpers.  `_load_manifest` remains readable so
        # success facades can inspect their explicitly written inert fixture.
        (staging, ("_journal_for_stage", "_verify_stage")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)


def _native_setup(tmp_path, monkeypatch, *, task_bound=True, bundle=False):
    contract = AlgorithmProblemContract.from_dict(_contract(evolution={"strategy": "population"}))
    sources = {"solve/main.py": b"# inert\n", "helper.py": b"# helper\n"}
    bundle_plan = CandidateSourceBundle(contract.digest(), "solve/main.py",
        tuple(CandidateSourceFile(name, len(raw), _sha(raw)) for name, raw in sources.items())) if bundle else None
    original = admission._fixture

    def bound(root):
        manifest, tree, intent, attestation, budget = original(root)
        intent = replace(intent, contract_sha256=contract.digest(), producer_id="openevolve", intent_sha256=None,
            task_id=intent.run_id + "-practice-0-0" if task_bound else intent.task_id,
            **{name: contract.digest() for name in ("evaluator_fingerprint", "runner_fingerprint",
                "generator_fingerprint", "dependency_sha256", "environment_sha256")})
        intent = replace(intent, intent_sha256=intent.digest())
        return manifest, tree, intent, attestation, budget

    monkeypatch.setattr(admission, "_fixture", bound)
    monkeypatch.setattr(admission, "DIGEST", contract.digest())
    monkeypatch.setattr(fixture, "DIGEST", bundle_plan.digest() if bundle else contract.digest())
    if bundle:
        original_item = fixture.ProducerBundleAdmissionItem
        def planned_item(*args, **kwargs):
            return replace(original_item(*args, **kwargs), entrypoint=bundle_plan.entrypoint,
                material_paths=tuple(item.path for item in bundle_plan.files))
        monkeypatch.setattr(fixture, "ProducerBundleAdmissionItem", planned_item)
    monkeypatch.setattr(fixture.selected, "DIGEST", contract.digest())
    value = fixture._setup(tmp_path, monkeypatch)
    binding = value.binding
    config = EvolutionConfig(
        strategy="population", evaluator_kind=binding.evaluator_kind,
        evaluator_fingerprint=binding.evaluator_fingerprint,
        runner_fingerprint=binding.intent.runner_fingerprint,
        generator_fingerprint=binding.intent.generator_fingerprint,
        dependency_sha256=binding.dependency_sha256, environment_sha256=binding.environment_sha256,
    )
    state = value.workspace / "evolution/state.json"
    state.write_bytes(canonical_json({"strategy": "population", "config": config.to_dict()}))
    strategy = PopulationStrategy(EvolutionContext(
        contract=contract, workspace=value.workspace, generate=_forbidden, evaluate=_forbidden, config=config,
    ), read_only=True)
    base = strategy._state_payload("running", 0, active_ids={"0": []}, stagnation=0,
        best_candidate_id=None, rng_seed=config.rng_seed, last_migration_iteration=0, error=None)
    state.write_bytes(canonical_json(base))
    value.journal = replace(value.journal,
        base_state_sha256=_sha(state.read_bytes()), population_config_sha256=_sha(canonical_json(config.to_dict())),
        archive_prefix_sha256=compute_archive_prefix_digest(_sha(b""), _sha(state.read_bytes()),
            strategy_config_sha256=_sha(canonical_json(config.to_dict())), active_ids_sha256=_sha(canonical_json({"0": []}))),
        candidates=tuple(replace(candidate, bundle_sha256=bundle_plan.digest() if bundle else candidate.bundle_sha256,
            candidate_id=derive_producer_bundle_candidate_id(value.journal.journal_id, index, candidate.bundle_id,
                bundle_plan.digest() if bundle else candidate.bundle_sha256))
            for index, candidate in enumerate(value.journal.candidates)), journal_sha256=None)
    (value.batch / "journal.prepared.json").write_bytes(_intent_content(value.journal)[0])
    native = NativeRSISchedulerContext(
        workspace=value.workspace,
        producer_root=next(Path(root.path) for root in binding.runtime_manifest.roots
                           if root.label == binding.interpreter.root_label),
        intent=binding.intent, attestation=binding.attestation, artifact=_inert_bootstrap(value.workspace),
        broker_config=ProducerBrokerConfig("http://127.0.0.1:9/unused", {}), contract=contract,
        groups=(BundleGroup("bundle-1", bundle_plan.entrypoint if bundle else "main.py",
            tuple(item.path for item in bundle_plan.files) if bundle else ("main.py",)),),
        evaluator_kind=binding.evaluator_kind, evaluator_fingerprint=binding.evaluator_fingerprint,
        runner_fingerprint=binding.intent.runner_fingerprint, dependency_sha256=binding.dependency_sha256,
        environment_sha256=binding.environment_sha256, strategy=strategy, failure_ledger=value.ledger,
        python_handoff_after_execution=_forbidden,
    )
    inputs = PythonRSISchedulerInputContext(native, value.sidecar, value.proof)
    value.gateway.producer_config = PythonProducerRSIExecutionConfig("openevolve", value.ledger, inputs)
    value.strategy, value.native, value.bundle_plan, value.bundle_sources = strategy, native, bundle_plan, sources
    return value


@contextmanager
def _waiting(tmp_path, monkeypatch, *, native=True, task_bound=True, bundle=False):
    original = fixture._setup
    if native:
        # The native inputs exist before owner construction. They are test-only
        # inert gateway configuration and never route a gateway call to a solver.
        def setup(root, patch):
            with monkeypatch.context() as nested:
                nested.setattr(fixture, "_setup", original)
                return _native_setup(root, patch, task_bound=task_bound, bundle=bundle)
        monkeypatch.setattr(fixture, "_setup", setup)
    with fixture._waiting(tmp_path, monkeypatch) as value:
        wire = fixture._before(value)
        value.owner.checkpoint_before(wire)
        record = fixture._pin(value)
        value.owner.acknowledge_prepared(value.journal, record)
        yield value


def _staged(value, *, bad_projection=False, record_mismatch=False, bundle_fault=None):
    wire = deepcopy(value.wave.state["producer_publication_lineage"])
    entry, strategy = wire["batches"][0], value.strategy
    candidate = value.journal.candidates[0]
    root = f"evolution/candidates/{candidate.candidate_id}"
    bundle = value.bundle_plan
    if bundle is not None and bundle_fault == "bundle-digest":
        bundle = replace(bundle, files=tuple(replace(item, sha256="f" * 64) for item in bundle.files))
    code = "unlisted.py" if bundle_fault == "entrypoint" else bundle.entrypoint if bundle else "main.py"
    record = Candidate(candidate.candidate_id, root + "/" + code,
        None, 0, 0, "population", 0, EvaluationReport("1", "inert", 1, 1.0, {}, (), quality=1.0),
        metadata={"producer_bundle": {}}, created_at=0.0,
        source_sha256=_sha(b"# inert\n") if bundle else None,
        receipt_sha256="c" * 64 if bundle else None, integrity={} if bundle else None,
        bundle_evidence={"protocol": "lunar-population-bundle-v1", "source_root": root,
            "bundle_path": root + "/bundle-manifest.json", "bundle_sha256": bundle.digest(),
            "run_root": "evolution/bundle-attempts/.bundle-run-" + "a" * 24,
            "evaluation_path": "evolution/bundle-attempts/.bundle-run-" + "a" * 24 + "/evaluations/.candidate-evaluation-" + "b" * 24,
            **{name: "d" * 64 for name in ("plan_sha256", "admission_sha256", "completion_sha256", "evaluation_sha256")}} if bundle else None)
    record_bytes = canonical_json(record.to_dict())
    if record_mismatch:
        # Keep retained record/receipt/material bytes unchanged while fabricating
        # a coherent archive/state projection for the same candidate identity.
        record = replace(record, metadata={"producer_bundle": {}, "fabricated": True})
    receipt = canonical_json({"publication_receipt_sha256": "c" * 64})
    candidate_root = value.batch / "stage/candidates" / candidate.candidate_id
    sidecar = "solve/" if bundle else ""
    contents = {sidecar + "record.json": record_bytes, sidecar + "receipt.json": receipt,
                **(value.bundle_sources if bundle else {"main.py": b"# inert\n"})}
    if bundle:
        contents["bundle-manifest.json"] = canonical_json(bundle.to_dict())
        if bundle_fault in {"source-size", "source-sha"}:
            contents["helper.py"] = (b"# coherent descriptor, different bundle declaration\n"
                                     if bundle_fault == "source-size" else b"# change\n")
    for name, raw in contents.items():
        _write(candidate_root / name, raw)
    binding = value.batch / "native-drafts" / candidate.candidate_id / "draft-binding.json"
    _write(binding, canonical_json({"protocol": "lunar-native-draft-binding-v1", "ordinal": 0,
        "journal_id": value.journal.journal_id, "journal_sha256": value.journal.digest(),
        **{name: getattr(candidate, name) for name in ("candidate_id", "bundle_id", "bundle_sha256",
                                                    "parent_id", "generation", "iteration", "island_id")}}))
    retained = _collect_retained_evidence(value.workspace, (binding, value.batch / "journal.prepared.json"))
    evidence = canonical_json(retained)
    _write(candidate_root / (sidecar + "retained.json"), evidence)
    contents[sidecar + "retained.json"] = evidence
    staged = replace(value.journal, state="publishing", publication_phase="staged", journal_sha256=None,
        candidates=(replace(candidate, status="admitted", execution_receipt_sha256="e" * 64,
                            evaluation_receipt_sha256="d" * 64, publication_receipt_sha256="c" * 64),))
    preflight = preflight_producer_bundle_publication(value.workspace, value.admission, value.journal)
    _write(value.batch / "preflight.json", canonical_json(preflight.to_dict()))
    base = json.loads((value.workspace / "evolution/state.json").read_bytes())
    projection = deepcopy(base)
    projection["producer_admissions"] = {"schema_version": "1", "events": [
        {"after_iteration": 0, "candidate_ids": [candidate.candidate_id]},
    ]}
    active, best, migration, stagnation = strategy._reconstruct_population_projection(projection, [record])
    projection.update(active_ids={str(key): item for key, item in active.items()}, best_candidate_id=best,
        last_migration_iteration=migration, stagnation=stagnation,
        candidate_archive_sha256=_sha(canonical_json([record.to_dict()])))
    if bad_projection:
        projection["best_candidate_id"] = "foreign"
    archive, state = canonical_json(record.to_dict()) + b"\n", canonical_json(projection)
    _write(value.batch / "stage/archive.jsonl", archive)
    _write(value.batch / "stage/state.json", state)
    _write(value.batch / "journal.staged.json", canonical_json(staged.to_dict()))
    descriptors = [{"path": name, "size": path.stat().st_size, "sha256": _sha(path.read_bytes())}
                   for name in contents
                   for path in (candidate_root / name,)]
    manifest = staging.ProducerBundlePublicationManifest(staged.journal_id, staged.digest(), preflight.digest(),
        staged.base_archive_sha256, staged.base_state_sha256, _sha(archive), _sha(state), (candidate.candidate_id,),
        ({"candidate_id": candidate.candidate_id, "paths": descriptors, "record_sha256": _sha(record_bytes),
          "receipt_sha256": _sha(receipt), "retained_evidence": {"path": sidecar + "retained.json", "sha256": _sha(evidence),
                                                                  "evidence_sha256": retained["evidence_sha256"]}},))
    _write(value.batch / "manifest.json", canonical_json(manifest.to_dict()))
    pins, sources = {}, {}
    for name, raw in (("archive", archive), ("state", state)):
        path = value.batch / "stage" / (name + (".jsonl" if name == "archive" else ".json"))
        source = capture_lineage_snapshot_pin(path, name=name + "-after")
        _path, pin = persist_lineage_snapshot(value.workspace, staged.journal_id,
            name=name + "-after", source=path, expected_pin=source, retained_bytes=0)
        pins[name + "-after"], sources[name] = pin.to_dict(), source.to_dict()
    transition = ProducerLineageStagedTransition(value.binding.run_id, staged.journal_id, 0,
        entry["before"]["descriptor_sha256"], staged.digest(), manifest.digest(), _sha(archive), _sha(state),
        (candidate.candidate_id,))
    _path, pin = persist_lineage_descriptor(value.workspace, transition)
    entry.update(state="staged", staged=transition.to_dict(), staged_file_pin=pin.to_dict(),
        state_projection_sha256=_sha(state), after_sources=sources)
    entry["snapshots"].update(pins)
    for name in ("journal.staged.json", "manifest.json", "preflight.json"):
        entry["evidence_pins"][name] = capture_lineage_snapshot_pin(value.batch / name, name=name).to_dict()
    value.staged, value.manifest = staged, manifest
    return wire


def _terminal(value):
    wire = deepcopy(value.wave.state["producer_publication_lineage"])
    entry = wire["batches"][0]
    staged, manifest = value.staged, value.manifest
    marker = {"schema_version": "1", "protocol": "lunar-producer-bundle-publication-v1",
        "journal_id": staged.journal_id, "staged_journal_sha256": staged.digest(),
        "manifest_sha256": manifest.digest(), "archive_after_sha256": manifest.archive_after_sha256,
        "state_after_sha256": manifest.state_after_sha256, "status": "published"}
    marker_sha = _sha(canonical_json(marker))
    _write(value.batch / "terminal.json", canonical_json(marker | {"terminal_marker_sha256": marker_sha}))
    published = replace(staged, state="published", publication_phase="committed", journal_sha256=None,
        terminal_marker_sha256=marker_sha, archive_after_sha256=manifest.archive_after_sha256,
        state_after_sha256=manifest.state_after_sha256)
    _write(value.batch / "journal.published.json", canonical_json(published.to_dict()))
    terminal = ProducerLineageTerminal(value.binding.run_id, staged.journal_id, 0,
        entry["staged"]["descriptor_sha256"], marker_sha, manifest.archive_after_sha256, manifest.state_after_sha256)
    _path, pin = persist_lineage_descriptor(value.workspace, terminal)
    head_sources = {}
    for name in ("archive", "state"):
        filename = name + (".jsonl" if name == "archive" else ".json")
        source, head = value.batch / "stage" / filename, value.workspace / "evolution" / filename
        source.replace(head)
        head_sources[name] = capture_lineage_snapshot_pin(head, name=name + "-before").to_dict()
    live_candidates = value.workspace / "evolution/candidates"
    live_candidates.mkdir()
    cid = staged.candidates[0].candidate_id
    (value.batch / "stage/candidates" / cid).rename(live_candidates / cid)
    entry.update(state="terminal", terminal=terminal.to_dict(), terminal_file_pin=pin.to_dict(),
        published_journal=published.to_dict(), head_sources=head_sources)
    for name in ("journal.published.json", "terminal.json"):
        entry["evidence_pins"][name] = capture_lineage_snapshot_pin(value.batch / name, name=name).to_dict()
    wire["head"] = {"journal_id": staged.journal_id, "terminal_sha256": marker_sha, "lineage_sha256": terminal.digest()}
    return wire


def test_real_owner_two_success_cas_keep_claim_running_and_do_not_publish(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        initial = fixture._capture(value)
        writes, write = [], value.ledger.write_controller_checkpoint
        def observe(run_id, state, *, expected_sha256):
            assert get_ident() == value.owner_thread and value.ledger.controller_lock_held(run_id)
            writes.append((expected_sha256, deepcopy(state)))
            return write(run_id, state, expected_sha256=expected_sha256)
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observe)
        staged = _staged(value)
        stage_head = value.owner.checkpoint_staged(staged)
        assert value.wave.state == initial[2] | {"producer_publication_lineage": staged}
        terminal = _terminal(value)
        terminal_head = value.owner.checkpoint_terminal(terminal)
        assert [item[0] for item in writes] == [initial[0], stage_head]
        assert value.owner._head == value.wave.checkpoint_sha256 == terminal_head
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (terminal_head, value.wave.state)
        assert value.wave.state == initial[2] | {"producer_publication_lineage": terminal}
        assert value.owner._phase == "terminal" and not value.owner._poisoned
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert value.controller.producer_multi_episode_publication is False
        assert json.loads(value.owner._policy_bytes)["online_publication"] is False


@pytest.mark.parametrize("phase", ["staged", "terminal"])
def test_missing_original_native_inputs_cannot_be_adopted_late(tmp_path, monkeypatch, phase):
    with _waiting(tmp_path, monkeypatch, native=False) as value:
        before = fixture._capture(value)
        if phase == "terminal":
            value.gateway.producer_config = object()
        with pytest.raises(RSILearningError, match="native_strategy_(required|drift)"):
            getattr(value.owner, "checkpoint_" + phase)({})
        fixture._unchanged(value, before)
        assert value.owner._poisoned


@pytest.mark.parametrize("phase", ["staged", "terminal"])
def test_original_legacy_root_task_does_not_gain_an_episode_success_binding(tmp_path, monkeypatch, phase):
    with _waiting(tmp_path, monkeypatch, task_bound=False) as value:
        assert value.owner._phase == "prepared-evidence"
        assert value.plan.task_id == "task-1" and value.request.episode_id != value.plan.task_id
        wire, before = _staged(value), fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_success_episode_task_required$"):
            getattr(value.owner, "checkpoint_" + phase)(wire)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned


@pytest.mark.parametrize("phase", ["staged", "terminal"])
@pytest.mark.parametrize("fault", ["phase-skip", "immutable", "snapshot-inode", "descriptor-inode", "native-strategy", "config", "claim-result", "instance-projection", "archive", "native-inputs"])
def test_success_checkpoint_original_gates_refuse_without_cas(tmp_path, monkeypatch, phase, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire = _staged(value)
        if phase == "terminal":
            value.owner.checkpoint_staged(wire)
            wire = _terminal(value)
        if fault == "phase-skip":
            value.owner._phase = "before" if phase == "staged" else "prepared-evidence"
        elif fault == "immutable":
            wire["batches"][0]["request_sha256"] = "f" * 64
        elif fault in {"snapshot-inode", "descriptor-inode"}:
            filename = "archive-after.snapshot" if fault == "snapshot-inode" else phase + ".json"
            path = value.batch / "lineage" / filename
            changed = path.with_suffix(path.suffix + ".replace")
            _write(changed, path.read_bytes())
            changed.replace(path)
        elif fault == "native-strategy":
            object.__setattr__(value.native, "strategy", replace(value.native, strategy=value.strategy))
        elif fault == "config":
            object.__setattr__(value.strategy.config, "population_size", 7)
        elif fault == "instance-projection":
            value.strategy._reconstruct_population_projection = _forbidden
        elif fault == "archive":
            value.strategy.archive = object()
        elif fault == "native-inputs":
            object.__setattr__(value.gateway.producer_config, "inputs", object())
        else:
            claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
            result = fixture.selected.SolverResult(episode_id=value.episode_id, request_sha256=value.request.digest(),
                status="completed", candidate_receipt_sha256=fixture.DIGEST, execution_receipt_sha256=fixture.DIGEST,
                official_evaluation_receipt_sha256=fixture.DIGEST, trace_digest=fixture.DIGEST, terminal_reason="inert")
            value.ledger.publish_native_episode_result(value.request, plan_sha256=value.plan.plan_sha256,
                result=result, expected_claim=claim)
        before = fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(ValueError):
            getattr(value.owner, "checkpoint_" + phase)(wire)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned


@pytest.mark.parametrize("fault", ["projection", "initial-window"])
def test_self_consistent_hashes_do_not_replace_native_projection_or_initial_window(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire = _staged(value, bad_projection=fault == "projection")
        if fault == "initial-window":
            _write(value.workspace / "evolution/offspring-outcomes.jsonl", b"{}\n")
        before = fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(RSILearningError, match="state_projection_drift|success_initial_window_required"):
            value.owner.checkpoint_staged(wire)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned


def test_archive_projection_cannot_substitute_manifest_candidate_record(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _staged(value, record_mismatch=True), fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(RSILearningError, match="archive_material_record_drift"):
            value.owner.checkpoint_staged(wire)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history


@pytest.mark.parametrize("fault", [None, "source-size", "source-sha", "bundle-digest", "entrypoint"])
def test_original_bundle_declarations_bind_staged_materials_before_success_cas(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch, bundle=True) as value:
        wire, before = _staged(value, bundle_fault=fault), fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        if fault is not None:
            with pytest.raises(RSILearningError, match="candidate_bundle_source_drift|candidate_materials_invalid"):
                value.owner.checkpoint_staged(wire)
            fixture._unchanged(value, before)
            assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
            assert value.owner._poisoned
            return
        entry = wire["batches"][0]
        files = {item["candidate_id"]: item for item in value.manifest.to_dict()["files"]}
        assert value.owner._candidate_materials(entry, files, (value.batch / "stage/archive.jsonl").read_bytes(),
            staged=True) == {value.staged.candidates[0].candidate_id: value.bundle_sources}
        value.owner.checkpoint_staged(wire)
        value.owner.checkpoint_terminal(_terminal(value))
        assert value.owner._phase == "terminal" and not value.owner._poisoned
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("target", ["config", "authority", "contract", "nested-contract"])
@pytest.mark.parametrize("shadow", ["to_dict", "__dataclass_fields__"])
def test_first_native_snapshot_refuses_nested_dto_shadows_before_callbacks(tmp_path, monkeypatch, target, shadow):
    value = _native_setup(tmp_path, monkeypatch)
    selected = {"config": value.strategy.config, "authority": value.strategy.integrity_authority,
                "contract": value.strategy.context.contract,
                "nested-contract": value.strategy.context.contract.objective}[target]
    object.__setattr__(selected, shadow, _forbidden)
    with pytest.raises(RSILearningError, match="native_strategy_shape_invalid"):
        brs._native_snapshot(value.strategy.config, value.strategy.integrity_authority, value.strategy.context.contract)


@pytest.mark.parametrize("target", ["config", "authority", "contract"])
def test_live_nested_serializer_shadows_refuse_without_callback_or_cas(tmp_path, monkeypatch, target):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _staged(value), fixture._capture(value)
        selected = {"config": value.strategy.config, "authority": value.strategy.integrity_authority,
                    "contract": value.strategy.context.contract}[target]
        object.__setattr__(selected, "to_dict", _forbidden)
        with pytest.raises(RSILearningError, match="native_strategy_shape_invalid"):
            value.owner.checkpoint_staged(wire)
        fixture._unchanged(value, before)


def test_staged_projection_uses_verified_source_bytes_before_live_candidate_install(tmp_path, monkeypatch):
    value = _native_setup(tmp_path, monkeypatch)
    config = replace(value.strategy.config, population_size=2)
    strategy = PopulationStrategy(replace(value.strategy.context, config=config), read_only=True)
    report = EvaluationReport("1", "inert", 1, 1.0, {}, (), quality=1.0)
    records = [Candidate(cid, f"evolution/candidates/{cid}/main.py", None, 0, 0, "population", 0,
                         report, metadata={"producer_bundle": {}} if cid == "a" else {}, created_at=0.0)
               for cid in ("z", "y", "a")]
    for cid in ("z", "y"):
        _write(value.workspace / f"evolution/candidates/{cid}/main.py", b"common\n")
    assert not (value.workspace / records[-1].code_path).exists()
    source_overrides = {"a": {"main.py": b"distinct\n"}}
    base = strategy._state_payload("running", 0, active_ids={"0": ["z", "y"]}, stagnation=0,
        best_candidate_id="z", rng_seed=config.rng_seed, last_migration_iteration=0, error=None)
    events = {"schema_version": "1", "events": [{"after_iteration": 0, "candidate_ids": ["a"]}]}
    projection = base | {"producer_admissions": events}
    exact = strategy._reconstruct_population_projection(projection, records, source_overrides=source_overrides)
    missing = strategy._reconstruct_population_projection(projection, records)
    assert exact[0] == {0: ["a", "z"]} and missing[0] == {0: ["z", "y"]}
    after = base | {"producer_admissions": events, "active_ids": {"0": exact[0][0]},
                    "best_candidate_id": exact[1], "last_migration_iteration": exact[2], "stagnation": exact[3],
                    "candidate_archive_sha256": _sha(canonical_json([item.to_dict() for item in records]))}
    raw = {"archive-before": b"".join(canonical_json(item.to_dict()) + b"\n" for item in records[:-1]),
           "archive-after": b"".join(canonical_json(item.to_dict()) + b"\n" for item in records),
           "state-before": canonical_json(base), "state-after": canonical_json(after)}
    entry = {"staged": {"candidate_ids": ["a"]}, "state_projection_sha256": _sha(raw["state-after"])}
    reader = SimpleNamespace(_strategy=strategy, _strategy_config=config,
        _strategy_authority=strategy.integrity_authority, _prepared=value.journal)
    brs._BRSLineageCheckpointOwner._verify_staged_projection(reader, entry, raw, source_overrides)
    with pytest.raises(RSILearningError, match="state_projection_drift"):
        brs._BRSLineageCheckpointOwner._verify_staged_projection(reader, entry, raw, {})


@pytest.mark.parametrize("phase", ["staged", "terminal"])
@pytest.mark.parametrize("fault", ["source-inode", "manifest-inode", "candidate-source", "journal-inode", "marker", "initial-window"])
def test_success_checkpoint_checks_original_evidence_and_live_sources(tmp_path, monkeypatch, phase, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire = _staged(value)
        if phase == "terminal":
            value.owner.checkpoint_staged(wire)
            wire = _terminal(value)
        if fault == "marker":
            _write(value.workspace / "evolution/producer-publication.json", b'{"status":"unknown"}')
        elif fault == "initial-window":
            _write(value.workspace / "evolution/offspring-outcomes.jsonl", b"{}\n")
        else:
            if fault == "source-inode":
                path = value.batch / "stage/archive.jsonl" if phase == "staged" else value.workspace / "evolution/archive.jsonl"
            elif fault == "candidate-source":
                cid = value.staged.candidates[0].candidate_id
                prefix = value.batch / "stage/candidates" if phase == "staged" else value.workspace / "evolution/candidates"
                path = prefix / cid / "main.py"
            else:
                path = value.batch / ("manifest.json" if fault == "manifest-inode" else "journal.staged.json")
            replacement = path.with_suffix(path.suffix + ".replace")
            _write(replacement, b"# changed\n" if fault == "candidate-source" else path.read_bytes())
            replacement.replace(path)
        before = fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(ValueError):
            getattr(value.owner, "checkpoint_" + phase)(wire)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned


@pytest.mark.parametrize("method", ["_success_entry", "_native_strategy", "_history", "_strategy_identity"])
def test_new_live_dependencies_cannot_run_after_replacement(tmp_path, monkeypatch, method):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _staged(value), fixture._capture(value)
        monkeypatch.setattr(brs._BRSLineageCheckpointOwner, method, _forbidden)
        expected = ("^rsi_brs_publication_lineage_native_reader_binding_drift$"
                    if method == "_history" else "(?:policy_drift|native_reader_globals_drift)")
        with pytest.raises(RSILearningError, match=expected):
            value.owner.checkpoint_staged(wire)
        fixture._unchanged(value, before)


@pytest.mark.parametrize("method", ["_native", "_projection", "_shape"])
def test_native_context_helper_rebinding_refuses_before_callback(tmp_path, monkeypatch, method):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _staged(value), fixture._capture(value)
        monkeypatch.setattr(scheduler_inputs, method, _forbidden)
        with pytest.raises(RSILearningError, match="(?:policy_drift|native_reader_globals_drift)"):
            value.owner.checkpoint_staged(wire)
        fixture._unchanged(value, before)


@pytest.mark.parametrize("phase", ["staged", "terminal"])
@pytest.mark.parametrize("fault", ["competing-cas", "missing-readback", "wrong-payload"])
def test_success_checkpoint_unknown_never_refreshes_or_retries(tmp_path, monkeypatch, phase, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire = _staged(value)
        if phase == "terminal":
            value.owner.checkpoint_staged(wire)
            wire = _terminal(value)
        before = fixture._capture(value)
        write, read, durable = value.ledger.write_controller_checkpoint, value.ledger.controller_checkpoint, []
        def observe(run_id, state, *, expected_sha256):
            if fault == "competing-cas":
                foreign = deepcopy(value.wave.state) | {"foreign": True}
                durable.append((write(run_id, foreign, expected_sha256=expected_sha256), foreign))
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            return head
        def readback(run_id):
            if not durable or fault == "competing-cas":
                return read(run_id)
            return None if fault == "missing-readback" else (durable[0][0], {"foreign": True})
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observe)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", readback)
        with pytest.raises(RSILearningError):
            getattr(value.owner, "checkpoint_" + phase)(wire)
        fixture._unchanged(value, before)
        assert len(durable) == 1 and read(value.binding.run_id) == durable[0]
        with pytest.raises(RSILearningError):
            getattr(value.owner, "checkpoint_" + phase)(wire)
        assert len(durable) == 1 and value.owner._poisoned
