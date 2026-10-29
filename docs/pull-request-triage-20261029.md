# Pull request consolidation — 2026-10-29

All 22 originally open PRs were examined by exact head, base, Git history,
patch/content equivalence, review metadata and original CI records. No original
PR had a complete passing CI gate. The replacement branch
`codex/pr-triage-ci-watchdog` retains the entire current development history and
targets main directly; it must pass its own complete CI before merging.

| Original PR | Decision | Evidence |
|---|---|---|
| #123 | Close; already included in main | Head is an ancestor of the original #138 head; squash tree proof below. |
| #124 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #125 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #126 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #127 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #128 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #129 | Close; already included in main | Side-branch patches, final fixture blob and its unique diagnostic block are preserved in #138/main. |
| #130 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #131 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #132 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #133 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #134 | Close; already included in main | SQLite sidecar patch has the same patch ID as the integrated commit. |
| #135 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #136 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #137 | Close; already included in main | Same original #138 ancestry and exact squash tree. |
| #188 | Replace with cumulative main PR | Exact head is an ancestor of #190 and #194. This does not mean it is already on main. |
| #189 | Replace with cumulative main PR | Exact head is an ancestor of #190 and #194; no unique commits are discarded. |
| #190 | Replace with cumulative main PR | Direct ancestor of #191–194; its original HEAD and mixed evidence stay intact. |
| #191 | Replace with cumulative main PR | Direct ancestor of #192–194; preserve original successful mixed and failed CI. |
| #192 | Replace with cumulative main PR | CI phase diagnostics are fully retained in #193–194. |
| #193 | Replace with cumulative main PR | Explicit VFS root acquisition is fully retained in #194. |
| #194 | Replace with cumulative main PR | Retained-snapshot implementation is the replacement branch's exact parent. |

## Squash and ancestry proofs

Main at audit: `0bff6b92b9b05f7b780bf4c2ee6f38bdab4b3833`.
The original #138 head `355c312e9b73dd89af9a77e40fd2fbf8e31a3ea2` and merged
squash `af1cc62db5ab26e0181d46cead0228e455931637` have exactly the same tree
`fa22f871…`. The squash is an ancestor of main. Squashing changed commit
ancestry; merging those old PRs again would repeat already integrated changes.
The two side branches (#129/#134) were checked separately by patch IDs, complete
fixture blob and the exact remaining added diagnostic lines, all present in main.

For the current development, main is an ancestor of #190, followed by the direct
chain #191 → #192 → #193 → #194 (`90b6d89059e0de4940e948ba3237f8abd1e17f97`).
#188/#189 are also exact ancestors. Keep these commits and branches; closing
superseded PRs does not discard their code. Reviews/comments on #188–194 were
empty at audit; original PR bodies remain available. Their full cumulative
change, rather than only the last snapshot feature, is the replacement review
scope. None of these seven changes is declared merged until main advances.

## CI and continued development

Original CI evidence includes six-hour platform cancellations and a separate
explicit hosted-runner communication failure (#191). Checkout/setup/install/
provenance succeeded for sampled jobs. A regression step name alone cannot
identify a test: every role first collects the complete inventory. Original log
downloads returned BlobNotFound, so the exact blocked node and cause stay open.

Original run metadata, steps, annotations and all five then-downloadable history
artifacts were retained before cancelling superseded active workflows. Results
remain cancelled/failed, never passing. Replacing five overlapping run queues
with one main-targeted workflow avoids spending runners on obsolete PRs. It does
not relax the six ordinary shards, seven separate heavy nodes, three Python
versions, historical inventories, exact JUnit checks or focused aggregation.

The successor adds only a diagnostics-mode five-minute built-in pytest stack
observer. It neither kills nor retries a test and leaves default execution
unchanged. This helps identify a future stall; it is not a proven fix for the
original runner failures. See [stack observation contract](../specs/193-static-python-rsi-launch/ci-stall-stacks.md).
All previous provider-free/VFS evidence and remaining full CPython, installed
authority and production acceptance limitations continue to apply.

Detailed per-head/tree/patch evidence, saved API responses and action receipts
are under the primary workspace's ignored
`.lunar-evolution/validation/pr-triage-20261029/`. Raw runtime/store snapshots,
keys and local process state are not committed. No model, remote evaluator or
solver campaign is run; production admission and online publication stay false.
