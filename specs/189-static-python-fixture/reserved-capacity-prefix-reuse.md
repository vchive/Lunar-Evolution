# Operation-local prefix parsing in reserved capacity accounting

The previous transition-only change is documented in
[reserved-rejection-prefix-reuse.md](reserved-rejection-prefix-reuse.md).
That historical change deliberately left capacity's standalone operations
independent. This continuation changes only the private reserved material
counter's two parses of one prefix during a single pure invocation.

## Contract

`_retained_reserved_brs_materials` first checks the caller's exact plain shapes
and retained ready references. It then freshly parses the original prefix once,
passes the detached facts to `_transition_scope_from_prefix`, and passes the
same facts to `_validated_entry_from_prefix`. Preserve the original order:
shape and ready failures, prefix failures, scope failures, wrapped entry
failures, then material/domain/aggregate failures. The entry helper preserves
the standalone entry validator's complete error translation.

Facts live only on this call's stack. Every subsequent call parses the original
prefix and current entry again. The standalone entry/scope validators remain
unchanged. The outer C2 capacity wrapper retains its own independent C2
transition validation; it does not reuse this counter's parsed result. Neither
the outer wrappers nor the counter expose parsed/trusted arguments or caches.

No SQL/FS observations, owner gates, callbacks, source/policy checks, inode
checks, original deadlines, budgets, retry counts or idle polling change.
The finite reserved executable policy already includes both modified and
reused helper modules; no extra policy bypass is introduced.

## Planned focused validation

The new `test_rsi_brs_reserved_capacity_prefix_reuse.py` covers valid empty,
mixed and seven-child historical prefixes; exact failure precedence and entry
error translation; mutation of each original prefix member and active entry
between calls; one-stack shared facts with fresh independent later objects;
and refusal before foreign methods or file access. It requires one prefix
parse in the private material counter, one in outer C1, and two independent
parses in outer C2 (transition plus material accounting).

Related existing coverage lives in `test_rsi_brs_reserved_rejection_consumers.py`,
`test_rsi_brs_reserved_rejection_prefix_reuse.py`,
`test_rsi_brs_reserved_rejection.py`, `test_rsi_brs_rejection_capacity.py`, and
`test_rsi_brs_reserved_policy.py`. Physical rejection provenance and the
original mixed serial acceptance remain separate from these pure tests.

The parent-owned16-file focused batch passed778 nodes, with no fail/error/skip
and matching2523-record source inventories. Ruff, compileall and diff checks
pass. The preceding collection-only failure from an unrelated huge-integer
parameter ID remains retained; no actual testcase ran in that attempt. No
prefix-only speedup or passing mixed/CI result is claimed. The preceding720c
unique v3 mixed still exceeded the original600-second limit; retain that failure
and all diagnostics rather than rerunning its source or increasing its budget.
