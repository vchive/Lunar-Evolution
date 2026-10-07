# Data model

`LINUX_FD_CONTROL_IMPLEMENTATION = native-bootstrap-linux-fd-control-v1` extends the existing
Linux input-mutation, fd-handoff and subreaper boundary. It does not alter a wire DTO.

Formal Linux admission accepts this exact implementation only. Old input-mutation and
fd-handoff descriptors retain their distinct prerequisite failures; all earlier versions
retain input-mutation-required. Historical descriptors are not relabelled during load/replay.

The target seccomp filter is compiled into the byte-bound artifact. Fcntl command and ioctl
request are argument1; F_SETFL flags are argument2. Supported ABIs remain x86_64, aarch64,
i386, little-endian. Alternate audit architecture/x32 continues to refuse before these gates.
Nonzero upper words are rejected rather than ignored. Unknown commands/requests fail EPERM.

No new execution, signal, evaluation, learning or publication authority is added. Receipts
remain process-only unless the existing independent publication evidence proves more.
