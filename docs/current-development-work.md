# Current development work

As of 2026-10-08, PR15–21 are merged into main after independent final-source
Linux CI/raw audits. Feature186 / PR20 source5f54309a was accepted by run37732579777
and merged as c6faf365 with the identical tested tree. Main19 postmerge run37732165231
also passed independent raw auditing. Feature187/PR21 source a15895c passed
run37738544048 (three versions, 21 phases, keyring52/0 skips) and merged as
518f1f4 with the identical tree. Main20 postmerge run37737899242 passed a separate
independent raw audit. Feature188 framed sealed material is now in implementation;
its own Linux acceptance is pending. Main21 postmerge CI is not yet audited.
The entries below describe current capability gaps;
older feature documents retain their historical submission state.

| Priority | Work | Completion evidence |
| --- | --- | --- |
| P0 | Independent native guardian, including bootstrap death/pause and exact child cleanup (Feature 183 / PR18) | Completed: PR18 raw run37724953798; main merge8f3377f |
| P0 | POSIX message queue syscall control and formal admission gate (Feature 185 / PR19) | Completed: PR19 raw run37725907868; main merge22394d26 |
| P0 | Fixed producer broker HTTP destination (Feature 186) | Completed: PR20 raw run37732579777; main mergec6faf365 |
| P0 | Native keyring syscall control (Feature187) | Completed: PR21 raw run37738544048; main merge518f1f4 |
| P0 | Other remaining kernel routes | A separately bounded route contract and actual native refusal/compatibility acceptance; mq or broker checks alone do not close this item |
| P1 | Framed immutable runtime material (Feature188) | Implementing bounded parser, guarded streaming copy, complete Linux seals and original live ownership/deadline; no Python load or production admission claim |
| P1 | Python archive/import/loader closure and immutable runtime loading | Existing declared-file and closed-tree inventories explicitly have runtime_load_protection=false; pinned static CPython and complete delivery/load enforcement need their own contract and native acceptance (Feature189 successor) |
| P1 | Versioned runtime delivery and formal Python worker admission | Bind an independently admitted immutable runtime to original launch/grants/attestation/deadline and verify it throughout the actual launch |
| P1 | OpenEvolve/Shinka Python process adapters | Use formal Python admission and existing lifecycle/request/publication evidence; accept local fixtures before any separately authorized campaign |
| P1 | Production RSI CLI composition | Wire only admitted workers through durable controller resume, unknown/drift/budget gates and retained provenance; verify a repeatable local end-to-end entry |
| P2 | Multi-host ownership, service operation and distributed scheduling | Deferred by current user scope; these are not prerequisites for the current local fixture work |

The real CPython pipe fixture on main demonstrates startup, SDK exchange and
native lifecycle composition using explicitly trusted host runtime roots. It
does not supply production runtime immutability or general Python admission.

Current verification is restricted to local inert C/Python/filesystem/pipe/socket/
loopback/provider-free fixtures and GitHub CI. No model, WebAgent, remote/company
evaluator or actual solver campaign is run; environment credentials are not read.
