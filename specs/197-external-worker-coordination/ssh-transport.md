# Slice C — opt-in SSH worker transport and trusted wrapper

Status: source and local subprocess fixtures implemented; concentrated root
validation passed (see `../../docs/parallel-batch-validation-20261027.md`).
Actual isolated deployment and remote cleanup remain unaccepted.

## Topology and installation

One local controller retains its existing RSILedger, run lock, native claim,
assignment and publication authority. SSH provides a foreground byte channel to
one fixed, preinstalled trusted wrapper. There is no daemon, HTTP endpoint, NFS
SQLite or additional authoritative controller. `5090gpu` can be a configured SSH
alias; this slice does not install or launch anything on that machine.

The operator must preinstall Lunar's wrapper module, a private wrapper configuration,
its private state directory, a per-worker key file and a trusted producer launcher.
The controller's registry has the corresponding independent key. Neither endpoint
sends a key through argv, environment, request/response wire, receipt or logs.
The wrapper is a trusted receipt-producing launcher, not an arbitrary candidate
runner. Its configured producer command must preserve the existing native
isolation/lifecycle boundary before executing candidate code. Untrusted candidates
must not run under the signing account or be able to read its key/config/state.
This isolation is an installation requirement, not a claim inferred from HMAC.

## Fixed command and request

Only trusted configuration chooses the SSH executable, host alias and remote argv.
Host aliases are bounded non-option identifiers. Remote argv is encoded with
`shlex.join` because OpenSSH uses a remote command shell; no request field selects
argv, shell fragments, environment, filesystem paths or a different destination.
SSH uses batch mode, strict host-key checking, no agent/port forwarding and no TTY.
Existing trusted SSH configuration may resolve the host alias and credentials.

A bounded canonical request carries the original assignment context, complete
original request dictionary/digest, original profile, action (`run` or `inspect`)
and fixed controller deadline/budget. The wrapper accepts only its configured
worker/host/boot/key/profile and allowed controller identity. It recomputes the
request digest. The response carries exact receipt bytes and the existing Slice A
signed origin, or a fixed `unknown`/`missing` status. It has no evaluator result,
native completion or cleanup authority.

## Once-only execution and controller recovery

The controller requires an existing assigned native claim and its original held
run lock. Before a process can start, an existing DurableCallbackJournal entry
records the assignment/config/request binding. Started transport intent is never
automatically retried. Original SolveExecutionControl narrows all channel waits;
local cleanup uses only the original local child/process-group identity.

The wrapper creates one durable episode directory and intent before spawning its
fixed trusted command. Its create-only directory/intent gate prevents two SSH
invocations from starting the same episode concurrently, even after process death.
The trusted producer receives only the bounded request on stdin and a minimal
environment. The wrapper bounds stdout/stderr, seals the receipt/origin response
before writing stdout, and never treats its process/channel exit as remote native
cleanup. The state directory is trusted private local storage on that worker.

Lost/invalid channels consume the controller assignment's shared settlement as
`unknown`. The original unknown record remains immutable. A later explicit
`inspect` operation never invokes the producer; it only returns an already sealed
response for the exact original intent. An explicit reconcile may append one
authenticated-receipt observation after that unknown record. It cannot relaunch,
reset the challenge/generation, settle the native claim, establish cleanup or
publish. Unfinished remote intent remains unknown without TTL takeover.

A controller crash after a remote launch leaves started transport intent. Recovery
may quarantine the original still-assigned claim and inspect retained remote state;
it never repeats `run`. If receipt consumption committed before the controller
transport result, assignment inspection remains authoritative for consumption.

## Planned files and concentrated validation

- `external_worker_io.py`: bounded stdin/stdout/stderr pump and original local
  process-group cleanup, without displaying raw child output.
- `external_worker_wrapper.py`: private fixed configuration/key loading,
  create-only intent/result, actual trusted subprocess and read-only inspect.
- `external_worker_transport.py`: fixed SSH argv, durable channel intent,
  actual assignment receipt/unknown/reconcile integration.
- `external_worker_assignment.py`: one appended unknown-origin reconciliation
  observation; no change to native-result/publication authority.
- New local process-fixture tests: execute the real wrapper using a fixed local
  SSH substitute, real HMAC and isolated SQLite; prove actual command execution,
  bounded output, lost-response recovery, interrupted intent and competing owners.

The implementation agent performs AST parsing only. Root executes the focused
tests and static checks together after all slices freeze. No real SSH, remote
worker, provider, model or evaluator is run during development of this slice.
Actual cross-host installation, account isolation and interruption acceptance
remain explicit deployment checks after that local regression.

## Implemented public entry points

`SSHWorkerConfig` accepts only the exact `lunar-external-worker-ssh-v1` fields:
`ssh_executable`, `host`, `remote_argv` and `worker_id` (plus schema). The complete
configuration is public and never contains a secret, but it controls execution:
its loader therefore requires a private 0600/0400 regular single-link file owned
by the current UID, descriptor-relative no-follow ancestors and stable bounded
reads. The wrapper configuration and key use the same private read policy;
state/job directories require 0700. Short reads are accumulated, and file identity,
metadata and size are rechecked against both the held descriptor and its name.
Wrapper file admission refuses a nonregular leaf before opening it and adds
`O_NONBLOCK` to the no-follow open. A stat-to-open regular-to-FIFO swap therefore
cannot hang the caller and is refused by the subsequent descriptor identity/type
checks. The FIFO race fixtures assert nonblocking flags before any real FIFO open
to keep a regression from hanging the pytest process.

`SSHWorkerTransport.dispatch` requires the caller's already held original run
lock, existing started native claim and assigned context. It consumes only the
origin settlement. `inspect` reads local retained checkpoints and never runs SSH.
`reconcile` uses only the original persisted invocation with action changed to
`inspect`; a separate recovery control limits that read without extending the
original remote intent deadline. An authenticated late origin appends an
`origin-reconcile` callback while preserving the original unknown settlement.

Remote work admission additionally requires the original `SolverRequest.budget`
to contain both positive finite `wall_timeout_seconds` and absolute
`deadline_unix`. They are part of the original request digest/native claim, not
values manufactured from the CLI's new channel control. Missing original wall or
deadline is refused (`worker_wrapper_original_budget_required`); episode/token
RSI budgets and relative wall-only requests can still reserve/inspect but cannot
dispatch SSH. An expired original deadline is refused before a launch intent.
The transport narrows its child channel and remote timeout to the minimum of
that original wall limit, remaining original absolute deadline, supplied control
and wrapper ceiling. The wrapper independently refuses any wire timeout/deadline
above the original request limits and rechecks expiry before producer admission.
A new reconcile control bounds only the read and may inspect expired original
intent; it never recreates production budget or restarts the producer.

Source review/AST parsing is the only agent-side check completed here. Root must
run the new transport, wrapper and assignment-reconcile tests together with the
existing assignment/origin tests, Ruff, compileall and `git diff --check` before
recording this slice as validated. No real host installation, key provisioning,
SSH acceptance, lifecycle or isolation evidence is implied by these fixtures.
