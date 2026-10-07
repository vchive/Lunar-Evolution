# Plan

1. Confirm the private pipe asynchronous-signal route with an unfiltered inert baseline.
2. Extend the real isolation header with bounded full-word fcntl/fcntl64 and ioctl branches.
   Every matched branch returns directly; unrelated syscall-number evaluation is unchanged.
3. Version the Linux bootstrap descriptor and formal admission, retaining historical scope.
4. Add Linux request/command negative probes and ordinary I/O/lock/native composition checks.
   Add platform-independent descriptor negotiation and pre-effect admission tests.
5. Run focused tests, Ruff, compileall and diff checks. Add retained raw XML CI phase;
   independently audit final-head Ubuntu 3.11/3.12/3.13 before merging after PR12.

Darwin compilation/skips do not establish Linux enforcement. Preserve first failure evidence;
do not change already-running PR11/12 heads or infer final evidence from their CI.
