# Original grants and private control v2

The live owner holds root, ancestor and leaf descriptors. `ProducerGrantBindingNode`
contains canonical path, original device/inode/kind, parent index and component name;
it has no descriptor and confers no access. `ProducerGrantExpectedBinding` pins an
original directory without granting it a role. `ProducerGrantMaterial` carries retained
protected bytes and original mtime/ctime; exact mode0400, nlink1, identity, size and bytes
are checked with a temporary reader opened relative to the held original parent.

The private `LNB1` v2 frame contains three original SHA64 bindings, sealed target and
bootstrap FD numbers, target path, fixed isolation kind, original parent graph, exact
leaf grant records, one merged writable/CWD index and argv. Integers are big endian;
root parent is UINT32_MAX. Only role masks1/2/4/12 are legal. Parent nodes have no grants.
The frame is live process setup data, not durable recovery or publication authority.

Existing owner bounds remain: 256nodes, depth64, 4096bytes/path, 65536total request path
bytes, 64read/16write/81requests. V2 has a separate 65536byte total control bound, 64argv
strings each4096bytes and 81grant records. Material bounds are 64entries, 512KiB each
and1MiB total; formal config remains512KiB, RSI request/memory each128KiB. Maximums
are independent ceilings, not a promise all maxima fit one frame.

No change to attestation consumption, deadline, registration, handoff, cleanup,
terminal, broker, execution receipt or publication schemas. Historical records keep
their original scope. Detached Feature180 manifests remain execution_enforced=false.
