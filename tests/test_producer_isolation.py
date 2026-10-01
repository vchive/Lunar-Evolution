from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target

from lunar_evolution.producer_isolation import (
    ProducerIsolationError,
    build_producer_isolation_policy,
)


def test_policy_is_canonical_and_self_digest_binds_paths(tmp_path: Path):
    source = tmp_path / "target"
    source.write_text("target", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    policy = build_producer_isolation_policy(read_paths=[source], write_dirs=[work])
    assert policy.platform == ("darwin-sandbox-v1" if sys.platform == "darwin" else "linux-landlock-seccomp-v1")
    assert policy.read_paths == (str(source),)
    assert policy.write_dirs == (str(work),)
    payload = {
        "platform": policy.platform,
        "profile": policy.profile,
        "read_paths": list(policy.read_paths),
        "write_dirs": list(policy.write_dirs),
    }
    assert policy.policy_sha256 == hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    policy.validate()


def test_policy_rejects_missing_or_relative_paths(tmp_path: Path):
    with pytest.raises(ProducerIsolationError) as missing:
        build_producer_isolation_policy(read_paths=[tmp_path / "missing"])
    assert missing.value.code == "producer_isolation_path_unavailable"
    with pytest.raises(ProducerIsolationError) as relative:
        build_producer_isolation_policy(read_paths=["relative-file"])
    assert relative.value.code == "producer_isolation_path_invalid"


def test_policy_rejects_unsupported_platform(tmp_path: Path):
    item = tmp_path / "target"
    item.write_text("target", encoding="utf-8")
    with pytest.raises(ProducerIsolationError) as exc:
        build_producer_isolation_policy(read_paths=[item], platform="windows-job-object-v1")
    assert exc.value.code == "producer_isolation_platform_unsupported"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux Landlock exact-file fixture")
def test_linux_exact_read_file_policy_keeps_network_and_outside_paths_denied(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    allowed = tmp_path / "allowed"
    allowed.write_text("local fixture")
    other = tmp_path / "other"
    other.write_text("denied")
    source = tmp_path / "policy.c"
    binary = tmp_path / "policy"
    source.write_text(
        '#define _GNU_SOURCE\n#include <fcntl.h>\n#include <sys/socket.h>\n#include <unistd.h>\n'
        '#include "native_producer_isolation.h"\n'
        'int main(int argc,char **argv){if(argc!=4)return 2;'
        'const char *r[]={argv[1]},*w[]={argv[3]};'
        'if(lunar_apply_isolation("linux-landlock-seccomp-v1",r,1,w,1)!=0)return 3;'
        'int fd=open(argv[1],O_RDONLY);if(fd<0)return 4;close(fd);'
        'fd=open(argv[1],O_WRONLY|O_TRUNC);if(fd>=0){close(fd);return 5;}'
        'fd=open(argv[2],O_RDONLY);if(fd>=0){close(fd);return 6;}'
        'fd=socket(AF_INET,SOCK_STREAM,0);if(fd>=0){close(fd);return 7;}'
        'if(chdir(argv[3])!=0)return 8;'
        'fd=open("ok",O_CREAT|O_WRONLY,0600);if(fd<0)return 9;return close(fd);}\n',
    )
    compile_native_target(source, binary, "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"))
    result = subprocess.run([str(binary), str(allowed), str(other), str(work)],
                            check=False, timeout=5, capture_output=True)
    assert result.returncode == 0
    assert allowed.read_text() == "local fixture"
    assert (work / "ok").is_file()


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin sandbox fixture")
def test_darwin_native_boundary_denies_network_and_outside_write(tmp_path: Path):
    clang = subprocess.run(["/usr/bin/clang", "--version"], capture_output=True, check=False)
    if clang.returncode:
        pytest.skip("clang unavailable")
    source = tmp_path / "target.c"
    binary = tmp_path / "target"
    source.write_text(
        '#include <fcntl.h>\n#include <stdio.h>\n#include <sys/socket.h>\n#include <netinet/in.h>\n#include <arpa/inet.h>\n#include <unistd.h>\n'
        '#include "native_producer_isolation.h"\n'
        'int main(int argc,char**argv){ if(argc!=3)return 2; const char *w[]={argv[2]}; '
        'if(lunar_apply_isolation(argv[1],0,0,w,1)!=0)return 3; '
        'int ok=open("' + str(tmp_path / "work" / "ok") + '",' + str(os.O_CREAT | os.O_WRONLY) + ',0600); '
        'if(ok<0)return 4; close(ok); '
        'int out=open("' + str(tmp_path / "outside") + '",' + str(os.O_CREAT | os.O_WRONLY) + ',0600); '
        'if(out>=0){close(out);return 5;} '
        'int s=socket(AF_INET,SOCK_STREAM,0); if(s<0)return 0; struct sockaddr_in a={0}; a.sin_family=AF_INET; a.sin_port=htons(9); inet_pton(AF_INET,"127.0.0.1",&a.sin_addr); if(connect(s,(struct sockaddr*)&a,sizeof(a))==0){close(s);return 6;} close(s); return 0;}\n',
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(
        ["/usr/bin/clang", str(source), "-I", str(Path(__file__).parents[1] / "src" / "lunar_evolution"), "-lsandbox", "-o", str(binary)],
        check=True,
        capture_output=True,
    )
    policy = build_producer_isolation_policy(read_paths=[binary], write_dirs=[work])
    result = subprocess.run([str(binary), policy.profile, str(work)], check=False)
    assert result.returncode == 0
    assert (work / "ok").is_file()
    assert not (tmp_path / "outside").exists()
