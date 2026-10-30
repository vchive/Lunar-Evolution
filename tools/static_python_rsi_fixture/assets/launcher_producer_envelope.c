/* Explicit envelope successor: bound argv, unchanged FD198/FD197 ownership. */
#define _POSIX_C_SOURCE 200809L
#include "Python.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "lunar_fixture_profile.h"

#define LIVE_SINK_FD 198
#define COMPLETION_FD 197
#define LIVE_LIMIT (128u * 1024u)

static int digest_valid(const char *value)
{
    if (value == NULL || strlen(value) != 64) return 0;
    for (int i = 0; i < 64; ++i)
        if (!((value[i] >= '0' && value[i] <= '9') ||
              (value[i] >= 'a' && value[i] <= 'f'))) return 0;
    return 1;
}

static int identifier_valid(const char *value)
{
    if (value == NULL || !*value || strlen(value) > 128) return 0;
    for (size_t i = 0; value[i]; ++i) {
        unsigned char ch = (unsigned char)value[i];
        if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') ||
            (ch >= '0' && ch <= '9')) continue;
        if (i && (ch == '_' || ch == '.' || ch == '-')) continue;
        return 0;
    }
    return 1;
}

static int original_deadline(const char *name, uint64_t *value)
{
    const char *text = getenv(name);
    uint64_t result = 0;
    if (!text || !*text || *text == '0') return -1;
    for (const char *p = text; *p; ++p) {
        if (*p < '0' || *p > '9' || result > (UINT64_MAX - (unsigned)(*p - '0')) / 10)
            return -1;
        result = result * 10 + (unsigned)(*p - '0');
    }
    if (unsetenv(name)) return -1;
    *value = result;
    return 0;
}

static int remaining_ms(uint64_t deadline)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec < 0 ||
        now.tv_nsec < 0 || now.tv_nsec >= 1000000000) return -1;
    if ((uint64_t)now.tv_sec > (UINT64_MAX - (uint64_t)now.tv_nsec) / 1000000000) return -1;
    uint64_t sampled = (uint64_t)now.tv_sec * 1000000000 + (uint64_t)now.tv_nsec;
    if (sampled >= deadline) return -1;
    uint64_t ms = (deadline - sampled) / 1000000;
    return ms > 50 ? 50 : (int)ms;
}

static int writer_valid(int fd)
{
    struct stat pipe;
    int flags = fcntl(fd, F_GETFL);
    return flags >= 0 && (flags & O_ACCMODE) == O_WRONLY &&
        (flags & O_NONBLOCK) && !fstat(fd, &pipe) && S_ISFIFO(pipe.st_mode);
}

static int collect_write(const char *raw, size_t length, uint64_t deadline)
{
    while (length) {
        int wait = remaining_ms(deadline);
        if (wait < 0) return -1;
        ssize_t count = write(LIVE_SINK_FD, raw, length);
        if (count > 0) { raw += count; length -= (size_t)count; continue; }
        if (count < 0 && errno == EINTR) continue;
        if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            struct pollfd pipe = {LIVE_SINK_FD, POLLOUT, 0};
            if (poll(&pipe, 1, wait) < 0 && errno != EINTR) return -1;
            continue;
        }
        return -1;
    }
    return remaining_ms(deadline) < 0 ? -1 : 0;
}

int main(int argc, char **argv)
{
    uint64_t startup_deadline, completion_deadline;
    if (argc != 6 || !argv || !argv[1] || !argv[4] ||
        strcmp(argv[1], "--lunar-fixed-producer-envelope-v1") ||
        !identifier_valid(argv[2]) || !digest_valid(argv[3]) ||
        strcmp(argv[4], "--lunar-rsi-input-v1") || !digest_valid(argv[5]) ||
        original_deadline("LUNAR_FIXED_LIVE_DEADLINE_NS", &startup_deadline) ||
        original_deadline("LUNAR_FIXED_COMPLETION_DEADLINE_NS", &completion_deadline) ||
        startup_deadline != completion_deadline ||
        remaining_ms(startup_deadline) < 0 || remaining_ms(completion_deadline) < 0 ||
        !writer_valid(LIVE_SINK_FD) || !writer_valid(COMPLETION_FD)) {
        close(LIVE_SINK_FD);
        close(COMPLETION_FD);
        return 64;
    }
    PyPreConfig preconfig;
    PyStatus status = lunar_preconfig(&preconfig);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    PyConfig config;
    status = lunar_config(&config);
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);

    PyObject *module = PyImport_ImportModule("_lunar_static_main");
    PyObject *collector = module ? PyObject_GetAttrString(module, "_lunar_collect_live_modules") : NULL;
    PyObject *argument = collector ? PyUnicode_FromString(argv[5]) : NULL;
    PyObject *captured = argument ? PyObject_CallOneArg(collector, argument) : NULL;
    char *raw = NULL;
    Py_ssize_t length = 0;
    int failed = !captured || !PyBytes_CheckExact(captured) ||
        PyBytes_AsStringAndSize(captured, &raw, &length) ||
        length <= 0 || length > LIVE_LIMIT || raw[length - 1] != '\n' ||
        collect_write(raw, (size_t)length, startup_deadline);
    /* Preserve the startup EOF before any solver import/call. */
    if (close(LIVE_SINK_FD)) failed = 1;
    Py_XDECREF(captured);
    Py_XDECREF(collector);
    PyObject *callable = !failed ? PyObject_GetAttrString(module, "_rsi_launch") : NULL;
    PyObject *deadline = callable ? PyLong_FromUnsignedLongLong(completion_deadline) : NULL;
    PyObject *run_id = deadline ? PyUnicode_FromString(argv[2]) : NULL;
    PyObject *fingerprint = run_id ? PyUnicode_FromString(argv[3]) : NULL;
    PyObject *result = fingerprint ? PyObject_CallFunctionObjArgs(
        callable, argument, deadline, run_id, fingerprint, NULL) : NULL;
    if (!result) failed = 1;
    /* The launcher alone owns/closes FD197; Python only borrows the writer. */
    close(COMPLETION_FD);
    if (failed) PyErr_Print();
    Py_XDECREF(result);
    Py_XDECREF(fingerprint);
    Py_XDECREF(run_id);
    Py_XDECREF(deadline);
    Py_XDECREF(callable);
    Py_XDECREF(argument);
    Py_XDECREF(module);
    if (Py_FinalizeEx() < 0) return 120;
    return failed ? 1 : 0;
}
