# Frozen bootstrap and codec-closure observation (2026-10-20)

This record captures a bounded Linux observation made on `5090gpu` (`worker01`).
It is diagnostic evidence only. It does not establish a sealed runtime, a
fixed-main launch, owner/lifecycle acceptance, authoritative input/result
consumption, publication, or production admission. The observation used no
WebAgent, remote evaluator, external worker, solver, model, or campaign.

## Artifact and ELF inspection

The observed executable was:

```text
path: /home/qinzhiqing/lunar-cpython-frozen/python
platform: ELF64 x86-64
size_bytes: 26198088
sha256: ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b
```

A read-only `readelf` inspection found no `PT_INTERP` program header and no
`DT_NEEDED` entry. These properties describe the file format only; they do not
prove that Python startup, the reviewed frozen closure, the fixed main, or the
broker path works.

## Clean-environment matrix

Every command used the same bounded environment:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  /home/qinzhiqing/lunar-cpython-frozen/python ...
```

| Probe | Exit | stdout | stderr | Result |
| --- | ---: | --- | --- | --- |
| `--version` | 0 | 15 bytes, SHA-256 `9acda2babae175a076c5eec85844a8033b0b454b9930d80523d355f5ed17c29f` (`Python 3.13.12\n`) | empty, SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | CLI metadata path only |
| `--help` | 0 | 2,585 bytes, SHA-256 `62374e89b79c1a069cfb61b33e582cad6134e02597d8bbd95ad8eff9ef3996b7` | empty, SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | CLI help path only |
| `-S -c 'print(1)'` | 1 | empty | 49 bytes, SHA-256 `6c29f59aeec62771de59b4daf306136c9f32fa4ec2d565b5994c769a3a9aadba` | `ModuleNotFoundError: No module named 'linecache'` |
| `-I -S -c 'print(1)'` | 1 | empty | same 49-byte digest | same `linecache` failure |
| `-S -c 'import sys; print(sys.version)'` | 1 | empty | same 49-byte digest | same `linecache` failure |
| `-S -c 'import _codecs; print(_codecs.getincrementaldecoder("utf-8"))'` | 1 | empty | same 49-byte digest | same `linecache` failure before user code |
| `-S -c 'import codecs; print(codecs.lookup("utf-8"))'` | 1 | empty | same 49-byte digest | same `linecache` failure before user code |
| `-S -c 'import encodings; print(encodings.__name__)'` | 1 | empty | same 49-byte digest | same `linecache` failure before user code |
| `-S -c 'import linecache; print(1)'` | 1 | empty | same 49-byte digest | expected missing-module failure |

The codec, `encodings`, and `linecache` rows all fail before the supplied
`-c` body can run. They therefore show that the ordinary command-line path has
not reached a usable finite stdlib/codec closure; they do **not** prove that an
individual codec implementation works or that the fixed-main path has the same
failure.

The bounded stderr bytes for the failing rows are exactly:

```text
ModuleNotFoundError: No module named 'linecache'\n
```

No raw stderr is placed in a runtime receipt. The hashes above are retained so
that the diagnostic can be independently compared without treating the error
text as an acceptance claim.

## Canonical diagnostic summary

The following summary is intentionally negative and is not a runtime receipt:

```json
{
  "schema": "lunar-static-python-frozen-bootstrap-observation-v1",
  "host": "5090gpu",
  "artifact": {
    "path": "/home/qinzhiqing/lunar-cpython-frozen/python",
    "sha256": "ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b",
    "size_bytes": 26198088,
    "elf_pt_interp": false,
    "elf_dt_needed": false
  },
  "clean_environment": {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "environment_source": "env-i"
  },
  "probe": {
    "version_exit": 0,
    "help_exit": 0,
    "command_body_probe_exit": 1,
    "command_body_failure": "missing_linecache",
    "command_body_stderr_sha256": "6c29f59aeec62771de59b4daf306136c9f32fa4ec2d565b5994c769a3a9aadba",
    "codec_and_encodings_body_executed": false
  },
  "claims": {
    "startup_performed": false,
    "runtime_execution_performed": false,
    "fixed_main_verified": false,
    "broker_exchange_verified": false,
    "input_consumption_verified": false,
    "owner_verified": false,
    "lifecycle_verified": false,
    "installation_accepted": false,
    "production_admission": false,
    "online_publication": false
  }
}
```

## Blocking interpretation

The image can answer `--version` and `--help`, but all command-body and codec
probes stop at the missing `linecache` module. A subsequent acceptance attempt
must use the reviewed fixed-main entry point, close and pin the finite
frozen/import/codec inventory, and retain source/object/header/link and
lifecycle/cleanup evidence. Only after that dedicated Linux no-skip matrix
passes can Feature189 G3 / Feature193 F03 be reconsidered. This observation
does not replace or combine with the earlier `missing_encodings` report in
[`docs/feature189-sealed-startup-probe.md`](../../docs/feature189-sealed-startup-probe.md)
or the previous frozen-bootstrap note in
[`docs/feature189-frozen-bootstrap-observation-20261020.md`](../../docs/feature189-frozen-bootstrap-observation-20261020.md).
