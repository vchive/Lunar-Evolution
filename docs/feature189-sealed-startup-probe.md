# Feature189/193 sealed startup probe (2026-10-19)

This note retains the first real Linux startup result from `5090gpu` and a
replay recipe. It is diagnostic material only. It does **not** change
`production_admission`, runtime acceptance, or publication state.

## Inputs and observed artifact

The probe used the independently staged CPython 3.13.12 tree and the static
core build under `/tmp/lunar-toolchains` on `worker01` (`5090gpu`). The target
was:

```
/tmp/lunar-toolchains/build-core-noffi/python
```

Observed bytes:

| item | value |
| --- | --- |
| ELF size | `26673400` bytes |
| ELF SHA-256 | `bfc4dbffc882d6f69540823cf32eef3994585c74d994b26677c3e61e17467a69` |
| `runtime.err` size | `223` bytes |
| `runtime.err` SHA-256 | `baaec70a3e250906a5a66cfda5f4078f43efc8cb237a5a2dbd0e43616d65fcca` |
| build source | CPython `3.13.12` staged tree; static core/no-ffi profile |

`readelf -l` reported an ELF executable with no `PT_INTERP`; `readelf -d`
reported no `DT_NEEDED` entries. That is an ELF property only and does not
establish startup.

## Baseline replay

Run on the same Linux host with a clean environment:

```sh
set +e
E=/tmp/lunar-toolchains/build-core-noffi/python
R=/tmp/lunar-toolchains/build-core-noffi/runtime.err
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 "$E" >runtime.out 2>runtime.err
printf 'exit=%s\\n' "$?"
sha256sum "$E" runtime.err
stat -c '%s %n' "$E" runtime.err
readelf -l "$E" | grep -E 'INTERP|Type' || true
readelf -d "$E" | grep NEEDED || true
```

The process exits nonzero before the user entry point. Bounded stderr is:

```text
Fatal Python error: Failed to import encodings module
Python runtime state: core initialized
ModuleNotFoundError: No module named 'encodings'

Current thread 0x0000000001520a00 (most recent call first):
  <no Python frame>
```

The fixed diagnostic classification is `missing_encodings`; the retained
runtime claims remain false (`runtime_execution_performed=false` and
`production_admission=false`). No raw stderr is included in a receipt.

## Minimum repair attempts

Two local Linux experiments were performed against a copy of the launcher and
profile, without changing the tracked recipe:

1. Set `PyConfig.module_search_paths_set=1` and supplied one absolute stdlib
   path (`/run/user/2110/lunar-probe/stdlib`) while keeping the strict getpath
   hook. The profile observed one path and the getpath hook observed the same
   path twice, but CPython still failed at the encodings bootstrap.
2. Disabled `module_search_paths_set` and pointed `home`, `prefix`, and
   `stdlib_dir` at the staged tree, using stock getpath. This also failed at the
   same bootstrap point, even with `Lib/` copied to the computed
   `lib/python3.13` location.

These results show that placing an ordinary host stdlib or setting a caller
path is not sufficient for this isolated image. A valid fix must freeze the
reviewed encodings/importlib bootstrap (or provide a reviewed PyConfig/getpath
implementation that is proven to hand the path to the pre-initialization
loader) and then repeat the full module/codec and lifecycle matrix.

The custom-path experiment produced these detached diagnostic binaries; they
are ephemeral `/run/user/2110` files and are identified here only to make the
failure auditable:

```
python-path2  sha256=4df76e7c63e8caaf743cfe9d3776bbdf4e93a1e3cef4ecef0c4ca50ae94bb6dd  size=26326456
python-debug2 sha256=98ad306234a9b34303f141cf003f23922097cecb3675b32bfccfaeffecaf72a9  size=26327144
python-stockpath2 sha256=148b3624e6341ba62e7d1ac3a19650812aa2f665585e47131fbb14da40733  size=26439768
```

## Loader-negative check

Invoking the static image through the host dynamic loader does not turn it
into a valid negative fixture: `/lib64/ld-linux-x86-64.so.2` simply reached the
same CPython bootstrap failure. Therefore no loader-negative acceptance is
claimed. A future negative case must be made from a separately built dynamic
variant and must retain its own `PT_INTERP`/`DT_NEEDED` evidence; it cannot be
inferred from this failed static run.

## Remaining gate

Feature189 G3 / Feature193 F03 remains open. The next controlled attempt must
freeze the reviewed finite bootstrap and retain source/object/header/link
pins, then run baseline, codec/import negative probes, original-executable
owner/lifecycle checks, and cleanup evidence on a dedicated Linux gate. Until
those observations pass, all runtime and production claims stay false.

## 2026-10-20 frozen-encodings experiment

An additional controlled build on `5090gpu` used the same CPython source family
with `encodings`, `encodings.aliases`, and `encodings.utf_8` frozen into the
image. The retained artifact was `/home/qinzhiqing/lunar-cpython-frozen/python`:

| item | value |
| --- | --- |
| ELF SHA-256 | `ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b` |
| ELF size | `26198088` bytes |
| `PT_INTERP` | absent |
| `DT_NEEDED` | absent |

With `env -i PATH=/usr/bin:/bin HOME=/nonexistent`, the image advanced past the
`encodings` bootstrap. A `-c 'print(1)'` probe then failed because the finite
image does not yet contain `linecache` (`ModuleNotFoundError: No module named
'linecache'`). The binary still accepts stock CPython command-line options and
does not expose the reviewed `_lunar_static_main._rsi_launch` launcher contract.
This is useful closure evidence only; it is not sealed-startup, lifecycle, or
production acceptance. The artifact is retained on the development host rather
than checked into the repository.
