# Bounded Linux process accounting diagnostic

Status: diagnostic development slice; not an acceptance or runtime capability.

The retained 600-second mixed failures have no attributable terminal process
accounting. A host load snapshot cannot identify the cause. Add a stdlib-only,
single-PID observer in `tools/linux_process_accounting.py` for a future, explicitly
separate diagnostic launch. Do not change the product, tests' execution budgets,
original acceptance runners or their outcomes, and do not retry a failed source.

## Contract

- The caller supplies one positive numeric PID. Only the current effective UID
  is allowed; an optional expected UID must equal it. An optional known starttime
  binds the observation to that identity. Without it, the first successful
  observation establishes a baseline, not attribution to an earlier execution.
- Hold a no-follow `/proc/PID` directory descriptor. Read only `stat`, `schedstat`,
  `io` and `status`, through that descriptor, each with a fixed byte bound. Do not
  discover threads/children or read command lines, environments, executable
  paths, maps, database contents or test inputs. Ignore process names in the
  required files; never extract or emit them. No execution,
  signals, networking, permission changes or product imports.
- Each sample checks directory ownership and required stat before and after the
  optional files. PID/starttime and ownership must remain the original identity.
  Disappearance, identity drift or required-stat failure stops collection; never
  adopt a replacement PID. Optional unavailable/denied/malformed/oversize files
  produce a fixed status and null values, not invented zero counters. A parsed
  status UID mismatch is fatal. This is an observational check, not an atomic
  proof that an entire process tree is unchanged or stopped.
- Parse stat as bytes after its final closing parenthesis; never emit comm or
  raw file contents. Retain only allowlisted nonnegative bounded integers.
  CPU user/system ticks describe the thread group and exclude child CPU ticks.
  Schedstat and context switches describe the leader task only. Schedstat zero
  may reflect disabled kernel accounting. IO counters do not cover every source
  of delay, cached IO or network activity. Optional stat42 block-IO delay ticks
  may also be disabled and do not cover all waits. Emit raw counters without deltas or
  causal conclusions.
- Emit JSONL to a create-only mode-0600 file. No existing file is replaced.
  Samples include monotonic start/end timestamps, explicit identity binding and
  per-source status. Count (1..1201), interval (0.05..60 seconds), duration
  (0..600 seconds, exclusive lower bound) and per-file bytes are bounded.
  Validate finite exact numeric inputs, excluding bool. Timing is cooperative:
  finish the bounded sample already in progress, check the monotonic deadline
  between samples, then sleep at most the lesser of interval and remaining time.
  Do not chase missed samples in a busy loop. This is not a hard syscall timeout.
- Exit successfully only on the configured sample/duration limit. A fixed error
  record and nonzero exit report target/identity failures. Output contains no
  command/environment/path diagnostics or authority to execute/admit/publish.

## Validation and limits

Use synthetic proc directories and injected clock/sleep only. Cover unusual comm
bytes, malformed and oversized sources, optional failures, identity/UID drift,
sampling limits and privacy. Run focused pytest, Ruff, compileall and diff check;
obtain independent code review. Do not launch a real child or repeat mixed
acceptance merely to validate this tool.

The observer cannot attribute CPU or waiting to descendants, diagnose a past
timeout, prove whole-group termination, accept static Python/OpenEvolve/Shinka,
or close the existing mixed/CI merge gate. `production_admission=false` and
`online_publication=false` remain unchanged.

## Implemented validation (2026-10-26)

The independent synthetic suite passed 162 cases, zero failures/errors/skips,
against tool SHA-256
`71d51f9eccbcca1eb8bbca24926f7cc895f35aa78cd87d05110e5f65a2e3ace9`.
Test bytes were unchanged across that run (SHA-256
`50ebd377770944b5ed29bc9ffc66ecee872dd0ad3f7d0b84c790ccb7dfe246bf`).
Coverage includes arbitrary comm bytes, required/optional field failures,
pre/post PID/starttime/UID drift, no-follow file/directory behavior, 3-byte short
reads stopping at the original limit+1, held-directory behavior after a synthetic
PID-path replacement, fixed private-free CLI errors, exclusive mode-0600 output,
and injected-clock sampling/deadline limits. Ruff, compileall and diff check
passed. Separate static code review found no remaining blocker.

Retained evidence is in the primary workspace's ignored
`release-closeout-20261025/linux-accounting-synthetic-final-pfvqgymh/`.
The earlier 160-case result remains its own result. An initial default-temp run
caused pytest's automatic old-garbage cleanup warnings; final runs used fresh
temporary roots and did not report warnings. No manual cleanup was performed.

No real proc sampling, child launch, SSH, mixed case, provider or model request
was executed to validate this tool. These tests establish its synthetic contract,
not compatibility with every target kernel or evidence about the failed runs.
