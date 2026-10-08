# Validation

Source implementation and ABI review are distinct from actual Linux execution.
Independent Linux v5.4/v6.12 UAPI tables, source bytes and SHA records are retained at
`/tmp/lunar182-linux-uapi-audit/{audit.json,sources.json}`. The checked x86_64,
aarch64 and native i386 literal numbers match; i386 semop/time32 use `ipc117`, while
semtimedop_time64/recvmmsg_time64 are i386-only. This is source table evidence.

The IPC author run `/tmp/lunar182-ipc-source-final.xml` collected97 cases:1 passed,
96 Darwin platform skips,0 failures/errors. The author suite also explicitly selected the existing unsupported-architecture
check; it is the one executing case. The new IPC module itself collects96 cases. New Linux IPC fixtures all skip on this
host. Ruff, compileall, diff check and strict Darwin bootstrap compilation pass.
The first missing-PYTHONPATH collection failure remains separately retained in
`/tmp/lunar182-ipc-first-focused.xml`; it is not overwritten by the final run.

Root final composition `/tmp/lunar182-root-final-composition.xml` collects388 cases:
169passed/219Darwin platform skips,0failures/errors. Independent focused review
`/tmp/lunar182-independent-boundary.xml` collects158 cases:55passed/103skips,
0failures/errors. These suites overlap; do not sum them. Ruff/compileall/diff check,
699 unique importable exports and retained XML workflow wiring pass. YAML parsing
uses the existing miniforge Python because the repository venv lacks PyYAML; the
first missing-module check output is retained and was not a source/test failure.

Exact source inventories collect current11421, IPC96 and descendants80. Expected
x64 Linux skips are current88, IPC6 (three i386-only calls in two header variants),
descendants1; raw final CI must confirm these and all other unchanged phase nodes.
Only the six inherited ENOSYS78-to38 parameter IDs need explicit Darwin/Linux ABI
projection, anchored in prior raw Linux inventories; no broad inventory relaxation.

Independent final source review passed with no open findings:
`/tmp/lunar182-independent-boundary-review.md` (SHA256
`e2154af4ab6083ebacdf681611e5d48817efc36bd459078378609b83876234b0`),
and `/tmp/lunar182-independent-boundary-review-evidence.json`. Root verified the
reviewed code/test/workflow/spec hashes before commit. Exact-head Ubuntu
Python3.11/3.12/3.13 CI and merge remain pending. The workflow retains dedicated IPC XML alongside
grant/FD/input/runtime/lifecycle/adapter/current/archive/frozen phases. Actual source
head, checkout parents/tree, raw XML inventories and all failures must be verified
before merge. Do not borrow prior feature results or count skips as Linux execution.

Fixtures use private disposable IPC IDs with parent cleanup, local anonymous socket
pairs, inert files and bounded nonblocking operations. Positive paths preserve
ordinary IO/fork/thread/broker and formal FD closure. No model, actual solver campaign,
WebAgent, remote/company evaluator or credential file is accessed.
