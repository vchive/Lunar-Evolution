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
`/lunar-static-python-fixture`) and the fixed computation/broker request. A
later Linux acceptance change can call it after the existing native fixture
has independently captured raw stdout, transcript, and filesystem evidence.
