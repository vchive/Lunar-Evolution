# Validation

Pending implementation and independent final-head Linux evidence. Never substitute Darwin
skips, earlier PR CI, filtered invalid syscalls or a static deny-list for the private signal
baseline, successful ordinary I/O and actual native composition. Retain raw JUnit/logs, exact
head/tree and first failures. Each edit requires focused tests, Ruff, compileall, diff checks.

Bounded scope: descriptor-control gate only; all other P0/P1 gaps remain explicitly open.

Local Darwin composition: `/tmp/lunar179-local-composition-final.xml`, 147 cases, 82 passed/65 skips,
zero failures/errors, SHA256 `a296cfe2fbb89adb4deab959c468dd83303dad81016ab2fdaf561c4f8c5178fa`.
The new Linux 58 cases all skip here; 7 skips are prior platform-specific cases. Binding/header
unsupported-ABI/source artifact and ordinary retained attempt checks ran. Ruff, compileall and
diff checks passed. The earlier overlapping 89-case suite is not summed into this result.
First collection failure from pytest's reserved parameter name is retained in
`/tmp/lunar179-first-local.xml`; renamed without dropping tests. Existing Darwin immutable
fixture cleanup warnings occur; they are not test failures or Linux enforcement evidence.

Final review strengthened independent i386 F_SETFL negatives, allowed FIONBIO with an O_ASYNC
nonzero payload (assert only NONBLOCK), GET_SEALS inside actual native filtering and private
fixture failure cleanup before reaping. No blind signal after PID/group ownership is lost.
Latest focused `/tmp/lunar179-final-review-gates.xml`: 94 cases, 36 passed/58 Darwin skips,
zero failures/errors, SHA256 `9017a0cb6b731f5af34107189002ac9353c554b4430e0d79d95fdadb62fae152`.
This overlaps the composition suite. Independent contract/fixture review passed.
An independent real-header C array expansion and offline BPF path review passed 2,040,390
cases for x86_64/aarch64/i386 syscall constants, including the i386 fcntl64 fallback/defined
branches. `/tmp/lunar-feature179-bpf-review/audit.json` retains header SHA256
`0d34a0698493c02afd47b2052a2ea334bbe5145c7467aaa406d6e222b8de8863`. This is only jump/word
logic validation; it does not establish Linux, ARM or i386 runtime enforcement.

Final-head Linux stage is `fd-control.xml`; expected x86_64 58 cases/22 explicit i386 skips.
This is not i386 runtime acceptance. Full current count and raw evidence will be recorded per PR.
