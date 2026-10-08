/* Fixed inert fixture entry point. No -c, module/path selection or code argument. */
#include "Python.h"
#include <stdlib.h>
#include <string.h>
#include "lunar_fixture_profile.h"

int main(int argc, char **argv)
{
    (void)argv;
    if (argc != 1) return 64;
    const char *fixture_case = getenv("LUNAR_STATIC_FIXTURE_CASE");
    if (fixture_case == NULL) fixture_case = "baseline";
    if (strcmp(fixture_case, "baseline") && strcmp(fixture_case, "loader-negative")) return 64;

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
    PyObject *callable = module == NULL ? NULL : PyObject_GetAttrString(module, "_main");
    PyObject *argument = callable == NULL ? NULL : PyUnicode_FromString(fixture_case);
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
