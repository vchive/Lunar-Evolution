# Feature189 linecache frozen-closure observation (2026-10-20)

This note records a bounded provider-free experiment on the Linux development
host `5090gpu` (`worker01`). It adds the reviewed CPython `Lib/linecache.py`
module to the custom frozen inventory and rebuilds the existing no-dynamic
fixed-main fixture. It does not change the production admission state and does
not establish a sealed CPython runtime, owner/lifecycle acceptance, or a real
producer/evaluator run.

## Why this experiment was run

The previously retained frozen bootstrap executable
`/run/user/2110/lunar-probe/nodyn-reviewed/python-frozen-main-nodyn`
(`sha256=0e0de672bc28425a7b6973093db057dbdd6e40a3ce95be252d012f4599e2bd36`,
24,533,096 bytes) had already passed the `encodings` stage but ordinary
`-c` execution failed with `ModuleNotFoundError: No module named 'linecache'`.
That negative result is retained in
`docs/feature189-frozen-bootstrap-observation-20261020.md`.

The experiment therefore used only the source-owned `Lib/linecache.py` and a
new generated frozen header. No host `PYTHONPATH`, ordinary host stdlib path,
or runtime installation was accepted.

## Reproducible inputs and outputs

All paths below are temporary, Linux-host evidence under
`/run/user/2110/lunar-probe`; they are not checked into the repository.

| item | SHA-256 | size |
| --- | --- | ---: |
| `linecache-closure/python-frozen-main-nodyn-linecache` | `a645d2d71e62a8f36aa2cd9e851e111d570497fe23dbd9cfba4e4387c4544ccc` | 24,542,136 |
| generated `Python/frozen_modules/linecache.h` | `048a5c025818b1f845e0653244b65097f0e98c1c6366b67d955425a15c737d28` | 27,659 |
| updated `_lunar_static_main` header | `8d5068c45d6cd8b041d239187f04bec3b50303f2403d269b2c5f2a922e21cb07` | 34,554 |
| custom frozen table source `frozen-linecache.c` | `494df5949db98241855d16bdb21ca13bd73db97c71a7ff283fff1e64cfcb13b6` | 2,174 |
| custom frozen object | `85f77204099168d626f6338991dd0c2f6387c370e184922d692da6d14c5d5b97` | 204,024 |
| patched no-dynamic archive | `c9d3df885f5080ececcea86631d408a5fb264b62258762dbb69f5a89f375c51c` | 48,466,214 |
| reviewed `Lib/linecache.py` | `09dbf03f17d86d843027cb6465d058859591d18d6ee166149d26c00e7dc30e0c` | 7,488 |
| target `freeze-module` executable | `af9c91e73878d967a6de40ed23a17693ccb383147192fa206707360c530ce64c` | — |
| `zig-cc` | `9c1a2c5e13c79bc6a079e644ee1d1ff7abf60aee2ad4a2070f3a15f1a26feec0` | — |
| `zig-ar` | `fe6589590fd4eb01e357ecdbf3d6d18456a9dbcafa86683aea4902db3a780fe5` | — |

The resulting ELF has class `ELF64`, machine `x86-64`, no `PT_INTERP`, and no
`DT_NEEDED` entries. Those are file properties only.

## Fixed-main observations

The fixed-main broker harness used a corrected local fixture harness that opens
the response FIFO nonblocking only to establish the writer and then sets the
child read descriptor back to blocking. The original harness's nonblocking
read can race and produce `EAGAIN`; that harness issue is kept separate from
the runtime result.

Baseline command:

```sh
python3 /run/user/2110/lunar-probe/linecache-closure/run-broker-fixed.py
```

Observed exit code was `0`. The child emitted one inert observation with:

- `frozen_names` containing `linecache`;
- `sys_path=[]`;
- `computed=285`;
- `broker_response_bytes=86`;
- no stderr.

The detached stdout was 2,758 bytes with SHA-256
`7ca548026150911dcde011e131cf5a6fe1440941e0f67763b0f4057b6b2f1e05`.

Loader-negative command:

```sh
python3 /run/user/2110/lunar-probe/linecache-closure/run-broker-negative.py
```

The fixture case was `loader-negative`; exit code was `0`, with all eight direct
loader attempts and all seven ordinary loader attempts refused (`true`). The
detached stdout was 2,861 bytes with SHA-256
`4b53d3fb31fae6e1b15c5cd3f2038e7736f8c4758bfba57b9411c1cfe6957b17`.
Both runs had zero-byte stderr (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).

Adding `linecache` without updating the reviewed frozen inventory was refused
by the fixed-main code as `RuntimeError: frozen inventory drift`. The successful
runs therefore include an explicit inventory update in the temporary
`_lunar_static_main` source/header; this is a controlled compatibility
experiment, not an implicit admission of an unreviewed module.

## Claims

The observations support only the following bounded statements:

```text
linecache_source_observed=true
linecache_frozen_header_generated=true
fixed_main_baseline_observed=true
fixed_main_loader_negative_observed=true
sys_path_empty_observed=true
runtime_execution_performed=false
installation_accepted=false
input_consumption_verified=false
owner_verified=false
lifecycle_verified=false
production_admission=false
online_publication=false
```

The fixture broker exchange is a parent-owned inert byte exchange. It is not an
authoritative input/result, solver execution, model evaluation, producer
campaign, or lifecycle receipt. A complete stdlib/codec closure remains open:
`linecache` is now demonstrated as a possible reviewed frozen module, but no
claim is made for the rest of the Python standard library or for a production
sealed runtime.
