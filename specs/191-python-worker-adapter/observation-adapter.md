# Feature191 provider-free observation adapter

`adapt_static_python_observation` is the first P1 slice after the pure binding
and terminal DTOs. It accepts the canonical JSON emitted by the sealed static
Python fixture and maps it to `PythonProducerRuntimeObservation`.

The adapter is deliberately detached from process launch. It never invokes a
Python executable, reads a host runtime, imports a provider, writes a journal,
or consumes an RSI budget. The caller supplies two independent observations:
the exact broker transcript bytes and a `pycache_absent` fact. The fixture
record cannot self-attest either value.

The boundary rejects host substitution (`/usr/bin/python*`, non-empty
`sys.path`, external module files, or a different cache tag), policy drift,
unexpected startup origins, malformed broker responses, and loader-negative
cases where any fixed route succeeds. All three protection claims remain
`false`; a valid observation is evidence for local reconciliation only and is
not a production-admission or evaluator result.

The adapter requires the Feature189 static target (`cpython-313` at
`/lunar-static-python-fixture`, with prefix and stdlib at `/lunar-static-fixture`)
and the exact CPython `3.13.12/final/0` version. The finite available builtin and
frozen inventories are shared immutable projections of the reviewed installation
profile. The distinct startup module inventory and each module's builtin/frozen
origin are checked independently. The boolean `safe_path` and `dev_mode` flags
retain their actual CPython wire types.

Broker evidence must be one complete JSON response frame with the existing
response keys, top-level completed status, fixed request ID, integer HTTP status
and valid bounded base64 body. Duplicate keys, nested decoys, multiple frames and
truncated responses cannot pass substring matching. Stdout accepts canonical
JSON with exactly one optional final newline from the frozen fixture asset.
Direct dict inputs pass the same finite exact builtin shape and aggregate bounds
before serialization; mapping, list and text subclasses cannot execute callbacks.

Focused contract tests generate observations from the reviewed emitted
`frozen_main.py` asset with explicit fake sys/loader/pipe inputs. This proves
adapter and encoder compatibility, without claiming real runtime enforcement. A
later Linux acceptance change can call it after the existing native fixture
has independently captured raw stdout, transcript, and filesystem evidence.
