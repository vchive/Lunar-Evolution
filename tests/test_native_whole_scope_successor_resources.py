"""Actual Linux FD ceilings for the explicit v4 native resource boundary.

These inert helpers use real descriptor tables, SCM_RIGHTS, openat, resource
limits and seccomp. They execute no candidate and project no root/account or
cgroup facts. Fork is a fixture acquisition shim, not a production fallback.
An independent fcntl scan counts actual open FDs without opening /proc itself.
"""
from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys

import pytest

from lunar_evolution.native_bootstrap import native_bootstrap_source_paths

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="actual Linux x86-64 descriptor/resource/seccomp mechanisms",
)

_HARNESS = r'''
#define _GNU_SOURCE
#include "native_whole_scope_successor_resources.h"
#include "native_whole_scope_successor_protocol.h"
#include <assert.h>
#include <linux/memfd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>

static size_t actual_count(void) {
    size_t count=0;
    /* All fixture sources are below 512. This acquires no observer FD and
     * counts the retained 197/198 outliers even after the low hard limit. */
    for(int fd=0;fd<512;fd++) {
        errno=0;
        if(fcntl(fd,F_GETFD)>=0)count++;
        else assert(errno==EBADF);
    }
    return count;
}
static int inert_file(void) {
    int fd=(int)syscall(SYS_memfd_create,"inert-resource-observation",MFD_CLOEXEC);
    assert(fd>2);
    assert(write(fd,"0123456789abcdef",16)==16);
    assert(lseek(fd,7,SEEK_SET)==7);
    return fd;
}
static void move_to(int *source,int destination) {
    assert(*source!=destination);
    assert(dup3(*source,destination,O_CLOEXEC)==destination);
    assert(!close(*source));*source=destination;
}
static size_t fill_to(size_t wanted,int *opened) {
    size_t used=0;
    while(actual_count()<wanted) {
        assert(used<96);
        opened[used]=open("/dev/null",O_RDONLY|O_CLOEXEC);
        assert(opened[used]>=0);used++;
    }
    assert(actual_count()==wanted);
    return used;
}
static void close_filled(int *opened,size_t used) {
    while(used)assert(!close(opened[--used]));
}
static void locked_limit(unsigned int low,const struct rlimit *original) {
    struct rlimit observed;
    assert(!getrlimit(RLIMIT_NOFILE,&observed));
    assert(observed.rlim_cur==low&&observed.rlim_max==low);
    assert(prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)==1);
    /* A same-value write is normally permitted even without privilege.
     * Its refusal proves the installed filter, rather than only hard-limit
     * privilege checks. Read-only prlimit remains usable. */
    errno=0;assert(setrlimit(RLIMIT_NOFILE,&observed)==-1&&errno==EPERM);
    struct rlimit raised={(rlim_t)low+1,(rlim_t)low+1};
    errno=0;assert(syscall(SYS_prlimit64,0,RLIMIT_NOFILE,&raised,NULL)==-1&&errno==EPERM);
    errno=0;assert(setrlimit(RLIMIT_NOFILE,original)==-1&&errno==EPERM);
    struct rlimit readback;
    assert(!syscall(SYS_prlimit64,0,RLIMIT_NOFILE,NULL,&readback));
    assert(readback.rlim_cur==low&&readback.rlim_max==low);
}
static int probe(void) {
    struct rlimit original;
    if(getrlimit(RLIMIT_NOFILE,&original)||original.rlim_cur<256)return 77;
    if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0))return 77;
    struct sock_filter allow[]={BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)};
    struct sock_fprog program={1,allow};
    if(syscall(SYS_seccomp,SECCOMP_SET_MODE_FILTER,SECCOMP_FILTER_FLAG_TSYNC,&program))return 77;
    return 0;
}
static void capacity(unsigned int fixed_count) {
    assert(fixed_count<=2);
    struct rlimit original;assert(!getrlimit(RLIMIT_NOFILE,&original));
    int ordinary=inert_file(),fixed_fds[2]={-1,-1};
    int *slots[]={&ordinary};w4_resource_fixed_t fixed[2];
    for(unsigned int i=0;i<fixed_count;i++) {
        fixed_fds[i]=inert_file();move_to(&fixed_fds[i],198-(int)i);
        fixed[i]=(w4_resource_fixed_t){&fixed_fds[i],198-(int)i};
    }
    assert(!w4_resource_enter(slots,1,fixed,fixed_count));
    unsigned int low=96-fixed_count;
    assert(ordinary>2&&(unsigned int)ordinary<low);
    assert(lseek(ordinary,0,SEEK_CUR)==7);
    for(unsigned int i=0;i<fixed_count;i++) {
        assert(fixed_fds[i]==198-(int)i);
        assert(lseek(fixed_fds[i],0,SEEK_CUR)==7);
        assert(fcntl(fixed_fds[i],F_GETFD)&FD_CLOEXEC);
    }
    locked_limit(low,&original);
    pid_t child=fork();assert(child>=0);
    if(!child) {
        locked_limit(low,&original);
        int child_fds[96];size_t child_used=fill_to(96,child_fds);
        errno=0;assert(open("/dev/null",O_RDONLY|O_CLOEXEC)==-1&&errno==EMFILE);
        assert(actual_count()==96);close_filled(child_fds,child_used);_exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&!WEXITSTATUS(status));
    assert(actual_count()==4+fixed_count);
    int opened[96];size_t used=fill_to(96,opened);
    errno=0;assert(open("/dev/null",O_RDONLY|O_CLOEXEC)==-1&&errno==EMFILE);
    errno=0;assert(dup(ordinary)==-1&&errno==EMFILE);
    int pair[2];errno=0;assert(socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,pair)==-1&&errno==EMFILE);
    assert(actual_count()==96);
    close_filled(opened,used);
    assert(actual_count()==4+fixed_count);
    assert(!close(ordinary));
    for(unsigned int i=0;i<fixed_count;i++)assert(!close(fixed_fds[i]));
    assert(actual_count()==3);
    locked_limit(low,&original);
}
static void normalization(const char *name) {
    int needs_move=strcmp(name,"bound-stable")!=0;
    int full=!strcmp(name,"bound-full-relocation");
    size_t count=needs_move&&!full?92:93;
    /* Acquire/move this original while the fixture still has spare capacity;
     * filling the final table itself never needs a transient 97th FD. */
    int original=inert_file();if(needs_move)move_to(&original,250);
    int fds[93],*slots[93];
    for(size_t i=0;i<count;i++) {
        fds[i]=i+1==count?original:open("/dev/null",O_RDONLY|O_CLOEXEC);
        assert(fds[i]>2);slots[i]=&fds[i];
    }
    assert(actual_count()==count+3);
    int result=w4_resource_enter(slots,count,NULL,0);
    if(full) {
        assert(result<0&&errno==EMFILE);
        assert(actual_count()==96);
        assert(fds[count-1]==250&&lseek(250,0,SEEK_CUR)==7);
        /* The caller must terminate this failed attempt. It neither resumes
         * resource acquisition nor tries to restore a partially lowered cap. */
        _exit(78);
    }
    assert(!result);
    assert(actual_count()==count+3);
    for(size_t i=0;i<count;i++)assert(fds[i]>2&&fds[i]<96);
    assert(lseek(fds[count-1],0,SEEK_CUR)==7);
    struct rlimit limit;assert(!getrlimit(RLIMIT_NOFILE,&limit));
    assert(limit.rlim_cur==96&&limit.rlim_max==96);
    for(size_t i=0;i<count;i++)assert(!close(fds[i]));
    assert(actual_count()==3);
}
static void failed_child(void) {
    struct rlimit original,after;assert(!getrlimit(RLIMIT_NOFILE,&original));
    size_t before=actual_count();pid_t child=fork();assert(child>=0);
    if(!child){normalization("bound-full-relocation");_exit(99);}
    int status;assert(waitpid(child,&status,0)==child);
    assert(WIFEXITED(status)&&WEXITSTATUS(status)==78);
    assert(actual_count()==before&&!getrlimit(RLIMIT_NOFILE,&after));
    assert(original.rlim_cur==after.rlim_cur&&original.rlim_max==after.rlim_max);
}
static void fixed_relocation(int full) {
    size_t count=full?92:91;
    int ordinary[92],*slots[92];
    for(size_t i=0;i<count;i++) {
        ordinary[i]=open("/dev/null",O_RDONLY|O_CLOEXEC);assert(ordinary[i]>2);slots[i]=&ordinary[i];
    }
    int source=inert_file();w4_resource_fixed_t fixed={&source,198};
    assert(actual_count()==(full?96u:95u));
    int result=w4_resource_enter(slots,count,&fixed,1);
    if(full) {
        assert(result<0&&errno==EMFILE&&actual_count()==96);
        assert(source!=198&&lseek(source,0,SEEK_CUR)==7);
        errno=0;assert(fcntl(198,F_GETFD)==-1&&errno==EBADF);
        return;
    }
    assert(!result&&source==198&&actual_count()==95);
    assert(lseek(source,0,SEEK_CUR)==7);
    struct rlimit limit;assert(!getrlimit(RLIMIT_NOFILE,&limit));
    assert(limit.rlim_cur==95&&limit.rlim_max==95);
}
static void invalid(const char *name) {
    int first=inert_file(),second=inert_file(),unlisted=inert_file();
    int *slots[]={&first,&second};w4_resource_fixed_t fixed={&second,198};
    struct rlimit before,after;assert(!getrlimit(RLIMIT_NOFILE,&before));
    if(!strcmp(name,"duplicate-input"))second=first;
    else if(!strcmp(name,"retained-fixed-target")){move_to(&first,198);}
    else if(!strcmp(name,"invalid-fixed-target"))fixed.target=196;
    else assert(0);
    size_t count=actual_count();
    int refused=!strcmp(name,"duplicate-input")?w4_resource_enter(slots,2,NULL,0):
        w4_resource_enter(slots,1,&fixed,1);
    assert(refused<0&&actual_count()==count);
    assert(fcntl(unlisted,F_GETFD)>=0&&lseek(first,0,SEEK_CUR)==7);
    assert(!getrlimit(RLIMIT_NOFILE,&after));
    assert(before.rlim_cur==after.rlim_cur&&before.rlim_max==after.rlim_max);
}
static void path_depth(const char *root,unsigned int room) {
    int directory=open(root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);assert(directory>2);
    int *slots[]={&directory};assert(!w4_resource_enter(slots,1,NULL,0));
    int fillers[96];size_t filled=fill_to(96-room,fillers);
    int chain[16],parent=directory;unsigned int opened=0;
    for(;;) {
        int next=openat(parent,"n",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        if(next<0){assert(errno==EMFILE);break;}
        assert(opened<16);chain[opened++]=next;parent=next;
        assert(actual_count()<=96);
    }
    assert(opened==room&&actual_count()==96);
    while(opened)assert(!close(chain[--opened]));
    assert(actual_count()==96-room);
    close_filled(fillers,filled);assert(!close(directory));assert(actual_count()==3);
}
static void binding(wq_binding_t *value,uint64_t deadline) {
    memset(value,0,sizeof(*value));value->deadline_ns=deadline;
    value->candidate_uid=value->candidate_gid=65534;
    char *digests[]={value->launch_sha256,value->intent_sha256,value->target_sha256,
        value->bootstrap_sha256,value->supervisor_sha256,value->profile_sha256};
    for(size_t i=0;i<6;i++)memset(digests[i],'a'+(int)i,64);
    assert(!wq_binding_valid(value));
}
static int receive(int channel,wq_message_t *message,int *rights,uint64_t deadline) {
    for(;;) {
        int result=w4_receive(channel,message,sizeof(*message),rights,2,deadline);
        if(!result||!(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))return result;
        struct pollfd observation={channel,POLLIN,0};int remaining=wq_remaining(deadline);
        assert(remaining>=0);
        assert(poll(&observation,1,remaining)>=0||errno==EINTR);
    }
}
static void incoming(unsigned int room) {
    int channels[2];assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,channels));
    int sources[]={inert_file(),inert_file()};move_to(&sources[0],198);move_to(&sources[1],197);
    uint64_t now;assert(!wq_now(&now));uint64_t deadline=now+5000000000ULL;
    wq_binding_t bound;binding(&bound,deadline);wq_message_t message;
    w4_init(&message,&bound,W4_R_CREATORS,1,2);
    pid_t sender=fork();assert(sender>=0);
    if(!sender) {
        int *slots[]={&channels[1]};w4_resource_fixed_t fixed[]={{&sources[0],198},{&sources[1],197}};
        assert(!w4_resource_enter(slots,1,fixed,2));
        assert(sources[0]==198&&sources[1]==197&&actual_count()==6);
        assert(!w4_send(channels[1],&message,sizeof(message),sources,2));_exit(0);
    }
    int *slots[]={&channels[0]};assert(!w4_resource_enter(slots,1,NULL,0));
    assert(actual_count()==4);
    int fillers[96];size_t filled=fill_to(96-room,fillers);
    int rights[2]={-1,-1};wq_message_t delivered;
    int result=receive(channels[0],&delivered,rights,deadline);
    if(room==2) {
        assert(!result&&actual_count()==96);
        assert(rights[0]>2&&rights[0]<96&&rights[1]>2&&rights[1]<96&&rights[0]!=rights[1]);
        assert(!memcmp(&message,&delivered,sizeof(message)));
        for(size_t i=0;i<2;i++) {
            assert(lseek(rights[i],0,SEEK_CUR)==7);
            assert(fcntl(rights[i],F_GETFD)&FD_CLOEXEC);
            char bytes[4];assert(pread(rights[i],bytes,sizeof(bytes),0)==4&&!memcmp(bytes,"0123",4));
            assert(!close(rights[i]));
        }
    } else {
        assert(result<0&&rights[0]==-1&&rights[1]==-1);
        /* A truncated actual SCM_RIGHTS packet must retire any partially
         * installed descriptions, without a second receive or retry. */
        assert(actual_count()==96-room);
    }
    int status;assert(waitpid(sender,&status,0)==sender&&WIFEXITED(status)&&!WEXITSTATUS(status));
    close_filled(fillers,filled);assert(!close(channels[0]));assert(actual_count()==3);
}
int main(int argc,char **argv) {
    assert(argc>=2);
    if(!strcmp(argv[1],"probe"))return probe();
    if(!strcmp(argv[1],"fixed-relocate-room"))fixed_relocation(0);
    else if(!strcmp(argv[1],"fixed-relocate-full"))fixed_relocation(1);
    else if(!strncmp(argv[1],"fixed-",6))capacity((unsigned int)atoi(argv[1]+6));
    else if(!strcmp(argv[1],"bound-full-relocation"))failed_child();
    else if(!strncmp(argv[1],"bound-",6))normalization(argv[1]);
    else if(!strncmp(argv[1],"incoming-",9))incoming((unsigned int)atoi(argv[1]+9));
    else if(!strncmp(argv[1],"path-",5)){assert(argc==3);path_depth(argv[2],(unsigned int)atoi(argv[1]+5));}
    else invalid(argv[1]);
    return 0;
}
'''

