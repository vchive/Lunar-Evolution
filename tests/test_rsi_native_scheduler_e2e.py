"""Actual native RSI input delivery, local broker, evaluator and durable gateway replay."""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_http_transport_deadline import clear_proxy_environment, local_http
from test_native_trusted_scheduler_e2e import fixture as native_fixture

import lunar_evolution.native_trusted_scheduler as native_scheduler
import lunar_evolution.rsi_native_scheduler as rsi_scheduler
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import CandidateArchive
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)
from lunar_evolution.rsi_native_inputs import (
    bind_native_rsi_launch,
    prepare_native_rsi_inputs,
)
from lunar_evolution.rsi_native_provenance import read_native_rsi_provenance
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    make_native_rsi_scheduler_provider,
)
from lunar_evolution.rsi_store import RSILedger

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native platform")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _native_rsi_fixture(tmp_path: Path, endpoint: str):
    prepared = native_fixture(tmp_path, endpoint)
    memory = EMPTY_MEMORY_SNAPSHOT
    authority = prepared.strategy.integrity_authority
    request = SolverRequest.build(
        episode_id="native-rsi-e2e-episode",
        contract_sha256=authority.contract_sha256,
        evaluator_sha256=authority.evaluator_fingerprint,
        environment_sha256=authority.environment_sha256,
        memory_snapshot_sha256=memory.digest(),
        solver_id="native_population",
        solver_settings={"search": {"width": 2}},
        budget={"max_solver_invocations": 1, "deadline_unix": time.time() + 120},
        practice_charter={"trigger": "fixture", "failure_boundary": "local only"},
    )
    workspace = prepared.context.workspace
    inputs = prepare_native_rsi_inputs(
        workspace, journal_id=prepared.intent.journal_id, request=request, memory=memory,
    )
    # Extend the same C fixture with full-byte request/memory checks. The target is compiled
    # before rebuilding its launch intent, so the attestation pins the final executable bytes.
    producer = prepared.arguments["producer_root"]
    source_path = producer / "target.c"
    source = source_path.read_text()
    assert "if(argc!=2)return 20;" in source
    source = source.replace("if(argc!=2)return 20;", "if(argc!=4)return 20;")
    request_json = canonical_json(request.to_dict()).decode()
    memory_json = memory.to_bytes().decode()
    checks = (
        ' char input[65536]; size_t size;\n'
        ' if(strcmp(argv[2],"--lunar-rsi-input-v1")!=0)return 40;\n'
        f' if(strcmp(argv[3],{json.dumps(inputs.manifest_sha256)})!=0)return 41;\n'
        ' f=fopen("../.rsi-input/request.json","rb");if(!f)return 42;\n'
        ' size=fread(input,1,sizeof(input)-1,f);fclose(f);input[size]=0;\n'
        f' if(strcmp(input,{json.dumps(request_json)})!=0)return 43;\n'
        ' f=fopen("../.rsi-input/memory.json","rb");if(!f)return 44;\n'
        ' size=fread(input,1,sizeof(input)-1,f);fclose(f);input[size]=0;\n'
        f' if(strcmp(input,{json.dumps(memory_json)})!=0)return 45;\n'
        ' f=fopen("input-observed","wb");if(!f)return 46;\n'
        f' if(fputs({json.dumps(request.digest() + ":" + memory.digest())},f)<0||fclose(f)!=0)return 47;\n'
    )
    source = source.replace(' if(mkdir("../output/solve",0700)!=0)return 3;\n',
                            checks + ' if(mkdir("../output/solve",0700)!=0)return 3;\n')
    source_path.write_text(source)
    compile_native_target(source_path, producer / "target")
    original = prepared.intent.to_dict()
    parameters = inspect.signature(build_producer_launch_intent).parameters
    launch_values = {name: original[name] for name in parameters if name not in {"producer_root", "argv"}}
    intent = build_producer_launch_intent(
        producer_root=producer, argv=(*prepared.intent.argv, *inputs.argv_fragment), **launch_values,
    )
    attestation = build_producer_launch_attestation(intent, "native-rsi-e2e-once")
    inputs = bind_native_rsi_launch(
        workspace, intent=intent, attestation=attestation, artifact=prepared.artifact, inputs=inputs,
    )
    context = NativeRSISchedulerContext(
        workspace=workspace, producer_root=producer, intent=intent, attestation=attestation,
        artifact=prepared.artifact, broker_config=prepared.arguments["broker_config"],
        contract=prepared.context.contract, groups=prepared.arguments["groups"],
        evaluator_kind=authority.evaluator_kind, evaluator_fingerprint=authority.evaluator_fingerprint,
        runner_fingerprint=authority.runner_fingerprint, dependency_sha256=authority.dependency_sha256,
        environment_sha256=authority.environment_sha256, strategy=prepared.strategy,
    )
    provider = make_native_rsi_scheduler_provider(context)
    plan = provider.plan(request, memory)
    ledger = RSILedger(tmp_path / "rsi.sqlite")
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, provider.plan, provider))
    return SimpleNamespace(
        native=prepared, request=request, memory=memory, inputs=inputs, plan=plan, context=context,
        provider=provider, ledger=ledger, gateway=gateway, workspace=workspace, batch=prepared.batch,
    )


