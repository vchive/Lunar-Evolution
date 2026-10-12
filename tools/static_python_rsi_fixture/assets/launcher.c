/* Source-only RSI marker fixture. Never an arbitrary Python entry point. */
#include "Python.h"
#include <string.h>
#include "lunar_fixture_profile.h"

static int valid_manifest_digest(const char *value)
{
    if (value == NULL || strlen(value) != 64) return 0;
    for (int index = 0; index < 64; ++index) {
        unsigned char byte = (unsigned char)value[index];
        if (!((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f'))) return 0;
    }
    return 1;
}

int main(int argc, char **argv)
{
    if (argc != 3 || argv == NULL || argv[1] == NULL ||
        strcmp(argv[1], "--lunar-rsi-input-v1") != 0 ||
        !valid_manifest_digest(argv[2])) return 64;

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
    PyObject *callable = module == NULL ? NULL : PyObject_GetAttrString(module, "_rsi_launch");
    PyObject *argument = callable == NULL ? NULL : PyUnicode_FromString(argv[2]);
    PyObject *result = argument == NULL ? NULL : PyObject_CallOneArg(callable, argument);
    int failed = result == NULL;
    if (failed) PyErr_Print();
    Py_XDECREF(result);
    Py_XDECREF(argument);
    Py_XDECREF(callable);
    Py_XDECREF(module);
    if (Py_FinalizeEx() < 0) return 120;
    return failed ? 1 : 0;
}
