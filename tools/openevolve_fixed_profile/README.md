# Fixed OpenEvolve source preparation

This development tool prepares a finite source profile from the retained
OpenEvolve v0.4.0 archive. It does not download or install anything, import or
execute OpenEvolve, build an image, call a model, or enable production admission.

From the repository root, use the existing retained archive and a destination
that does not exist:

```bash
python -m tools.openevolve_fixed_profile \
  --archive /path/to/archive-second-download.tar.gz \
  --destination /path/to/new-source-profile
```

The exact archive size/SHA-256 and selected original files are pinned in
`prepare.py`. Every tar member is checked without filesystem extraction. The
output contains seven Python modules, the original Apache-2.0 `LICENSE`, the
Lunar MIT notice as `LICENSE.lunar`, and canonical `source-manifest.json` written
last. Failed partial output remains inspectable and is never silently reused.
Errors expose fixed codes rather than caller paths or source/provider prose.

The target broker module is generated from explicitly pinned source segments of
this checkout's existing `producer_broker_ipc.py` and `http_transport.py`. It
imports only the standard library, reads the two existing anonymous-pipe file
descriptor handoffs, and retains the host broker wire. The tool never imports the
Lunar host package or an upstream SDK to obtain that client.

`prepare_openevolve_sources(archive_bytes, *, broker_source_bytes,
transport_source_bytes)` returns immutable source records plus canonical
manifest bytes and a separately computed manifest SHA-256. It reads only its
fixed pinned assets and writes nothing. Source preparation is not an accepted
runtime observation or producer result; manifest claims remain explicitly false
for execution, builds, complete closure, production admission and publication.

The adapter consumes the existing two RSI input grants and makes at most one
brokered proposal. Its output `{"candidate_path":"candidate.py"}` is only the
existing candidate wrapper. The native host retains original grant custody,
launch/deadline binding, request accounting and publication authority. Native
closure/build, upstream diff semantics, sealed startup, original runtime
observation and export/handoff still require separate acceptance.
