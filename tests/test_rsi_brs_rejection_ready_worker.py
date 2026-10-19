"""Real inert channel threads; no owner admission, fixture solver or evaluator."""

from __future__ import annotations

import builtins
import threading
from types import FunctionType

import pytest
import test_rsi_python_brs_admission as channel_fixture

from lunar_evolution import rsi_python_brs_admission as admission
from lunar_evolution.rsi_learning import RSILearningError

threads = channel_fixture.threads
DIGEST, OTHER = channel_fixture.DIGEST, channel_fixture.OTHER


def _deliver_after_callback(threads, monkeypatch, mutate, *, guarded=True, downgrade=False,
                            arm_before_enqueue=False, mutate_channel=False):
    channel = threads.channel()
    channel._rejection_ready_worker_guarded = guarded
    published = threading.Event()
    changed = threading.Event()
    first_check, armed = threading.Event(), threading.Event()
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if checks == 1 and arm_before_enqueue:
            first_check.set()
            assert armed.wait(5)
        if checks >= 2:
            assert published.wait(5)
            if not changed.is_set():
                if downgrade:
                    channel._rejection_ready_worker_guarded = False
                mutate(channel) if mutate_channel else mutate()
                changed.set()

    with monkeypatch.context():
        worker = threads.request(channel, check=check)
        try:
            if arm_before_enqueue:
                assert first_check.wait(5)
                with channel._condition:
                    assert not channel._queue and not channel._requests
                    channel._rejection_ready_worker_guarded = True
                armed.set()
            worker.wait_posted()
            assert channel.service(lambda ready: OTHER, timeout=0) is True
            original = channel._requests["episode-1"].ack
            fields = channel._requests["episode-1"].ack_fields
            published.set()
            worker.wait_done()
            assert changed.is_set()
            assert channel._requests["episode-1"].ack is original
            assert channel._requests["episode-1"].ack_fields is fields
            return worker, original, fields
        finally:
            armed.set()
            published.set()


@pytest.mark.parametrize("guarded", [False, True])
def test_original_worker_ack_returns_detached_original_fields_without_changing_legacy(
        threads, monkeypatch, guarded):
    worker, original, fields = _deliver_after_callback(threads, monkeypatch, lambda: None, guarded=guarded)
    assert worker.error is None
    assert worker.result is not original
    assert (worker.result.run_id, worker.result.episode_id,
            worker.result.request_sha256, worker.result.record_sha256) == fields


@pytest.mark.parametrize("mutation", ["constructor-code", "post-init-code", "identity-code", "digest-code",
                                      "fail-code", "ack-alias", "field-metadata", "guard-code", "guard-alias"])
def test_staged_worker_refuses_post_check_ack_graph_changes_before_execution(
        threads, monkeypatch, mutation):
    calls = []

    def trap(*args, **kwargs):
        raise AssertionError("substituted ACK graph executed")

    def mutate():
        functions = {
            "constructor-code": admission.BRSAdmissionAck.__init__,
            "post-init-code": admission.BRSAdmissionAck.__post_init__,
            "identity-code": admission._identity, "digest-code": admission._sha,
            "fail-code": admission._fail, "guard-code": admission._assert_rejection_ready_worker_ack_graph,
        }
        if mutation in functions:
            function = functions[mutation]
            # Keep the original closure arity while making any invocation fail.
            code = function.__code__.replace(co_code=trap.__code__.co_code,
                                             co_consts=trap.__code__.co_consts,
                                             co_names=trap.__code__.co_names)
            monkeypatch.setattr(function, "__code__", code)
        elif mutation == "ack-alias":
            monkeypatch.setattr(admission, "BRSAdmissionAck", trap)
        elif mutation == "guard-alias":
            monkeypatch.setattr(admission, "_assert_rejection_ready_worker_ack_graph", trap)
        else:
            field = admission.BRSAdmissionAck.__dataclass_fields__["record_sha256"]
            monkeypatch.setattr(field, "metadata", {"changed": True})

    worker, _original, fields = _deliver_after_callback(threads, monkeypatch, mutate)
    assert isinstance(worker.error, RSILearningError)
    assert "rejection_ready_worker" in str(worker.error)
    assert worker.result is None and calls == []
    assert fields[-1] == OTHER


def test_staged_worker_refuses_guard_closure_rebinding_before_guard_execution(threads, monkeypatch):
    guard = admission._assert_rejection_ready_worker_ack_graph
    index = guard.__code__.co_freevars.index("kind")
    cell = guard.__closure__[index]
    original = cell.cell_contents
    calls = []

    def trap(*args, **kwargs):
        calls.append(True)
        raise AssertionError("changed guard primitive executed")

    def mutate():
        cell.cell_contents = trap

    try:
        worker, _ack, _fields = _deliver_after_callback(threads, monkeypatch, mutate)
        assert isinstance(worker.error, RSILearningError)
        assert "worker_guard_drift" in str(worker.error)
        assert calls == []
    finally:
        cell.cell_contents = original


