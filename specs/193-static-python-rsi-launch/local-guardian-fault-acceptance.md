# Explicit local guardian fault observations

Status: the successor unified Linux regression of tree `7628e971` passed both
actual same-UID fault cases and all 69 cases in this file. The complete batch
passed 758 of 759 cases; one legacy host watcher mock requires correction.
The prior 618/620 batch and its two actual deadline failures remain retained.
A separate sealed-target diagnostic identified uutils' executable-name refusal;
the explicit compiled nanosleep profile and original-watcher readiness checks
address that observed failure without changing the original 20-second budgets.
These are local fixture observations, not production or independent-account
deployment acceptance.
The entry point is `tools/native_guardian_fault_acceptance.py`. It is a separate
acceptance tool and is not connected to the root CLI or its defaults.

## Reuse and boundary

Feature 197 already provides the native receiver, creator-owned guardian launch,
original-reference inspection, native registration pairing and installed
bridge/vault sidecar. Existing fixtures already demonstrate controller
`os._exit` and original-reference reading. This tool does not replace or extend
those protocols, install an account, generate an attestation, provision a key,
construct a worker assignment, or claim installed-vault acceptance.

It calls the existing `start_durable_native_guardian` and
`inspect_native_guardian_custody` APIs using explicitly supplied, already built
receiver and guardian ELF images. It reuses the existing sealed-executable
owners and their image checks. The target is a fixed inert wait, executed from
the explicitly selected trusted-local image profile described below, with one
duration capped to the original remaining budget.
It starts no candidate algorithm, model, solver, WebAgent or evaluator. Native
images are caller-trusted local installations; there is no build attestation,
immutable source/bytecode custody, closed dynamic-library tree or account
isolation claim. The target can use the host ELF interpreter/libraries.

The coordinator, controller, receiver, guardian and target all retain the
calling UID. No root privilege, account transition or separate candidate
identity is simulated. The independent receiver process is not an independent
security principal. Missing installed images, non-ELF images, unsupported sealed
execution or missing kernel pidfd group-signaling support must fail; there is
no alternate Python watcher or numeric PGID fallback.

## One explicit invocation

Run one fault per fresh absolute output directory, for example:

```sh
python -B tools/native_guardian_fault_acceptance.py run \
  --fault controller-exit \
  --receiver /absolute/installed/native-guardian-receiver \
  --guardian /absolute/installed/native-bootstrap \
  --output /absolute/private/fresh-controller-exit-evidence \
  --budget-seconds 20
```

The other fixed fault is `receiver-kill`. All five options are mandatory.
The optional `--target-profile` is a finite explicit selection; its default is
`system-sleep`. It is never inferred or changed after a failed attempt.
Budgets are finite, between 5 and 60 seconds. The script does not compile,
download, install or choose another target. Both actual fault tests keep their
original 20-second budgets and zero retries. They use the existing real native
compiler fixture to build the checked-in inert nanosleep source before a single
explicit run, when the batch owner runs the focused test file.

An existing output directory refuses even when its prior attempt failed. No
original file is removed, replaced, repaired or retried. A separate invocation
with a new directory is a separate explicit experiment, never an automatic
retry. Exit 0 means the narrowly specified local fixture was observed; it does
not mean native execution, cleanup, production or release acceptance passed.
Exit 2 means the observation failed or remains unknown. Configuration/setup
errors can also terminate the tool without a completed result; retained partial
files must not be interpreted as a pass.

## Original reference and faults

The coordinator fixes one monotonic origin and one absolute deadline before
pinning images or launching a process. The controller receives those exact
values. Sealing, native launch/readiness, trigger exchange, abnormal cleanup,
event observation and the fresh reader all consume that budget. No stage
renews the deadline. Event polling reserves reader time within the same original
deadline; it does not extend the guardian's execution deadline.

After the real receiver durably registers and the existing API returns its
original live owner, the controller writes that owner's exact canonical
reference to the coordinator over its original stdout pipe. The coordinator
exclusively creates and fsyncs `original-reference.json` and its containing
directory before sending the single `G` trigger. The reference is never derived
from current receiver records. The context/launch/profile hashes identify only
this local fixture's original inputs and are not attestation or credentials.

