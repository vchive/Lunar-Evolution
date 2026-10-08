#include "lunar_fixture_profile.h"

PyStatus lunar_preconfig(PyPreConfig *config)
{
    PyPreConfig_InitIsolatedConfig(config);
    config->parse_argv = 0; config->isolated = 1; config->use_environment = 0;
    config->configure_locale = 0; config->coerce_c_locale = 0;
    config->coerce_c_locale_warn = 0; config->utf8_mode = 1; config->dev_mode = 0;
    config->allocator = PYMEM_ALLOCATOR_PYMALLOC;
    if (config->_config_init != 3) return PyStatus_Error("isolated preconfig mismatch");
    return PyStatus_Ok();
}

PyStatus lunar_config(PyConfig *config)
{
    PyConfig_InitIsolatedConfig(config);
    if (config->_config_init != 3) return PyStatus_Error("isolated config mismatch");
#define SET(field, value) do { config->field = (value); } while (0)
    SET(isolated, 1); SET(use_environment, 0); SET(dev_mode, 0);
    SET(install_signal_handlers, 0); SET(use_hash_seed, 1); SET(hash_seed, 0UL);
    SET(faulthandler, 0); SET(tracemalloc, 0); SET(perf_profiling, 0); SET(import_time, 0);
    SET(code_debug_ranges, 1); SET(show_ref_count, 0); SET(dump_refs, 0);
    SET(malloc_stats, 0); SET(parse_argv, 0); SET(site_import, 0); SET(bytes_warning, 0);
    SET(warn_default_encoding, 0); SET(inspect, 0); SET(interactive, 0);
    SET(optimization_level, 0); SET(parser_debug, 0); SET(write_bytecode, 0);
    SET(verbose, 0); SET(quiet, 0); SET(user_site_directory, 0); SET(configure_c_stdio, 1);
    SET(buffered_stdio, 1); SET(use_frozen_modules, 1); SET(safe_path, 1);
    SET(int_max_str_digits, 4300); SET(cpu_count, 1); SET(pathconfig_warnings, 0);
    SET(module_search_paths_set, 1); SET(skip_source_first_line, 0);
    SET(_install_importlib, 1); SET(_init_main, 1); SET(_is_python_build, 0);
    PyStatus status;
#define STR(field, value) do { status = PyConfig_SetString(config, &config->field, value); \
    if (PyStatus_Exception(status)) return status; } while (0)
    STR(filesystem_encoding, L"utf-8"); STR(filesystem_errors, L"surrogateescape");
    STR(stdio_encoding, L"utf-8"); STR(stdio_errors, L"strict");
    STR(check_hash_pycs_mode, L"always"); STR(program_name, L"lunar-static-python-fixture");
    STR(home, L"/lunar-static-fixture"); STR(platlibdir, L"lib");
    STR(stdlib_dir, L"/lunar-static-fixture"); STR(executable, L"/lunar-static-python-fixture");
    STR(base_executable, L"/lunar-static-python-fixture"); STR(prefix, L"/lunar-static-fixture");
    STR(base_prefix, L"/lunar-static-fixture"); STR(exec_prefix, L"/lunar-static-fixture");
    STR(base_exec_prefix, L"/lunar-static-fixture");
    STR(dump_refs_file, NULL); STR(pycache_prefix, NULL); STR(pythonpath_env, NULL);
    STR(run_command, NULL); STR(run_module, NULL); STR(run_filename, NULL); STR(sys_path_0, NULL);
    wchar_t *argv[] = {L"lunar-static-python-fixture"};
    status = PyConfig_SetWideStringList(config, &config->orig_argv, 1, argv);
    if (PyStatus_Exception(status)) return status;
    status = PyConfig_SetWideStringList(config, &config->argv, 1, argv);
    if (PyStatus_Exception(status)) return status;
    status = PyConfig_SetWideStringList(config, &config->xoptions, 0, NULL);
    if (PyStatus_Exception(status)) return status;
    status = PyConfig_SetWideStringList(config, &config->warnoptions, 0, NULL);
    if (PyStatus_Exception(status)) return status;
    status = PyConfig_SetWideStringList(config, &config->module_search_paths, 0, NULL);
    if (PyStatus_Exception(status)) return status;
    return PyStatus_Ok();
}
