# Pinned Zig 0.16 linker-input capture observations

Status: real support preparation acceptance is **blocked**. The generation and
explicit-consumption software path exists, but the fixed driver has not produced
an accepted linker-input capture. The observations below are independent,
bounded software diagnostics; they do not accept a configured CPython build,
support bundle, runtime, immutable custody, production admission or publication.

## Fixed inputs and evidence identity

The remote toolchain was the original complete
`/tmp/lunar-toolchains/zig-x86_64-linux-0.16.0` extraction:

| Input | Bytes / files | SHA256 |
| --- | --- | --- |
| `zig` executable | 172,641,672 bytes | `2317bbb91798556d9d0f38aabdac23db83f0979b25f767259ae474546724087c` |
| Complete extraction manifest | 3,926,082 bytes | `b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90` |
| Complete regular-file inventory | 19,546 files / 357,913,169 bytes | `f04a2872ab404f9a180ad1d18b2921583e236e95300a6d67dd26194aa6a56adb` |

The inventory digest is over the diagnostic runner's canonical sorted rows of
relative path, size, SHA256 and executable bit. Every regular member was checked
against the extraction manifest before and after each diagnostic group; all
matched. Only `zig` was executable in that inventory. This establishes the
observed bytes, not immutable custody or a generally supported toolchain profile.

The frozen product-source reference was Git tree
`0f400305da5c0914eb5875ad0202baadf167991c`, with 2,591 regular files / 2,899
entries. Its source archive SHA256 was
`d4b89e3afcb0b7ab3b732dc38383d1f0ecdeaf8bc7a190beac7b29543c22a040`.
The standalone diagnostics did not invoke that product source.

Original reports, controlled launch vectors, logs, collection manifests and
create-only `actual-summary.json` files are retained locally under the ignored
validation base `.lunar-evolution/validation/parallel-batch-20261027/`. The
directories named below identify separate original runs, not retries or
interchangeable evidence. They are local validation artifacts, not bundled
release assets.

## Original support-seed attempts remain separate

The corrected original support recipe requests:

```text
@toolchain/zig cc -target x86_64-linux-musl -static
-o @work/support/seed
@work/support/probe.o @work/support/main.o @work/support/div.o
-lm -lpthread -lc
-Xlinker --dependency-file -Xlinker @work/support/seed.d
```

The runner supplies the fixed toolchain `ZIG_LIB_DIR` and fresh private cache,
HOME and TMPDIR roots. The illegal earlier `cc --zig-lib-dir` vector is a
different preserved failure, described in
[the resource-root correction](zig-driver-resource-root.md).

* `final-real-zig-support-once-h9kdf6kk`: the original `/home` attempt generated
  three objects, but persistence of the original outcome/report failed with
  `EDQUOT` / errno 122. Its first product failure remains **unknown**. A separate
  read-only recovery retained 48 originals. Later `/tmp` results cannot establish
  which operation first failed in this `/home` attempt.
* `final-real-zig-tmp-profile-once-qz0n9xfh`: a separately authorized fresh `/tmp`
  storage-profile attempt completed configure, freeze and compile, then the
  original link returned `-11` / SIGSEGV with empty stdout and stderr. The seed
  was not produced or executed. Its 54 originals were collected and verified;
  elapsed time was 75.607 seconds. The source tree and 239 loaded source origins
  matched before/after.

Neither run produced an accepted support bundle. In particular, the expected
five support names were not demonstrated by a successful original full graph.

## Independent controlled diagnostics

All cells used new private `/tmp` work/cache/HOME/TMPDIR roots, the fixed complete
toolchain above, one dispatch and retry 0. Each cell had a 120-second absolute
budget. Generated ELF files were never executed. Driver completion means the
observations were collected; it does not mean the individual links passed.

### Original split depfile capture, 2 by 2

Evidence: `zig-minimal-diagnostic-matrix-once-90umoext/actual-summary.json`.
Group budget 480 seconds; observed elapsed 36.082 seconds; 67 original regular
files collected and verified.

| Independent cell | Compile rc | Link rc | Elapsed seconds |
| --- | --- | --- | --- |
| Freestanding, no capture | 0 | 0 | 0.093 |
| Freestanding, original split capture | 0 | -11 | 0.092 |
| Ordinary libc, no capture | 0 | 0 | 31.651 |
| Ordinary libc, original split capture | 0 | -11 | 33.480 |

