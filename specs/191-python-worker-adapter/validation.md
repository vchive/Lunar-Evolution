# Validation plan

No validation in this document is a completed acceptance. Until Features189 and
190 pass their dedicated Linux gates, only provider-free inert fixtures may run.

| Area | Required evidence | Refusal cases |
| --- | --- | --- |
| Binding parser | Canonical DTO round trip, exact type/order/bounds and fixed errors | unknown field, bool-as-int, duplicate key, placeholder digest, path/env/target drift |
| Runtime closure | Original manifest/tree digest, no-follow identity snapshots and target ABI | missing interpreter, symlink/hardlink, unlisted file, changed inode/bytes/resource/native input |
| Launch | Exact argv/env, intent+attestation, private owner and original deadline | host Python substitution, argv/module/path injection, env leak, deadline/nonce drift |
| Loader policy | Readable decoy source/pyc/extension/zip and unknown codec are refused | permission-only denial, `sys.path` discovery, `.pth`/site/customization/pycache |
| Fixture execution | Real CPython version/cache tag/flags, fixed computation, one broker exchange, bounded envelope | fabricated observation, oversized output, second request, malformed response |
| Lifecycle | registration, ready/release/start/terminal, request journal, reap and FD census | parent loss, cancel, signal, nonzero exit, cleanup uncertainty, missing terminal |
| Resume | Completed replay is read-only; unknown reconcile is idempotent under original deadline | blind restart, refreshed budget, changed binding/fingerprint, changed journal |
| Admission | Local exact evaluator receipt and atomic seed/publication evidence | external score/correct/generation used as Lunar rank or validity |
| Adapters | Explicit OpenEvolve wrapper and Shinka program/result export through common envelope | automatic project discovery/start, remote/Slurm/network campaign |

The dedicated run must retain raw process terminal, broker journal, runtime
observation, source/tree identity, ELF/static audit and first failure artifacts.
An independent review must verify that `execution_performed` and successful
publication are derived from observed Python/process/evaluator evidence, not from
descriptor fields or child claims. `runtime_load_protection`,
`production_admission` and `general_code_origin_protection` remain false.
