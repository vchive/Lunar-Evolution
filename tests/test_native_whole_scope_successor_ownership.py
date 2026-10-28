"""V4 original descriptions, strict history and actual Linux wait ownership.

Python custody fixtures project only root metadata/ancestor installation and
use synthetic v4 context/terminal observations. They do not run Q/S/G/R or a
candidate. The small C harness consumes the actual production wait/check
helpers with fork-created inert children; fork replaces clone3 acquisition in
that fixture only. The R cases run its actual create/fsync/creator/ACK path with
root metadata projected. No cgroup, credentials or deployed lifecycle is proved.
"""
from __future__ import annotations

import array
import copy
import errno
import json
import os
import pickle
import platform
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from test_external_worker_whole_scope_vault import _project_modules

from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_successor as wire
from lunar_evolution import native_whole_scope_successor_custody as custody
from lunar_evolution.native_whole_scope_build import native_whole_scope_source_paths

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux statx/xattr/pidfd mechanisms")


@pytest.fixture
def created(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("actual Linux creator-description and mount mechanisms")
    projected, ancestors = set(), set()
    for path in (tmp_path, *tmp_path.parents):
        info = path.stat()
        ancestors.add((info.st_dev, info.st_ino))
    proxy = _project_modules(monkeypatch, projected, ancestors)
    monkeypatch.setattr(custody, "os", proxy)
    execution = tmp_path / "execution"
    attempt = execution / ("lunar-" + "a" * 64)
    execution.mkdir(mode=0o700)
    attempt.mkdir(mode=0o700)
    for path in (execution, attempt):
        info = path.stat()
        projected.add((info.st_dev, info.st_ino))
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    owner._profile = {"paths": ("/unused", str(execution)), "uid": 65534, "gid": 65534,
                      "groups": (), "bootstrap_sha256": "b" * 64, "supervisor_sha256": "c" * 64}
    owner._profile_sha256 = "d" * 64
    owner._deadline = time.monotonic_ns() + 20_000_000_000
    owner._preparation_key = "a" * 64
    owner._successor_session = wire._SuccessorSession(wire._SESSION_TOKEN, owner)
    parent = owner._own(os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
    owner._published = (parent,)
    owner._publication_pins = ((whole._kernel_identity(parent), None),)
    monkeypatch.setattr(owner, "_check_published_grants", lambda: None)
    monkeypatch.setattr(owner, "_check_installation", lambda: None)
    child = owner.acquire_custody_owner(profile=wire.PROFILE_NAME)
    child._borrow_for_start()
    owner._binding = owner._core(launch="1" * 64, intent="2" * 64, target="3" * 64,
                                 deadline_ns=owner.deadline_ns)
    owner._scope = whole._IDENTITY.pack(31, 41, 51, 0, 0, stat.S_IFDIR | 0o700, 0)
    owner._target_pid = 123
    publications = b"".join(whole._PUBLICATION.pack(71, 81 + i, 12, 15, 16, b"e" * 64 + b"\0")
                            for i in range(3))
    registration = wire.context(owner._binding, owner._scope, owner._target_pid, publications, 79, 1)
    owner._successor_session.registration = registration
    path = attempt / custody._DIRECTORY
    files = []
    try:
        for name, raw in zip(custody._NAMES, (registration, b""), strict=True):
            fd = os.open(path / name, os.O_RDWR | os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            files.append(fd)
            info = os.fstat(fd)
            projected.add((info.st_dev, info.st_ino))
            assert os.write(fd, raw) == len(raw)
            os.fsync(fd)
        os.fsync(child._directory)
        yield SimpleNamespace(owner=owner, child=child, path=path, files=tuple(files),
                              publications=publications, registration=registration, projected=projected)
    finally:
        owner.close()
        for fd in reversed(files):
            os.close(fd)


def _adopt(g, descriptors=None):
    g.child._adopt_creator_descriptions(whole._TOKEN, g.owner,
                                      g.files if descriptors is None else descriptors, g.publications)


def _commit(g, *, normal=True):
    # Finite synthetic observations solely for codec/consumer validation. These
    # timestamps and facts are not evidence that native operations occurred.
    deadline = g.owner.deadline_ns
    source = wire.context(g.owner._binding, g.owner._scope, 123, g.publications, 91, 7)
    source += struct.pack("<4IQ", 1 if normal else 2, 0 if normal else 1,
                          10 if normal else 1, 0, deadline - 10)
    context = wire.context(g.owner._binding, g.owner._scope, 123, g.publications,
                           98 if normal else 99, 2)
    return context + struct.pack("<4IQ4I", 1 if normal else 2, 0 if normal else 1, 1,
                                 58 if normal else 1, deadline - 5,
                                 1 if normal else 0, 0, 1 if normal else 0, 0) + source


def _write_terminal(g, raw):
    assert os.pwrite(g.files[1], raw, 0) == len(raw)
    os.fsync(g.files[1])


def _unknown_authority(report):
    assert report["cleanup_status"] == "unknown"
    for name in ("durable_acknowledgement_verified", "native_success", "whole_group_cleanup_verified",
                 "original_quiescence_observed", "production_admission", "publication_authority",
                 "online_publication"):
        assert report[name] is False


def test_v4_scm_creator_adoption_keeps_original_ofds_and_uses_only_pread(created, monkeypatch):
    g = created
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
    incoming = ()
    try:
        packet = wire.context(g.owner._binding, g.owner._scope, 123, g.publications, 81, 2, 2)
        assert sender.sendmsg([packet], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", g.files))]) == len(packet)
        raw, ancillary, flags, _ = receiver.recvmsg(wire.CONTEXT_SIZE + 1,
            socket.CMSG_SPACE(2 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
        assert raw == packet and not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
        rights = array.array("i")
        rights.frombytes(ancillary[0][2])
        incoming = tuple(rights)
        _adopt(g, incoming)
    finally:
        for fd in incoming:
            os.close(fd)
        sender.close()
        receiver.close()
    held = g.child._creators
    assert len(held) == 2 and not set(held) & set(g.files) and not set(held) & set(incoming)
    assert os.lseek(g.files[0], 7, os.SEEK_SET) == 7
    assert os.lseek(held[0], 0, os.SEEK_CUR) == 7
    with monkeypatch.context() as readonly:
        for name in ("open", "read", "lseek", "write", "ftruncate"):
            readonly.setattr(custody.os, name, lambda *_a, **_k: pytest.fail("original description reopened or mutated"))
        g.child._check_registration()
    assert os.lseek(g.files[0], 0, os.SEEK_CUR) == 7
    assert g.child.reference.canonical_bytes
    for fd in incoming:
        with pytest.raises(OSError) as raised:
            os.fstat(fd)
        assert raised.value.errno == errno.EBADF


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy, pickle.dumps])
def test_v4_live_owner_cannot_be_copied_or_serialized(created, clone):
    with pytest.raises(custody.NativeWholeScopeSuccessorCustodyError, match="owner_invalid"):
        clone(created.child)


@pytest.mark.parametrize("shape", ["none", "one", "alias", "reverse", "readonly", "bool"])
def test_v4_creator_shape_failure_consumes_attempt_and_retires_only_owned_duplicates(created, shape):
    g = created
    opened = None
    if shape == "readonly":
        opened = os.open(g.path / custody._NAMES[0], os.O_RDONLY | os.O_CLOEXEC)
    descriptors = {"none": (), "one": g.files[:1], "alias": (g.files[0], g.files[0]),
                   "reverse": tuple(reversed(g.files)), "readonly": (opened, g.files[1]),
                   "bool": (True, g.files[1])}[shape]
    try:
        with pytest.raises(custody.NativeWholeScopeSuccessorCustodyError):
            _adopt(g, descriptors)
        assert g.child._creators == () and g.child._creator_delivery_started
        with pytest.raises(custody.NativeWholeScopeSuccessorCustodyError, match="owner_invalid"):
            _adopt(g)
        for fd in g.files:
            os.fstat(fd)
    finally:
        if opened is not None:
            os.close(opened)


@pytest.mark.parametrize("normal", [True, False])
def test_v4_historical_terminal_after_original_close_never_recovers_ack_or_wait_authority(created, normal):
    g = created
    _adopt(g)
    reference = g.child.reference
    raw = _commit(g, normal=normal)
    _write_terminal(g, raw)
    if normal:
        with pytest.raises(custody.NativeWholeScopeSuccessorCustodyError, match="terminal_unknown"):
            g.child._check_registration(terminal=True)
        g.child._check_registration(terminal=True, commit=raw)
    else:
        with pytest.raises(custody.NativeWholeScopeSuccessorCustodyError, match="terminal_unknown"):
            g.child._check_registration(terminal=True, commit=raw)
    g.owner._deadline = time.monotonic_ns() - 1
    g.child.close()
    report = custody.inspect_native_whole_scope_successor_custody(reference)
    assert report["state"] == ("terminal_record_observed" if normal else "abnormal_record_observed")
    assert report["recorded_supervisor_wait"] is normal and report["recorded_guardian_wait"] is normal
    assert report["recorded_bootstrap_exit"] is False
    assert report["recorded_reason"] == ("normal" if normal else "controller_lost")
    _unknown_authority(report)


@pytest.mark.parametrize("fault", ["legacy-profile", "legacy-magic", "registration-write", "terminal-write-truncate",
                                    "registration-replace", "terminal-replace", "extra-name", "partial-terminal"])
def test_v4_reference_requires_exact_original_profile_files_and_stable_empty_pin(created, fault):
    g = created
    _adopt(g)
    reference = g.child.reference
    if fault in {"legacy-profile", "legacy-magic"}:
        value = json.loads(reference.canonical_bytes)
        if fault == "legacy-profile":
            value["profile"] = "linux-whole-scope-private-custody-v3"
        else:
            raw = bytearray.fromhex(value["registration"])
            struct.pack_into("<II", raw, 0, 0x3151574C, 3)
            value["registration"] = raw.hex()
        reference = custody.NativeWholeScopeSuccessorCustodyReference(custody._json(value))
    elif fault == "registration-write":
        assert os.pwrite(g.files[0], g.registration, 0) == len(g.registration)
    elif fault == "terminal-write-truncate":
        assert os.pwrite(g.files[1], b"x", 0) == 1
        os.ftruncate(g.files[1], 0)
    elif fault in {"registration-replace", "terminal-replace"}:
        index = 0 if fault.startswith("registration") else 1
        original = g.path / custody._NAMES[index]
        replacement = g.path / "replacement"
        replacement.write_bytes(original.read_bytes())
        replacement.chmod(0o600)
        info = replacement.stat()
        g.projected.add((info.st_dev, info.st_ino))
        replacement.replace(original)
    elif fault == "extra-name":
        (g.path / "extra").write_bytes(b"")
    else:
        _write_terminal(g, _commit(g)[:101])
    report = custody.inspect_native_whole_scope_successor_custody(reference)
    assert report["state"] == "unknown"
    _unknown_authority(report)


@pytest.mark.parametrize("raw", [b"", b"{}", b"null", b"[]", b"x" * 32769])
def test_v4_malformed_reference_refuses_before_any_filesystem_lookup(raw, monkeypatch):
    monkeypatch.setattr(custody, "_open_chain", lambda *_a: pytest.fail("malformed reference opened files"))
    report = custody.inspect_native_whole_scope_successor_custody(
        custody.NativeWholeScopeSuccessorCustodyReference(raw))
    assert report["state"] == "unknown"
    _unknown_authority(report)


@LINUX
@pytest.mark.parametrize("outcome", ["normal", "abnormal", "signal", "externally-reaped"])
def test_python_session_consumes_only_its_original_q_pidfd_wait(tmp_path, outcome):
    if not hasattr(os, "pidfd_open") or not hasattr(os, "P_PIDFD"):
        pytest.skip("actual pidfd wait unavailable")
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    owner._profile = {"paths": (str(tmp_path),)}
    owner._deadline = time.monotonic_ns() + 5_000_000_000
    session = wire._SuccessorSession(wire._SESSION_TOKEN, owner)
    owner._successor_session = session
    code = 78 if outcome == "abnormal" else 0
    script = "import os,signal; os.kill(os.getpid(),signal.SIGTERM)" if outcome == "signal" else f"raise SystemExit({code})"
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={"PATH": os.defpath, "LANG": "C"})
    session._q = owner._supervisor = process
    session._q_pidfd = owner._own(os.pidfd_open(process.pid, 0))
    try:
        if outcome == "externally-reaped":
            waited, status = os.waitpid(process.pid, 0)
            assert waited == process.pid and os.waitstatus_to_exitcode(status) == 0
            with pytest.raises(whole.NativeWholeScopeError, match="original_wait_unavailable"):
                session._wait_original_q()
            assert not session._q_waited and process.returncode is None
            # Test cleanup bookkeeping after the explicit refusal is not an
            # original-session wait observation or an accepted completion.
            process.returncode = 0
        else:
            expected = -signal.SIGTERM if outcome == "signal" else code
            assert session._wait_original_q() == expected
            assert session._q_waited and process.returncode == expected
            with pytest.raises(ChildProcessError):
                os.waitid(os.P_PIDFD, session._q_pidfd, os.WEXITED | os.WNOHANG)
            with pytest.raises(whole.NativeWholeScopeError, match="original_wait_unavailable"):
                session._wait_original_q()
    finally:
        owner.close()


_WAIT_HARNESS = r'''
#define _GNU_SOURCE
#include <sys/stat.h>
#include <sys/socket.h>
#include <unistd.h>
static const char *test_case;
static int projected_fstat(int fd, struct stat *info);
static int projected_fstatat(int fd, const char *name, struct stat *info, int flags);
static int injected_fsync(int fd);
static ssize_t injected_recvmsg(int fd, struct msghdr *message, int flags);
#define fstat projected_fstat
#define fstatat projected_fstatat
#define fsync injected_fsync
#define recvmsg injected_recvmsg
#define main installed_scope_main
#include "native_whole_scope.c"
#undef main
#include "native_whole_scope_successor.h"
#undef recvmsg
#undef fsync
#undef fstatat
#undef fstat
#include <assert.h>

static int projected_fstat(int fd, struct stat *info) {
    int result=fstat(fd,info);if(!result)info->st_uid=info->st_gid=0;return result;
}
static int projected_fstatat(int fd,const char *name,struct stat *info,int flags) {
    int result=fstatat(fd,name,info,flags);if(!result)info->st_uid=info->st_gid=0;return result;
}
static int injected_fsync(int fd) {
    struct stat info; assert(!fstat(fd,&info));
    if(!strcmp(test_case,"receiver-terminal-fsync") && S_ISREG(info.st_mode) &&
        info.st_size==(off_t)sizeof(w4_commit_t)) {errno=EIO;return -1;}
    return fsync(fd);
}
static ssize_t injected_recvmsg(int fd,struct msghdr *message,int flags) {
    ssize_t result=recvmsg(fd,message,flags);
    if(result==(ssize_t)sizeof(w4_commit_t) && message->msg_iovlen &&
        message->msg_iov[0].iov_len>=sizeof(w4_commit_t)) {
        w4_commit_t ack;memcpy(&ack,message->msg_iov[0].iov_base,sizeof(ack));
        if(ack.context.operation==W4_ACK) {
            if(!strcmp(test_case,"receiver-lost-ack")){errno=ECONNRESET;return -1;}
            if(!strcmp(test_case,"receiver-corrupt-ack")) {
                ack.proposal.observed_ns^=1;
                memcpy(message->msg_iov[0].iov_base,&ack,sizeof(ack));
            }
        }
    }
    return result;
}
static void pair(int fds[2]) { assert(!pipe2(fds, O_CLOEXEC)); }
static void binding(wq_binding_t *b, uint64_t deadline) {
    memset(b, 0, sizeof(*b)); b->deadline_ns = deadline;
    b->candidate_uid = b->candidate_gid = 65534;
    char *hashes[] = {b->launch_sha256,b->intent_sha256,b->target_sha256,
                     b->bootstrap_sha256,b->supervisor_sha256,b->profile_sha256};
    for (size_t i=0;i<6;i++) memset(hashes[i], 'a'+(int)i, 64);
    assert(!wq_binding_valid(b));
}
static void ownership(void) {
    int channel[2]; assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,channel));
    uint64_t now; assert(!wq_now(&now)); uint64_t deadline = now+5000000000ULL;
    pid_t qp = fork(); assert(qp>=0);
    if (!qp) {
        close(channel[0]); w4_q_t q; memset(&q,0,sizeof(q));
        q.profile=q.delegation=q.controller=q.enrollment=q.lifecycle=q.lifeline=q.image=-1;
        q.custody=q.bootstrap=q.target=q.scope.leaf=q.scope.delegation=-1;
        for(size_t i=0;i<8;i++)q.scope.files[i]=-1;
        for(size_t i=0;i<3;i++)q.publications[i]=-1;
        q.creators[0]=q.creators[1]=-1;
        int *unused[]={q.qs,q.qg,q.qr,q.sr,q.gr,q.qlife,q.slife,q.glife};
        for(size_t i=0;i<8;i++)unused[i][0]=unused[i][1]=-1;
        q.deadline=deadline; q.abnormal=1;
        for(size_t i=0;i<3;i++) q.children[i].pidfd=-1;
        int commands[3][2]; pid_t pids[3]; int observers[3]; pid_t actual_q=getpid();
        for(size_t i=0;i<3;i++) {
            pair(commands[i]); pids[i]=fork(); assert(pids[i]>=0);
            if(!pids[i]) {
                int keep[]={commands[i][0]}; assert(!w4_keep(keep,1)); char byte;
                assert(getppid()==actual_q);
                assert(read(commands[i][0],&byte,1)==1 && byte=='X');
                _exit((int)i);
            }
            close(commands[i][0]); q.children[i].pid=pids[i];
            q.children[i].pidfd=(int)syscall(SYS_pidfd_open,pids[i],0);
            assert(q.children[i].pidfd>2); observers[i]=q.children[i].pidfd;
        }
        assert(send(channel[1],pids,sizeof(pids),0)==(ssize_t)sizeof(pids));
        wq_binding_t b; binding(&b,deadline); wq_message_t m;
        w4_init(&m,&b,W4_B_PEERS,2,3);
        assert(!w4_send(channel[1],&m,sizeof(m),observers,3));
        char byte; assert(recv(channel[1],&byte,1,0)==1 && byte=='X');
        for(size_t i=0;i<3;i++) assert(write(commands[i][1],"X",1)==1);
        for(int i=0;i<3;i++) {
            assert(!w4_q_wait(&q,i));
            assert(q.children[i].reaped && q.waited[i].si_pid==pids[i]);
            assert(q.waited[i].si_code==CLD_EXITED && q.waited[i].si_status==i);
            siginfo_t again={0}; errno=0;
            assert(waitid(P_PIDFD,(id_t)observers[i],&again,WEXITED|WNOHANG)==-1 && errno==ECHILD);
            assert(w4_q_wait(&q,i)); close(observers[i]); close(commands[i][1]);
        }
        assert(send(channel[1],"D",1,0)==1); _exit(0);
    }
    close(channel[1]); pid_t children[3];
    assert(recv(channel[0],children,sizeof(children),0)==(ssize_t)sizeof(children));
    wq_message_t m; int rights[3]={-1,-1,-1};
    assert(!w4_transfer(channel[0],&m,sizeof(m),rights,3,0,deadline,NULL,NULL));
    for(size_t i=0;i<3;i++) {
        char path[80],line[256]; snprintf(path,sizeof(path),"/proc/%ld/status",(long)children[i]);
        FILE *f=fopen(path,"r"); assert(f); int observed=0;
        while(fgets(line,sizeof(line),f)) { long pp;
            if(sscanf(line,"PPid: %ld",&pp)==1) { assert(pp==qp); observed=1; break; }
        }
        assert(!fclose(f) && observed); siginfo_t info={0}; errno=0;
        assert(waitid(P_PIDFD,(id_t)rights[i],&info,WEXITED|WNOHANG)==-1 && errno==ECHILD);
    }
    assert(send(channel[0],"X",1,0)==1); char byte;
    assert(recv(channel[0],&byte,1,0)==1 && byte=='D');
    for(size_t i=0;i<3;i++) { siginfo_t info={0}; errno=0;
        assert(waitid(P_PIDFD,(id_t)rights[i],&info,WEXITED|WNOHANG)==-1 && errno==ECHILD); close(rights[i]); }
    int status; assert(waitpid(qp,&status,0)==qp && WIFEXITED(status) && !WEXITSTATUS(status)); close(channel[0]);
}
static void draining(const char *fault) {
    int c[2],q[2],r[2],g[2]; pair(c);pair(q);pair(r);pair(g);
    /* Production lifeline observation is nonblocking. Keep READY and inert
     * child waits blocking, but prepare the actual C/Q readers identically. */
    assert(!pipe_reader(c[0])&&!pipe_reader(q[0]));
    int ready[2];pair(ready);
    pid_t rp=fork(); assert(rp>=0);
    if(!rp) {
        int keep[]={r[0],ready[1]};assert(!w4_keep(keep,2));
        assert(write(ready[1],"R",1)==1);assert(!close(ready[1]));
        char b;assert(read(r[0],&b,1)==0);_exit(0);
    }
    close(ready[1]);char acknowledged;
    assert(read(ready[0],&acknowledged,1)==1&&acknowledged=='R');close(ready[0]);
    pair(ready);
    pid_t gp=fork(); assert(gp>=0);
    if(!gp) {
        int keep[]={g[0],ready[1]};assert(!w4_keep(keep,2));
        assert(write(ready[1],"R",1)==1);assert(!close(ready[1]));
        char b;assert(read(g[0],&b,1)==0);_exit(0);
    }
    close(ready[1]);
    assert(read(ready[0],&acknowledged,1)==1&&acknowledged=='R');close(ready[0]);
    /* Both children have retired every unlisted lifeline writer before the
     * parent injects C/Q EOF; their fork-time fd inventories cannot mask it. */
    int rfd=(int)syscall(SYS_pidfd_open,rp,0),gfd=(int)syscall(SYS_pidfd_open,gp,0); assert(rfd>2&&gfd>2);
    uint64_t now;assert(!wq_now(&now)); w4_role_t role;memset(&role,0,sizeof(role));
    role.deadline=now+5000000000ULL;role.cutoff=now-1;role.normal_draining=1;
    role.source=W4_SOURCE_S;role.c_life=c[0];role.q_life=q[0];role.peers[0]=-1;
    role.peers[1]=gfd;role.peers[2]=rfd;
    uint32_t trigger=0;
    if(!strcmp(fault,"controller-lost")) {close(c[1]);c[1]=-1;trigger=1;}
    if(!strcmp(fault,"coordinator-lost")) {close(q[1]);q[1]=-1;trigger=7;}
    if(!strcmp(fault,"receiver-lost")) {assert(!kill(rp,SIGKILL));assert(waitpid(rp,NULL,0)==rp);rp=-1;trigger=3;}
    if(!strncmp(fault,"guardian-lost",13)) {
        assert(!kill(gp,SIGKILL));assert(waitpid(gp,NULL,0)==gp);gp=-1;
        if(!strcmp(fault,"guardian-lost-after-prepare"))role.prepared=1;else trigger=6;
    }
    assert((w4_role_check(&role)!=0)==(trigger!=0));assert(role.trigger==trigger);
    if(rp>0){assert(!kill(rp,SIGKILL));assert(waitpid(rp,NULL,0)==rp);}
    if(gp>0){assert(!kill(gp,SIGKILL));assert(waitpid(gp,NULL,0)==gp);}
    close(rfd);close(gfd);int *pairs[]={c,q,r,g};
    for(size_t i=0;i<4;i++)for(size_t j=0;j<2;j++)if(pairs[i][j]>=0)close(pairs[i][j]);
}
static void receiver(const char *path) {
    int qr[2],sr[2],gr[2],life[2];
    assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,qr));
    assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,sr));
    assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,gr));pair(life);
    /* The installed parent validates and makes each lifeline nonblocking
     * before the actual receiver; reproduce that prerequisite here. */
    assert(!pipe_reader(life[0]));
    uint64_t now;assert(!wq_now(&now));uint64_t deadline=now+5000000000ULL;
    wq_binding_t b;binding(&b,deadline);
    pid_t rp=fork();assert(rp>=0);
    if(!rp){int keep[]={qr[1],sr[1],gr[1],life[0]};assert(!w4_keep(keep,4));
        w4_receiver(qr[1],sr[1],gr[1],life[0],&b);}
    close(qr[1]);close(sr[1]);close(gr[1]);close(life[0]);
    int directory=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);assert(directory>2);
    wq_identity_t parent;assert(!wq_identity(directory,&parent,0));
    wq_message_t registration;w4_init(&registration,&b,W4_R_INIT,0,1);registration.scope=parent;
    assert(!w4_transfer(qr[0],&registration,sizeof(registration),&directory,1,1,deadline,NULL,NULL));
    wq_message_t reply;
    assert(!w4_transfer(qr[0],&reply,sizeof(reply),NULL,0,0,deadline,NULL,NULL));
    assert(!w4_check(&reply,&b,W4_READY,1,0));
    w4_change(&registration,W4_R_REGISTER,1,0);registration.target_pid=123;
    for(size_t i=0;i<3;i++){registration.publications[i].inode=80+i;
        registration.publications[i].size=12;memset(registration.publications[i].sha256,'e',64);}
    if(!strcmp(test_case,"receiver-registration-scope-substitution"))registration.scope.inode++;
    assert(!w4_transfer(qr[0],&registration,sizeof(registration),NULL,0,1,deadline,NULL,NULL));
    int creators[2]={-1,-1};
    if(!strcmp(test_case,"receiver-registration-scope-substitution")) {
        /* INIT's original scope is immutable before either creator exists.
         * This is a registration boundary, before any source proposal. */
        assert(w4_transfer(qr[0],&reply,sizeof(reply),creators,2,0,deadline,NULL,NULL));
        assert(creators[0]==-1&&creators[1]==-1);
        int status;assert(waitpid(rp,&status,0)==rp&&WIFEXITED(status)&&WEXITSTATUS(status)==W4_FAILURE);
        for(size_t i=0;i<2;i++){struct stat missing;errno=0;
            assert(fstatat(directory,w4_record_names[i],&missing,AT_SYMLINK_NOFOLLOW)==-1&&errno==ENOENT);}
        close(directory);close(qr[0]);close(sr[0]);close(gr[0]);close(life[1]);return;
    }
    assert(!w4_transfer(qr[0],&reply,sizeof(reply),creators,2,0,deadline,NULL,NULL));
    assert(!w4_check(&reply,&b,W4_R_CREATORS,1,2)&&w4_context_equal(&reply,&registration));
    wq_identity_t pins[2];struct stat reg_pin,empty_pin;
    assert(!wq_identity(creators[0],&pins[0],0)&&!wq_identity(creators[1],&pins[1],0));
    assert(!projected_fstat(creators[0],&reg_pin)&&!projected_fstat(creators[1],&empty_pin));
    assert(lseek(creators[0],0,SEEK_CUR)==(off_t)sizeof(registration));
    assert(lseek(creators[1],0,SEEK_CUR)==0);
    assert(!w4_records(directory,creators,&parent,pins,&registration,NULL,&reg_pin,&empty_pin,deadline));
    assert(lseek(creators[0],7,SEEK_SET)==7);
    w4_proposal_t proposal={0};proposal.context=registration;
    w4_change(&proposal.context,W4_PROPOSAL,7,0);proposal.source=W4_SOURCE_S;proposal.facts=10;
    assert(!wq_now(&now));proposal.observed_ns=now;
    int route=!strcmp(test_case,"receiver-wrong-source-route")?gr[0]:sr[0];
    assert(!w4_transfer(route,&proposal,sizeof(proposal),NULL,0,1,deadline,NULL,NULL));
    w4_commit_t commit={0};commit.context=registration;w4_change(&commit.context,W4_COMMIT_NORMAL,2,0);
    commit.decision=1;commit.decision_sequence=1;commit.facts=W4_NORMAL_Q_FACTS;
    commit.s_code=commit.g_code=CLD_EXITED;commit.proposal=proposal;
    if(!strcmp(test_case,"receiver-source-copy-mismatch"))commit.proposal.observed_ns++;
    assert(!wq_now(&now));commit.committed_ns=now;
    if(commit.committed_ns<commit.proposal.observed_ns)commit.committed_ns=commit.proposal.observed_ns;
    assert(!w4_commit_check(&commit,&registration));
    if(strcmp(test_case,"receiver-wrong-source-route"))
        assert(!w4_transfer(qr[0],&commit,sizeof(commit),NULL,0,1,deadline,NULL,NULL));
    w4_commit_t ack,expected=commit;expected.context.operation=W4_ACK;
    int received=!w4_transfer(qr[0],&ack,sizeof(ack),NULL,0,0,deadline,NULL,NULL);
    int accepted=received&&!memcmp(&ack,&expected,sizeof(ack));
    assert(accepted==!strcmp(test_case,"receiver-normal"));
    int status;assert(waitpid(rp,&status,0)==rp&&WIFEXITED(status));
    int refused=!strcmp(test_case,"receiver-terminal-fsync")||
        !strcmp(test_case,"receiver-source-copy-mismatch")||!strcmp(test_case,"receiver-wrong-source-route");
    assert(WEXITSTATUS(status)==(refused?W4_FAILURE:0));
    assert(lseek(creators[0],0,SEEK_CUR)==7);
    if(!strcmp(test_case,"receiver-source-copy-mismatch")||!strcmp(test_case,"receiver-wrong-source-route")) {
        struct stat terminal;assert(!fstat(creators[1],&terminal)&&!terminal.st_size);
    } else {
        w4_commit_t persisted;assert(pread(creators[1],&persisted,sizeof(persisted),0)==(ssize_t)sizeof(persisted));
        assert(!memcmp(&persisted,&commit,sizeof(commit)));
        assert(lseek(creators[1],0,SEEK_CUR)==(off_t)sizeof(commit));
        assert(!w4_records(directory,creators,&parent,pins,&registration,&commit,&reg_pin,NULL,deadline));
        /* Valid complete bytes and even R wait0 remain distinct from having
         * consumed the exact original full ACK (lost/corrupt cases above). */
    }
    close(creators[0]);close(creators[1]);close(directory);close(qr[0]);close(sr[0]);close(gr[0]);close(life[1]);
}
int main(int argc,char **argv) {
    assert(argc==2||argc==3);test_case=argv[1];
    if(!strncmp(test_case,"receiver-",9)&&strcmp(test_case,"receiver-lost")) {
        assert(argc==3);receiver(argv[2]);
    }
    else if(!strcmp(test_case,"ownership")){assert(argc==2);ownership();}
    else {assert(argc==2);draining(test_case);}
    return 0;
}
'''


@pytest.fixture(scope="module")
def wait_native(tmp_path_factory):
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        pytest.skip("actual Linux x86-64 pidfd/wait helpers")
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        pytest.skip("native C compiler unavailable")
    root = tmp_path_factory.mktemp("successor-waits")
    source, executable = root / "waits.c", root / "waits"
    source.write_text(_WAIT_HARNESS, encoding="ascii")
    build = subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wpedantic",
         "-Wno-unused-function", "-O2", "-I", str(native_whole_scope_source_paths()[0].parent),
         str(source), "-o", str(executable)], check=False, capture_output=True, text=True, timeout=30,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    assert build.returncode == 0, build.stderr
    return executable


def _run_native_case(executable, *arguments):
    with subprocess.Popen(
        [str(executable), *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, start_new_session=True,
        env={"PATH": os.defpath, "LANG": "C"},
    ) as process:
        try:
            _stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stderr
        finally:
            # Retire only this invocation's original process group. Inert
            # fork children cannot keep captured pipes alive after failure.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


@pytest.mark.parametrize("case", ["ownership", "normal-reserve", "controller-lost", "coordinator-lost",
                                  "receiver-lost", "guardian-lost-before-prepare", "guardian-lost-after-prepare"])
def test_actual_original_parent_consuming_wait_and_prepared_stopper_checks(wait_native, case):
    _run_native_case(wait_native, case)


@pytest.mark.parametrize("case", ["receiver-normal", "receiver-terminal-fsync", "receiver-lost-ack",
                                  "receiver-corrupt-ack", "receiver-source-copy-mismatch", "receiver-wrong-source-route",
                                  "receiver-registration-scope-substitution"])
def test_actual_receiver_creator_ofds_full_ack_and_original_source_route(wait_native, tmp_path, case):
    # R alone executes its actual create/write/fsync/SCM_RIGHTS path. Root
    # uid/gid metadata is explicitly projected; no scope or candidate is run.
    directory = tmp_path / "receiver-private"
    directory.mkdir(mode=0o700)
    _run_native_case(wait_native, case, str(directory))
