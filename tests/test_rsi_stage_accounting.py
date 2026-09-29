"""Persistence failure also stops stage callers already waiting for the accounting lock."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_stage_accounting import DurableStageAccounting


class ObservedLock:
    def __init__(self):
        self.lock = threading.RLock()
        self.waiting = threading.Event()
        self.owner = threading.get_ident()

    def __enter__(self):
        if threading.get_ident() != self.owner:
            self.waiting.set()
        self.lock.acquire()
        return self

    def __exit__(self, *_):
        self.lock.release()


@pytest.mark.parametrize("operation", ["reserve", "complete"])
def test_queued_stage_cannot_continue_after_persistence_failure(operation):
    lock = ObservedLock()
    state = {"invocations": []}
    budget = RSIRunBudget.create({"max_evaluator_invocations": 3}).state
    writes = []
    fail = False

    def persist():
        writes.append(len(state["invocations"]))
        if fail:
            raise OSError("checkpoint unavailable")

    accounting = DurableStageAccounting(state, budget, persist, lock=lock)
    row = accounting.reserve("evaluator", {"episode_id": "original"}) if operation == "complete" else None

    def act():
        if operation == "complete":
            accounting.complete(row, "a" * 64)
        else:
            accounting.reserve("evaluator", {"episode_id": "queued"})

    with ThreadPoolExecutor(max_workers=1) as executor:
        with lock:
            queued = executor.submit(act)
            assert lock.waiting.wait(5), "worker did not reach the locked operation"
            fail = True
            with pytest.raises(OSError, match="checkpoint unavailable"):
                act()
            write_count = len(writes)
            fail = False
        with pytest.raises(RSILearningError, match="rsi_stage_accounting_poisoned"):
            queued.result(timeout=5)
    assert len(writes) == write_count
    assert budget["consumed"]["evaluator_invocations"] == (1 if row else 0)
    assert row is None or row["evidence"] is None