_BOOTSTRAP_HARNESS = r'''
#define main original_bootstrap_main
#include "native_bootstrap.c"
#undef main
#include <assert.h>
#include <linux/memfd.h>

static int original_sink(int target) {
    int original=(int)syscall(SYS_memfd_create,"inert-fixed-sink",MFD_CLOEXEC);
    assert(original>2&&original!=target);
    assert(write(original,"0123456789abcdef",16)==16&&lseek(original,7,SEEK_SET)==7);
    assert(dup3(original,target,O_CLOEXEC)==target&&!close(original));return target;
}
static void bootstrap_resources(unsigned int version) {
    int live[2],complete[2]={-1,-1};assert(!pipe2(live,O_CLOEXEC));
    if(version==4)assert(!pipe2(complete,O_CLOEXEC));
    pid_t child=fork();assert(child>=0);
    if(!child) {
        w4_bootstrap_fds_t f;memset(&f,0,sizeof(f));
        f.control=f.q_lifeline=-1;
        int *fields[]={&f.gate,&f.frame,&f.lifeline,&f.enrollment,&f.lifecycle,&f.profile};
        for(size_t i=0;i<6;i++) {
            *fields[i]=(int)syscall(SYS_memfd_create,"inert-B-original-input",MFD_CLOEXEC);
            assert(*fields[i]>2);
            assert(write(*fields[i],"0123456789abcdef",16)==16&&lseek(*fields[i],7,SEEK_SET)==7);
        }
        assert(dup3(f.frame,250,O_CLOEXEC)==250&&!close(f.frame));f.frame=250;
        control_t control;memset(&control,0,sizeof(control));control.version=version;
        control.target_fd=(int)syscall(SYS_memfd_create,"inert-B-target-input",MFD_CLOEXEC);
        control.bootstrap_fd=(int)syscall(SYS_memfd_create,"inert-B-bootstrap-input",MFD_CLOEXEC);
        assert(control.target_fd>2&&control.bootstrap_fd>2);
        uint64_t now;assert(!wq_now(&now));f.deadline=now+5000000000ULL;
        struct stat info;assert(!fstat(live[1],&info));
        control.sink_fd=live[1];control.sink_device=(uint64_t)info.st_dev;
        control.sink_inode=(uint64_t)info.st_ino;control.sink_deadline_ns=f.deadline;
        control.completion_fd=-1;
        if(version==4) {
            assert(!fstat(complete[1],&info));control.completion_fd=complete[1];
            control.completion_device=(uint64_t)info.st_dev;control.completion_inode=(uint64_t)info.st_ino;
            control.completion_deadline_ns=f.deadline;
        }
        int broker_r=-1,broker_w=-1;
        assert(!w4_b_resources(&f,&control,&broker_r,&broker_w));
        assert(broker_r==-1&&broker_w==-1);
        struct rlimit limit;assert(!getrlimit(RLIMIT_NOFILE,&limit));
        assert(limit.rlim_cur==96-(version==4?2u:1u)&&limit.rlim_max==limit.rlim_cur);
        for(size_t i=0;i<6;i++) {
            assert(*fields[i]>2&&(rlim_t)*fields[i]<limit.rlim_cur);
            assert(lseek(*fields[i],0,SEEK_CUR)==7);
        }
        assert(control.target_fd>2&&(rlim_t)control.target_fd<limit.rlim_cur);
        assert(control.bootstrap_fd>2&&(rlim_t)control.bootstrap_fd<limit.rlim_cur);
        assert(control.sink_fd==198&&fcntl(198,F_GETFD)&FD_CLOEXEC);
        if(version==4)assert(control.completion_fd==197&&fcntl(197,F_GETFD)&FD_CLOEXEC);
        assert(!w4_b_inherit_sinks(&control));
        assert(write(198,"S",1)==1);
        if(version==4)assert(write(197,"C",1)==1);
        _exit(0);
    }
    assert(!close(live[1]));if(version==4)assert(!close(complete[1]));
    char byte;assert(read(live[0],&byte,1)==1&&byte=='S');assert(!close(live[0]));
    if(version==4){assert(read(complete[0],&byte,1)==1&&byte=='C');assert(!close(complete[0]));}
    int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&!WEXITSTATUS(status));
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"resources-v3")){bootstrap_resources(3);return 0;}
    if(!strcmp(argv[1],"resources-v4")){bootstrap_resources(4);return 0;}
    control_t control;memset(&control,0,sizeof(control));
    control.version=!strcmp(argv[1],"v2")?2:!strcmp(argv[1],"v3")?3:4;
    control.sink_fd=control.completion_fd=-1;
    w4_resource_fixed_t fixed[2];size_t count=0;
    if(control.version>=3) {
        control.sink_fd=original_sink(198);
        fixed[count++]=(w4_resource_fixed_t){&control.sink_fd,198};
    }
    if(control.version==4) {
        control.completion_fd=original_sink(197);
        fixed[count++]=(w4_resource_fixed_t){&control.completion_fd,197};
    }
    assert(!w4_resource_enter(NULL,0,fixed,count));
    struct rlimit bound;assert(!getrlimit(RLIMIT_NOFILE,&bound));
    assert(bound.rlim_cur==96-count&&bound.rlim_max==96-count);
    if(!strcmp(argv[1],"misbound")) {
        control.completion_fd=198;
        assert(w4_b_inherit_sinks(&control)<0);
        assert(fcntl(198,F_GETFD)&FD_CLOEXEC);
        assert(fcntl(197,F_GETFD)&FD_CLOEXEC);
    } else if(!strcmp(argv[1],"closed")) {
        assert(!close(control.sink_fd));assert(w4_b_inherit_sinks(&control)<0);
        assert(fcntl(197,F_GETFD)&FD_CLOEXEC);
    } else {
        assert(!w4_b_inherit_sinks(&control));
        if(control.version>=3) {
            assert(!(fcntl(198,F_GETFD)&FD_CLOEXEC));assert(lseek(198,0,SEEK_CUR)==7);
        }
        if(control.version==4) {
            assert(!(fcntl(197,F_GETFD)&FD_CLOEXEC));assert(lseek(197,0,SEEK_CUR)==7);
        }
    }
    return 0;
}
'''


