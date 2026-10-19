# Feature189 frozen bootstrap observation (2026-10-20)

This note records a bounded observation from the Linux development host
`5090gpu`. It is diagnostic material only. It does not establish sealed
startup, runtime acceptance, owner/lifecycle validation, publication, or
production admission.

## Observed artifact

The independently staged executable was:

```
/home/qinzhiqing/lunar-cpython-frozen/python
```

The observed file was an ELF64 x86-64 executable of 26,198,088 bytes with
SHA-256
`ad52a2764ee24aef0f75e29b8d01cf049081e7c979369c86e05a980bcd78058b`. The
inspection showed no `PT_INTERP` program header and no `DT_NEEDED` entries.
Those are properties of the file and do not prove that its fixed entry point
or its broker path is usable.

## Bounded bootstrap probe

With a clean environment, the probe was:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  /home/qinzhiqing/lunar-cpython-frozen/python -c 'print(1)'
```

It exited with status `1`, produced no stdout, and produced this bounded
stderr:

```text
ModuleNotFoundError: No module named 'linecache'
```

The failure shows that this image gets beyond the earlier `encodings`
bootstrap failure, but its ordinary command-line path still imports a module
that is outside the retained frozen closure. The `-c` path is therefore a
diagnostic negative observation, not the sealed fixed-main acceptance path.

The detached stderr was 49 bytes with SHA-256
`6c29f59aeec62771de59b4daf306136c9f32fa4ec2d565b5994c769a3a9aadba`.

## Claims retained as false

The following remain false for this observation:

```text
startup_performed=false
runtime_execution_performed=false
fixed_main_verified=false
broker_exchange_verified=false
owner_verified=false
lifecycle_verified=false
production_admission=false
```

The next acceptance attempt must use the reviewed fixed-main entry point,
prove the finite frozen/import closure without ordinary `-c` or `linecache`
fall-through, and retain source/object/header/link pins plus raw lifecycle and
cleanup evidence. The existing `missing_encodings` report remains the source
for the earlier artifact; this note does not replace or combine those
observations.