* `controller-exit`: the actual controller calls `os._exit(79)` with its sole
  lifeline writer still open, without normal finish or a Python `finally` cleanup.
  Its death produces EOF. The surviving receiver can retain the original native
  guardian's abnormal exit 78 before the original deadline. The required fresh
  read reports `watcher_exit_observed`, D=false, exit-kind=1 and exit-value=78.
* `receiver-kill`: the live controller kills and reaps only its exact original
  receiver `Popen`, closes its own lifeline writer and invokes the existing
  owner cleanup once, using the remaining original budget. The receiver's
  actual return code must be `-SIGKILL`. The fresh read must preserve the original
  registration, and the durable owner's cleanup result must remain false.
  Reaping the receiver cannot establish retirement of its nested guardian.

The fresh process uses only the retained original reference and existing
read-only inspector. Signaling and process creation are disabled in that reader
process after imports. The coordinator pins the registration/event files before
and after the read and requires identical identities and bytes. No stored PID,
PGID, argv, environment, ledger or `.env` is read to reconstruct authority.
Only original owned children and the existing original group FD participate in
faults or cleanup.

## Evidence, failure and limits

The fresh directory retains the request and image/tool identities, original
reference, exact controller stdout/stderr/result, fresh-reader stdout/stderr/
result, custody pins before/after reading, final result and file manifest. The
native custody directory retains its original registration/event, including
empty or partial failed records. Header failures retain already consumed stdout
prefixes and the remaining stdout/stderr; timeouts retain available output and
unknown process status rather than creating another execution.

Fresh-reader stdout and stderr are exclusive retained files opened before its
Popen, so an OSError or KeyboardInterrupt during communication cannot discard
unreturned pipe buffers. A finally path owns that exact reader, attempts its
retirement with only the original deadline's remaining time, and records the
observed return code or unknown. It never opens another reader or turns that
retirement into cleanup authority. Interrupts retain the failed result before
propagating to the caller.

Every result preserves `execution_status=unknown`, `cleanup_status=unknown`,
zero retries, and false native-success, signal-result, whole-group-cleanup,
publication, cleanup, isolation, immutable-custody and production authority.
Missing records, source drift, wrong exits, changed custody files, reader
failure, expiry or promoted authority cannot become an observed fixture.

The original deadline bounds requested waits. On timeout, only the exact
owned child is killed; output draining/reaping receives no new timeout and can
remain unknown. Filesystem writes/fsync and OS scheduling have no proven hard
completion bound. Evidence retention can finish after the execution budget;
it grants no new execution or receiver-event deadline. A sleep duration and a
successful signal attempt do not prove whole-group retirement.

This fills a repeatable local tooling gap. Actual SSH/launcher disconnection,
blocked storage, independently installed accounts and access-denial checks,
authenticated remote deployment custody, whole-group termination proof, and
accepted build/runtime composition remain separate acceptance work. It changes
neither F05 production admission nor the installed-worker channel/vault formats.

## Focused verification prepared

`tests/test_native_guardian_fault_acceptance.py` covers explicit invocation,
budget refusal, create-only partial failures, no-follow/device refusal,
conservative result projection, original reference custody before the trigger,
unchanged absolute deadlines, output preservation before readiness, no redispatch,
and expiry after observation. Its two explicit Linux cases reuse the existing
real receiver/bootstrap fixture and run both fixed faults. Contract mocks test
orchestration only and are never reported as native/account acceptance. No test
or real harness invocation was run while preparing the initial implementation;
the subsequent first batch failures are retained below.

## Retained failure and explicit installed sleep profiles

The first combined regression's two actual Linux cases failed before dispatch:
`controller-exit` in 0.002048953 seconds and `receiver-kill` in 0.002148680
seconds. Their original result files contain `error_kind=OSError`, not an errno.
Both directories contain only the empty custody directory, failed result and
manifest; neither has a request, launch or controller output. They remain at:

```text
/tmp/lunar-tools-compat-focused-avl2b5v5/execution/pytest-temp/popen-gw2/
  test_actual_same_uid_fault_ret0/controller-exit/
  test_actual_same_uid_fault_ret1/receiver-kill/
```

A subsequent read-only inventory found `/usr/bin/sleep` is a symlink with the
literal target `../lib/cargo/bin/coreutils/sleep`. A separate read-only open with
the original no-follow flags returned errno 40 (`ELOOP`). Its fixed destination
`/usr/lib/cargo/bin/coreutils/sleep` was a regular executable ELF. This identifies
the installation-layout mismatch; it is not a passing fault observation and
does not retrofit an errno into the original result.