@pytest.mark.parametrize("fault", ["pending-setattr", "condition-notify", "pending-and-notify"])
def test_guarded_failure_uses_held_pending_slots_and_original_native_waiters(threads, monkeypatch, fault):
    calls = []

    def trap(*args, **kwargs):
        calls.append(True)
        raise AssertionError("substituted failure callback executed")

    def mutate(channel):
        if fault in {"pending-setattr", "pending-and-notify"}:
            monkeypatch.setattr(admission._Pending, "__setattr__", trap)
        if fault in {"condition-notify", "pending-and-notify"}:
            monkeypatch.setattr(channel._condition, "notify_all", trap)
            monkeypatch.setattr(admission.BRSAdmissionAck, "__post_init__", trap)

    worker, original, fields = _deliver_after_callback(threads, monkeypatch, mutate, mutate_channel=True)
    assert isinstance(worker.error, RSILearningError)
    assert "worker_ack_graph_drift" in str(worker.error)
    assert worker.result is None and calls == []
    assert original.record_sha256 == fields[-1] == OTHER


def test_guarded_failure_catches_original_baseexception_after_callback_rebinds_builtin(threads, monkeypatch):
    original_base = BaseException

    class ForeignBase(Exception):
        pass

    channel = threads.channel()
    channel._rejection_ready_worker_guarded = True
    posted, published, done = threading.Event(), threading.Event(), threading.Event()
    outcome = {}

    def run():
        checks = 0
        try:
            # Restore the process builtin before reporting completion or letting
            # pytest inspect the failure; only request's local catch is tested.
            with monkeypatch.context() as changed:
                def check():
                    nonlocal checks
                    checks += 1
                    if checks >= 2:
                        posted.set()
                        assert published.wait(5)
                        changed.setattr(builtins, "BaseException", ForeignBase)

                try:
                    outcome["result"] = channel.request(channel_fixture._ready(), check=check)
                except original_base as failure:
                    outcome["error"] = failure
        finally:
            done.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert posted.wait(5)
        assert channel.service(lambda ready: OTHER, timeout=0) is True
        pending = channel._requests["episode-1"]
        ack, fields = pending.ack, pending.ack_fields
        published.set()
        assert done.wait(5)
        assert builtins.BaseException is original_base
        assert "result" not in outcome and isinstance(outcome["error"], RSILearningError)
        assert "worker_ack_graph_drift" in str(outcome["error"])
        assert pending.cancelled is True and pending.error == "worker_refused"
        assert channel._closed is True and channel._servicing is False
        assert pending.ack is ack and pending.ack_fields is fields
    finally:
        published.set()
        worker.join(5)
        assert not worker.is_alive()


@pytest.mark.parametrize("flag", [None, 0, 1, "true", object()])
def test_worker_scope_flag_is_exact_bool_before_ack_constructor(threads, monkeypatch, flag):
    channel = threads.channel()
    channel._rejection_ready_worker_guarded = flag
    worker = threads.request(channel)
    worker.wait_done()
    assert isinstance(worker.error, RSILearningError)
    assert "worker_scope_invalid" in str(worker.error)
    assert worker.result is None and not channel._requests and not channel._queue


def test_staged_callback_cannot_downgrade_worker_guard_to_legacy(threads, monkeypatch):
    worker, _ack, _fields = _deliver_after_callback(threads, monkeypatch, lambda: None, downgrade=True)
    assert isinstance(worker.error, RSILearningError)
    assert "worker_scope_invalid" in str(worker.error)
    assert worker.result is None


def test_owner_arming_during_first_callback_is_retained_at_real_worker_enqueue(threads, monkeypatch):
    # The request began while the channel was legacy/empty, then the owner armed
    # under its condition before the original request was actually enqueued.
    worker, _ack, _fields = _deliver_after_callback(
        threads, monkeypatch, lambda: None, guarded=False, downgrade=True, arm_before_enqueue=True)
    assert isinstance(worker.error, RSILearningError)
    assert "worker_scope_invalid" in str(worker.error)
    assert worker.result is None


def test_legacy_worker_does_not_enable_staged_guard(threads, monkeypatch):
    original = admission.BRSAdmissionAck.__post_init__
    calls = []

    def changed(self):
        calls.append(True)
        return original(self)

    worker, _ack, _fields = _deliver_after_callback(
        threads, monkeypatch, lambda: monkeypatch.setattr(admission.BRSAdmissionAck, "__post_init__", changed),
        guarded=False)
    assert worker.error is None and worker.result.record_sha256 == OTHER
    assert calls == [True]


@pytest.mark.parametrize("fault", ["inflight", "servicing", "closed", "cancelled", "fields-missing",
                                   "fields-short", "fields-foreign", "fields-mismatch"])
