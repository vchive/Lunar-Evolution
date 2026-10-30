# Explicit sparse whole-deadline stack window

The original `1bb66721` mixed run exhausted its unchanged 600-second outer
deadline. Its own-stack v2 collector stopped honestly after 180 seconds; the
last 420 seconds have no stack observations. Known-PID CPU/read counters do not
identify those later functions or execution stages. That failed source and all
original results remain retained without retry.

The API-only diagnostic gains an explicit `profile="whole-deadline-v3"` option.
It requires exactly `seconds=600, interval=5`; it does not change the default
early-v2 profile or its 180-second limit and 0.25/0.5-second intervals. The new
start record identifies protocol `lunar-own-python-stack-diagnostic-v3` and
declares the actual bounds. At most 121 samples can be attempted. Normal fake
clock progression samples times 0 through 595 and stops at 600. Delays never
produce a catch-up burst. Thread/frame/slot, record/total-byte, privacy,
create-only and truthful terminal rules remain unchanged.

An external SIGTERM at the original case deadline may prevent a stop record;
missing terminal/completion remains unknown. Sampling is cooperative and cannot
prove continuous coverage, the final five seconds, exact CPU attribution or
that an unsampled operation was absent. No product check, timeout, retry or
acceptance gate changes. No stage counters, signals, process scanning, argv/env
or unapproved source text are introduced.

This tool does not launch tests. A later explicitly prepared successor runner
may opt into this profile during its one original-budget run. The old v2
runner/validator must not silently accept v3 as v2, and no failed source is
rerun to seek a pass. Focused tests use fake clocks/frames/threads only; adding
this collector does not resolve P0 or authorize merging.
