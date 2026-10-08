# Plan

Base: Feature183 implementation, with the final 5561c30 cancellation reason and
original-owner teardown fix to be included before submission. Its PR18
Linux acceptance/merge is separately tracked; this spec does not borrow it.

1. Native author owns native_producer_isolation.h plus
   tests/test_native_named_ipc_control.py. Extend the existing intersecting target
   seccomp denial using stable per-ABI syscall tables. Do not change C watcher.
2. Root owns Python selector/default/earliest gate, exports and compatibility
   tests, docs/HANDOFF and dedicated CI XML/annotation/upload wiring.
3. Native fixture establishes parent-owned queue usability then filtered refusal,
   plus real formal v2 launch composition and useful IO. i386-only syscalls are
   executed only on native i386 and explicitly skipped on other actual ABIs.
4. Focused pytest, Ruff, compileall and git diff --check after each change;
   independent source review and exact final three-version Linux raw audit precede merge.

No expansion into other kernel route filters in this slice. No changes to guardian
R/F/EOF/D, ECHILD drain, original deadline/grants or nonce/registration/receipts.