def _ledger_counts(ledger: RSILedger) -> tuple[int, int]:
    with sqlite3.connect(ledger.database) as connection:
        return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in (
            "rsi_native_episode_claims", "rsi_episode_results",
        ))


def _retained_bytes(workspace: Path) -> dict[str, tuple[object, ...]]:
    return {
        path.relative_to(workspace).as_posix(): (
            path.read_bytes(), path.stat().st_dev, path.stat().st_ino,
            path.stat().st_mode, path.stat().st_nlink, path.stat().st_mtime_ns,
        )
        for path in workspace.rglob("*") if path.is_file()
    }


def test_real_native_rsi_provider_gateway_receipts_and_completed_replay(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    actual_runs = []
    run_scheduler = rsi_scheduler.run_native_trusted_producer

    def observe_scheduler(*args, **kwargs):
        result = run_scheduler(*args, **kwargs)
        actual_runs.append(result)
        return result

    monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", observe_scheduler)
    with local_http() as (endpoint, requests):
        fixture = _native_rsi_fixture(tmp_path, endpoint)
        result = fixture.gateway.run(fixture.request, fixture.memory)
        assert result.status == "completed"
        assert len(actual_runs) == 1 and len(requests) == 1
        native_run = actual_runs[0]
        journal = native_run.publication.published_journal
        candidate_id = native_run.publication.admitted_candidate_ids[0]
        entry = next(item for item in journal.candidates if item.candidate_id == candidate_id)
        assert result.request_sha256 == fixture.request.digest()
        assert result.candidate_receipt_sha256 == entry.preparation_receipt_sha256
        assert result.execution_receipt_sha256 == entry.execution_receipt_sha256
        assert result.official_evaluation_receipt_sha256 == entry.evaluation_receipt_sha256
        assert dict(result.solver_provenance)["publication_receipt_sha256"] == entry.publication_receipt_sha256
        assert dict(result.solver_provenance)["candidate_id"] == candidate_id
        saved_provenance = read_native_rsi_provenance(fixture.batch)
        assert dict(result.solver_provenance)["native_provenance_sha256"] == saved_provenance["provenance_sha256"]
        assert dict(result.solver_provenance)["native_plan_sha256"] == fixture.plan.plan_sha256
        assert result.trace_digest == native_run.output.output_capture_sha256
        assert (fixture.batch / "work" / "input-observed").read_text() == (
            fixture.request.digest() + ":" + fixture.memory.digest()
        )
        assert native_run.receipt.trusted_execution["broker_coverage"] == "brokered_requests_only"
        assert (fixture.batch / "attestation-consumption.json").is_file()
        archive = CandidateArchive(fixture.workspace, requested_strategy="population", read_only=True)
        candidate = next(item for item in archive.records() if item.candidate_id == candidate_id)
        archive.validate_candidate_integrity(require_all=True)
        assert candidate.evaluation.validity == 1 and candidate.evaluation.combined_score == 9
        assert result.candidate_source_sha256 == candidate.source_sha256
        assert result.candidate_source_sha256 == _sha((fixture.workspace / candidate.code_path).read_bytes())
        assert fixture.ledger.episode_result(fixture.request.episode_id) == (fixture.request, result)
        before = _retained_bytes(fixture.workspace)
        counts = _ledger_counts(fixture.ledger)
        monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", lambda *_a, **_k: pytest.fail("replay spawned"))
        assert fixture.gateway.run(fixture.request, fixture.memory) == result
        restarted_ledger = RSILedger(fixture.ledger.database)
        restarted_provider = make_native_rsi_scheduler_provider(fixture.context)
        restarted_gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
            restarted_ledger, restarted_provider.plan, restarted_provider,
        ))
        original_deadline = dict(fixture.request.budget)["deadline_unix"]
        monkeypatch.setattr(rsi_scheduler.time, "time", lambda: original_deadline + 1)
        # Reconstructing a completed result never renews an already expired original deadline.
        assert restarted_gateway.run(fixture.request, fixture.memory) == result
        assert _retained_bytes(fixture.workspace) == before
        assert _ledger_counts(fixture.ledger) == counts == (1, 1)
        assert len(requests) == 1


