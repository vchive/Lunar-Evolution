/* One bounded raw-byte exchange through existing parent-owned broker pipes. */
#define PY_SSIZE_T_CLEAN
#include "Python.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static int used;

static int pipe_fd(const char *name, int required_access)
{
    const char *value = getenv(name);
    if (value == NULL || *value == '\0') return -1;
    unsigned long number = 0;
    for (const char *p = value; *p; p++) {
        if (*p < '0' || *p > '9' || number > (INT_MAX - (*p - '0')) / 10UL) return -1;
        number = number * 10 + (*p - '0');
    }
    if (number < 3 || number > INT_MAX) return -1;
    struct stat info;
    int fd = (int)number;
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || (flags & O_ACCMODE) != required_access ||
        fstat(fd, &info) < 0 || !S_ISFIFO(info.st_mode)) return -1;
    return fd;
}

static PyObject *exchange(PyObject *self, PyObject *argument)
{
    (void)self;
    if (used || !PyBytes_CheckExact(argument)) {
        PyErr_SetString(PyExc_ValueError, "one fixed byte exchange required");
        return NULL;
    }
    Py_ssize_t length = PyBytes_GET_SIZE(argument);
    const char *request = PyBytes_AS_STRING(argument);
    if (length < 1 || length > 4096 || request[length - 1] != '\n') {
        PyErr_SetString(PyExc_ValueError, "bounded newline request required");
        return NULL;
    }
    int write_fd = pipe_fd("LUNAR_PRODUCER_REQUEST_FD", O_WRONLY);
    int read_fd = pipe_fd("LUNAR_PRODUCER_RESPONSE_FD", O_RDONLY);
    if (write_fd < 0 || read_fd < 0 || write_fd == read_fd) {
        PyErr_SetString(PyExc_ValueError, "existing broker pipes required");
        return NULL;
    }
    used = 1;
    Py_ssize_t offset = 0;
    while (offset < length) {
        ssize_t count = write(write_fd, request + offset, (size_t)(length - offset));
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return PyErr_SetFromErrno(PyExc_OSError);
        offset += count;
    }
    char response[4096];
    size_t received = 0;
    while (received < sizeof(response)) {
        ssize_t count = read(read_fd, response + received, 1);
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) return PyErr_SetFromErrno(PyExc_OSError);
        if (count == 0) {
            PyErr_SetString(PyExc_EOFError, "broker response incomplete");
            return NULL;
        }
        if (response[received++] == '\n')
            return PyBytes_FromStringAndSize(response, (Py_ssize_t)received);
    }
    PyErr_SetString(PyExc_ValueError, "broker response exceeds fixture bound");
    return NULL;
}

static PyMethodDef methods[] = {
    {"exchange", exchange, METH_O, "Bounded parent broker byte exchange."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef definition = {
    PyModuleDef_HEAD_INIT, "_lunar_fixture_pipe", NULL, -1, methods,
    NULL, NULL, NULL, NULL
};
PyMODINIT_FUNC PyInit__lunar_fixture_pipe(void) { return PyModule_Create(&definition); }
