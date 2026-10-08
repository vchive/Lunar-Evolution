# Linux native keyring control

Feature187 adds native-bootstrap-linux-keyring-control-v1. The actual Linux
target filter refuses add_key, request_key and all keyctl commands with EPERM on
x86_64, aarch64 and i386, using stable tables even when build headers omit names.
Older POSIX-mq-only descriptors fail keyring_control_required before cancellation,
budget, input staging, nonce, broker setup or spawn. Earlier rejection order,
historical read-only evidence and Darwin platform scope remain unchanged.

This preserves held v2 grants, exact guardian ownership, original deadlines,
private IO, broker and record schemas. It is a bounded kernel keyring control,
not a complete kernel-egress proof or production Python admission.

The dedicated keyring-control.xml covers native/raw keyctl probes, fresh anonymous
private session rings in disposable processes, unchanged original keys after
refusal, useful IO and formal v2/broker/FD closure. Tests never inspect or mutate
pre-existing host keyrings; NULL request_key callout avoids external helpers.

A runner whose ambient policy denies private keyring creation records explicit
private-baseline skips. Raw EPERM alone on such a runner does not establish
dynamic keyring enforcement; final acceptance requires actual usable private
baselines and filtered refusals, in addition to source/UAPI and formal composition.
Darwin skips are not Linux execution evidence. Final CI/raw audit/merge is pending.
