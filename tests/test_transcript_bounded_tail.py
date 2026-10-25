"""Check actual transcript read sizes, including oversized and growing files."""

import json
import os
import stat
from pathlib import Path

import pytest

import lunar_evolution.transcript as module
from lunar_evolution.transcript import SessionTranscript


@pytest.mark.parametrize("confined", [False, True])
@pytest.mark.parametrize("grow", [False, True])
def test_loader_reads_only_a_bounded_tail_and_keeps_valid_recent_jsonl(
    tmp_path, monkeypatch, confined, grow,
):
    path = tmp_path / "history.jsonl"
    expected = [{"role": "user", "content": "tail-尾"}, {"role": "assistant", "content": "done"}]
    with path.open("wb") as stream:
        stream.seek(64 * 1024 * 1024)
        stream.write(b"invalid-leading-part" * 200 + b"\nnot-json\n")
        stream.write("".join(json.dumps(value) + "\n" for value in expected).encode())
    original_size = path.stat().st_size
    transcript = SessionTranscript(
        path, max_messages=3, max_message_bytes=256, max_total_bytes=1024,
        confined_workspace=tmp_path if confined else None,
    )
    reads, seeks = [], []
    original_open, original_fdopen = Path.open, os.fdopen

    class ObservedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def seek(self, offset):
            seeks.append(offset)
            return self.stream.seek(offset)

        def read(self, size=-1):
            reads.append(size)
            assert 0 <= size <= 2048
            if grow:
                with original_open(path, "ab") as writer:
                    writer.write(b"GROWTH-IGNORED" * 1000)
            return self.stream.read(size)

    if confined:
        monkeypatch.setattr(module.os, "fdopen", lambda *args, **kwargs: ObservedStream(original_fdopen(*args, **kwargs)))
    else:
        def observed_open(supplied, *args, **kwargs):
            stream = original_open(supplied, *args, **kwargs)
            return ObservedStream(stream) if supplied == path else stream

        monkeypatch.setattr(Path, "open", observed_open)
    assert transcript.load() == expected
    assert reads == [2048] and seeks == [original_size - 2048]


def test_fresh_history_is_exclusive_confined_and_private(tmp_path):
    path = tmp_path / "sessions/history.jsonl"
    transcript = SessionTranscript(path, confined_workspace=tmp_path)
    transcript.create_fresh()
    assert path.read_bytes() == b"" and stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        transcript.create_fresh()
    assert path.read_bytes() == b""
    with pytest.raises(ValueError, match="confined workspace"):
        SessionTranscript(tmp_path / "unconfined.jsonl").create_fresh()


@pytest.mark.parametrize("confined", [False, True])
def test_bounded_loader_keeps_missing_and_small_file_semantics(tmp_path, confined):
    path = tmp_path / "history.jsonl"
    transcript = SessionTranscript(path, confined_workspace=tmp_path if confined else None)
    assert transcript.load() == []
    path.write_text('invalid\n{"role":"assistant","content":"done"}\n')
    assert transcript.load() == [{"role": "assistant", "content": "done"}]
