# Feature187 native keyring control

Priority P0. Linux keyrings hold kernel objects independently of filesystem grants
and inherited descriptor closure. This bounded slice refuses add_key, request_key
and the entire keyctl syscall, including current and future commands, on native
x86_64, aarch64 and i386. Stable native syscall tables prevent older build headers
from silently omitting a running kernel entry. Refusal is EPERM.

Add Linux default/formal selector native-bootstrap-linux-keyring-control-v1.
Earlier rejection reasons retain their order. A preceding POSIX-mq-only descriptor
fails native_trusted_attempt_keyring_control_required before cancellation, budget,
input staging, nonce consumption, broker endpoint effects or spawn. Historical
read-only artifact/recovery contracts and Darwin remain in their original scope.

Preserve v2 held grants, original lifeline/deadline, exact guardian ownership,
child drain, private pipe/socketpair and useful file/fork/thread IO, broker and
receipt/publication schemas. No native watcher protocol or additional inherited
keyring/descriptor authority is added.

Only inert fixtures are allowed. Raw probes use invalid IDs/pointers or a NULL
request_key callout to avoid external key helpers if a filter regresses. Any usable
keyring baseline must live in a freshly created anonymous private session inside
a disposable subprocess; create bounded user keys there, never inspect/modify
pre-existing user/session/system keys. The owning subprocess retains the private
ring and its cleanup. Record explicit kernel-policy baseline unavailability.

Final-source three-version Linux raw CI, independent review and tested tree merge
are required. Darwin skips or EPERM from ambient kernel policy alone are not a
usable keyring baseline. Final enforcement acceptance requires non-skipped usable
private baselines and filtered refusal on the actual Linux matrix. This is not a full kernel-egress/information-flow proof:
other kernel facilities remain separately scoped. Immutable Python runtime,
formal Python admission and production adapters/RSI are P1; multi-host P2 deferred.
No models, solvers, WebAgent, remote/company evaluator or credentials.
