# Feature 193 tasks

Stage 1 implementation and local verification are complete; final-source CI
and independent raw/source/tree audit remain pending. Completing source preparation does not complete a later
installation/runtime stage.

## Stage 1 — reviewed source preparation

- [x] T01 Record independent size/SHA256 pins for all six old templates, the old
  profile, recipe and reviewed build inputs; verify existing assets/parser bytes
  are retained unchanged.
- [x] T02 Add independently pinned new launcher and frozen-main templates for
  the sole `rsi-marker-launch-v1` source-preparation version.
- [x] T03 Implement exact argc-three marker/lowercase-hex validation before Python
  initialization, fixed module/callable dispatch and no environment selector.
- [x] T04 Add `_rsi_launch` exact-string validation followed by one unchanged
  baseline encoder call, without input reads, new imports or result envelopes.
- [x] T05 Implement the finite six-asset emitter with checked input snapshots,
  deterministic source/profile/launch-policy manifest and no build/freezer driver.
- [x] T06 Implement an explicit-output CLI with create-only writes, exact output
  set validation and byte/size/digest readback before success.
- [x] T07 Test deterministic pins/outputs, input drift refusal ordering, existing
  destination refusal, write/readback failures and false capability claims.
- [x] T08 Test launcher acceptance/refusal with inert C API stubs and wrapper
  delegation/refusal with fake Python facts; preserve fixed Python argv domains.
- [x] T09 Verify old Feature 189 assets/profile/recipe/reviewed-input/parser bytes
  and native marker/wire/grant behavior unchanged through focused compatibility.
- [x] T10 Run final focused tests, Ruff, compileall and `git diff --check`; retain
  source-bound results and first failures without inflating repeated pass counts.
- [x] T11a Add the bounded 82-case CI gate with retained XML and annotations.
- [ ] T11b Complete final-source CI plus independent raw/source/tree audit before
  merge. Parent task owns Git and CI integration.
- [x] T12 Update validation and handoff with implemented stage 1 scope, exact
  evidence and remaining stage boundaries only after the corresponding checks.

## F01 bounded preparation continuation

- [x] F01a Specify the pure fixed overlay preparation API and separate candidate
  schemas in `profile-preparation.md` without changing accepted installations.
- [x] F01b Independently pin the original build inputs, two-record reviewed overlay,
  source plan and six assets; preserve every other record and fixed Python vectors.
- [x] F01c Prepare source-only candidate inputs and nine pending frozen headers,
  without generated digests, artifact/runtime evidence or promoted claims.
- [x] F01d Verify strict types/bounds, independent pins, re-signed mutant refusal,
  deterministic output, old-parser refusal and no side effects: 113 focused cases.
- [x] F01e Verify 183 disjoint compatibility cases and root JUnit inventory,
  296 unique cases total; add the bounded 113-case retained CI gate.
- [ ] F01f Complete this final source's CI plus independent raw/source/tree audit
  and merge in dependency order after PR46–50.

## F04 bounded two-input report continuation

- [x] F04a Specify the separate source prototype and pure caller-byte comparison
  seam in `input-read-report.md`; retain old emitter/profile/pins unchanged.
- [x] F04b Read only the existing two fixed paths with bounded binary reads;
  encode canonical ASCII hex fields after both reads and fixed computation285.
- [x] F04c Compare independent caller marker/request/memory bytes with exact
  types/bounds, strict canonical JSON and five false claims; return only digests
  and sizes without promoting caller DTOs or manufacturing a solver envelope.
- [x] F04d Verify219 new source/mock cases plus195 disjoint preparation/source
  compatibility cases,414 unique passes; retain the219-case CI gate.
- [ ] F04e Complete final-source CI plus independent raw/source/tree audit and
  merge after the preceding dependencies. Live F04 below remains incomplete.

## Later stages — installation and runtime remain unaccepted

- [ ] F01 Specify and accept a separately versioned installation profile; retain
  the old argc-one profile/parser behavior without an implicit compatibility bypass.
- [ ] F02 Verify upstream source/toolchain identity, build closure, matching
  frozen headers, static link inputs and final ELF/artifact properties.
- [ ] F03 Verify actual sealed-image startup, original executable owner/native
  lifecycle, original OS marker intent and fixed Python observation vectors.
- [ ] F04 Verify authoritative marker-to-manifest/request/memory correspondence,
  read the existing two grants and generate a bounded RSI producer result.
- [ ] F05 Compose actual runtime/post-execution handoff and publication with
  original terminal/broker/material evidence, budgets and durable recovery.
- [ ] F06 Complete actual local OpenEvolve/Shinka lifecycle/export and production
  RSI CLI/Linux acceptance against their own source/runtime evidence.

P2 remote evaluator, worker authentication, multi-host ownership and service/
distributed scheduling remain outside this feature and are not acceptance tasks.