def _run(executable, *arguments):
    with subprocess.Popen(
        [str(executable), *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, start_new_session=True,
        env={"PATH": os.defpath, "LANG": "C"},
    ) as process:
        try:
            _stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stderr
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


@pytest.fixture(scope="module")
def resource_helpers(tmp_path_factory):
    compiler = shutil.which("gcc") or shutil.which("cc")
    if compiler is None:
        pytest.skip("actual Linux C compiler unavailable")
    root = tmp_path_factory.mktemp("successor-resources")
    include = native_bootstrap_source_paths()[0].parent
    helpers = []
    for name, harness in (("resources", _HARNESS), ("bootstrap-resources", _BOOTSTRAP_HARNESS)):
        source, executable = root / f"{name}.c", root / name
        source.write_text(harness, encoding="ascii")
        build = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wpedantic",
             "-Wno-unused-function", "-O2", "-I", str(include), str(source), "-o", str(executable)],
            check=False, capture_output=True, text=True, timeout=30,
            env={"PATH": os.defpath, "LANG": "C"},
        )
        assert build.returncode == 0, build.stderr
        helpers.append(executable)
    probe = subprocess.run(
        [str(helpers[0]), "probe"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        check=False, timeout=8, env={"PATH": os.defpath, "LANG": "C"},
    )
    if probe.returncode == 77:
        pytest.skip("actual inherited FD limit or no-new-privileges/TSYNC seccomp prerequisite unavailable")
    assert probe.returncode == 0, probe.stderr
    return helpers


@pytest.mark.parametrize("fixed_count", [0, 1, 2])
def test_actual_total_limit_counts_fixed_outliers_and_refuses_limit_restoration(resource_helpers, fixed_count):
    _run(resource_helpers[0], f"fixed-{fixed_count}")


@pytest.mark.parametrize("case", ["bound-stable", "bound-room-relocation", "bound-full-relocation",
                                  "fixed-relocate-room", "fixed-relocate-full"])
def test_exact_boundary_normalization_preserves_ofds_or_refuses_without_transient_extra(resource_helpers, case):
    _run(resource_helpers[0], case)


@pytest.mark.parametrize("case", ["duplicate-input", "retained-fixed-target", "invalid-fixed-target"])
def test_invalid_original_resource_inventory_refuses_before_closing_or_lowering(resource_helpers, case):
    _run(resource_helpers[0], case)


@pytest.mark.parametrize("room", [0, 1, 2])
def test_actual_high_sender_rights_respect_receiver_capacity_and_retire_truncated_rights(resource_helpers, room):
    _run(resource_helpers[0], f"incoming-{room}")


@pytest.mark.parametrize("room", [1, 8])
def test_actual_temporary_path_chain_descriptors_share_the_same_kernel_ceiling(resource_helpers, tmp_path, room):
    current = tmp_path
    for _ in range(12):
        current /= "n"
        current.mkdir(mode=0o700)
    _run(resource_helpers[0], f"path-{room}", str(tmp_path))


@pytest.mark.parametrize("case", ["v2", "v3", "v4", "misbound", "closed", "resources-v3", "resources-v4"])
def test_original_fixed_sink_inheritance_avoids_reduplication_above_hard_limit(resource_helpers, case):
    _run(resource_helpers[1], case)
