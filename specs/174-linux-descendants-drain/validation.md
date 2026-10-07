# Validation

Implementation and local validation are complete. Local Darwin skips cannot establish Linux
subreaper or syscall behavior. Actual Linux acceptance and merge still require this feature's
final-head CI. No prior PR's green result is reused as evidence for this slice.

Retain raw JUnit files with failure/error/skip counts; do not rerun the current complete phase
to conceal failures. Existing narrow archived-suite retry rules remain unchanged.

## Local evidence

- Combined host/bootstrap/attempt/deadline/controller-death/anchor/worker-verifier focus:
  242 cases,214 passed,28 Darwin platform skips,0failure/error;
  `/tmp/lunar-feature174-final-focus.xml`. This ran on final C/Python implementation before
  adding the final no-Darwin-relabel test and Linux-only non-SIGCHLD seam.
- Scheduler/broker/RSI/controller/OpenEvolve composition:84 passed,0skip/failure/error;
  `/tmp/lunar-feature174-composition-final.xml`.
- Binding+descendants focus after the no-relabel test:46 cases,25 passed,21 Linux skips,
 0failure/error; `/tmp/lunar-feature174-binding-final.xml`. The later final descendants suite
  has32 cases,10 passed,22 Linux skips,0failure/error;
  `/tmp/lunar-native-descendants-darwin-tests-v6.xml`. Final combined binding+descendants suite
  has47 cases,25 passed,22 Linux skips,0failure/error;
  `/tmp/lunar-feature174-final47.xml`. Counts overlap and are not additive.
- Common guard retirement/terminal/closed-frame compatibility:6 passed on final C;
  `/tmp/lunar-feature174-c-join-final-oct8.xml`.
- Ruff `src tests tools`, compileall and diff check passed. Independent review closed the
  guardian join-tail observation window and confirmed no added historical evidence authority.

The descendants fixtures wait for direct exit, redirect child streams and require the bootstrap
to remain alive with no terminal. Natural success requires child PID disappearance, not merely
zombie inactivity. Orphan clone is compatibility coverage: Linux reparents it with SIGCHLD.
The separate `__WALL` seam creates a real clone(flags0) child in the bootstrap after direct wait,
independently observes PPid and exit_signal0 through `/proc`, and requires it to be reaped before
terminal. This is a test-only kernel-child seam, not a new production target interface.

The join fault wrapper really joins the watcher, closes the sole actual owner writer while
paused, and verifies a nonzero bootstrap exit on resumption despite an already-observed seq3.
Setup/wait faults are compile-time wrappers; production has no environment bypass. Linux
EOF/deadline/controller SIGKILL cases retain bounded original-group fixture teardown.

CI preserves a dedicated `descendants-drain.xml` before existing phases, original current/archive/
frozen XML and any sole permitted historical archive retry. Complete final-head three-version
CI and main merge remain pending at this source commit; the PR checks and merge record supply
actual status. No real model, campaign or remote/company evaluator was used.
