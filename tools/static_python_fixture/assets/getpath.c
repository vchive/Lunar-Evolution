/* Fixed logical path metadata. No filesystem, environment or global path discovery. */
#include "Python.h"
#include "pycore_pathconfig.h"
#include <wchar.h>

static int equal(const wchar_t *value, const wchar_t *expected)
{
    return value != NULL && wcscmp(value, expected) == 0;
}

PyStatus _PyConfig_InitPathConfig(PyConfig *config, int compute_path_config)
{
    (void)compute_path_config;
    if (config == NULL || config->module_search_paths_set != 1 ||
        config->module_search_paths.length != 0 || config->pythonpath_env != NULL ||
        !equal(config->program_name, L"lunar-static-python-fixture") ||
        !equal(config->executable, L"/lunar-static-python-fixture") ||
        !equal(config->base_executable, L"/lunar-static-python-fixture") ||
        !equal(config->home, L"/lunar-static-fixture") ||
        !equal(config->prefix, L"/lunar-static-fixture") ||
        !equal(config->base_prefix, L"/lunar-static-fixture") ||
        !equal(config->exec_prefix, L"/lunar-static-fixture") ||
        !equal(config->base_exec_prefix, L"/lunar-static-fixture") ||
        !equal(config->stdlib_dir, L"/lunar-static-fixture") ||
        !equal(config->platlibdir, L"lib"))
        return PyStatus_Error("fixed lunar path profile mismatch");
    return PyStatus_Ok();
}
