"""Linux input permission APIs remain denied while output creation works."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target

import lunar_evolution.native_bootstrap as bootstrap

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Landlock/seccomp fixture")


@pytest.mark.parametrize("bound_inputs", [False, True])
def test_linux_bound_input_permission_gate_preserves_output_io(tmp_path, bound_inputs):
    work = tmp_path / "work"
    work.mkdir()
    material = tmp_path / "input.json"
    material.write_bytes(b"immutable-input")
    material.chmod(0o400)
    header = Path(bootstrap.__file__).with_name("native_producer_isolation.h")
    source = tmp_path / "metadata.c"
    source.write_text(
        '#define _GNU_SOURCE\n#include <errno.h>\n#include <fcntl.h>\n#include <stdio.h>\n'
        '#include <sys/stat.h>\n#include <sys/syscall.h>\n#include <unistd.h>\n'
        f'#include "{header}"\n'
        'static int expected(int result,int bound){return bound?result==-1&&errno==EPERM:result==0;}\n'
        'int main(int argc,char **argv){if(argc!=4)return 1;int bound=argv[3][0]==\'1\';'
        'const char *reads[]={argv[1]};const char *writes[]={argv[2]};'
        'int result=lunar_apply_isolation("local-fixture",reads,bound?1:0,writes,1);'
        'if(result){fprintf(stderr,"isolation:%d",result);return 2;}'
        'if(chdir(argv[2])||mkdir("nested",0700))return 3;'
        'int output=open("nested/output",O_CREAT|O_WRONLY,0600);'
        'if(output<0||write(output,"output",6)!=6||close(output))return 4;'
        'const char *path=bound?argv[1]:"nested/output";'
        'int fd=open(path,O_RDONLY);if(fd<0)return 5;'
        'errno=0;if(!expected(chmod(path,0600),bound))return 6;'
        'errno=0;if(!expected(fchmod(fd,0600),bound))return 7;'
        'errno=0;if(!expected(syscall(__NR_fchmodat,AT_FDCWD,path,0600),bound))return 8;'
        'errno=0;result=syscall(LUNAR_NR_FCHMODAT2,AT_FDCWD,path,0600,0);'
        'if(!expected(result,bound)&&!(result==-1&&errno==ENOSYS&&!bound))return 9;'
        'if(bound){char input[32];if(read(fd,input,sizeof(input))!=15)return 10;'
        'errno=0;if(chmod("nested/output",0644)!=-1||errno!=EPERM)return 11;}'
        'if(close(fd))return 12;return 0;}\n'
    )
    target = tmp_path / "metadata"
    compile_native_target(source, target)
    completed = subprocess.run(
        [str(target), str(material), str(work), "1" if bound_inputs else "0"],
        capture_output=True, timeout=5, check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    assert (work / "nested" / "output").read_bytes() == b"output"
    assert stat.S_IMODE((work / "nested" / "output").stat().st_mode) == 0o600
    assert stat.S_IMODE((work / "nested").stat().st_mode) == 0o700
    assert material.read_bytes() == b"immutable-input"
    assert stat.S_IMODE(material.stat().st_mode) == 0o400