@pytest.mark.parametrize("drift", ["request", "memory", "intent"])
def test_real_native_rsi_input_drift_refuses_before_attestation_consumption(tmp_path, monkeypatch, drift):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _native_rsi_fixture(tmp_path, endpoint)
        request, memory = fixture.request, fixture.memory
        if drift == "request":
            request = replace(request, environment_sha256=_sha(b"drifted environment"))
            refusal = "plan_failed"
        elif drift == "memory":
            memory = type(memory)("drifted snapshot", None, ())
            refusal = "memory_binding_mismatch"
        else:
            intent = replace(fixture.context.intent, task_id="drifted-task", intent_sha256=None)
            context = replace(
                fixture.context, intent=intent,
                attestation=build_producer_launch_attestation(intent, "drifted-intent-once"),
            )
            provider = make_native_rsi_scheduler_provider(context)
            fixture.gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
                fixture.ledger, provider.plan, provider,
            ))
            refusal = "plan_failed"
        monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", lambda *_a, **_k: pytest.fail("drift spawned"))
        with pytest.raises(NativeRSISolverGatewayError, match=refusal):
            fixture.gateway.run(request, memory)
        assert not (fixture.batch / "attestation-consumption.json").exists()
        assert not (fixture.batch / "work" / "started").exists()
        assert _ledger_counts(fixture.ledger) == (0, 0)
        assert requests == []


def test_real_native_rsi_crash_before_result_publication_never_relaunches(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    calls = []
    publication_calls = []
    run_scheduler = rsi_scheduler.run_native_trusted_producer

    def observe_scheduler(*args, **kwargs):
        result = run_scheduler(*args, **kwargs)
        calls.append(result)
        return result

    def interrupted_publish(*_args, **_kwargs):
        publication_calls.append(True)
        raise RuntimeError("fixture crash before RSI result publication")

    monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", observe_scheduler)
    with local_http() as (endpoint, requests):
        fixture = _native_rsi_fixture(tmp_path, endpoint)
        monkeypatch.setattr(fixture.ledger, "publish_native_episode_result", interrupted_publish)
        with pytest.raises(NativeRSISolverGatewayError, match="attempt_unknown"):
            fixture.gateway.run(fixture.request, fixture.memory)
        assert len(calls) == 1 and len(requests) == 1
        assert publication_calls == [True]
        assert calls[0].status == "published"
        assert (fixture.batch / "native-rsi.provenance.json").is_file()
        assert _ledger_counts(fixture.ledger) == (1, 0)
        before = _retained_bytes(fixture.workspace)
        restarted_ledger = RSILedger(fixture.ledger.database)
        restarted_provider = make_native_rsi_scheduler_provider(fixture.context)
        restarted_gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
            restarted_ledger, restarted_provider.plan, restarted_provider,
        ))
        monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", lambda *_a, **_k: pytest.fail("unknown attempt relaunched"))
        with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
            restarted_gateway.run(fixture.request, fixture.memory)
        assert _retained_bytes(fixture.workspace) == before
        assert _ledger_counts(restarted_ledger) == (1, 0)
        assert len(requests) == 1


def _fixture_cancelled() -> bool:
    return True


@pytest.mark.parametrize("stop", ["deadline", "cancelled"])
def test_real_native_rsi_admission_stops_without_nonce_or_spawn(tmp_path, monkeypatch, stop):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _native_rsi_fixture(tmp_path, endpoint)
        if stop == "deadline":
            deadline = dict(fixture.request.budget)["deadline_unix"]
            monkeypatch.setattr(rsi_scheduler.time, "time", lambda: deadline + 1)
        else:
            context = replace(fixture.context, cancelled=_fixture_cancelled)
            provider = make_native_rsi_scheduler_provider(context)
            fixture.gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
                fixture.ledger, provider.plan, provider,
            ))
            assert provider.rsi_fingerprint_config()["cancelled_sha256"]
        monkeypatch.setattr(native_scheduler, "run_native_trusted_attempt", lambda *_a, **_k: pytest.fail("admission spawned"))
        with pytest.raises(NativeRSISolverGatewayError, match="attempt_unknown"):
            fixture.gateway.run(fixture.request, fixture.memory)
        assert not (fixture.batch / "attestation-consumption.json").exists()
        assert not (fixture.batch / "work" / "started").exists()
        assert not (fixture.batch / "native-rsi.provenance.json").exists()
        assert _ledger_counts(fixture.ledger) == (1, 0)
        assert requests == []
        with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
            fixture.gateway.run(fixture.request, fixture.memory)


