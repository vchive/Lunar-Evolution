"""Actual C producer → host broker → exact seed admission through OpenEvolveStrategy."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_evolution import _contract, _report
from test_http_transport_deadline import clear_proxy_environment, local_http

import lunar_evolution.openevolve_native as native
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
)
from lunar_evolution.evolution import (
    CandidateArchive,
    CandidateDraft,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    OpenEvolveStrategy,
)
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_launch_inputs import bind_producer_launch_inputs
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
SOURCE = "def solve():\n    return 42\n"


def _snapshot(root: Path):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_dev, path.stat().st_ino,
                                         path.stat().st_mtime_ns, path.stat().st_ctime_ns)
            for path in root.rglob("*") if path.is_file()}


def _fixture(tmp_path: Path, endpoint: str, *, delay: int = 0, evaluator=None, cancelled=lambda: False,
             deadline_seconds: float = 15, target_exit: int = 0):
    workspace, producer = tmp_path / "canonical", tmp_path / "producer"
    workspace.mkdir()
    producer.mkdir()
    target = producer / "target"
    calls = []

    def evaluate(path, contract):
        calls.append(path)
        assert path.read_text() == SOURCE
        assert contract.digest() == context.contract.digest()
        return evaluator(path, contract) if evaluator is not None else _report(0.75)

    config = EvolutionConfig(strategy="openevolve", command=(str(target),), timeout_seconds=20,
                             evaluator_fingerprint="a" * 64, runner_fingerprint="b" * 64)
    context = EvolutionContext(_contract("openevolve"), workspace, lambda _: CandidateDraft("unused"),
                               evaluate, config, cancelled=cancelled)
    producer_pin = OpenEvolveStrategy(context, read_only=True)._producer_fingerprint()
    envelope = {"schema_version": "1", "producer_id": "openevolve", "producer_fingerprint": producer_pin,
                "status": "completed", "contract_sha256": context.contract.digest(), "budget": {"requests": 1},
                "external_evidence": {"external_score": 999},
                "materials": [{"kind": "candidate_source", "path": "candidate.py", "size": len(SOURCE.encode()),
                               "sha256": hashlib.sha256(SOURCE.encode()).hexdigest()}]}
    program = (
        '#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n'
        'int main(int argc,char **argv){\n'
        'if(argc!=4||strcmp(argv[1],"../.producer-input/config.json")'
        '||strcmp(argv[2],"--lunar-producer-input-v1")||strlen(argv[3])!=64)return 2;\n'
        'FILE *f=fopen(argv[1],"rb");if(!f)return 3;char config[65536];'
        'size_t size=fread(config,1,sizeof(config)-1,f);config[size]=0;fclose(f);\n'
        f'if(!strstr(config,{json.dumps(producer_pin)})||!strstr(config,"evolution-fixture"))return 4;\n'
        'f=fopen("started","wb");if(!f||fputs("target",f)<0||fclose(f))return 5;\n'
        f'sleep({delay});if({target_exit})return {target_exit};\n'
        'const char *w=getenv("LUNAR_PRODUCER_REQUEST_FD"),*r=getenv("LUNAR_PRODUCER_RESPONSE_FD");'
        'if(!w||!r)return 6;\n'
        'const char *q="{\\"protocol\\":\\"lunar-producer-broker-ipc-v1\\",'
        '\\"request_id\\":\\"req-1\\",\\"body_base64\\":\\"aGVsbG8=\\"}\\n";\n'
        'if(write(atoi(w),q,strlen(q))!=(ssize_t)strlen(q))return 7;\n'
        'char reply[4096];int n=0;char c;while(n<4095&&read(atoi(r),&c,1)==1){reply[n++]=c;if(c==10)break;}'
        'reply[n]=0;if(!strstr(reply,"\\"status\\":\\"completed\\""))return 8;\n'
        f'f=fopen("../output/candidate.py","wb");if(!f||fputs({json.dumps(SOURCE)},f)<0||fclose(f))return 9;\n'
        f'f=fopen("../output/producer-result.json","wb");if(!f||fputs({json.dumps(json.dumps(envelope))},f)<0||fclose(f))return 10;'
        'return 0;}\n'
    )
    source = producer / "target.c"
    source.write_text(program)
    compile_native_target(source, target)
    artifact = build_native_bootstrap_artifact(tmp_path / "bootstrap")
    inputs = native.prepare_openevolve_native_inputs(context, journal_id="journal")
    runtime = native.openevolve_native_workspace(workspace)
    intent = build_producer_launch_intent(
        producer_root=producer, launch_id="launch", journal_id="journal", run_id="run",
        parent_task_id="parent", task_id="task", contract_sha256=context.contract.digest(),
        evaluator_kind="exact_harness", evaluator_fingerprint=config.evaluator_fingerprint,
        runner_fingerprint="b" * 64, generator_fingerprint=producer_pin,
        dependency_sha256="c" * 64, environment_sha256="d" * 64,
        producer_id="openevolve", producer_fingerprint=producer_pin, executable_relative="target",
        argv=("target", "../.producer-input/config.json", *inputs.argv_fragment),
        working_directory="work", output_directory="output", request_timeout_seconds=5,
        max_requests=1, output_max_bytes=65536, wall_timeout_seconds=12,
    )
    attestation = build_producer_launch_attestation(intent, "fixture-once")
    bound = bind_producer_launch_inputs(runtime, intent=intent, attestation=attestation, artifact=artifact, inputs=inputs)
    execution = native.OpenEvolveNativeExecution(
        producer, intent, attestation, artifact, ProducerBrokerConfig(endpoint, {"X-Fixture": "host-only"}),
        (BundleGroup("single", "candidate.py", ("candidate.py",)),), time.time() + deadline_seconds,
    )
    context = replace(context, trusted_native_execution=execution)
    return SimpleNamespace(context=context, execution=execution, calls=calls, inputs=bound, runtime=runtime,
                           batch=runtime / "evolution" / "producer-batches" / "journal")


def test_actual_native_strategy_commits_local_score_and_readonly_replay(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        monkeypatch.setattr(OpenEvolveStrategy, "_run_producer", lambda *args: pytest.fail("legacy Popen invoked"))
        result = OpenEvolveStrategy(fixture.context).run()
        assert result.status == "completed" and result.best_score == 0.75
        assert len(fixture.calls) == len(requests) == 1
        state = CandidateArchive(fixture.context.workspace).read_state()
        assert state["trusted_native_admission"]["protocol"] == "lunar-openevolve-native-admission-v1"
        assert (fixture.runtime / "completion.json").is_file()
        local = json.loads((fixture.runtime / "admission.json").read_text())
        assert local["seed_dependency_sha256"] != fixture.execution.intent.dependency_sha256
        assert local["seed_environment_sha256"] != fixture.execution.intent.environment_sha256
        before = _snapshot(fixture.context.workspace)
        monkeypatch.setattr(native, "run_native_trusted_lifecycle", lambda *a, **k: pytest.fail("relaunch"))
        monkeypatch.setattr(native, "admit_producer_envelope", lambda *a, **k: pytest.fail("reevaluate"))
        monkeypatch.setattr(CandidateArchive, "commit_initial_seeds", lambda *a, **k: pytest.fail("recommit"))
        for _ in range(2):
            assert OpenEvolveStrategy(fixture.context).resume() == result
        assert len(fixture.calls) == len(requests) == 1
        assert _snapshot(fixture.context.workspace) == before


@pytest.mark.parametrize("mode", ["started", "evaluation_error", "publication_error", "missing_ack"])
def test_unknown_never_relaunches_reevaluates_or_republishes(tmp_path, monkeypatch, mode):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        def evaluate(path, contract):
            raise RuntimeError("uncertain local evaluator")

        fixture = _fixture(tmp_path, endpoint, evaluator=evaluate if mode == "evaluation_error" else None)
        strategy = OpenEvolveStrategy(fixture.context)
        if mode == "started":
            binding = native._binding(strategy, fixture.execution)
            native._checkpoint(fixture.runtime / "admission-claim.json", {
                "protocol": native._PROTOCOL, "status": "started", "binding": binding,
                "plan_sha256": native._sha(binding),
            })
        elif mode == "publication_error":
            monkeypatch.setattr(strategy.archive, "commit_initial_seeds", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("lost")))
        elif mode == "missing_ack":
            checkpoint = native._checkpoint

            def lose_ack(path, payload):
                if path.name == "completion.json":
                    raise RuntimeError("lost acknowledgement")
                return checkpoint(path, payload)

            monkeypatch.setattr(native, "_checkpoint", lose_ack)
        if mode != "started":
            with pytest.raises(EvolutionError):
                strategy.run()
        before, call_count, request_count = _snapshot(fixture.context.workspace), len(fixture.calls), len(requests)
        monkeypatch.setattr(native, "run_native_trusted_lifecycle", lambda *a, **k: pytest.fail("relaunch"))
        monkeypatch.setattr(native, "admit_producer_envelope", lambda *a, **k: pytest.fail("reevaluate"))
        monkeypatch.setattr(CandidateArchive, "commit_initial_seeds", lambda *a, **k: pytest.fail("recommit"))
        with pytest.raises(EvolutionError, match="^openevolve_native_recovery_required$"):
            OpenEvolveStrategy(fixture.context).resume()
        assert (len(fixture.calls), len(requests)) == (call_count, request_count)
        assert _snapshot(fixture.context.workspace) == before


@pytest.mark.parametrize("phase", ["before_launch", "active", "evaluation"])
def test_cancellation_preserves_one_shot_claim(tmp_path, monkeypatch, phase):
    clear_proxy_environment(monkeypatch)
    signal = {"cancelled": phase == "before_launch"}
    with local_http() as (endpoint, requests):
        def evaluate(path, contract):
            signal["cancelled"] = True
            return _report(0.75)

        fixture = _fixture(tmp_path, endpoint, delay=2 if phase == "active" else 0,
                           evaluator=evaluate if phase == "evaluation" else None,
                           cancelled=lambda: signal["cancelled"] or (
                               phase == "active" and (fixture.batch / "work" / "started").exists()))
        with pytest.raises(SolveExecutionCancelled):
            OpenEvolveStrategy(fixture.context).run()
        assert not (fixture.context.workspace / "evolution" / "state.json").exists()
        if phase == "before_launch":
            assert not (fixture.runtime / "admission-claim.json").exists()
        else:
            before = _snapshot(fixture.context.workspace)
            with pytest.raises(EvolutionError, match="recovery_required"):
                OpenEvolveStrategy(fixture.context).run()
            assert _snapshot(fixture.context.workspace) == before
        assert len(requests) == (1 if phase == "evaluation" else 0)


def test_original_total_deadline_stops_active_target_and_prevents_retry(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint, delay=3, deadline_seconds=0.4)
        with pytest.raises(SolveExecutionBudgetExceeded):
            OpenEvolveStrategy(fixture.context).run()
        assert not fixture.calls and not requests
        before = _snapshot(fixture.context.workspace)
        with pytest.raises(EvolutionError, match="recovery_required"):
            OpenEvolveStrategy(fixture.context).run()
        assert _snapshot(fixture.context.workspace) == before


@pytest.mark.parametrize("drift", ["config", "intent", "deadline", "executable", "input_inode", "runtime_inode"])
def test_start_binding_drift_refuses_before_any_effect(tmp_path, monkeypatch, drift):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        strategy = OpenEvolveStrategy(fixture.context)
        binding = native._binding(strategy, fixture.execution)
        native._checkpoint(fixture.runtime / "admission-claim.json", {
            "protocol": native._PROTOCOL, "status": "started", "binding": binding,
            "plan_sha256": native._sha(binding),
        })
        context = fixture.context
        if drift == "config":
            context = replace(context, config=replace(context.config, max_rounds=6))
        elif drift == "deadline":
            context = replace(context, trusted_native_execution=replace(fixture.execution, deadline_unix=time.time() + 10))
        elif drift == "intent":
            context = replace(context, trusted_native_execution=replace(fixture.execution, intent=replace(
                fixture.execution.intent, task_id="different", intent_sha256=None)))
        elif drift == "executable":
            (fixture.execution.producer_root / "target").write_bytes(b"changed")
        elif drift == "input_inode":
            path = fixture.inputs.config_path
            raw = path.read_bytes()
            path.parent.chmod(0o700)
            path.unlink()
            path.write_bytes(raw)
            path.chmod(0o400)
            path.parent.chmod(0o500)
        else:
            retained = fixture.runtime.with_name("old-runtime")
            fixture.runtime.rename(retained)
            fixture.runtime.mkdir()
        before = _snapshot(fixture.context.workspace)
        with pytest.raises(EvolutionError):
            OpenEvolveStrategy(context).run()
        assert not fixture.calls and not requests
        assert _snapshot(fixture.context.workspace) == before


@pytest.mark.parametrize("path", ["completion.json", "admission.json", "admission-claim.json",
                                  "evolution/state.json", "evolution/archive.jsonl", "candidate.py"])
def test_completed_evidence_drift_refuses_readonly(tmp_path, monkeypatch, path):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        result = OpenEvolveStrategy(fixture.context).run()
        if path == "candidate.py":
            target = fixture.context.workspace / result.best_candidate_path
        elif path.startswith("evolution/"):
            target = fixture.context.workspace / path
        else:
            target = fixture.runtime / path
        target.chmod(0o600)
        target.write_bytes(target.read_bytes() + b" ")
        target.chmod(0o400)
        before = _snapshot(fixture.context.workspace)
        with pytest.raises(EvolutionError):
            OpenEvolveStrategy(fixture.context).resume()
        assert _snapshot(fixture.context.workspace) == before
        assert len(fixture.calls) == len(requests) == 1


@pytest.mark.parametrize("completed", [True, False])
def test_missing_injection_cannot_downgrade_to_legacy(tmp_path, monkeypatch, completed):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        if completed:
            OpenEvolveStrategy(fixture.context).run()
        context = replace(fixture.context, trusted_native_execution=None)
        before = _snapshot(fixture.context.workspace)
        monkeypatch.setattr(OpenEvolveStrategy, "_run_producer", lambda *a: pytest.fail("legacy relaunch"))
        with pytest.raises(EvolutionError, match="protocol_mismatch"):
            OpenEvolveStrategy(context).run()
        assert _snapshot(fixture.context.workspace) == before
        assert len(requests) == (1 if completed else 0)


def test_completed_replay_ignores_expired_admission_deadline(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        result = OpenEvolveStrategy(fixture.context).run()
        before = _snapshot(fixture.context.workspace)
        wall = time.time()
        monkeypatch.setattr(native.time, "time", lambda: wall + 1000)
        assert OpenEvolveStrategy(fixture.context).resume() == result
        assert _snapshot(fixture.context.workspace) == before
        assert len(fixture.calls) == len(requests) == 1


def test_native_nonzero_does_not_evaluate_or_publish(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint, target_exit=17)
        with pytest.raises(EvolutionError):
            OpenEvolveStrategy(fixture.context).run()
        assert not fixture.calls and not requests
        with pytest.raises(EvolutionError, match="recovery_required"):
            OpenEvolveStrategy(fixture.context).run()


def test_shorter_parent_budget_is_applied_to_active_target(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint, delay=3)
        deadline = time.monotonic() + 0.4
        context = replace(fixture.context, remaining_timeout=lambda stage: deadline - time.monotonic())
        started = time.monotonic()
        with pytest.raises(SolveExecutionBudgetExceeded):
            OpenEvolveStrategy(context).run()
        assert time.monotonic() - started < 2
        assert not fixture.calls and not requests
        assert not (fixture.runtime / "completion.json").exists()


def test_active_owner_loss_stops_native_target(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint, delay=3)

        def owner_guard():
            if (fixture.batch / "work" / "started").exists():
                raise EvolutionError("owner_lost")

        context = replace(fixture.context, continuation_guard=owner_guard)
        started = time.monotonic()
        with pytest.raises(EvolutionError, match="^owner_lost$"):
            OpenEvolveStrategy(context).run()
        assert time.monotonic() - started < 2
        assert not fixture.calls and not requests


@pytest.mark.parametrize("failure", [False, True])
def test_evaluator_timeout_hook_is_restored(tmp_path, monkeypatch, failure):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)

        class Evaluator:
            def __init__(self):
                self.callback = None
                self.calls = []

            def set_remaining_timeout(self, callback):
                self.callback = callback

            def __call__(self, path, contract):
                self.calls.append(self.callback("evaluate"))
                if failure:
                    raise RuntimeError("uncertain")
                return _report(0.75)

        evaluator = Evaluator()
        parent = lambda stage: 5
        context = replace(fixture.context, evaluate=evaluator, remaining_timeout=parent)
        strategy = OpenEvolveStrategy(context)
        assert evaluator.callback is parent
        if failure:
            with pytest.raises(EvolutionError, match="local_evaluation_failed"):
                strategy.run()
        else:
            strategy.run()
        assert len(evaluator.calls) == 1 and 0 < evaluator.calls[0] <= 5
        assert evaluator.callback is parent
        assert len(requests) == 1


@pytest.mark.parametrize("file", ["config", "executable", "native_terminal"])
def test_evaluator_cannot_drift_launch_evidence_before_commit(tmp_path, monkeypatch, file):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        def evaluate(path, contract):
            if file == "config":
                target = fixture.inputs.config_path
            elif file == "executable":
                target = fixture.execution.producer_root / "target"
            else:
                target = fixture.batch / "native-trusted-process-terminal.json"
            assert target.is_file()
            target.chmod(0o600)
            target.write_bytes(target.read_bytes() + b"drift")
            return _report(0.75)

        fixture = _fixture(tmp_path, endpoint, evaluator=evaluate)
        with pytest.raises(EvolutionError):
            OpenEvolveStrategy(fixture.context).run()
        assert len(fixture.calls) == len(requests) == 1
        assert not (fixture.runtime / "completion.json").exists()
        assert not (fixture.context.workspace / "evolution" / "state.json").exists()


def test_nested_retry_during_evaluation_has_no_effects(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        def evaluate(path, contract):
            before = _snapshot(fixture.context.workspace)
            with pytest.raises(EvolutionError, match="recovery_required"):
                OpenEvolveStrategy(fixture.context).run()
            assert _snapshot(fixture.context.workspace) == before
            return _report(0.75)

        fixture = _fixture(tmp_path, endpoint, evaluator=evaluate)
        assert OpenEvolveStrategy(fixture.context).run().status == "completed"
        assert len(fixture.calls) == len(requests) == 1


@pytest.mark.parametrize("clock", ["wall_sample", "parent_callback"])
def test_clock_sampling_pause_cannot_extend_original_budget(tmp_path, monkeypatch, clock):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint, deadline_seconds=0.2 if clock == "wall_sample" else 15)
        context = fixture.context
        if clock == "wall_sample":
            wall = time.time()

            def paused_wall():
                time.sleep(0.4)
                return wall

            monkeypatch.setattr(native.time, "time", paused_wall)
        else:
            def parent(stage):
                time.sleep(0.3)
                return 0.1

            context = replace(context, remaining_timeout=parent)
        with pytest.raises(SolveExecutionBudgetExceeded):
            OpenEvolveStrategy(context).run()
        assert not fixture.calls and not requests
        assert not (fixture.runtime / "admission-claim.json").exists()


@pytest.mark.parametrize("file", ["config", "native_terminal", "output"])
def test_publication_guard_cannot_drift_evidence_before_commit(tmp_path, monkeypatch, file):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        mutated = []

        def owner_guard():
            if (fixture.runtime / "admission.json").exists() and not mutated:
                if file == "config":
                    target = fixture.inputs.config_path
                elif file == "native_terminal":
                    target = fixture.batch / "native-trusted-process-terminal.json"
                else:
                    target = fixture.batch / "output" / "candidate.py"
                target.chmod(0o600)
                target.write_bytes(target.read_bytes() + b"drift")
                mutated.append(target)

        context = replace(fixture.context, continuation_guard=owner_guard)
        with pytest.raises(EvolutionError):
            OpenEvolveStrategy(context).run()
        assert mutated and len(fixture.calls) == len(requests) == 1
        assert not (fixture.runtime / "completion.json").exists()
        assert not (fixture.context.workspace / "evolution" / "state.json").exists()


@pytest.mark.parametrize("endpoint", ["http://user:password@localhost/", "http://localhost/?api_key=fixture",
                                      "http://localhost/#token"])
def test_endpoint_auth_is_not_persisted_in_execution_plan(tmp_path, endpoint):
    fixture = _fixture(tmp_path, "http://127.0.0.1:1/")
    before = _snapshot(fixture.context.workspace)
    with pytest.raises(EvolutionError, match="broker_endpoint_invalid"):
        replace(fixture.execution, broker_config=ProducerBrokerConfig(endpoint, {}))
    assert _snapshot(fixture.context.workspace) == before


def test_commit_critical_region_retains_success_after_late_cancellation(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    signal = {"cancelled": False}
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint, cancelled=lambda: signal["cancelled"])
        strategy = OpenEvolveStrategy(fixture.context)
        commit = strategy.archive.commit_initial_seeds

        def commit_then_cancel(*args, **kwargs):
            result = commit(*args, **kwargs)
            signal["cancelled"] = True
            return result

        monkeypatch.setattr(strategy.archive, "commit_initial_seeds", commit_then_cancel)
        assert strategy.run().status == "completed"
        assert (fixture.runtime / "completion.json").is_file()
        assert len(fixture.calls) == len(requests) == 1


@pytest.mark.parametrize("name", [".evolution-seed-backup-v1", ".evolution-seed-stage-v1"])
def test_constructor_does_not_repair_trusted_seed_recovery_trees(tmp_path, monkeypatch, name):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        fixture = _fixture(tmp_path, endpoint)
        OpenEvolveStrategy(fixture.context).run()
        recovery = fixture.context.workspace / name
        recovery.mkdir()
        (recovery / "contract.json").write_text(json.dumps(fixture.context.contract.to_dict(), sort_keys=True, indent=2) + "\n")
        before = _snapshot(fixture.context.workspace)
        with pytest.raises(EvolutionError, match="recovery_required"):
            OpenEvolveStrategy(fixture.context).resume()
        assert _snapshot(fixture.context.workspace) == before
        assert recovery.is_dir() and len(fixture.calls) == len(requests) == 1
