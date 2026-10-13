# Tasks

- [x] Define the path-free retained replay source and independent pin fingerprint.
- [x] Implement completed/unknown/drift result mapping with fixed refusal codes.
- [x] Revalidate cached replay results during controller resume/replay paths.
- [x] Add focused local tests and static checks.
- [x] Exercise the real local replay inspector with retained fixture files, reject
  source drift and complete request drift before missing-receipt handling.
- [x] Exercise terminal controller resume without another dispatch and reject evidence
  drift while preserving the original ledger head.
- [x] Verify integrated replay/resume PR64 source `367fd1c` against completed/
  success run `38216044832`, all 15 checks, merged at `23a0953`.
- [ ] Complete the current final dependency source's Linux matrix and independent
  raw/source/tree audit. The later replay-context changes are merged through PR73,
  whose original run `38293790980` failed/cancelled; PR64's earlier success cannot
  accept them. PR82's subsequent integrated source passed 15 checks, but does not
  close PR73's original-source CI/audit obligation. Unified PR87 final-source
  acceptance is tracked in `../../docs/current-release-backlog.md`.
- [ ] Connect a real sealed runtime observation and producer lifecycle after Feature189/190 acceptance.
- [ ] Add official evaluator and external worker authenticity only under a separately approved scope.
