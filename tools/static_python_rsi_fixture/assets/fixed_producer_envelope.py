"""Explicit fixed-producer envelope delivery; no runtime or publication authority."""
# The composer appends this fragment to the independently pinned producer.
# ruff: noqa: F821

import fcntl as _lunar_completion_fcntl
import select as _lunar_completion_select


def _lunar_completion_fail(code):
    raise RuntimeError("fixed_producer_envelope_" + code)


def _lunar_completion_check(deadline_ns, request=None):
    if (type(deadline_ns) is not int or not 0 < deadline_ns < 2 ** 64
            or time.monotonic_ns() >= deadline_ns
            or (request is not None and time.time() >= request["budget"]["deadline_unix"])):
        _lunar_completion_fail("deadline")


def _lunar_completion_blob(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 256 * 1024:
        _lunar_completion_fail("material")
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _lunar_completion_emit(record, deadline_ns):
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if len(raw) > 8192:
        _lunar_completion_fail("size")
    waiter = _lunar_completion_select.poll()
    waiter.register(197, _lunar_completion_select.POLLOUT)
    offset = 0
    while offset < len(raw):
        _lunar_completion_check(deadline_ns)
        try:
            count = os.write(197, raw[offset:])
        except InterruptedError:
            continue
        except BlockingIOError:
            remaining = deadline_ns - time.monotonic_ns()
            if remaining <= 0:
                _lunar_completion_fail("deadline")
            waiter.poll(min(50, max(1, (remaining + 999999) // 1000000)))
            continue
        if count <= 0:
            _lunar_completion_fail("write")
        offset += count
    _lunar_completion_check(deadline_ns)


def _lunar_completion_write_at(directory, name, raw, deadline_ns, request):
    _lunar_completion_check(deadline_ns, request)
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o400, dir_fd=directory,
    )
    try:
        observed = os.fstat(descriptor)
        if (not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
                or stat.S_IMODE(observed.st_mode) != 0o400):
            _lunar_completion_fail("output")
        offset = 0
        while offset < len(raw):
            _lunar_completion_check(deadline_ns, request)
            count = os.write(descriptor, raw[offset:])
            if count <= 0:
                _lunar_completion_fail("output")
            offset += count
        _lunar_completion_check(deadline_ns, request)
        os.fsync(descriptor)
        _lunar_completion_check(deadline_ns, request)
        committed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    # Compare the persisted original file, not a hash supplied by the caller.
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory)
    try:
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if committed.st_size != len(raw):
            _lunar_completion_fail("output")
        observed = os.fstat(descriptor)
        chunks = []
        remaining = len(raw) + 1
        while remaining:
            _lunar_completion_check(deadline_ns, request)
            part = os.read(descriptor, min(65536, remaining))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (b"".join(chunks) != raw or any(
            getattr(committed, field) != getattr(value, field)
            for value in (observed, after, named) for field in fields
        )):
            _lunar_completion_fail("output_drift")
        _lunar_completion_check(deadline_ns, request)
    finally:
        os.close(descriptor)


def _lunar_envelope_main(manifest_sha256, deadline_monotonic_ns, run_id, producer_fingerprint):
    """Run the fixed proposal, reporting actual facts through inherited FD 197.

    The manifest/deadline/run/fingerprint come from the versioned native launcher.
    The original host must join the exact argv to its intent before gate release.
    Supplying matching strings here never authenticates a launch or its output.
    This callable is never selected by the original main/propose entrypoints.
    FD197 is borrowed; only the native launcher closes its writer after this call.
    The host must acquire the original private pipe and independently join its
    bytes; calling this function does not establish that host-side acquisition.
    """
    if (type(manifest_sha256) is not str or _HEX.fullmatch(manifest_sha256) is None
            or _LUNAR_COMPLETION_SOLVER not in {"openevolve", "shinka"}
            or type(run_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id) is None
            or type(producer_fingerprint) is not str
            or _HEX.fullmatch(producer_fingerprint) is None):
        _lunar_completion_fail("input")
    _lunar_completion_check(deadline_monotonic_ns)
    flags = _lunar_completion_fcntl.fcntl(197, _lunar_completion_fcntl.F_GETFL)
    if (flags & os.O_ACCMODE != os.O_WRONLY or not flags & os.O_NONBLOCK
            or not stat.S_ISFIFO(os.fstat(197).st_mode)):
        _lunar_completion_fail("pipe")
    # The original deadline is reported unchanged. A stricter local cap is
    # anchored once, before input work, and never renews that original budget.
    deadline_ns = min(deadline_monotonic_ns, time.monotonic_ns() + MAX_ATTEMPT_SECONDS * 1000000000)
    common = {
        "protocol": "lunar-fixed-producer-completion-v2",
        "profile": "fixed-producer-lifecycle-v2",
        "solver": _LUNAR_COMPLETION_SOLVER,
        "manifest_sha256": manifest_sha256,
        "target_pid": os.getpid(),
        "deadline_monotonic_ns": deadline_monotonic_ns,
    }
    _lunar_completion_emit(dict(common, seq=0, phase="begun"), deadline_ns)
    parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        inputs = os.open(".rsi-input", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
        try:
            _lunar_completion_check(deadline_ns)
            request_raw = _read_at(inputs, "request.json")
            _lunar_completion_check(deadline_ns)
            memory_raw = _read_at(inputs, "memory.json")
            _lunar_completion_check(deadline_ns)
        finally:
            os.close(inputs)
        request, memory = _inputs(request_raw, memory_raw)
        _lunar_completion_check(deadline_ns, request)
        body = _body(request, memory)
        _lunar_completion_check(deadline_ns, request)
        status, reply = brokered_producer_post("req-1", body, deadline_ns=deadline_ns)
        if type(status) is not int or status != 200:
            _lunar_completion_fail("http")
        _lunar_completion_check(deadline_ns, request)
        candidate = _candidate(request, reply)
        _lunar_completion_check(deadline_ns, request)
        if _LUNAR_COMPLETION_SOLVER == "openevolve":
            exported = _canonical({"candidate_path": "candidate.py"})
            paths = ("candidate.py", "result.json")
        else:
            exported = _snapshot(candidate)
            paths = ("gen_0/main.py", "programs.sqlite")
        _lunar_completion_check(deadline_ns, request)
        output = os.open("output", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
        try:
            if _LUNAR_COMPLETION_SOLVER == "shinka":
                os.mkdir("gen_0", 0o700, dir_fd=output)
                generation = os.open("gen_0", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     dir_fd=output)
                try:
                    _lunar_completion_write_at(generation, "main.py", candidate, deadline_ns, request)
                    os.fsync(generation)
                    _lunar_completion_check(deadline_ns, request)
                finally:
                    os.close(generation)
            else:
                _lunar_completion_write_at(output, "candidate.py", candidate, deadline_ns, request)
            _lunar_completion_write_at(output, paths[1], exported, deadline_ns, request)
            empty_evidence = {"present": False, "score_present": False, "payload_sha256": None}
            material_evidence = dict(empty_evidence)
            if _LUNAR_COMPLETION_SOLVER == "shinka":
                proposal = {"correct": False, "generation": 0, "program_id": "proposal"}
                material_evidence = {
                    "present": True, "score_present": False,
                    "payload_sha256": hashlib.sha256(_canonical(proposal)).hexdigest(),
                }
            envelope = _canonical({
                "schema_version": "1", "producer_id": _LUNAR_COMPLETION_SOLVER,
                "producer_fingerprint": producer_fingerprint, "producer_run_id": run_id,
                "status": "completed", "contract_sha256": request["contract_sha256"],
                "budget": {"requests": 1}, "materials": [{
                    "kind": "candidate_source", "path": paths[0], "lineage": [],
                    **_lunar_completion_blob(candidate), "external_evidence": material_evidence,
                }], "external_evidence": empty_evidence,
            })
            _lunar_completion_write_at(output, "producer-result.json", envelope, deadline_ns, request)
            os.fsync(output)
            _lunar_completion_check(deadline_ns, request)
        finally:
            os.close(output)
    finally:
        os.close(parent)
    record = dict(
        common, seq=1, phase="committed",
        request=_lunar_completion_blob(request_raw), memory=_lunar_completion_blob(memory_raw),
        broker={"request_id": "req-1", "request_count": 1,
                "request_body": _lunar_completion_blob(body), "status": status,
                "reply": _lunar_completion_blob(reply)},
        envelope=dict(path="producer-result.json", **_lunar_completion_blob(envelope)),
        artifacts=[dict(path=path, **_lunar_completion_blob(raw))
                   for path, raw in zip(paths, (candidate, exported))],
    )
    _lunar_completion_emit(record, deadline_ns)
