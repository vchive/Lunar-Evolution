# Linux native descendants

New Lunar-owned Linux bootstrap builds use `native-bootstrap-linux-subreaper-v1`. Before
launching a target, the bootstrap verifies child-subreaper setup and resets SIGCHLD to a waitable
default. When the direct worker exits, it preserves that status and continues reaping adopted
children until the kernel reports ECHILD. The guardian remains active during this wait.

The formal Linux launch explicitly negotiates `--child-supervision linux-subreaper-v1`, using
the original lifeline and absolute deadline. EOF, unexpected lifeline data or deadline exhaustion
stop the bootstrap's original private group. Waiting for descendants does not allocate another
budget. Older Linux descriptors are rejected before formal admission; historical evidence
remains available through the existing read-only recovery path.

The control record and sequence-3 terminal frame remain version 1. The durable terminal remains
`process_only`, with its existing original deadline/cleanup checks. Generic handshake success or
an installation descriptor alone does not establish tree-drain evidence or grant publication
authority. Missing terminal is still unknown and cannot authorize execution again.

All runnable entries in the new Linux binary perform natural drain. Direct fixture interfaces
without a guardian prove cooperative drain only. Under the formal target policy, inherited
session/group/namespace/signal restrictions remain necessary for private-group cleanup. The
bootstrap's own termination or pause (including cleanup SIGTERM, SIGKILL or SIGSTOP) is outside
this guarantee, as are full filesystem/egress
containment and independent watchdog ownership. Darwin retains its direct-child lifecycle and
rejects the Linux flag. Common final guardian checks and terminal-write failure handling also
apply there; they do not establish Darwin child-subreaper parity.

Only local inert C fixtures are used for this feature's validation. Actual OpenEvolve/Shinka
Python runtime launch, failure settlement, and multi-host orchestration remain separate work.
