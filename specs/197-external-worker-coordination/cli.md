# Explicit SSH worker commands

Expose the existing assignment and SSH transport through `external-worker
reserve|dispatch|inspect|reconcile`. The commands operate on an existing local
RSI ledger. They never create a native episode claim, a controller checkpoint,
or a candidate result. The original controller remains the sole authority.

Every invocation names a controller/run/task, a private local registry and a
fixed SSH configuration. Registry entries contain worker/host/boot/key IDs and
an absolute path to a separately installed private key file, never key bytes.
JSON configuration and request documents use the existing canonical worker JSON
encoding (sorted keys, compact separators, UTF-8, no trailing newline); raw key
files contain the installed key bytes. Both configuration and key reads are bounded, no-follow, same-owner private-file
reads with stable metadata and held parent directories. Errors use fixed codes.
Nonregular leaves are refused before open. File and ledger descriptor opens use
`O_NONBLOCK` as well as `O_NOFOLLOW`, so a regular-to-FIFO replacement between
stat and open cannot block admission; descriptor/name identity rechecks still
refuse that replacement before a read or SQLite connection.

`reserve` requires an original request, plan, independent claim digest, profile,
and controller checkpoint digest. It locks the original controller and records
one assignment through the existing once-only journal. It sends nothing.
`dispatch` requires a pre-existing assignment and uses the existing durable
transport. `reconcile` requests only the already retained remote result; it
cannot relaunch a producer. Both accept a bounded channel timeout, which cannot
extend the producer's original persisted budget. `inspect` makes no SSH call.
All commands refuse a missing ledger before initialization. Recovery uses an
explicit `RSILedger(create=False)` route whose every write-capable connection
uses SQLite `mode=rw`; a database removed between checks cannot be recreated.
Malformed databases return a fixed CLI error. Inspection does not
consume, reserve, reconcile or publish an assignment; opening an existing ledger
retains its existing schema initialization behavior.

Outputs identify the evidence scope as authenticated external-worker transport.
Even an authenticated receipt is not proof of candidate validity, remote process
cleanup, accepted native runtime, or publication. These authority flags remain
false. Raw receipt bytes, origin challenges, keys, configured paths and provider
credentials are not printed. The CLI returns a compact status and digest-only
projection. Unknown work remains gated after restart and is never reassigned by
a timer. Focused tests use local inert transport seams, real SQLite and HMAC;
actual SSH deployment remains a separate integration acceptance.