Within each source pair, object bytes were identical, and the controlled compile
vectors and environment matched after normalizing the distinct cell root. The
link vectors differed only by
`-Xlinker --dependency-file -Xlinker <private-path>`. The freestanding pair had no
libc or CRT inputs. The original split capture is therefore a sufficient trigger
for SIGSEGV in these fixed minimal reproductions; libc generation and the old
resource-root spelling are not necessary causes. This does not identify the
precise upstream implementation defect.

### Three alternate dependency-file spellings

Evidence: `zig-dep-syntax-diagnostic-once-87nbhpbv/actual-summary.json`.
Group budget 360 seconds; observed elapsed 2.647 seconds; 55 original regular
files collected and verified. A new inert freestanding source and freshly
compiled objects were used.

| Explicit capture spelling | Compile rc | Link rc |
| --- | --- | --- |
| `-Wl,--dependency-file,<private-path>` | 0 | -11 |
| `-Wl,--dependency-file=<private-path>` | 0 | -11 |
| `-Xlinker --dependency-file=<private-path>` | 0 | -11 |

The three objects were byte-identical; their normalized compile, link base and
environment matched. No cell generated an ELF or depfile, so depfile target and
object validation was impossible. This group had no no-capture control for its
new source and does not independently establish causal isolation. It establishes
that none of these proposed spellings supplied a working compatibility path.

### Trace and reproduce, final bounded group

Evidence: `zig-trace-reproduce-diagnostic-once-uk_0v3dg/actual-summary.json`.
Group budget 480 seconds; observed elapsed 2.691 seconds; 65 original regular
files collected and verified. Both new freestanding and new ordinary-libc sources
were compiled, with independent fresh caches per cell.

| Source / capture | Compile rc | Link rc | Exact stderr |
| --- | --- | --- | --- |
| Freestanding / `-Wl,--trace` | 0 | 1 | `error: unsupported linker arg: --trace` |
| Ordinary libc / `-Wl,--trace` | 0 | 1 | `error: unsupported linker arg: --trace` |
| Freestanding / `-Wl,--reproduce=<private.tar>` | 0 | 1 | `error: unsupported linker arg: --reproduce` |
| Ordinary libc / `-Wl,--reproduce=<private.tar>` | 0 | 1 | `error: unsupported linker arg: --reproduce` |

Each stderr ended with one newline. Trace stdout was empty; no reproduce tar or
ELF was produced. There is consequently no archive member list or actual-input
capture to accept. No archive contents were extracted or executed. Additional
diagnostics stopped after this group.

## A separate support-layout clue

The successful minimal `libc-no-dep` link's retained verbose final `ld.lld`
dispatch references `crt1.o`, the compiled object, `libubsan_rt.a`, `libc.a`,
`libzigc.a` and `libcompiler_rt.a`; that line contains neither `crti.o` nor
`crtn.o`. This is a concrete clue that the fixed driver's default support layout
may differ from the software's narrow five-name assumption. It is scoped to the
minimal libc graph. A verbose dispatch is not proof of every actual file read,
and it cannot be converted into an invented depfile or an observed closure for
the original support-seed graph.

The accepted software set remains exactly `crt1.o`, `crti.o`, `crtn.o`, `libc.a`
and `libcompiler_rt.a`. Do not add names, remove required names or infer the full
seed layout from this clue. A real successor profile must observe and validate
its own complete actual closure before proposing a reviewed acceptance change.

## Disposition and successor boundary

The fixed Zig 0.16 driver is incompatible with the **tested** actual-input
capture routes: depfile requests crash, and trace/reproduce requests are explicitly
unsupported. This is a real acceptance blocker, not a test timeout or an accepted
support-generation result. It does not prove that every possible toolchain or
capture mechanism is unavailable.

Keep current acceptance fail-closed. Do not remove capture, automatically switch
flags/toolchains/backends, retry after the failure, fabricate a depfile from
expected inputs or `-v` output, or let a current cache digest approve its own
undeclared inputs. The original failed and unknown attempts remain retained.

A successor must be an **explicit, independently pinned compiler/linker capture
profile**, selected before dispatch and described in SDD before implementation.
It needs genuine emitted capture with bounded parsing, exact target/object
validation, and complete observed CRT/runtime/archive closure. The original
full-seed graph then needs its own authorized single-attempt acceptance and exact
downstream consumption. A successful minimal link alone cannot close those gates.
No new DTO, backend, acceptance set or automatic fallback is introduced here.
