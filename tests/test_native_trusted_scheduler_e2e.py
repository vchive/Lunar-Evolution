"""Actual local native producer, host broker, formal receipt and population publication."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from _native_target_fixture import compile_native_target
from test_bundle_population import MAIN_SOURCE, build_context
from test_http_transport_deadline import clear_proxy_environment, local_http
from test_producer_bundle_transaction import _archive_projection, _initialize_native_population

import lunar_evolution.native_trusted_scheduler as scheduler
import lunar_evolution.producer_bundle_staging as staging
import lunar_evolution.producer_bundle_transaction as transaction
from lunar_evolution import bundle_evolution
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.bundle_delivery import inspect_bundle_delivery, publish_bundle_delivery
from lunar_evolution.bundle_evolution import read_bundle_delivery_materials
from lunar_evolution.evolution import CandidateArchive, EvolutionError, PopulationStrategy
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import recover_native_trusted_attempt
from lunar_evolution.producer_bootstrap import TrustedBootstrapSession
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    resume_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    run_native_producer_bundle_publication_transaction,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")


def fixture(tmp_path: Path, endpoint: str, *, delay: int = 0, candidate_delay: int = 0, evaluator_delay: int = 0):
    context = build_context(tmp_path / "native")
    if evaluator_delay:
        pipeline = context.bundle_pipeline
        harness = (
            "import json, time\nfrom pathlib import Path\n"
            'if json.loads(Path("output/result.json").read_text())["value"] == 9:\n'
            '    Path("evaluation-started").write_text(str(time.monotonic()))\n'
            f"    time.sleep({evaluator_delay})\n"
            + pipeline.harness_path.read_text()
        ).encode()
        pipeline.harness_path.write_bytes(harness)
        pipeline.evaluator = replace(pipeline.evaluator, harness_sha256=hashlib.sha256(harness).hexdigest(),
                                     harness_size=len(harness))
        context = replace(context, config=pipeline.configure(replace(
            context.config, evaluator_fingerprint=None, runner_fingerprint=None,
        )))
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    authority = strategy.integrity_authority
    producer = tmp_path / "producer"
    producer.mkdir()
    main_source = MAIN_SOURCE
    if candidate_delay:
        main_source = ('import time\nfrom pathlib import Path\n'
                       'Path("candidate-started").write_text(str(time.monotonic()))\n'
                       f'time.sleep({candidate_delay})\n') + MAIN_SOURCE
    sources = {"solve/main.py": main_source, "solve/helper.py": "def choose(limit):\n    return 9\n"}
    producer_pin = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    envelope = {
        "schema_version": "1", "producer_id": "local-formal-fixture", "producer_fingerprint": producer_pin,
        "status": "completed", "contract_sha256": context.contract.digest(), "budget": {"requests": 1},
        "materials": [{"kind": "candidate_source", "path": path, "size": len(source.encode()),
                       "sha256": hashlib.sha256(source.encode()).hexdigest()} for path, source in sources.items()],
    }
    body = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    program = (
        '#include <stdio.h>\n#include <sys/stat.h>\n#include <sys/socket.h>\n#include <arpa/inet.h>\n'
        '#include <errno.h>\n#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n'
        'int main(int argc, char **argv) {\n'
        ' FILE *f = fopen("started", "wb"); if(!f || fputs("target",f)<0 || fclose(f)!=0)return 2;\n'
        f' sleep({delay});\n'
        # The endpoint is running, so denial must be an OS permission failure, not refused I/O.
        ' if(argc!=2)return 20; int s=socket(AF_INET,SOCK_STREAM,0);\n'
        ' if(s>=0){struct sockaddr_in a;memset(&a,0,sizeof(a));a.sin_family=AF_INET;\n'
        ' a.sin_port=htons((unsigned short)atoi(argv[1]));a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);\n'
        ' int connected=connect(s,(struct sockaddr*)&a,sizeof(a));int e=errno;close(s);\n'
        ' if(connected==0 || (e!=EPERM && e!=EACCES))return 21;\n'
        ' }else if(errno!=EPERM && errno!=EACCES)return 22;\n'
        ' f=fopen("../.host-request-journal/requests","ab");if(f){fclose(f);return 23;}\n'
        ' if(errno!=EPERM && errno!=EACCES)return 24;\n'
        ' const char *w=getenv("LUNAR_PRODUCER_REQUEST_FD"),*r=getenv("LUNAR_PRODUCER_RESPONSE_FD");\n'
        ' if(!w||!r)return 10;\n'
        ' const char *q="{\\"protocol\\":\\"lunar-producer-broker-ipc-v1\\",'
        '\\"request_id\\":\\"req-1\\",\\"body_base64\\":\\"aGVsbG8=\\"}\\n";\n'
        ' if(write(atoi(w),q,strlen(q))!=(ssize_t)strlen(q))return 11;\n'
        ' char reply[4096];int n=0;char c;\n'
        ' while(n<4095&&read(atoi(r),&c,1)==1){reply[n++]=c;if(c==10)break;}\n'
        ' reply[n]=0;if(!strstr(reply,"\\"status\\":\\"completed\\""))return 12;\n'
        ' if(mkdir("../output/solve",0700)!=0)return 3;\n'
    )
    for index, (path, source) in enumerate(sources.items()):
        program += f' f=fopen({json.dumps("../output/" + path)},"wb");\n'
        program += f' if(!f||fputs({json.dumps(source)},f)<0||fclose(f)!=0)return {30 + index};\n'
    program += ' f=fopen("../output/producer-result.json","wb");\n'
    program += f' if(!f||fputs({json.dumps(body)},f)<0||fclose(f)!=0)return 35;return 0;}}\n'
    source_path = producer / "target.c"
    source_path.write_text(program)
    target = producer / "target"
    compile_native_target(source_path, target)
    artifact = build_native_bootstrap_artifact(tmp_path / "bootstrap")
    intent = build_producer_launch_intent(
        producer_root=producer, launch_id="local-launch", journal_id="local-journal", run_id="local-run",
        parent_task_id="local-parent", task_id="local-task", contract_sha256=authority.contract_sha256,
        evaluator_kind=authority.evaluator_kind, evaluator_fingerprint=authority.evaluator_fingerprint,
        runner_fingerprint=authority.runner_fingerprint, generator_fingerprint=producer_pin,
        dependency_sha256=authority.dependency_sha256, environment_sha256=authority.environment_sha256,
        producer_id="local-formal-fixture", producer_fingerprint=producer_pin, executable_relative="target",
        argv=("target", str(urlparse(endpoint).port)), working_directory="work", output_directory="output",
        # This suite asserts scheduler/publication cancellation, not one-second HTTP timing.
        # Keep local worker startup bounded with room for a loaded CI runner.
        request_timeout_seconds=5, max_requests=1, output_max_bytes=65536, wall_timeout_seconds=12,
    )
    # This nonce certifies only this local fixture target's observed execution bytes and inode.
    attestation = build_producer_launch_attestation(intent, "local-fixture-once")
    groups = (BundleGroup("local-two-file", "solve/main.py", tuple(sources)),)
    recovery = {
        "intent": intent, "attestation": attestation, "artifact": artifact, "contract": context.contract,
        "groups": groups, "evaluator_kind": authority.evaluator_kind,
        "evaluator_fingerprint": authority.evaluator_fingerprint, "runner_fingerprint": authority.runner_fingerprint,
        "dependency_sha256": authority.dependency_sha256, "environment_sha256": authority.environment_sha256,
    }
    arguments = recovery | {"producer_root": producer, "broker_config": ProducerBrokerConfig(endpoint, {"X-Fixture-Secret": "host-only"}),
                            "strategy": strategy, "execution_control": SolveExecutionControl(25)}
    batch = context.workspace / "evolution" / "producer-batches" / intent.journal_id
    return SimpleNamespace(context=context, strategy=strategy, intent=intent, attestation=attestation,
                           artifact=artifact, arguments=arguments, recovery=recovery, batch=batch)


def assert_publication_readback(prepared, publication, tmp_path):
    assert publication.publication_status == "published"
    assert len(publication.admitted_candidate_ids) == 1
    assert publication.journal.native_execution_receipt_sha256
    archive = CandidateArchive(prepared.context.workspace, requested_strategy="population", read_only=True)
    records = archive.records()
    archive.validate_candidate_integrity(require_all=True, records=records)
    admitted = next(item for item in records if item.candidate_id == publication.admitted_candidate_ids[0])
    assert admitted.evaluation.validity == 1 and admitted.evaluation.combined_score == 9
    state = archive.read_state()
    assert state["best_candidate_id"] == admitted.candidate_id
    assert sum(len(values) for values in state["active_ids"].values()) == 2
    materials = read_bundle_delivery_materials(prepared.context.workspace, admitted)
    assert {name for name in materials if name.startswith("source/")} == {
        "source/solve/main.py", "source/solve/helper.py",
    }
    delivery_root = tmp_path / "delivery"
    delivery_root.mkdir()
    delivered = publish_bundle_delivery(delivery_root, identity={
        "candidate_id": admitted.candidate_id, "contract_sha256": prepared.context.contract.digest(),
        "bundle_sha256": admitted.bundle_evidence["bundle_sha256"], "receipt_sha256": admitted.receipt_sha256,
        "evaluation_sha256": admitted.bundle_evidence["evaluation_sha256"],
    }, materials=materials)
    assert inspect_bundle_delivery(delivered.delivery_path) == delivered
    assert json.loads((delivered.delivery_path / "output/result.json").read_bytes()) == {
        "value": 9, "claimed_score": 999999,
    }


def test_real_scheduler_broker_receipt_publication_and_readonly_recovery(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        result = scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments)
    assert result.status == "published" and result.deadline_scope == "caller_lifecycle"
    assert len(requests) == 1 and result.receipt.trusted_execution["broker_coverage"] == "brokered_requests_only"
    assert result.publication.journal.native_execution_receipt_sha256 == result.receipt.receipt_sha256
    assert_publication_readback(prepared, result.publication, tmp_path)
    archive_before = _archive_projection(prepared.context.workspace)
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *_args, **_kwargs: pytest.fail("recovery must not spawn"))
    recovered = scheduler.recover_native_trusted_producer(prepared.context.workspace, **prepared.recovery)
    assert recovered.receipt.receipt_sha256 == result.receipt.receipt_sha256
    assert recovered.output.execution_receipt_sha256 == result.receipt.receipt_sha256
    assert _archive_projection(prepared.context.workspace) == archive_before


def test_real_active_cancellation_cleans_owner_without_request_or_publication(tmp_path: Path, monkeypatch):
    """Cancel an observed active target; target-authored bytes alone are not handshake proof."""
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint, delay=3)
        before = _archive_projection(prepared.context.workspace)
        accepted_starts = []
        active_cancellations = []
        accept_frame = TrustedBootstrapSession.accept_frame

        def cancelled():
            active = bool(accepted_starts) and (prepared.batch / "work" / "started").exists()
            if active:
                active_cancellations.append(True)
            return active

        def accept_then_observe(session, frame):
            if frame.kind == "target_started":
                # A fast static target may already have written its marker. Cancellation
                # must still wait until the controller accepts the authenticated frame.
                assert cancelled() is False
            accept_frame(session, frame)
            if frame.kind == "target_started":
                assert session.state == "target_started" and session.target_start_count == 1
                accepted_starts.append(frame)

        monkeypatch.setattr(TrustedBootstrapSession, "accept_frame", accept_then_observe)
        with pytest.raises(SolveExecutionCancelled):
            scheduler.run_native_trusted_producer(
                prepared.context.workspace, **prepared.arguments,
                cancelled=cancelled,
            )
    assert len(accepted_starts) == 1 and active_cancellations
    terminal = recover_native_trusted_attempt(prepared.context.workspace, intent=prepared.intent,
                                              attestation=prepared.attestation, artifact=prepared.artifact)
    assert terminal["process_status"] == "cancelled"
    assert terminal["cleanup_status"] in {"cleaned", "already_exited"}
    assert requests == [] and not (prepared.batch / "execution-receipt.json").exists()
    assert _archive_projection(prepared.context.workspace) == before


def test_interruption_after_formal_receipt_recovers_without_relaunch_then_publishes(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    persist = scheduler.persist_native_trusted_execution_receipt

    def interrupted(*args, **kwargs):
        persist(*args, **kwargs)
        raise RuntimeError("fixture controller interruption after formal receipt fsync")

    monkeypatch.setattr(scheduler, "persist_native_trusted_execution_receipt", interrupted)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        before = _archive_projection(prepared.context.workspace)
        with pytest.raises(RuntimeError, match="fixture controller interruption"):
            scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments)
    assert len(requests) == 1 and (prepared.batch / "execution-receipt.json").exists()
    assert _archive_projection(prepared.context.workspace) == before
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *_args, **_kwargs: pytest.fail("recovery must not spawn"))
    recovered = scheduler.recover_native_trusted_producer(prepared.context.workspace, **prepared.recovery)
    assert _archive_projection(prepared.context.workspace) == before
    publication = run_native_producer_bundle_publication_transaction(
        prepared.context.workspace, prepared.strategy, recovered.output.drafts, recovered.output.admission_plan,
        journal_id=prepared.intent.journal_id, run_id=prepared.intent.run_id,
        parent_task_id=prepared.intent.parent_task_id, task_id=prepared.intent.task_id,
        native_execution_receipt_sha256=recovered.receipt.receipt_sha256,
        execution_control=prepared.arguments["execution_control"],
    )
    assert_publication_readback(prepared, publication, tmp_path)


def retained_files(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_ino)
            for path in root.rglob("*") if path.is_file()}


def test_exact_published_recovery_does_not_evaluate_stage_or_commit(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        result = scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments)
    before = retained_files(prepared.context.workspace)

    def forbidden(*_args, **_kwargs):
        pytest.fail("published recovery must not launch, evaluate, stage or commit")

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", forbidden)
    monkeypatch.setattr(prepared.context.bundle_pipeline, "evaluate_draft_non_publishing", forbidden)
    monkeypatch.setattr(transaction, "stage_producer_bundle_publication", forbidden)
    monkeypatch.setattr(transaction, "commit_producer_bundle_publication", forbidden)
    for _ in range(2):
        recovered = scheduler.recover_native_trusted_producer(prepared.context.workspace, **prepared.recovery)
        publication = resume_producer_bundle_publication(
            prepared.context.workspace, recovered.output.admission_plan, result.publication.published_journal,
        )
        assert publication.status == "published"
        assert publication.candidate_ids == result.publication.admitted_candidate_ids
        assert recovered.receipt.receipt_sha256 == result.receipt.receipt_sha256
        assert retained_files(prepared.context.workspace) == before
    assert len(requests) == 1


def test_actual_commit_interruption_retains_unknown_without_automatic_retry(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)

    def interrupt_archive_move(source, target):
        assert source.name == "archive.jsonl" and target.name == "archive.jsonl"
        raise OSError("fixture interruption after durable unknown marker and candidate move")

    monkeypatch.setattr(staging, "_replace_file", interrupt_archive_move)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        archive_before = tuple((prepared.context.workspace / "evolution" / name).read_bytes()
                               for name in ("archive.jsonl", "state.json"))
        with pytest.raises(scheduler.NativeTrustedSchedulerError, match="publication_failed") as caught:
            scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments)
    assert caught.value.__cause__.code == "producer_bundle_publication_commit_unknown"
    assert len(requests) == 1 and (prepared.batch / "execution-receipt.json").exists()
    marker = prepared.context.workspace / "evolution/producer-publication.json"
    assert json.loads(marker.read_bytes())["status"] == "unknown"
    assert tuple((prepared.context.workspace / "evolution" / name).read_bytes()
                 for name in ("archive.jsonl", "state.json")) == archive_before
    with pytest.raises(EvolutionError, match="recovery_required"):
        CandidateArchive(prepared.context.workspace, requested_strategy="population", read_only=True)
    journal = parse_producer_bundle_publication_journal(prepared.batch / "journal.json")
    assert (prepared.context.workspace / "evolution/candidates" / journal.candidates[0].candidate_id).exists()
    before = retained_files(prepared.context.workspace)
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *_args, **_kwargs: pytest.fail("unknown recovery must not spawn"))
    recovered = scheduler.recover_native_trusted_producer(prepared.context.workspace, **prepared.recovery)
    with pytest.raises(ProducerBundleRecoveryError, match="unknown_terminal"):
        resume_producer_bundle_publication(prepared.context.workspace, recovered.output.admission_plan, journal)
    assert retained_files(prepared.context.workspace) == before
    assert not (prepared.batch / "terminal.json").exists()


@pytest.mark.parametrize("phase", ["candidate", "evaluation"])
@pytest.mark.parametrize("control_mode", ["shared_wall", "cancellation_only"])
def test_active_candidate_or_evaluator_cancellation_cleans_without_publication(tmp_path: Path, monkeypatch, phase, control_mode):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint, **{("candidate_delay" if phase == "candidate" else "evaluator_delay"): 3})
        if control_mode == "cancellation_only":
            prepared.arguments.pop("execution_control")
        before = _archive_projection(prepared.context.workspace)
        processes, released = [], []
        prepared.context.bundle_pipeline.set_process_observer(
            lambda pid, pgid: processes.append((pid, pgid)),
            lambda pid, pgid: released.append((pid, pgid)),
        )
        observed_cancel_at = []

        def cancelled():
            markers = list(prepared.context.workspace.rglob(phase + "-started"))
            observed = bool(markers)
            if observed and not observed_cancel_at:
                observed_cancel_at.append(float(markers[0].read_text()))
            return observed

        with pytest.raises(SolveExecutionCancelled) as caught:
            scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments, cancelled=cancelled)
        assert time.monotonic() - observed_cancel_at[0] < 1.5
    assert caught.value.stage == ("candidate_execution" if phase == "candidate" else "evaluation")
    assert len(processes) == (1 if phase == "candidate" else 2) and processes == released
    for _, pgid in processes:
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)
    assert len(requests) == 1 and (prepared.batch / "execution-receipt.json").exists()
    assert (prepared.batch / "journal.prepared.json").exists()
    assert not (prepared.context.workspace / "evolution/producer-publication.json").exists()
    assert not (prepared.batch / "terminal.json").exists()
    assert _archive_projection(prepared.context.workspace) == before
    assert prepared.context.bundle_pipeline._remaining_timeout is None
    bindings = list((prepared.batch / "native-drafts").glob("*/draft-binding.json"))
    assert len(bindings) == 1
    run_root = prepared.context.workspace / json.loads(bindings[0].read_bytes())["run_root"]
    assert (run_root / "attempt/launch-intent.json").exists()
    assert (run_root / "attempt/completed.json").exists() is (phase == "evaluation")
    assert not list((run_root / "evaluations").rglob("evaluation.json"))

    def forbidden(*_args, **_kwargs):
        pytest.fail("interrupted retained draft must not automatically execute or evaluate again")

    monkeypatch.setattr(bundle_evolution, "run_candidate_execution_recorded", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    recovered = scheduler.recover_native_trusted_producer(prepared.context.workspace, **prepared.recovery)
    with pytest.raises(NativeProducerBundleTransactionError, match="recovery_required"):
        run_native_producer_bundle_publication_transaction(
            prepared.context.workspace, prepared.strategy, recovered.output.drafts, recovered.output.admission_plan,
            journal_id=prepared.intent.journal_id, run_id=prepared.intent.run_id,
            parent_task_id=prepared.intent.parent_task_id, task_id=prepared.intent.task_id,
            native_execution_receipt_sha256=recovered.receipt.receipt_sha256,
            execution_control=prepared.arguments.get("execution_control"),
        )
    assert _archive_projection(prepared.context.workspace) == before
    assert processes == released


def test_actual_parent_deadline_cleans_and_retains_original_deadline(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint, delay=3)
        before = _archive_projection(prepared.context.workspace)
        started = time.monotonic()
        parent_deadline = started + 1.5
        with pytest.raises(SolveExecutionBudgetExceeded):
            scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments,
                                                  parent_deadline=parent_deadline)
        assert time.monotonic() - started < 2.5
    assert (prepared.batch / "work/started").exists()
    deadline = json.loads((prepared.batch / "native-trusted-attempt-deadline.json").read_bytes())
    assert deadline["deadline_monotonic"] == parent_deadline
    assert prepared.arguments["execution_control"].deadline > parent_deadline
    assert requests == [] and not (prepared.batch / "execution-receipt.json").exists()
    terminal = recover_native_trusted_attempt(prepared.context.workspace, intent=prepared.intent,
                                              attestation=prepared.attestation, artifact=prepared.artifact)
    assert terminal["status"] == "recovery_required"
    cleanup = json.loads((prepared.batch / "native-trusted-cleanup.json").read_bytes())
    assert cleanup["cleanup_status"] in {"cleaned", "already_exited"} and cleanup["alive_after"] is False
    assert _archive_projection(prepared.context.workspace) == before


@pytest.mark.parametrize("failure", ["nonbool", "exception"])
def test_invalid_active_cancellation_callback_fails_closed_after_cleanup(tmp_path: Path, monkeypatch, failure):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint, candidate_delay=3)
        prepared.arguments.pop("execution_control")
        before = _archive_projection(prepared.context.workspace)
        processes, released = [], []
        prepared.context.bundle_pipeline.set_process_observer(
            lambda pid, pgid: processes.append((pid, pgid)),
            lambda pid, pgid: released.append((pid, pgid)),
        )
        markers = []

        def cancelled():
            found = list(prepared.context.workspace.rglob("candidate-started"))
            if not found:
                return False
            if not markers:
                markers.append(float(found[0].read_text()))
            if failure == "exception":
                raise RuntimeError("fixed local cancellation fixture")
            return "invalid"

        with pytest.raises(scheduler.NativeTrustedSchedulerError, match="publication_failed"):
            scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments, cancelled=cancelled)
        assert time.monotonic() - markers[0] < 1.5
    assert len(processes) == 1 and processes == released
    assert len(requests) == 1 and (prepared.batch / "execution-receipt.json").exists()
    assert not (prepared.context.workspace / "evolution/producer-publication.json").exists()
    assert not (prepared.batch / "terminal.json").exists()
    assert _archive_projection(prepared.context.workspace) == before
    assert prepared.context.bundle_pipeline._remaining_timeout is None


def test_explicit_publication_guard_constrains_active_candidate_with_shared_control(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint, candidate_delay=3)
        arguments = prepared.arguments.copy()
        arguments.pop("strategy")
        produced = scheduler.run_native_trusted_producer(prepared.context.workspace, **arguments)
    before = _archive_projection(prepared.context.workspace)
    started = []

    def guard(stage):
        markers = list(prepared.context.workspace.rglob("candidate-started"))
        if markers:
            started.append(float(markers[0].read_text()))
            raise SolveExecutionCancelled(stage)

    with pytest.raises(SolveExecutionCancelled) as caught:
        run_native_producer_bundle_publication_transaction(
            prepared.context.workspace, prepared.strategy, produced.output.drafts, produced.output.admission_plan,
            journal_id=prepared.intent.journal_id, run_id=prepared.intent.run_id,
            parent_task_id=prepared.intent.parent_task_id, task_id=prepared.intent.task_id,
            native_execution_receipt_sha256=produced.receipt.receipt_sha256,
            execution_control=prepared.arguments["execution_control"], continuation_guard=guard,
        )
    assert caught.value.stage == "candidate_execution" and time.monotonic() - started[0] < 1.5
    assert len(requests) == 1 and _archive_projection(prepared.context.workspace) == before
    assert prepared.context.bundle_pipeline._remaining_timeout is None