def test_staged_worker_refuses_ack_prefix_without_complete_transport_commit(threads, monkeypatch, fault):
    channel = threads.channel()
    channel._rejection_ready_worker_guarded = True
    published = threading.Event()
    changed = threading.Event()
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if checks >= 2:
            assert published.wait(5)
        if checks >= 2 and not changed.is_set():
            with channel._condition:
                pending = channel._requests["episode-1"]
                if fault == "inflight":
                    pending.state = "inflight"
                elif fault == "servicing":
                    channel._servicing = True
                elif fault == "closed":
                    channel._closed = True
                elif fault == "cancelled":
                    pending.cancelled = True
                elif fault == "fields-missing":
                    pending.ack_fields = None
                elif fault == "fields-short":
                    pending.ack_fields = pending.ack_fields[:3]
                elif fault == "fields-foreign":
                    pending.ack_fields = (*pending.ack_fields[:3], object())
                else:
                    pending.ack_fields = (*pending.ack_fields[:3], DIGEST)
                changed.set()

    worker = threads.request(channel, check=check)
    try:
        worker.wait_posted()
        # Block the worker's callback until all original assignments complete.
        with channel._condition:
            pending = channel._requests["episode-1"]
            channel._queue.popleft()
            pending.state = "done"
            pending.ack = admission.BRSAdmissionAck("run-1", "episode-1", pending.ready.request_sha256, OTHER)
            pending.ack_fields = ("run-1", "episode-1", pending.ready.request_sha256, OTHER)
            original = pending.ack
            published.set()
            channel._condition.notify_all()
        worker.wait_done()
        assert changed.is_set() and worker.result is None
        assert isinstance(worker.error, RSILearningError)
        assert "worker_commit_incomplete" in str(worker.error)
        assert pending.ack is original
    finally:
        published.set()


def test_channel_private_delegation_refuses_foreign_owner_without_callbacks():
    channel = admission.BRSAdmissionChannel("run-1", ("episode-1",))
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("foreign owner callback")

    with pytest.raises(RSILearningError, match="service_owner_required"):
        channel._service_selected_rejection_ready(Foreign(), timeout=1)
    assert calls == []


@pytest.mark.parametrize("fault", ["foreign-channel", "owner-subclass", "wrong-channel", "wrong-thread",
                                   "bool-thread", "worker-thread"])
def test_channel_private_delegation_requires_original_channel_and_owner_thread(fault):
    from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    class ForeignOwner(_BRSLineageCheckpointOwner):
        pass

    class ForeignChannel(admission.BRSAdmissionChannel):
        pass

    channel = (ForeignChannel if fault == "foreign-channel" else admission.BRSAdmissionChannel)(
        "run-1", ("episode-1",))
    owner = object.__new__(ForeignOwner if fault == "owner-subclass" else _BRSLineageCheckpointOwner)
    owner._channel = object() if fault == "wrong-channel" else channel
    owner._thread = (True if fault == "bool-thread" else
                     threading.get_ident() + 1 if fault == "wrong-thread" else threading.get_ident())
    errors = []

    def attempt():
        try:
            admission.BRSAdmissionChannel._service_selected_rejection_ready(channel, owner, timeout=1)
        except RSILearningError as exc:
            errors.append(exc)

    if fault == "worker-thread":
        worker = threading.Thread(target=attempt)
        worker.start()
        worker.join(5)
        assert not worker.is_alive()
    else:
        attempt()
    assert len(errors) == 1 and "service_owner_required" in str(errors[0])


def test_private_delegation_has_no_handler_or_ack_argument():
    channel = admission.BRSAdmissionChannel("run-1", ("episode-1",))
    with pytest.raises(TypeError):
        channel._service_selected_rejection_ready(object(), timeout=1, handler=lambda ready: DIGEST)


def test_private_delegation_forwards_original_owner_timeout_and_digest(monkeypatch):
    from lunar_evolution import rsi_brs_rejection_ready_service as service
    from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    channel = admission.BRSAdmissionChannel("run-1", ("episode-1",))
    owner = object.__new__(_BRSLineageCheckpointOwner)
    owner._channel, owner._thread = channel, threading.get_ident()
    calls = []

    def fixed_delegate(actual, *, timeout):
        calls.append((actual, timeout))
        return DIGEST

    monkeypatch.setattr(service, "service_rejection_ready", fixed_delegate)
    assert channel._service_selected_rejection_ready(owner, timeout=0.5) is DIGEST
    assert calls == [(owner, 0.5)]


def test_guard_original_code_cannot_be_rebaselined_by_equal_function_clone(monkeypatch):
    original = admission._identity
    clone = FunctionType(original.__code__, original.__globals__, original.__name__,
                         original.__defaults__, original.__closure__)
    monkeypatch.setattr(admission, "_identity", clone)
    with pytest.raises(RSILearningError, match="worker_ack_graph_drift"):
        admission._assert_rejection_ready_worker_ack_graph()
