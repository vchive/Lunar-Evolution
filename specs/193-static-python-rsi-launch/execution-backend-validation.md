# Local validation — pinned build execution mechanism

`tests/test_static_python_rsi_execution_backend.py` contains 26 distinct cases.
They compile a small inert C test helper with the local test compiler, then
execute pinned snapshots of that helper through the new mechanism. The helper
copies tiny fixture bytes and exercises process failure/loop/output behavior;
it is not a CPython compiler, freezer, static image, solver or evaluator.

The cases cover successful real child-process graph execution and immutable
reports; explicit environment without inherited credentials/PATH; recipe pin,
preparation binding, graph, executable, path, strict-size and environment
preflight refusals; source pin/symlink failures; existing destination preservation;
nonzero exit and partial output; one shared deadline; cancellation; bounded pipe
output; missing outputs; prior-output and source-snapshot drift; expired deadline;
no numeric-PID signalling after successful reap; literal compiler `-c`; invalid
environment references; terminal report write failure; and huge-integer deadline
normalization; and interruption between chunks of a pinned input copy.

The local Python 3.11 run passed all 26 cases, zero failures/errors/skips, in
3.11 seconds using an explicit new temporary root:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/Users/liminghan/Documents/lunar_agent/src:/Users/liminghan/Documents/lunar_agent \
.venv/bin/python -m pytest tests/test_static_python_rsi_execution_backend.py \
  --basetemp /tmp/lunar-build-execution-1791890002 --disable-warnings
```

Ruff for both new Python files, compileall and `git diff --check` passed.
The final integrated source is rechecked by the parent task with retained XML;
repeated executions do not add distinct cases. This document does not claim
final-source remote CI or independent raw/source/tree acceptance.

Initial validation used a copied macOS `/bin/sh` fixture. Nine child-process cases
were killed by the host before script output (returncode -9, empty logs), while
12 preflight cases passed. That original failed attempt evidence remains in the
pytest-3230 directory. The subsequent inert C helper avoids that platform-specific
copied-system-executable behavior. A later fixture drift test initially refused
its own read-only snapshot write; its helper now explicitly exercises permission
change before mutation so the product's input drift gate can be verified.
Neither failure is treated as actual CPython build or startup evidence.

No actual source/toolchain acquisition, release signature verification, CPython
build/freezer/static link/image launch, OpenEvolve/Shinka campaign, remote/company
evaluator or production admission occurred. Actual command success cannot close
configured/static/ELF or installation/runtime acceptance.
