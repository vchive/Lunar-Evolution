# Data model

`ProducerGrantIdentity`: positive inode, unsigned 64-bit device/inode, kind `file` or
`directory`. `ProducerGrantRequest`: absolute canonical string, known role, optional identity;
protected-file requires a file identity and directory roles require directory identities.

`ProducerGrantRecord`: path, sorted tuple of unique roles, original identity. `ProducerGrantManifest`:
sorted unique records, canonical SHA; fixed scope and false execution flag in serialization.
No parser or authority conversion. `ProducerGrantAnchor`: validated record + live leaf FD,
available only from an active owner. FD numbers are not part of durable observation identity.

Private node: path, held FD, original identity and optional held-parent/name. A single
owner keeps all nodes and bindings; after close there is no live grant authority.
