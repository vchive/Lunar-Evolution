"""Process-local request stop for one registered native acceptance run."""
from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager


class AcceptanceRequestBudgetError(ValueError):
    """Fixed-code request or observed-token limit failure."""


class AcceptanceRequestBudget:
    def __init__(self, max_requests: int, max_observed_tokens: int) -> None:
        if type(max_requests) is not int or max_requests < 1:
            raise AcceptanceRequestBudgetError("acceptance_request_limit_invalid")
        if type(max_observed_tokens) is not int or max_observed_tokens < 1:
            raise AcceptanceRequestBudgetError("acceptance_token_limit_invalid")
        self.max_requests = max_requests
        self.max_observed_tokens = max_observed_tokens
        self.requests = 0
        self.observed_tokens = 0
        self.usage_unknown = False
        self._lock = threading.Lock()

    def begin(self) -> None:
        with self._lock:
            if self.requests >= self.max_requests:
                raise AcceptanceRequestBudgetError("acceptance_request_limit_exhausted")
            if self.usage_unknown:
                raise AcceptanceRequestBudgetError("acceptance_token_usage_unknown")
            if self.observed_tokens >= self.max_observed_tokens:
                raise AcceptanceRequestBudgetError("acceptance_token_limit_exhausted")
            self.requests += 1

    def finish(self, usage: Mapping[str, int] | None) -> None:
        with self._lock:
            count = usage.get("total_tokens") if isinstance(usage, Mapping) else None
            if type(count) is not int or count < 0:
                self.usage_unknown = True
                raise AcceptanceRequestBudgetError("acceptance_token_usage_unknown")
            self.observed_tokens += count
            if self.observed_tokens > self.max_observed_tokens:
                raise AcceptanceRequestBudgetError("acceptance_token_limit_exhausted")

    def fail(self) -> None:
        with self._lock:
            self.usage_unknown = True

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "request_count": self.requests,
                "observed_tokens": self.observed_tokens,
                "usage_unknown": self.usage_unknown,
            }


_active_lock = threading.Lock()
_active: AcceptanceRequestBudget | None = None


def active_request_budget() -> AcceptanceRequestBudget | None:
    with _active_lock:
        return _active


@contextmanager
def own_request_budget(budget: AcceptanceRequestBudget) -> Iterator[None]:
    global _active
    if type(budget) is not AcceptanceRequestBudget:
        raise AcceptanceRequestBudgetError("acceptance_request_budget_invalid")
    with _active_lock:
        if _active is not None:
            raise AcceptanceRequestBudgetError("acceptance_request_budget_busy")
        _active = budget
    try:
        yield
    finally:
        with _active_lock:
            if _active is budget:
                _active = None


__all__ = ["AcceptanceRequestBudget", "AcceptanceRequestBudgetError", "own_request_budget"]
