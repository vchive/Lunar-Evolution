# Static Python loader closure probe (2026-10-21)

This is a read-only run of existing 5090gpu artifacts plus a disposable copy
for inspection. It did not run configure, make, the freezer, or a producer. It
does not establish sealed startup, source ownership, project lifecycle, input/
result authority, or production admission.

## Probe inputs

The disposable directory is
`/tmp/lunar189-g2probe-20261021.Fqpy3B` (mode `0700`). It contains copies of
the 115 MiB CPython source tree and 128 MiB build tree, the existing static
interpreter and finite diagnostic image, and path-free command output. The
original source/build trees and binaries were rehashed after inspection and
were unchanged.

Input identity:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| CPython 3.13.12 source archive | 22,926,488 | `2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593` |
| Zig 0.16.0 Linux x86_64 archive | 55,478,392 | `70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00` |
| Zig executable inside archive and host binary | — | `2317bbb91798556d9d0f38aabdac23db83f0979b25f767259ae474546724087c` |
| Archive/original `Lib/operator.py` | — | `c048f8a6852832d5fa750d6ae772d7658c52c3511d261cb902f7edfd262e9127` |

The existing `build-fullfreeze/python` is 27,476,152 bytes, SHA-256
`799077a30b340cff0f33274060e0711e152a577ed600b5b42830a8fc9ec4984e`. Read-only
ELF inspection observed ELF64, x86_64, `ET_EXEC`, no `PT_INTERP`, and no
`DT_NEEDED`. These are file-format observations only.

## Runtime observations

Every command used an empty environment with only fixed `PATH`, locale and
home values:

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent \
  /tmp/lunar189-g2probe-20261021.Fqpy3B/build/python -S -c '...'
```

The image returned exit 0 for `--version`, `--help`, and a bounded `-S -c`
inspection program. `sys.meta_path` contained only the builtin and frozen
importers; `sys.path_hooks` was empty. Four `sys.path` entries were present,
one empty and the others absolute build/source paths (redacted from output).
The probe observed `linecache` and `keyword` loading from the frozen importer.

Importing `traceback` and `collections` failed with
`ModuleNotFoundError.name == "operator"`; importing `json` failed with
`ModuleNotFoundError.name == "json"`. The captured stdout is retained at
`stock_loader_imports.stdout`, SHA-256
`ae9826a6eedc199f269dc988dbe65fc1b151cf424c5d64f8915871f37650cd26`; stderr
was empty. This identifies a concrete missing frozen dependency, `operator`,
in this specific build. It does not say the overall closure is only one module.

The separately retained finite diagnostic image is 26,198,088 bytes, SHA-256
`ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b`. It passed
`--version`, but `-c 'print(1)'` failed before user code with missing
`linecache`. In this probe, the path-free stderr was 162 bytes, SHA-256
`49de4bdb2bd47082e209bf0e75c57c13d12852aa55989b1f0da18f82bf7cca5e`; it
includes `<prefix>` and `<exec_prefix>` notices before the import failure. The
earlier 49-byte observation remains separately recorded in
`frozen-bootstrap-observation-20261020.md` with SHA-256
`6c29f59aeec62771de59b4daf306136c9f32fa4ec2d565b5994c769a3a9aadba`.
This is the earlier constrained image described by the October 20 observation,
not the `build-fullfreeze` image above.

## Stop condition and next P1 work

The current build tree has no `build/Python/frozen_modules/operator.h`. Its
Makefile records a freezer command using the ambient
`/home/qinzhiqing/software/miniforge/bin/python` and `Programs/_freeze_module.py`;
that generator is not independently pinned to the Feature189 same-source
freezer contract. More importantly, the existing generated
`Python/frozen.c` is not the archive file: build-tree SHA-256
`2d86d84f863f511c2eec70e33db2efda0e8d40fb322e21b32fa365cc23557aff`, archive
member SHA-256 `ac246e0144ddfae629315a605049ad1ffb191db4b35df419dbd039e7f2f6ed829`.

For those reasons the probe deliberately did not generate `operator.h`, invoke
the freezer, or relink. A safe continuation first needs a pinned finite module
inventory including transitive imports, an audited same-source freezer and
its opcode/marshal provenance, plus an independently observed input/object/
link closure. The earlier `linecache → traceback → collections → keyword`
chain belongs to a different, deliberately constrained image and remains
valid historical evidence.

No code or original toolchain directory was changed. The probe does not change
`production_admission=false` or `online_publication=false`.
