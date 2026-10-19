# Feature189 reviewed no-dynamic bootstrap observation (2026-10-20)

This note records a bounded Linux development observation from `5090gpu`. It
is diagnostic material only. It does not establish sealed startup, runtime
acceptance, owner or lifecycle validation, publication, or production
admission.

## Reviewed build material

The temporary review directory was `/run/user/2110/lunar-probe/nodyn-reviewed`.
It used the staged CPython 3.13.12 source and the existing static core build.
The only configuration delta was an isolated copy of `pyconfig.h` in which
`HAVE_DYNAMIC_LOADING` was undefined:

```
pyconfig-no-dynamic.patch sha256=6273b3a66a53aa4f6fe7f7532e173562a7df939c37c3832d5b2581065955d37c
import.o              sha256=c5511afd171abbe8612f5bcd29c76f1788f751f26a6a132a672bc33f9896b1ac
importdl.o            sha256=dcc4c814151a45d296b48acd1c6cf3214445bfdcb16359372c329eb5d31ba53c
libpython-nodyn.a     sha256=76b1bcce1b69f091362f4d1355ec279d94c05630fed14abca2ee2a62e42e136e
```

The archive was linked with the existing `Modules/getpath.o`, launcher,
profile, frozen-main, pipe, and config objects. `getpath_noop.o` was not used;
it causes the fixed profile to reject path configuration. The resulting
executable was:

```
/run/user/2110/lunar-probe/nodyn-importdl/python-frozen-main-nodyn
size=24533096
sha256=0e0de672bc28425a7b6973093db057dbdd6e40a3ce95be252d012f4599e2bd36
```

`readelf` identified an ELF64 x86-64 executable with no `PT_INTERP` and no
`DT_NEEDED`. `nm` over the executable and archive found no
`_imp.create_dynamic`, `_imp.exec_dynamic`, `_PyImport_GetModInitFunc`, or
`_PyImport_FindSharedFuncptr` symbols. The retained string
`dynamic extension entry point retained` belongs to the fixture's negative
check and is not an exported runtime entry point.

## Replay

The broker helper opens the response FIFO as blocking before launching the
fixed executable. Replay both cases on the same host with:

```sh
cd /run/user/2110/lunar-probe/nodyn-importdl
python3 run-broker.py > /tmp/lunar-nodyn-baseline.out 2>/tmp/lunar-nodyn-baseline.err
LUNAR_STATIC_FIXTURE_CASE=loader-negative \
  python3 run-broker.py > /tmp/lunar-nodyn-negative.out 2>/tmp/lunar-nodyn-negative.err
```

The helper's target invocation is the fixed executable with the two inherited
broker FDs; it does not use `-c`, a shell command, or a host stdlib path.

## Observed results

Both broker runs exited `0` with empty stderr. The baseline observation had
output size 2746 bytes and SHA-256
`4ebd8187e11353c542f64bcfffb125ec5e02333fe9140fe599370f09b4b44bbb`. Its
fixed-main JSON reported `computed=285`, `fixture_case=baseline`,
`broker_response_bytes=86`, `sys_path=[]`, and isolated/no-site/safe-path
flags. The loader-negative output had size 2849 bytes and SHA-256
`a55f36568619e0081102802cdf3e4699a55f48e9bd623da30eda4698b1271539`; all
8 direct loader attempts and all 7 ordinary loader attempts were refused.

These are provider-free inert fixture observations. The JSON itself retains
`production_admission=false`, `runtime_load_protection=false`, and
general-code-origin protection false.

## Claims retained as false

The following remain false for this observation:

```
sealed_startup_verified=false
runtime_execution_performed=false
authoritative_input_verified=false
authoritative_result_verified=false
owner_verified=false
lifecycle_verified=false
publication_verified=false
production_admission=false
```

A later acceptance gate still needs source/archive/header/link provenance,
original-executable owner and cleanup evidence, an authoritative input/result
path, and a no-skip Linux matrix. This note does not combine with or replace
the earlier `missing_encodings` and `missing_linecache` diagnostic reports.
