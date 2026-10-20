# Feature189 source-owned `linecache` closure probe (2026-10-20)

This note records a bounded Linux build probe on `5090gpu` (`worker01`). It is
diagnostic evidence only. It does not establish a sealed runtime, a reviewed
fixed-main build, owner/lifecycle acceptance, publication, or production
admission. The probe used no WebAgent, evaluator, external worker, solver,
model, or campaign.

## Baseline and controlled change

The baseline executable was `/home/qinzhiqing/lunar-cpython-frozen/python`:

```text
sha256: ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b
```

The source tree already contained generated headers for the reviewed startup
modules (`codecs`, `encodings`, `io`, and others), but its `Python/frozen.c`
table did not contain `linecache`. A disposable source edit generated a
`linecache.h` header from the source-owned `Lib/linecache.py`, added that one
module to the frozen stdlib table, rebuilt `Python/frozen.o`, and relinked a
copy of the executable. The source tree and baseline executable were restored
after the probe.

The source and generated-header pins observed during the probe were:

```text
Lib/linecache.py: 09dbf03f17d86d843027cb6465d058859591d18d6ee166149d26c00e7dc30e0c
linecache.h:      4cf681d27caf442ad4817c8ab80f55598981b3c32c32ddabb94ab9dde9357f80
```

The resulting disposable executable was:

```text
sha256: 6ab9a738f317d6640a64cf4fe9a069a620a6e5ae7a1890db38c830d5b10229bf
```

This is a controlled closure experiment, not a release artifact. It has no
independent source, compiler, object, linker, or fixed-main attestation.

## Clean-environment results

Every command used:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 <probe> -S -c '<command>'
```

| Command | Exit | Observation |
| --- | ---: | --- |
| `print(1)` | 0 | stdout `1` |
| `import sys; print(sys.version)` | 0 | Python 3.13.12 metadata printed |
| `import codecs; print(codecs.lookup("utf-8"))` | 0 | UTF-8 codec lookup returned |
| `import os; print(os.getcwd())` | 0 | `os` imported and cwd printed |
| `import linecache; print(linecache.__name__)` | 0 | frozen `linecache` imported |
| `import traceback; print(1)` | 1 | expected next missing source module: `traceback` |

The successful command rows are evidence that adding source-owned `linecache`
to the frozen table removes the previous `-c` command-path failure. They do
not show that the full stdlib closure is complete; the `traceback` row gives a
concrete remaining gap. The disposable executable also printed the existing
`Could not find platform independent libraries <prefix>` diagnostic, so it is
not a sealed installation.

For independent comparison, the successful rows emitted the same 113-byte
stderr diagnostic (SHA-256
`a84bcc3d691c2d0c8abf5889c55d2f498cab1ac1708ef99e5af76ab88acd370d`) and
the following stdout digests, in table order:

```text
4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865
fd1f5bcda7d1d75e36755867eaadb6cb61ab79a09682e6b8c3fd0e866b70eb85
abd8e59c029dc6f5487c2f3e8defe6f956ad967f1e2994130955b8aa972b68b8
6720e286d94a60c22fc5041298fd97476c294966117986c42163cbbf04bb5783
34f2cd220c8427e47c89c53d95b2903409e2d7fede2afa1a6ad7d03bbb2cbc5a
```

The failing `traceback` row had empty stdout and stderr SHA-256
`2a7792e0856644ffa653060fbfc38a21df94ca17ab27e60105456af54b195d27`.

The bounded receipt projection for this experiment is:

```json
{
  "schema": "lunar-static-python-linecache-closure-probe-v1",
  "host": "5090gpu",
  "baseline_sha256": "ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b",
  "probe_sha256": "6ab9a738f317d6640a64cf4fe9a069a620a6e5ae7a1890db38c830d5b10229bf",
  "source_sha256": "09dbf03f17d86d843027cb6465d058859591d18d6ee166149d26c00e7dc30e0c",
  "generated_header_sha256": "4cf681d27caf442ad4817c8ab80f55598981b3c32c32ddabb94ab9dde9357f80",
  "command_probe": "passed_after_linecache_freeze",
  "next_missing_module": "traceback",
  "claims": {
    "startup_performed": false,
    "runtime_execution_performed": false,
    "fixed_main_verified": false,
    "owner_verified": false,
    "lifecycle_verified": false,
    "installation_accepted": false,
    "production_admission": false,
    "online_publication": false
  }
}
```

## Claims retained as false

```text
startup_performed=false
runtime_execution_performed=false
fixed_main_verified=false
broker_exchange_verified=false
input_consumption_verified=false
owner_verified=false
lifecycle_verified=false
installation_accepted=false
production_admission=false
online_publication=false
```

The next controlled step is to close the reviewed command/error-report import
set (at minimum `traceback` and its source-owned dependencies), regenerate the
frozen inventory from the pinned source, and repeat the no-skip matrix with
independent source/toolchain/object/link/ELF evidence. This probe does not
replace the existing `frozen-bootstrap-observation` or `missing_encodings`
reports.
