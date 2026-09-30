# Feature 153: durable controlled producer deadline

## Scope and decision

Controlled native producer publication retains the caller's original absolute monotonic deadline
in `execution.deadline.json`, before writing `journal.prepared.json`. Both writes hold the existing
publication lock. A complete clock-only interruption can finish the same prepared intent; any
prepared intent or later work without its clock fails closed. There is no migration for older
controlled attempts. Uncontrolled transactions preserve the existing prepared-intent path.

The bounded canonical record pins the full prepared journal digest, original timeout, monotonic
start/deadline, native boot identity, clock kind, and its own file device/inode. Native Linux boot
identity is read from `/proc/sys/kernel/random/boot_id`; Darwin uses native `sysctlbyname` for
`kern.bootsessionuuid`. No wall-clock, process-ID boot fallback, shell, provider, or network call is
used. The original allowance and absolute deadline are restored only within the same OS boot.

Explicit injected clocks remain supported for deterministic local tests, with their clock kind
and PID recorded. They are never accepted by the cross-process restore API. A production clock
cannot adopt an injected-clock record, and a fixture clock cannot replace a native clock.

## Retention and failure rules

Files are created with descriptor-relative `O_EXCL|O_NOFOLLOW|O_CLOEXEC` writes in a checked
`DirectoryChain`; short writes are completed, then both file and directory are fsynced. Failed or
partial writes remain as recovery evidence. Reads use bounded no-follow/nonblocking descriptors,
require a regular private file with one link, and compare opened/named inode, size, mode, and
modification metadata before and after the read. Exact canonical bytes, strict schema and digest,
clock arithmetic, and recorded device/inode are verified. Symlinks, hard links, copied replacement
inodes, missing files, malformed JSON, duplicate fields, nonfinite values, and changed journal or
boot identity cannot refresh the budget.

The retained object reopens and verifies its original bytes/inode at each execution boundary.
This is immutable workspace integrity, not an authenticity claim against a privileged writer who
can rewrite all journal, file identity, and evidence records together.

## Transaction binding

The transaction derives its portable budget digest from the declared allowance as before. Once
the controlled prepared intent is fixed, its checkpoint binds the retained deadline alongside the
caller's and parent's controls. Every subsequent execution, evaluator, adjudication, staging, and
pre-commit boundary takes the minimum remaining time and preserves all cancellation callbacks.
The caller's control object is never mutated. A fresh control with the same nominal allowance
therefore cannot extend a retained attempt. Retained expiry also bounds publication-lock waiting.

Once publication crosses the existing durable unknown marker, its original critical-region rule
continues: it finishes publication or preserves unknown evidence instead of interrupting halfway
through commit. This change does not introduce automatic unknown reconciliation, immediate
mid-process cancellation, a scheduler, or a real producer campaign.

`restore_producer_bundle_execution_control(workspace, prepared_journal)` returns the original
allowance/start/deadline with the native monotonic clock. Current parent/task cancellation authority
must still be supplied by the caller; cancellation state is not inferred from a new process.

## Validation

Provider-free tests cover a real subprocess's persisted clock restored after process exit,
concurrent local processes preserving one clock, changed boot and clock rollback, expiry and
cancellation, old controlled-intent refusal, clock-only interruption, retained partial writes,
corruption/symlink/hardlink/inode replacement, journal/allowance drift, fresh-control non-extension,
expiry while publication lock is held, runtime mutation before a second candidate, and unchanged
no-control publication. Existing transaction/control, intent, staging and recovery tests remain
required. No model, remote evaluator, WebAgent or external campaign is run.