The current tool supports exactly these explicit profiles:

| Profile | Fixed installed image | Behavior |
| --- | --- | --- |
| `system-sleep` (default) | `/usr/bin/sleep` | Original no-follow regular ELF checks; a symlink still fails. |
| `ubuntu-uutils-sleep` | Formerly `/usr/lib/cargo/bin/coreutils/sleep` | Refuses before output/dispatch with `fixture_target_profile_sealed_incompatible`; the retained diagnostic below proves its sealed-name incompatibility. |
| `compiled-nanosleep-fixture-v1` | Explicit absolute `--fixture-target`, pinned by `--fixture-target-sha256` | Fixed checked-in source and original caller-trusted image digest are required; no arbitrary argv or build-authenticity claim. |

For `system-sleep`, argv is exactly `sleep <original-remaining-duration>`.
For the compiled fixture it is exactly
`lunar-guardian-nanosleep-fixture <original-remaining-duration>`. In both cases,
`executable` and inherited image FD name the original sealed independent copy
described below. No symlink resolution, PATH lookup, arbitrary program/argv API,
alternate applet or automatic profile fallback is added. The request and result
retain the selected profile; the controller rechecks its original image pin.
Pins remain trusted-local byte comparisons, not source authenticity, immutable
consumption or account evidence.

The compiled profile additionally requires the exact checked-in file
`tools/native_guardian_nanosleep_fixture.c`: 691 bytes, SHA256
`a4620a7d6f02bf8f12e7c544164aff2f25099086bd3ae3306d03109ea96550e4`.
The coordinator and controller independently pin those exact source bytes and
retain the source identity in `fixture_source`. The source parses exactly one
finite duration in `(0, 60]`, calls `nanosleep`, and resumes only after EINTR. It
opens no files and performs no process creation or signaling. The explicit
original ELF SHA256 must match the caller's image before copying or dispatch.
An example adds these three options to the invocation above:

```text
--target-profile compiled-nanosleep-fixture-v1
--fixture-target /absolute/trusted-local/nanosleep-fixture
--fixture-target-sha256 <original-lowercase-64-hex-image-sha256>
```

This uses the same caller-trusted local image assumption as the receiver and
guardian. Compiling the pinned C file in local test setup does not prove that
the supplied ELF was produced from it: `build_authenticity_verified` is explicitly
false and a request promoting it refuses. Compiler, linker, libc and ordinary
runtime trust remain. Source-to-ELF build authenticity requires a separate
verified build chain and is not asserted here. No old directory is reused and no
failed original case is redispatched by selecting this explicit profile.

New contract coverage checks finite paths, unchanged no-follow refusal with
numeric `error_errno` retained, non-root image refusal, exact sealed-FD dispatch
with fixed argv[0], and rejection of a request that changes the selected target
path. The first profile follow-up's contract cases passed, but both actual fault
observations failed as recorded below. All prior false authority and
unknown-cleanup claims remain unchanged.

## Retained hardlink refusal and independent sleep-image copy

The first profile follow-up completed with 39 passed and two failed cases in
this file. Both failures reached the controller but not the sleep or guardian
launch. Their retained `failed-controller.stderr` reports the original
`sealed_linux_executable` refusal `linux_execution_source_invalid`; controller
return code was 1 and stdout was empty. Elapsed times were 2.116760182 seconds
and 2.252454078 seconds, without timeout. The original fixture directories are:

```text
/tmp/lunar-tools-compat-focused-fsdid9_5/execution/pytest-temp/popen-gw13/
  test_actual_same_uid_fault_ret0/controller-exit/
  test_actual_same_uid_fault_ret1/receiver-kill/
```

Read-only metadata identified 116 hardlinks to the fixed uutils sleep inode.
Its 11,807,104 bytes are below the original 128 MiB sealed-image bound, but the
original product gate requires exactly one source hardlink. That gate remains
unchanged. This is a missing adaptation in this diagnostic tool, not evidence
that native guardian custody or the fault was observed.

Before creating the request or any child, the coordinator now reads the fixed
source through the same no-follow, stable-FD pin operation while retaining its
bounded bytes. That observed identity must equal the previously retained source
pin. It exclusively creates `sleep-image` in the fresh output with mode 0700,
fsyncs the file and directory, and pins a readback. The copied size and SHA must
match the original source; its device/inode pair must differ. It is a fresh file
copy, never a hardlink, install, compiler invocation or replacement source.

