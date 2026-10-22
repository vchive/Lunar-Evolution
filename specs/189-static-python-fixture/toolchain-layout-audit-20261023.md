# Zig layout and CPython cross-configure source audit — 2026-10-23

This is a read-only source/layout observation on `5090gpu` (`worker01`). It
does not select an executable build recipe, run configure or a compiler, build
CRT/libc/compiler-rt, or admit an installation. No remote file was changed by
this audit. The earlier small static executable and failed configure attempt
are separate diagnostics, not evidence that the candidate recipe was used.

## Relationship to existing evidence

[`release-input-audit-20261021.md`](release-input-audit-20261021.md) already
records the fixed Zig archive size/hash and the distinction between Zig's
bundled musl and the separately downloaded Ubuntu musl packages. This audit
adds source-layout and archive-to-extracted-file observations; it does not
repeat that package cross-check or establish that those packages were used.

[`source-readiness-receipt.md`](source-readiness-receipt.md) already defines a
bounded, independently pinned, archive-rooted Zig file projection. That
projection remains `evidence_status="unverified"`; it is not a complete
toolchain inventory. Its declared LLVM `21.1.0` value is a profile declaration,
not an independently confirmed compiler fact. The current audit does not change
the receipt, its pin or any of its false claims.

The earlier archive observation in
[`linux-input-observation-20261019.md`](linux-input-observation-20261019.md)
records manifest digest
`b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90`.
The transient comparison below did not regenerate, compare or retain that
canonical manifest. Its matching counts do not independently validate that
digest.

## Archive and extracted tree

The archive is
`/tmp/lunar-toolchains/sources/zig-x86_64-linux-0.16.0.tar.xz`:

| Property | Observed value |
| --- | --- |
| Size | 55,478,392 bytes |
| SHA-256 | `70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00` |
| Archive root | `zig-x86_64-linux-0.16.0/` |
| Members | 20,832: 1,286 directories and 19,546 regular files |
| Regular-file bytes | 357,913,169 |

The extracted root is
`/home/qinzhiqing/vchive/lunar-feature189-toolchain-probe-20261023/zig-x86_64-linux-0.16.0/`.
A transient read-only Python `tarfile` comparison read each regular archive
member, computed its SHA-256 and compared its size/hash to the corresponding
extracted regular file. It reported zero missing or mismatching regular files
and zero extra extracted files. The separate executable-bit listing contained
only `zig`. No regular `.o` or `.a` files occurred anywhere in this extracted
tree.

This comparison did **not** retain a complete canonical per-file inventory or
its digest. It used ordinary pathname reads, not a single held immutable
archive/tree snapshot or the bounded admission observer. It did not validate
directory permissions, parent-directory identity, concurrent mutation, release
signature trust or an actual compiler's file consumption. This prose and its
selected hashes are not a replayable toolchain custody receipt. Complete
toolchain custody remains open.

### Later independent complete archive replay

A separate create-only replay on `worker01` retained the full canonical
extraction manifest using the existing `snapshot_archive` and
`observe_archive_snapshot` APIs from exact source
`cfd76f8ed2fbe3e0a91c5f9240e852cc50a67c82`. Its expected manifest pin was
taken from the previously committed `linux-input-observation-20261019.md`,
not derived from the new output. The held immutable archive snapshot matched
the fixed 55,478,392-byte archive pin. The full manifest is 3,926,082 bytes,
SHA-256 `b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90`,
with 20,832 members, 19,546 files, 1,286 directories and 357,913,169 regular-file
bytes. The process exited 0 with empty stderr; metadata validation was
`validated`, profile-pin validation was true, and signature verification was
`not-performed`.

The complete manifest, exact replay script, stdout/stderr, process status,
source/API digests and transfer verification are retained locally under ignored
`.lunar-evolution/validation/feature189-20261023/toolchain-complete/` and remotely
under `/home/qinzhiqing/vchive/lunar-feature189-cfd76f8-validation/results/zig-complete-observation-20261022T215150Z-ccbc395a/`.
An independent local read verified canonical bytes, manifest hash, all counts
and the regular-file byte total after transfer. This closes the missing retained
complete **archive** inventory from the earlier transient comparison. It does
not establish an extracted-tree observation, a single acquisition/observation
deadline (the existing public archive observer has no deadline parameter),
compiler consumption, signature trust or measured LLVM version. The new
deadline-bound record API in `toolchain-observation.md` has not been used by
this earlier replay and must be validated separately.

## Actual bundled source layout

The release README describes a Zig installation as the `zig` executable and
the `lib/` directory. This archive contains no separate executable named
`clang`, `lld`, `ar` or `ranlib`; source layout alone cannot prove which internal
compiler/linker mode or external program a future command would use.

The relevant shipped inputs are:

