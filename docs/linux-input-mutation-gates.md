# Linux input mutation gates

New formal Linux attempts require the trusted descriptor implementation
`native-bootstrap-linux-input-mutation-v1` before consuming a nonce or starting
execution. New builds default to that version. Historical subreaper artifacts
remain readable within their original scope and cannot launch under the new gate.
The existing child-supervision flag and control protocol are unchanged.

The native Linux boundary requires Landlock ABI 3 or newer. It queries the
running kernel before installing policy; unavailable or older kernels reject
the requested execution boundary instead of accepting weaker truncation control.
The known REFER/TRUNCATE rights are retained even with older build headers.

Exact read files cannot be truncated through the pathname policy. Declared
work/output directories permit ordinary creation, writes and truncation. When
any read input exists, ownership, timestamp and xattr mutation APIs join chmod
in a process-wide seccomp deny gate, including modern xattr-at and 32-bit legacy/
time64 entries. This also prevents output metadata changes;
metadata-preserving copying/extraction needs a separately compatible runtime
contract. No-read attempts preserve their prior metadata behavior.

This is a bounded input mutation gate. It does not claim full filesystem or
network containment, clean every inherited FD, seal runtime imports, close
regular-file ioctls or supervise workloads after bootstrap death/pause. Darwin
retains its separate sandbox behavior. Existing evidence retains its original
artifact/version scope; it is not retroactively upgraded.
