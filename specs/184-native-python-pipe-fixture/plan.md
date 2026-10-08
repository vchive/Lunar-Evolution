# Plan

Read-only gap report: /tmp/lunar-p1-native-runtime-gap-plan.md. A fresh Python pipe probe
passed but did not use native bootstrap; this feature supplies that missing composition.
171/177 remain filesystem preflight and confer no runtime load protection.

1. Prepare a finite explicit trusted installed CPython layout and source fixture. Use
   an inert static C launcher and originalv2 helper contracts; do not modify production
   admission, isolation or selectors. Do not automatically grant a user home or / tree.
2. Fixture runtime roots are explicit host layout choices (CI CPython prefix, necessary
   platform loader directories and source SDK root). Refuse unsupported layouts rather
   than silently run without native control. Darwin skips do not prove Linux loading.
3. Use a private parent pipe responder first. Actual Python -I -S -B imports the SDK,
   reports observed interpreter identity/flags, exchanges framed inert bytes and writes
   only a disposable work marker. Host endpoint/headers/secrets never enter target env.
4. Exercise valid and malformed response paths, isolated import flags/no pyc, and exact
   inherited endpoints. All fixture processes/FDs are retained and reaped/closed by their
   original parent. Preserve startup/compiler/first test failures.
5. Root owns specs/docs/HANDOFF/workflow; delegated author owns only test and optional
   dedicated helper. Independent boundary review and focused/Ruff/compileall/diff checks
   precede commit. Retain dedicated XML and exact-head three-version Linux CI before merge.

Start with private pipes, zero HTTP. Loopback host broker/budget composition can be added
only if useful after startup works; it is not required to invent a provider connection.