| Role | Archive-relative location |
| --- | --- |
| Compiler/tool driver | `zig` |
| Compiler builtin headers | `lib/include/` |
| musl C source and architecture files | `lib/libc/musl/` |
| Generic musl headers | `lib/libc/include/generic-musl/` |
| x86-64 musl headers | `lib/libc/include/x86_64-linux-musl/` |
| Linux kernel header families | `lib/libc/include/x86-linux-any/`, `lib/libc/include/any-linux-any/` |
| musl startup C sources | `lib/libc/musl/crt/crt1.c`, `Scrt1.c`, `rcrt1.c` |
| x86-64 entry assembly source | `lib/libc/musl/arch/x86_64/crt_arch.h` |
| Zig libc replacement sources | `lib/c.zig`, `lib/c/` |
| Zig compiler support sources | `lib/compiler_rt.zig`, `lib/compiler_rt/` |

There is no `lib/libc/include/x86_64-linux-any/` directory. The musl version
header says `#define VERSION "1.2.5"`; this identifies the bundled source's
version string, not an independently audited upstream patch set. `lib/c.zig`
explicitly describes a multi-target libc implementation providing ABI
compatibility with bundled libcs. `Scrt1.c` includes `crt1.c`; `rcrt1.c` includes
the dynamic-start source and is a distinct possible input, not proof that this
profile selects it. Actual target/header selection and generated CRT/library
membership must be observed later.

`README.md` states that building Zig from source requires LLVM, Clang and LLD
development libraries of version `21.x`. It does not independently establish
that this shipped binary uses exactly LLVM `21.1.0`. This audit did not execute
the compiler to query a backend version or inspect a retained upstream binary
build attestation. Do not promote the existing profile's `21.1.0` declaration
to a verified toolchain fact.

The following selected member bytes matched both archive and extracted tree.
Paths are relative to the fixed archive root; they are not the complete
inventory:

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| `zig` | 172,641,672 | `2317bbb91798556d9d0f38aabdac23db83f0979b25f767259ae474546724087c` |
| `lib/c.zig` | 3,288 | `5a037aa5eb2890aff80369c1a2f3362384afa81b24cfe0f40f2e0ffd800ceda6` |
| `lib/compiler_rt.zig` | 25,527 | `8f518ff1a2d8de659d847c1e366d301d52fbc07cb60c4fb20129cb45a9c6a15e` |
| `lib/include/stddef.h` | 5,053 | `b3e62a046ddf28d09eedebe6eb9461cb7060e47cad2c69964b222c4eea10347e` |
| `lib/libc/include/generic-musl/stdio.h` | 5,862 | `917c7faec2c17fb7515cb2db964e4547e8764fb590f3ded9077f3f252472640d` |
| `lib/libc/include/x86_64-linux-musl/bits/alltypes.h` | 11,445 | `54aba956a68b48f20910eafaa00261e3344a1675164f7a15cd217fd451468d64` |
| `lib/libc/musl/COPYRIGHT` | 6,204 | `f9bc4423732350eb0b3f7ed7e91d530298476f8fec0c6c427a1c04ade22655af` |
| `lib/libc/musl/arch/x86_64/crt_arch.h` | 246 | `3dceeb0644f95a5003201705ac78ba869b595c729d868d56f4fd84824a857a7b` |
| `lib/libc/musl/crt/Scrt1.c` | 18 | `3927b1f5417e5a513a404dc30d218616f0a3f6dc5631a7017417e67fddb44bcd` |
| `lib/libc/musl/crt/crt1.c` | 352 | `f6c08ffd3125bedd3f0ec0f3c5135e7d95f3e1e5c033c99081819ef37712e99d` |
| `lib/libc/musl/crt/rcrt1.c` | 335 | `7540730b9b5bb77a7a054ece8312c4316754460c01ebf2e9d3a238d501deee9b` |
| `lib/libc/musl/src/env/__libc_start_main.c` | 2,635 | `5e5487e579a3c8f14fcb38bb54f2ede10a74f94130ebb9134dcba8d5f28c0cf4` |
| `lib/libc/musl/src/internal/version.h` | 24 | `5098e3a8f94aacf5587a6cb22b8b1699919876fc269f6a7e9d3a96521b07f4b6` |

The absence of shipped objects/archives means a future Zig invocation must
generate relevant CRT, musl, Zig-libc and compiler-support artifacts. Their
cache directories, actual bytes and link participation need separate evidence.
The synthetic descriptor's example `zig/libc.a` is not an observed file in
this release. The auxiliary Ubuntu musl prefix is also not implicitly the
selected sysroot.

## CPython cross-cache source review

