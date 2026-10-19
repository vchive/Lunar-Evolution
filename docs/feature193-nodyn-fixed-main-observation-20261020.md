# Feature193 no-dynamic fixed-main observation (2026-10-20)

This note records a bounded Linux development-host observation. It is retained
as diagnostic evidence only. It does not establish sealed runtime acceptance,
production admission, or a real producer campaign.

## Observed artifact

On `5090gpu` (`worker01`), a temporary CPython 3.13.12 static image was linked
with the reviewed `HAVE_DYNAMIC_LOADING`-disabled `import.c`/`importdl.c`
objects and the existing fixed getpath/profile/launcher objects. The temporary
artifact was:

```text
/run/user/2110/lunar-probe/nodyn-importdl/python-frozen-main-nodyn
```

| item | value |
| --- | --- |
| ELF size | `24533096` bytes |
| ELF SHA-256 | `0e0de672bc28425a7b6973093db057dbdd6e40a3ce95be252d012f4599e2bd36` |
| `PT_INTERP` | absent |
| `DT_NEEDED` | absent |
| dynamic-loader symbols | absent from `nm` output |

The source-side change was one reviewed configuration difference: both import
translation units were compiled with `HAVE_DYNAMIC_LOADING` undefined. The
temporary patch and objects remain on the development host; they are not an
accepted source recipe or a checked-in runtime image.

The remote `nodyn-reviewed/rebuild.sh` was rerun from the same reviewed
inputs. Its script SHA-256 was
`8c0a447c875983f8b9c0234f59b5d9a20d9c02bef642b2769af10bf9297a0c6a`, and it
reproduced the executable SHA-256 above. The linked archive had SHA-256
`76b1bcce1b69f091362f4d1355ec279d94c05630fed14abca2ee2a62e42e136e`. The
script and archive are temporary host material and are not treated as the
repository's pinned build recipe.

## Fixed-main broker probe

The image was invoked through the existing fixed launcher and inert broker
fixture, rather than through ordinary `-c` execution. The baseline exited zero
with an empty stderr and reported:

```json
{"computed":285,"broker_response_bytes":86,"sys_path":[]}
```

The loader-negative case (`LUNAR_STATIC_FIXTURE_CASE=loader-negative`) also
exited zero with an empty stderr. Eight direct loader attempts and seven
ordinary loader attempts were all refused by the fixture. These observations
show that the no-dynamic link and fixed-main test seam can be exercised on the
development host; they do not prove that the artifact has independently
audited source/object/header/link provenance or the native owner lifecycle.

## Claims retained as false

The observation keeps `runtime_execution_performed=false`,
`installation_accepted=false`, `input_consumption_verified=false`,
`owner_verified=false`, `lifecycle_verified=false`,
`production_admission=false`, and `online_publication=false`. The broker and
loader-negative results are inert fixture evidence and are not a solver result.

The remaining Feature189/193 gates are the pinned source/toolchain audit,
complete finite import/codec closure, independent Linux no-skip acceptance,
owner/cleanup evidence, authoritative input/result handoff, and the real
OpenEvolve/Shinka process lifecycle. The temporary artifact is not used by the
CLI or by CI.
