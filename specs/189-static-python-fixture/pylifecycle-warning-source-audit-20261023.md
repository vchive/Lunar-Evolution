# Feature 189 — bounded `pylifecycle.c` warning/site branch audit (2026-10-23)

`tests/fixtures/static_python_source/Python/pylifecycle.c.source` is the exact
106,247-byte `Python-3.13.12/Python/pylifecycle.c` member observed from the
release archive identified in `provenance.json` (archive SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`; member
SHA-256 `21296f86275077e4f19234a2c32691ee087fea961c28745770373a6c4ef70789`).
It is an inert supporting source fixture, not a module-profile member.

The pinned startup source imports Python-level `warnings` only when the
main-interpreter `warnoptions` value is a list with at least one item. It calls
`init_import_site()` only when `config->site_import` is true; that helper imports
`site`. The candidate metadata currently records `warnoptions=[]` and
`site_import=0`, and excludes both module names from the finite expected startup
inventory. The fixture test checks these exact source guards against those
metadata pins without claiming they are the values observed in a running
interpreter.

This source observation narrows the configured startup import branches but
does not establish launcher-to-runtime configuration binding, debug/presite
behavior, fixed-workload warning reachability, complete import closure,
configured build consumption, or sealed-target startup. Keep `warnings` and
`site` outside the finite inventory until the approved build and runtime
evidence resolves those gates; keep production admission and online publication
disabled.
