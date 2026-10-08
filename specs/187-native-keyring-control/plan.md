# Plan

Continue merged Feature186 main c6faf365 (tree ea358eef), whose source5f54309a
was independently accepted by final run37732579777. This does not substitute for
Feature187 final-source Linux acceptance. The earlier stacked source6d20238
preflight run37736544121 remains separate from the final rebased head.

1. Freeze three-syscall keyring boundary before edits. Native author owns the
   isolation header and a dedicated inert keyring module; root owns selector/gate,
   compatibility tests, docs and dedicated CI XML/annotation/upload wiring.
2. Check literals against supported Linux UAPI; exercise normal and omitted
   header-name builds, actual filtered raw probes, private keyring baselines and
   formal v2 IO/descriptor-closure composition.
3. Focused pytest, Ruff, compileall and diff checks follow changes. Independent
   source review precedes final-source Linux 3.11–3.13 CI/raw artifact audit.
4. Merge only the audited source tree after Feature186 acceptance; preserve all
   original failures and cancelled runs separately.

No bpf/perf/fanotify or other syscall families are silently included in this slice.
