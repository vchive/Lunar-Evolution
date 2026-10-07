# Data model

No control, receipt, attestation, broker request or durable store schema changes.

The Linux implementation selector gains native-bootstrap-linux-fd-handoff-v1. Old constants
retain their exact meanings. A selector is not independent authority: installation-owned byte/
inode pins and the existing admission chain remain required.

The child uses an internal bounded FD keep set only. It includes 0/1/2, the CLOEXEC error writer,
a target FD only for explicit FD execution and zero or two validated broker handles. The executable
FD remains inherited to preserve sealed shebang reopen compatibility. Broker endpoints must be
different underlying anonymous pipe objects; Linux PIPEFS_MAGIC plus FIFO type and F_GETFL direction
checks establish the endpoint kind. Fresh endpoint provenance still belongs to the trusted host. Sorted unique
FD numbers define disjoint close_range segments through UINT_MAX. Invalid/reserved aliases,
wrong endpoint kinds/directions and unavailable descriptor closing cause pre-exec refusal.

No durable success field, new recovery ownership or historical evidence upgrade is introduced.