The reviewed member is `Python-3.13.12/configure` from
`/home/qinzhiqing/vchive/lunar-cpython31312-probe.4V1KB0/Python-3.13.12.official-verified.tar.xz`.
That archive is 22,926,488 bytes with SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`.
The configure member is 893,475 bytes with SHA-256
`0495fd50c8441437de8df5bd681b94bda00492ad3cf0d0db07f52f928dc12f20`.
The source was read directly from the archive without extraction or execution.

For the candidate's explicit Linux musl cross target:

- Lines 27518–27538 explicitly require `ac_cv_file__dev_ptmx` and
  `ac_cv_file__dev_ptc` to be supplied. These are the only unconditional
  manual site-cache requirements identified by this review for that target.
  The candidate's `no` values are feature-disable policies, not host device
  observations.
- Lines 22923–22931 give `ac_cv_buggy_getaddrinfo` a cross-build value of
  `no -- configured with --(en|dis)able-ipv6` when the IPv6 option is explicit.
  The fatal check at 23044–23049 applies only when IPv6 remains enabled.
  The candidate already passes `--disable-ipv6`; adding an unsupported claim
  that `getaddrinfo` was tested is unnecessary.
- Endianness uses compile/object inspection for cross builds. Lines
  24804–24806 can fail if that result remains unknown; they do not require an
  unconditional manual answer for x86-64. A later actual failure must be
  retained and reviewed rather than bypassed with an invented cache value.
- Lines 3690–3724 require a build-Python command and matching major/minor
  version. This is a tool/helper binding, not a site-cache answer. Lines
  3740–3747 choose the stock host-Python freezer route for cross builds; it
  does not satisfy Lunar's separate same-source C-freezer requirement.

Other cross-only branches supply defaults rather than demand manual answers.
These defaults are upstream configuration behavior, not observed target
capabilities:

| Variables | Cross behavior in this source |
| --- | --- |
| `ac_cv_pthread_is_default`, `ac_cv_kpthread`, `ac_cv_kthread`, `ac_cv_pthread` | `no` |
| `ac_cv_aligned_required` | `yes` for this non-Android target |
| `ac_cv_pthread_system_supported` | `no` |
| `ac_cv_have_chflags`, `ac_cv_have_lchflags` | `cross` |
| `ac_cv_x87_double_rounding` | `no` |
| `ac_cv_posix_semaphores_enabled` | `yes` |
| `ac_cv_broken_sem_getvalue` | `yes` |
| `ac_cv_wchar_t_signed`, `ac_cv_rshift_extends_sign` | `yes` |
| `ac_cv_broken_nice`, `ac_cv_broken_poll`, `ac_cv_working_tzset`, `ac_cv_broken_mbstowcs` | `no` |
| `ac_cv_computed_gotos` | `no` unless the option is explicitly supplied |
| `have_glibc_memmove_bug`, `have_ipa_pure_const_bug` | `undefined` in their cross-run branches |

The candidate's `ac_cv_func_dlopen=no` is also a feature-disable policy. No
list here authorizes overriding new failed feature checks or claims that the
configured object/header/library closure is complete.

## Gate before an actual configure-only run

The deterministic assets in
[`configure-candidate.md`](configure-candidate.md) remain plans. Both emitted
entry points must keep their exit-78 execution gate. Before introducing a
separate reviewed configure-only path:

1. Retain and independently pin the complete selected toolchain inventory and
   concrete wrappers. Choose Zig's bundled musl/Zig-libc source explicitly;
   bind the target, compiler/archive/indexer dispositions and actual linker
   route. Resolve C++ discovery explicitly instead of inheriting host `c++`.
2. Retain the exact independently observed patched CPython staging input and
   patch set. Use a fresh configure workspace; the previous disposable tree
   was configured in place and cannot serve as an untouched staged source.
3. Bind concrete build-Python and shell/helper dependencies, clean environment,
   cache policy, candidate `config.site`, `Modules/Setup.local`, argv and
   output budgets. Keep the unsupported `--with-system-ffi=no` diagnostic
   invocation separate. Do not permit stock regeneration/freezing or make.
4. Retain the first failure and full bounded configure transcript. On success,
   bind `config.log`, `config.status`, Makefile, `pyconfig.h`, makesetup output,
   environment and relevant substitutions to the exact input/recipe pins.
   Audit optional discovery, role flags, generated dependencies and object/
   library substitutions before allowing compilation.
5. Keep later compiler-generated CRT/libc/compiler-rt object/archive inventory,
   same-source C freezer, frozen headers, static link, ELF, sealed startup and
   lifecycle acceptance as separate gates. No prebuilt library from the old
   probe may silently substitute for those outputs.

The selected source profile disables the optional zlib/libffi modules, so the
old broad experimental build's zlib/libffi artifacts need not become candidate
dependencies. Actual configure output must confirm that disposition; template
coverage alone is not evidence of the configured result.

This audit leaves G1 complete-toolchain/source/recipe custody and G2/G3
acceptance open. `production_admission=false` and `online_publication=false`
remain unchanged.