The private request retains the fixed `target_source` path and original pin,
and the separate `images.target` copy path and original copy pin. The controller
requires exactly `<original output>/sleep-image`, rechecks the fixed source and
every image pin, compares source/copy bytes, and refuses a shared inode. The
existing sealed-executable gate then independently retains its single-link
requirement. The copied image remains an ordinary same-UID file until sealing;
this adds no immutable source/view custody, authenticity, account or production
claim. A failed or existing copy is retained and never repaired or retried.

Read, write or fsync failures remain primary even if the same original FD's
single close attempt also fails. Finite close-operation/kind/errno details are
attached to the retained primary failure, without paths or exception messages.
The parent's result now retains one finite `error_phase`, a whitelisted
`error_reason` when available, and numeric errno/secondary close facts. It does
not infer a native reason by parsing a child traceback or alter actor protocols.

New focused cases cover a multi-hardlink source copied into an independent
single-link inode, original source-byte/inode drift before copy creation,
create-only refusal, combined copy fsync/close failures with partial-image
retention and no dispatch, source-read/close error and interrupt preservation,
and controller refusal of a changed path, changed bytes or source-alias inode
even when caller copy records are internally consistent. The original deadline
and all false authority flags remain. These new cases and the two actual faults
were included in the later batch below; the prior failures are kept.

## Retained deadline failures and sealed-name diagnostic

The independent-copy unified batch passed 618 of 620 cases. This file passed 48
of 50. The two actual faults failed after 20.020800981 and 20.020164838 seconds,
with `error_phase=controller`, `error_kind=TimeoutError` and
`error_reason=original_fixture_deadline`. Their retained directories are:

```text
/tmp/lunar-tools-compat-focused-w_ihevqq/execution/pytest-temp/popen-gw5/
  test_actual_same_uid_fault_ret0/controller-exit/
  test_actual_same_uid_fault_ret1/receiver-kill/
```

The failed controller stdout/stderr were both empty; no original reference was
delivered. Registration/event files existed but contained zero bytes. Their
retained manifests, current hashes and modification times remained identical on
the subsequent read-only inspection; no delayed valid registration was found.
This alone does not identify an exact bootstrap exit or prove a missing kernel
capability. Both original attempts remain failed/unknown, with no retry or
deadline extension.

A separate finite sealed-target diagnostic retained rc1 after approximately
0.0426 seconds and the uutils error `Requested utility sleep does not match
executable name /memfd:lunar-producer-executable (deleted)`, despite fixed
argv[0]=`sleep`. Its local record is
`.lunar-evolution/validation/parallel-batch-20261027/sealed-uutils-target-diagnostic-9asm3zx1/ssh.stdout`.
That establishes the target's sealed-name self-refusal, not successful guardian
startup. The tool now refuses that explicit profile; it does not disable the
check, remove sealing, or try another target automatically.

## Original watcher readiness and startup evidence

The product readiness wait now receives the exact just-created watcher `Popen`
from both guardian launch paths. It polls that original owner before and after
each bounded ACK wait and again after reading the exact `R`. A watcher exit,
including queued `R` followed by exit0, refuses readiness. Wait slices are at
most 50 milliseconds and always recompute from the original absolute deadline;
the legacy call without a watcher retains its original single-poll semantics.
ACK masks, malformed payload refusal and retained failed owner/group-FD
ownership remain unchanged. This observes original process liveness and adds no
saved-PID reconstruction, signal authority or cleanup success.

On a launch-readiness error the tool attempts a create-only
`controller-startup-failure.json` before teardown. It records original target
and receiver `poll()` observations or unknown, the original deadline, finite
error kinds, zero retries and all false authority claims. Persistence failure
adds a finite note without replacing the primary startup error. Subsequent
cleanup cannot retrospectively become that pre-cleanup observation.

New contract tests cover source/image pin refusal, drifted request metadata,
explicit profile configuration, fixed one-duration sealed-FD dispatch and no
build-authenticity promotion. Deterministic readiness tests cover early and
simultaneous watcher exits, exact `R`, deadline consumption, malformed ACKs,
poll failures and preservation of the original failed owner. These additions
have only static checks at preparation time; the two actual 20-second fault
observations still require a fresh, explicitly dispatched unified batch.
