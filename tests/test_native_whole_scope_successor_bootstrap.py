"""Real v4 B gate/retirement helper mechanisms, without an installed scope.

The production C entry helpers consume actual pipes, pidfds, queued SCM_RIGHTS
and exact frames. Child creation here is test-only fork/pidfd_open; this does
not run the installed B/T clone3/cgroup/credential path or a candidate program.
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
    reason="actual Linux x86-64 B helpers and pidfds",
)

_HARNESS = r'''
#define main installed_bootstrap_main
#include "native_bootstrap.c"
#undef main
#include <assert.h>

static void context(wq_message_t *m, uint64_t deadline) {
    wq_binding_t b = {0};
    b.deadline_ns = deadline; b.candidate_uid = b.candidate_gid = 65534;
    char *digests[] = {b.launch_sha256, b.intent_sha256, b.target_sha256,
        b.bootstrap_sha256, b.supervisor_sha256, b.profile_sha256};
    for (size_t i = 0; i < 6; ++i) memset(digests[i], 'a' + (int)i, 64);
    w4_init(m, &b, W4_REGISTER, 1, 3);
    m->scope.inode = 101; m->scope.mount_id = 102; m->scope.mode = S_IFDIR | 0700;
    m->target_pid = 123;
    for (size_t i = 0; i < 3; ++i) {
        m->publications[i].inode = 200 + i; m->publications[i].size = 17;
        memset(m->publications[i].sha256, 'a', 64);
    }
}
static void result_packet(w4_result_t *r, const wq_message_t *registration) {
    memset(r, 0, sizeof(*r));
    uint64_t now; assert(!wq_now(&now));
    r->context = *registration; w4_change(&r->context, W4_RESULT, 4, 0);
    r->commit.context = *registration; w4_change(&r->commit.context, W4_COMMIT_NORMAL, 2, 0);
    r->commit.decision = r->commit.decision_sequence = 1;
    r->commit.facts = W4_NORMAL_Q_FACTS;
    r->commit.committed_ns = now;
    r->commit.s_code = r->commit.g_code = CLD_EXITED;
    r->commit.proposal.context = *registration;
    w4_change(&r->commit.proposal.context, W4_PROPOSAL, 7, 0);
    r->commit.proposal.source = W4_SOURCE_S; r->commit.proposal.facts = 10;
    r->commit.proposal.observed_ns = now;
    r->facts = 7; r->r_code = CLD_EXITED; r->observed_ns = now;
}
static void make_pipe(int p[2]) { assert(!pipe2(p, O_CLOEXEC | O_NONBLOCK)); }
static void make_pair(int p[2]) {
    assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, p));
}
static int count_fds(void) {
    DIR *d = opendir("/proc/self/fd"); assert(d);
    int n = 0; struct dirent *e;
    while ((e = readdir(d))) if (strcmp(e->d_name, ".") && strcmp(e->d_name, "..")) ++n;
    assert(!closedir(d)); return n;
}
static void kill_wait(pid_t pid, int fd) {
    assert(!syscall(SYS_pidfd_send_signal, fd, SIGKILL, NULL, 0));
    siginfo_t status = {0};
    assert(!waitid(P_PIDFD, (id_t)fd, &status, WEXITED));
    assert(status.si_pid == pid && status.si_code == CLD_KILLED && status.si_status == SIGKILL);
}
static int gate_case(const char *which) {
    w4_bootstrap_fds_t f = {0}; uint64_t now; assert(!wq_now(&now));
    f.deadline = now + 3000000000ULL; f.peers_required = 1;
    int c[2], q[2], channel[2], gate[2]; make_pipe(c); make_pipe(q); make_pair(channel); make_pipe(gate);
    f.lifeline = c[0]; f.q_lifeline = q[0]; f.lifecycle = channel[0];
    pid_t pids[3];
    for (size_t i = 0; i < 3; ++i) {
        int armed[2]; make_pipe(armed);
        pids[i] = fork(); assert(pids[i] >= 0);
        if (!pids[i]) {
            for (unsigned int fd = 0; fd <= (unsigned int)armed[1]; ++fd)
                if (fd != (unsigned int)armed[1]) close((int)fd);
            assert(!syscall(SYS_close_range, (unsigned int)armed[1] + 1, UINT_MAX, 0));
            assert(write(armed[1], "R", 1) == 1); close(armed[1]);
            for (;;) pause();
        }
        close(armed[1]);
        struct pollfd armed_poll = {armed[0], POLLIN, 0};
        assert(poll(&armed_poll, 1, 3000) == 1);
        unsigned char ready; assert(read(armed[0], &ready, 1) == 1 && ready == 'R'); close(armed[0]);
        f.peers[i] = (int)syscall(SYS_pidfd_open, pids[i], 0); assert(f.peers[i] > 2);
    }
    assert(!w4_b_before_gate(&f));
    if (!strcmp(which, "cutoff")) f.deadline = now + W4_RESERVE_NS;
    wq_message_t original; context(&original, f.deadline);
    wq_message_t permit = original; w4_change(&permit, W4_PERMIT, 3, 0);
    assert(!w4_send(channel[1], &permit, sizeof(permit), NULL, 0));
    int dead = -1;
    if (!strcmp(which, "c-lost")) assert(!close(c[1]));
    else if (!strcmp(which, "q-lost")) assert(!close(q[1]));
    else if (strncmp(which, "peer-", 5) == 0) {
        dead = which[5] - '0'; assert(dead >= 0 && dead < 3);
        kill_wait(pids[dead], f.peers[dead]);
    }
    wq_message_t received;
    int accepted = !w4_b_receive(&f, channel[0], &received, NULL, 0) &&
                   !w4_check(&received, &original.binding, W4_PERMIT, 3, 0) &&
                   w4_context_equal(&received, &original) && !w4_b_before_gate(&f);
    if (accepted) assert(write(gate[1], "1", 1) == 1);
    unsigned char byte; ssize_t size = read(gate[0], &byte, 1);
    if (!strcmp(which, "live")) assert(accepted && size == 1 && byte == '1');
    else assert(!accepted && size < 0 && errno == EAGAIN);
    for (size_t i = 0; i < 3; ++i) {
        if ((int)i != dead) kill_wait(pids[i], f.peers[i]);
        close(f.peers[i]);
    }
    return 0;
}
static int final_case(const char *which) {
    w4_bootstrap_fds_t f = {0}; uint64_t now; assert(!wq_now(&now));
    f.deadline = now + 3000000000ULL; f.peers_required = 0;
    int c[2], q[2], pair[2]; make_pipe(c); make_pipe(q); make_pair(pair);
    f.lifeline = c[0]; f.q_lifeline = q[0]; f.lifecycle = pair[0];
    wq_message_t registration; context(&registration, f.deadline);
    w4_result_t result; result_packet(&result, &registration);
    if (!strcmp(which, "ack-missing")) result.facts = 6;
    if (!strcmp(which, "r-wait-missing")) result.facts = 5;
    if (!strcmp(which, "r-nonzero")) result.r_status = 78;
    if (!strcmp(which, "s-nonzero")) result.commit.s_status = 78;
    if (!strcmp(which, "g-nonzero")) result.commit.g_status = 78;
    if (!strcmp(which, "bad-context")) ++result.commit.context.target_pid;
    if (!strcmp(which, "bad-proposal")) ++result.commit.proposal.context.target_pid;
    if (!strcmp(which, "source-after-commit")) ++result.commit.proposal.observed_ns;
    if (!strcmp(which, "result-before-commit")) --result.observed_ns;
    if (!strcmp(which, "abnormal")) result.commit.decision = 2;
    if (!strcmp(which, "wrong-wire")) result.context.magic = WQ_MAGIC;
    if (!strcmp(which, "at-deadline")) result.observed_ns = f.deadline;
    pid_t sender = fork(); assert(sender >= 0);
    if (!sender) {
        close(c[1]); close(q[0]); close(pair[0]);
        if (strcmp(which, "missing")) {
            int extra = -1;
            if (!strcmp(which, "extra-rights")) {
                extra = open("/dev/null", O_RDONLY | O_CLOEXEC); assert(extra > 2);
                result.context.fd_count = 1;
            }
            assert(!w4_send(pair[1], &result, sizeof(result), extra < 0 ? NULL : &extra, extra < 0 ? 0 : 1));
        }
        close(q[1]); close(pair[1]); _exit(0);
    }
    close(q[1]); close(pair[1]);
    /* The queued result really survives sender exit. This test's own exact
     * wait does not stand in for the controller's original production Q wait. */
    int status; assert(waitpid(sender, &status, 0) == sender && status == 0);
    int before = count_fds(); w4_result_t observed;
    int accepted = !w4_b_final_result(&f, &registration, &observed);
    assert(count_fds() == before);
    assert(accepted == !strcmp(which, "queued-normal"));
    return 0;
}
static int done_case(void) {
    w4_bootstrap_fds_t f = {0}; uint64_t now; assert(!wq_now(&now));
    f.deadline = now + 3000000000ULL; f.peers_required = 1;
    int c[2], q[2], pair[2]; make_pipe(c); make_pipe(q); make_pair(pair);
    f.lifeline = c[0]; f.q_lifeline = q[0]; f.lifecycle = pair[0];
    pid_t peers[3];
    for (size_t i = 0; i < 3; ++i) {
        peers[i] = fork(); assert(peers[i] >= 0);
        if (!peers[i]) { assert(!syscall(SYS_close_range, 3, UINT_MAX, 0)); for (;;) pause(); }
        f.peers[i] = (int)syscall(SYS_pidfd_open, peers[i], 0); assert(f.peers[i] > 2);
    }
    wq_message_t message; context(&message, f.deadline); w4_change(&message, W4_B_DONE, 4, 0);
    assert(!w4_b_done(&f, &message)); assert(!f.peers_required);
    wq_message_t got;
    assert(!w4_receive(pair[1], &got, sizeof(got), NULL, 0, f.deadline));
    assert(!memcmp(&got, &message, sizeof(got)));
    /* Successful DONE transfers into retirement; exited peer copies no longer
     * block a complete result, while the original C lifeline still does. */
    for (size_t i = 0; i < 3; ++i) kill_wait(peers[i], f.peers[i]);
    wq_message_t registration; context(&registration, f.deadline);
    w4_result_t result; result_packet(&result, &registration);
    assert(!w4_send(pair[1], &result, sizeof(result), NULL, 0));
    assert(!w4_b_final_result(&f, &registration, &result));
    for (size_t i = 0; i < 3; ++i) close(f.peers[i]);
    return 0;
}
int main(int argc, char **argv) {
    assert(argc == 3);
    if (!strcmp(argv[1], "gate")) return gate_case(argv[2]);
    if (!strcmp(argv[1], "final")) return final_case(argv[2]);
    assert(!strcmp(argv[1], "done")); return done_case();
}
'''


@pytest.fixture(scope="module")
def bootstrap_harness(tmp_path_factory):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler is unavailable")
    directory = tmp_path_factory.mktemp("successor-b-helpers")
    source, executable = directory / "harness.c", directory / "harness"
    source.write_text(_HARNESS)
    build = subprocess.run(
        [compiler, "-std=c11", "-O2", "-pthread", "-I", str(native_bootstrap_source_paths()[0].parent),
         str(source), "-o", str(executable)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert build.returncode == 0, build.stderr
    return executable


def _case(executable, group, name):
    process = subprocess.Popen([str(executable), group, name], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        _stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
    finally:
        # Retire only this fixture's actual process group, including inert
        # children on assertion/timeout. No process discovery or redispatch.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


@pytest.mark.parametrize("case", ["live", "c-lost", "q-lost", "peer-0", "peer-1", "peer-2", "cutoff"])
def test_original_queued_permit_still_requires_live_peers_and_original_cutoff(bootstrap_harness, case):
    _case(bootstrap_harness, "gate", case)


@pytest.mark.parametrize("case", [
    "queued-normal", "missing", "ack-missing", "r-wait-missing", "r-nonzero", "s-nonzero", "g-nonzero",
    "bad-context", "bad-proposal", "source-after-commit", "result-before-commit", "abnormal", "wrong-wire",
    "at-deadline", "extra-rights",
])
def test_original_final_result_drains_before_expected_q_eof_and_refuses_incomplete_facts(bootstrap_harness, case):
    _case(bootstrap_harness, "final", case)


def test_target_done_has_distinct_expected_retirement_boundary(bootstrap_harness):
    _case(bootstrap_harness, "done", "exact")