def test_real_native_rsi_validate_replay_is_read_only(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _native_rsi_fixture(tmp_path, endpoint)
        result = fixture.gateway.run(fixture.request, fixture.memory)
        before = _retained_bytes(fixture.workspace)
        restarted_provider = make_native_rsi_scheduler_provider(fixture.context)
        restarted_gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
            RSILedger(fixture.ledger.database), restarted_provider.plan, restarted_provider,
        ))
        monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", lambda *_a, **_k: pytest.fail("validation spawned"))
        assert restarted_gateway.validate_replay(fixture.request, fixture.memory, result) == result
        assert _retained_bytes(fixture.workspace) == before
        assert len(requests) == 1


@pytest.mark.parametrize("tamper", ["content", "inode", "inode_rehashed", "candidate_source"])
def test_real_native_rsi_completed_replay_rejects_provenance_tampering(tmp_path, monkeypatch, tamper):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _native_rsi_fixture(tmp_path, endpoint)
        result = fixture.gateway.run(fixture.request, fixture.memory)
        sidecar = fixture.batch / "native-rsi.provenance.json"
        original = sidecar.read_bytes()
        original_inode = sidecar.stat().st_ino
        if tamper == "content":
            payload = json.loads(original)
            payload["plan"]["request_sha256"] = _sha(b"drifted request")
            sidecar.chmod(0o600)
            sidecar.write_bytes(canonical_json(payload))
            sidecar.chmod(0o400)
        elif tamper in {"inode", "inode_rehashed"}:
            replacement = sidecar.with_suffix(".replacement")
            replacement.write_bytes(original)
            if tamper == "inode_rehashed":
                # Even a newly canonical, self-consistent sidecar cannot change the identity
                # already pinned in the durable SolverResult.
                payload = json.loads(original)
                info = replacement.stat()
                payload["file_identity"] = {"device": info.st_dev, "inode": info.st_ino}
                payload["provenance_sha256"] = _sha(canonical_json({
                    key: value for key, value in payload.items() if key != "provenance_sha256"
                }))
                replacement.write_bytes(canonical_json(payload))
            replacement.chmod(0o400)
            replacement.replace(sidecar)
            assert sidecar.stat().st_ino != original_inode
            if tamper == "inode_rehashed":
                saved = read_native_rsi_provenance(fixture.batch)
                assert saved["provenance_sha256"] != dict(result.solver_provenance)["native_provenance_sha256"]
        else:
            archive = CandidateArchive(fixture.workspace, requested_strategy="population", read_only=True)
            candidate_id = dict(result.solver_provenance)["candidate_id"]
            candidate = next(item for item in archive.records() if item.candidate_id == candidate_id)
            source = fixture.workspace / candidate.code_path
            mode = source.stat().st_mode & 0o777
            source.chmod(0o600)
            source.write_bytes(source.read_bytes() + b"\n# changed after completion\n")
            source.chmod(mode)
            # Retained evidence must refuse source drift before any process or evaluator call.
        before = _retained_bytes(fixture.workspace)
        counts = _ledger_counts(fixture.ledger)
        restarted_provider = make_native_rsi_scheduler_provider(fixture.context)
        restarted_gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
            RSILedger(fixture.ledger.database), restarted_provider.plan, restarted_provider,
        ))
        monkeypatch.setattr(rsi_scheduler, "run_native_trusted_producer", lambda *_a, **_k: pytest.fail("tampered replay spawned"))
        with pytest.raises(NativeRSISolverGatewayError, match="replay_evidence_invalid"):
            restarted_gateway.run(fixture.request, fixture.memory)
        assert _retained_bytes(fixture.workspace) == before
        assert _ledger_counts(fixture.ledger) == counts == (1, 1)
        assert fixture.ledger.episode_result(fixture.request.episode_id) == (fixture.request, result)
        assert len(requests) == 1
