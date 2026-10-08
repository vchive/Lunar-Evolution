"""Pure, finite source preparation for the installation-owned CPython fixture.

Old-byte snippets are CPython 3.13.12 source under the upstream PSF license;
see tests/fixtures/static_python_source/LICENSE and provenance.json. Matching
these reviewed Git file bytes does not verify the python.org release archive.
No source file is executed, read or written by this module.
The external-init call to stock init_zipimport is removed; its unused source
helper remains. No linked image or removal of all zip-related bytes is proved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import NoReturn

SOURCE_COMMIT = "1cbe481834751b0125e006042ffbd8cd5eaec8a8"
SOURCE_VERSION = "3.13.12"
MAX_SOURCE_BYTES = 256 * 1024
MAX_TOTAL_SOURCE_BYTES = 512 * 1024
REFUSAL_MESSAGE = "lunar_static_external_loader_refused"


class StaticPythonSourceError(ValueError):
    """A fixed refusal code, never caller-controlled source text or paths."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_source_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonSourceError(reason)


@dataclass(frozen=True, slots=True)
class _Snippet:
    label: str
    old: bytes
    new: bytes


@dataclass(frozen=True, slots=True)
class _SourceProfile:
    path: str
    before_size: int
    before_sha256: str
    after_size: int
    after_sha256: str
    snippets: tuple[_Snippet, ...]


# Whole-file pins and snippets come only from the reviewed fixed Git commit.
# The profile is installation-owned; there is no caller-defined patch API.
_PROFILES = (
    _SourceProfile(
        path='Lib/importlib/_bootstrap_external.py', before_size=73219,
        before_sha256='a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae',
        after_size=64722,
        after_sha256='2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab',
        snippets=(
            _Snippet(
                label='_LoaderBasics.exec_module',
                old=(
                b'    def exec_module(self, module):\n'
                b'        """Execute the module."""\n'
                b'        code = self.get_code(module.__name__)\n'
                b'        if code is None:\n'
                b"            raise ImportError(f'cannot load module {module.__name__!r} when '\n"
                b"                              'get_code() returns None')\n"
                b'        _bootstrap._call_with_frames_removed(exec, code, module.__dict__)\n'
            ),
                new=(
                b'    def exec_module(self, module):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='SourceLoader.get_code',
                old=(
                b'    def get_code(self, fullname):\n'
                b'        """Concrete implementation of InspectLoader.get_code.\n'
                b'\n'
                b'        Reading of bytecode requires path_stats to be implemented. To write\n'
                b'        bytecode, set_data must also be implemented.\n'
                b'\n'
                b'        """\n'
                b'        source_path = self.get_filename(fullname)\n'
                b'        source_mtime = None\n'
                b'        source_bytes = None\n'
                b'        source_hash = None\n'
                b'        hash_based = False\n'
                b'        check_source = True\n'
                b'        try:\n'
                b'            bytecode_path = cache_from_source(source_path)\n'
                b'        except NotImplementedError:\n'
                b'            bytecode_path = None\n'
                b'        else:\n'
                b'            try:\n'
                b'                st = self.path_stats(source_path)\n'
                b'            except OSError:\n'
                b'                pass\n'
                b'            else:\n'
                b"                source_mtime = int(st['mtime'])\n"
                b'                try:\n'
                b'                    data = self.get_data(bytecode_path)\n'
                b'                except OSError:\n'
                b'                    pass\n'
                b'                else:\n'
                b'                    exc_details = {\n'
                b"                        'name': fullname,\n"
                b"                        'path': bytecode_path,\n"
                b'                    }\n'
                b'                    try:\n'
                b'                        flags = _classify_pyc(data, fullname, exc_details)\n'
                b'                        bytes_data = memoryview(data)[16:]\n'
                b'                        hash_based = flags & 0b1 != 0\n'
                b'                        if hash_based:\n'
                b'                            check_source = flags & 0b10 != 0\n'
                b"                            if (_imp.check_hash_based_pycs != 'never' and\n"
                b'                                (check_source or\n'
                b"                                 _imp.check_hash_based_pycs == 'always')):\n"
                b'                                source_bytes = self.get_data(source_path)\n'
                b'                                source_hash = _imp.source_hash(\n'
                b'                                    _RAW_MAGIC_NUMBER,\n'
                b'                                    source_bytes,\n'
                b'                                )\n'
                b'                                _validate_hash_pyc(data, source_hash, fullname,\n'
                b'                                                   exc_details)\n'
                b'                        else:\n'
                b'                            _validate_timestamp_pyc(\n'
                b'                                data,\n'
                b'                                source_mtime,\n'
                b"                                st['size'],\n"
                b'                                fullname,\n'
                b'                                exc_details,\n'
                b'                            )\n'
                b'                    except (ImportError, EOFError):\n'
                b'                        pass\n'
                b'                    else:\n'
                b"                        _bootstrap._verbose_message('{} matches {}', bytecode_path,\n"
                b'                                                    source_path)\n'
                b'                        return _compile_bytecode(bytes_data, name=fullname,\n'
                b'                                                 bytecode_path=bytecode_path,\n'
                b'                                                 source_path=source_path)\n'
                b'        if source_bytes is None:\n'
                b'            source_bytes = self.get_data(source_path)\n'
                b'        code_object = self.source_to_code(source_bytes, source_path)\n'
                b"        _bootstrap._verbose_message('code object from {}', source_path)\n"
                b'        if (not sys.dont_write_bytecode and bytecode_path is not None and\n'
                b'                source_mtime is not None):\n'
                b'            if hash_based:\n'
                b'                if source_hash is None:\n'
                b'                    source_hash = _imp.source_hash(_RAW_MAGIC_NUMBER,\n'
                b'                                                   source_bytes)\n'
                b'                data = _code_to_hash_pyc(code_object, source_hash, check_source)\n'
                b'            else:\n'
                b'                data = _code_to_timestamp_pyc(code_object, source_mtime,\n'
                b'                                              len(source_bytes))\n'
                b'            try:\n'
                b'                self._cache_bytecode(source_path, bytecode_path, data)\n'
                b'            except NotImplementedError:\n'
                b'                pass\n'
                b'        return code_object\n'
            ),
                new=(
                b'    def get_code(self, fullname):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='SourcelessFileLoader.get_code',
                old=(
                b'    def get_code(self, fullname):\n'
                b'        path = self.get_filename(fullname)\n'
                b'        data = self.get_data(path)\n'
                b'        # Call _classify_pyc to do basic validation of the pyc but ignore the\n'
                b"        # result. There's no source to check against.\n"
                b'        exc_details = {\n'
                b"            'name': fullname,\n"
                b"            'path': path,\n"
                b'        }\n'
                b'        _classify_pyc(data, fullname, exc_details)\n'
                b'        return _compile_bytecode(\n'
                b'            memoryview(data)[16:],\n'
                b'            name=fullname,\n'
                b'            bytecode_path=path,\n'
                b'        )\n'
            ),
                new=(
                b'    def get_code(self, fullname):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='ExtensionFileLoader.create_module',
                old=(
                b'    def create_module(self, spec):\n'
                b'        """Create an uninitialized extension module"""\n'
                b'        module = _bootstrap._call_with_frames_removed(\n'
                b'            _imp.create_dynamic, spec)\n'
                b"        _bootstrap._verbose_message('extension module {!r} loaded from {!r}',\n"
                b'                         spec.name, self.path)\n'
                b'        return module\n'
            ),
                new=(
                b'    def create_module(self, spec):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='ExtensionFileLoader.exec_module',
                old=(
                b'    def exec_module(self, module):\n'
                b'        """Initialize an extension module"""\n'
                b'        _bootstrap._call_with_frames_removed(_imp.exec_dynamic, module)\n'
                b"        _bootstrap._verbose_message('extension module {!r} executed from {!r}',\n"
                b'                         self.name, self.path)\n'
            ),
                new=(
                b'    def exec_module(self, module):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='PathFinder.find_spec',
                old=(
                b'    def find_spec(cls, fullname, path=None, target=None):\n'
                b'        """Try to find a spec for \'fullname\' on sys.path or \'path\'.\n'
                b'\n'
                b'        The search is based on sys.path_hooks and sys.path_importer_cache.\n'
                b'        """\n'
                b'        if path is None:\n'
                b'            path = sys.path\n'
                b'        spec = cls._get_spec(fullname, path, target)\n'
                b'        if spec is None:\n'
                b'            return None\n'
                b'        elif spec.loader is None:\n'
                b'            namespace_path = spec.submodule_search_locations\n'
                b'            if namespace_path:\n'
                b'                # We found at least one namespace path.  Return a spec which\n'
                b'                # can create the namespace package.\n'
                b'                spec.origin = None\n'
                b'                spec.submodule_search_locations = _NamespacePath(fullname, namespace_path, cls._get_spec)\n'
                b'                return spec\n'
                b'            else:\n'
                b'                return None\n'
                b'        else:\n'
                b'            return spec\n'
            ),
                new=(
                b'    def find_spec(cls, fullname, path=None, target=None):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='FileFinder.find_spec',
                old=(
                b'    def find_spec(self, fullname, target=None):\n'
                b'        """Try to find a spec for the specified module.\n'
                b'\n'
                b'        Returns the matching spec, or None if not found.\n'
                b'        """\n'
                b'        is_namespace = False\n'
                b"        tail_module = fullname.rpartition('.')[2]\n"
                b'        try:\n'
                b'            mtime = _path_stat(self.path or _os.getcwd()).st_mtime\n'
                b'        except OSError:\n'
                b'            mtime = -1\n'
                b'        if mtime != self._path_mtime:\n'
                b'            self._fill_cache()\n'
                b'            self._path_mtime = mtime\n'
                b'        # tail_module keeps the original casing, for __file__ and friends\n'
                b'        if _relax_case():\n'
                b'            cache = self._relaxed_path_cache\n'
                b'            cache_module = tail_module.lower()\n'
                b'        else:\n'
                b'            cache = self._path_cache\n'
                b'            cache_module = tail_module\n'
                b'        # Check if the module is the name of a directory (and thus a package).\n'
                b'        if cache_module in cache:\n'
                b'            base_path = _path_join(self.path, tail_module)\n'
                b'            for suffix, loader_class in self._loaders:\n'
                b"                init_filename = '__init__' + suffix\n"
                b'                full_path = _path_join(base_path, init_filename)\n'
                b'                if _path_isfile(full_path):\n'
                b'                    return self._get_spec(loader_class, fullname, full_path, [base_path], target)\n'
                b'            else:\n'
                b"                # If a namespace package, return the path if we don't\n"
                b'                #  find a module in the next section.\n'
                b'                is_namespace = _path_isdir(base_path)\n'
                b'        # Check for a file w/ a proper suffix exists.\n'
                b'        for suffix, loader_class in self._loaders:\n'
                b'            try:\n'
                b'                full_path = _path_join(self.path, tail_module + suffix)\n'
                b'            except ValueError:\n'
                b'                return None\n'
                b"            _bootstrap._verbose_message('trying {}', full_path, verbosity=2)\n"
                b'            if cache_module + suffix in cache:\n'
                b'                if _path_isfile(full_path):\n'
                b'                    return self._get_spec(loader_class, fullname, full_path,\n'
                b'                                          None, target)\n'
                b'        if is_namespace:\n'
                b"            _bootstrap._verbose_message('possible namespace for {}', base_path)\n"
                b'            spec = _bootstrap.ModuleSpec(fullname, None)\n'
                b'            spec.submodule_search_locations = [base_path]\n'
                b'            return spec\n'
                b'        return None\n'
            ),
                new=(
                b'    def find_spec(self, fullname, target=None):\n'
                b"        raise ImportError('lunar_static_external_loader_refused')\n"
            ),
            ),
            _Snippet(
                label='_get_supported_file_loaders',
                old=(
                b'def _get_supported_file_loaders():\n'
                b'    """Returns a list of file-based module loaders.\n'
                b'\n'
                b'    Each item is a tuple (loader, suffixes).\n'
                b'    """\n'
                b'    extension_loaders = []\n'
                b"    if hasattr(_imp, 'create_dynamic'):\n"
                b'        if sys.platform in {"ios", "tvos", "watchos"}:\n'
                b'            extension_loaders = [(AppleFrameworkLoader, [\n'
                b'                suffix.replace(".so", ".fwork")\n'
                b'                for suffix in _imp.extension_suffixes()\n'
                b'            ])]\n'
                b'        extension_loaders.append((ExtensionFileLoader, _imp.extension_suffixes()))\n'
                b'    source = SourceFileLoader, SOURCE_SUFFIXES\n'
                b'    bytecode = SourcelessFileLoader, BYTECODE_SUFFIXES\n'
                b'    return extension_loaders + [source, bytecode]\n'
            ),
                new=(
                b'def _get_supported_file_loaders():\n'
                b'    return []\n'
            ),
            ),
            _Snippet(
                label='_install',
                old=(
                b'def _install(_bootstrap_module):\n'
                b'    """Install the path-based import components."""\n'
                b'    _set_bootstrap_module(_bootstrap_module)\n'
                b'    supported_loaders = _get_supported_file_loaders()\n'
                b'    sys.path_hooks.extend([FileFinder.path_hook(*supported_loaders)])\n'
                b'    sys.meta_path.append(PathFinder)\n'
            ),
                new=(
                b'def _install(_bootstrap_module):\n'
                b'    _set_bootstrap_module(_bootstrap_module)\n'
            ),
            ),
        ),
    ),
    _SourceProfile(
        path='Python/import.c', before_size=146770,
        before_sha256='4e18922dc31001c24fd9875746881ab407252bddc6bca544f22403d50e493a61',
        after_size=146559,
        after_sha256='58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1',
        snippets=(
            _Snippet(
                label='_PyImport_InitExternal',
                old=(
                b'PyStatus\n'
                b'_PyImport_InitExternal(PyThreadState *tstate)\n'
                b'{\n'
                b'    int verbose = _PyInterpreterState_GetConfig(tstate->interp)->verbose;\n'
                b'\n'
                b'    // XXX Initialize here: sys.path_hooks and sys.path_importer_cache.\n'
                b'\n'
                b'    if (init_importlib_external(tstate->interp) != 0) {\n'
                b'        _PyErr_Print(tstate);\n'
                b'        return _PyStatus_ERR("external importer setup failed");\n'
                b'    }\n'
                b'\n'
                b'    if (init_zipimport(tstate, verbose) != 0) {\n'
                b'        PyErr_Print();\n'
                b'        return _PyStatus_ERR("initializing zipimport failed");\n'
                b'    }\n'
                b'\n'
                b'    return _PyStatus_OK();\n'
                b'}\n'
            ),
                new=(
                b'PyStatus\n'
                b'_PyImport_InitExternal(PyThreadState *tstate)\n'
                b'{\n'
                b'    /* Fixed fixture: retain bootstrap metadata, never install a zip hook. */\n'
                b'    if (init_importlib_external(tstate->interp) != 0) {\n'
                b'        _PyErr_Print(tstate);\n'
                b'        return _PyStatus_ERR("external importer setup failed");\n'
                b'    }\n'
                b'\n'
                b'    return _PyStatus_OK();\n'
                b'}\n'
            ),
            ),
        ),
    ),
    _SourceProfile(
        path='Lib/encodings/aliases.py', before_size=15713,
        before_sha256='cac92d68c7ea5bc0f05b448b9144e3bdf236d0b7d27ab66112e96d43aad15b3f',
        after_size=802,
        after_sha256='43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106',
        snippets=(
            _Snippet(
                label='aliases',
                old=(
                b'aliases = {\n'
                b'\n'
                b'    # Please keep this list sorted alphabetically by value !\n'
                b'\n'
                b'    # ascii codec\n'
                b"    '646'                : 'ascii',\n"
                b"    'ansi_x3.4_1968'     : 'ascii',\n"
                b"    'ansi_x3_4_1968'     : 'ascii', # some email headers use this non-standard name\n"
                b"    'ansi_x3.4_1986'     : 'ascii',\n"
                b"    'cp367'              : 'ascii',\n"
                b"    'csascii'            : 'ascii',\n"
                b"    'ibm367'             : 'ascii',\n"
                b"    'iso646_us'          : 'ascii',\n"
                b"    'iso_646.irv_1991'   : 'ascii',\n"
                b"    'iso_ir_6'           : 'ascii',\n"
                b"    'us'                 : 'ascii',\n"
                b"    'us_ascii'           : 'ascii',\n"
                b'\n'
                b'    # base64_codec codec\n'
                b"    'base64'             : 'base64_codec',\n"
                b"    'base_64'            : 'base64_codec',\n"
                b'\n'
                b'    # big5 codec\n'
                b"    'big5_tw'            : 'big5',\n"
                b"    'csbig5'             : 'big5',\n"
                b'\n'
                b'    # big5hkscs codec\n'
                b"    'big5_hkscs'         : 'big5hkscs',\n"
                b"    'hkscs'              : 'big5hkscs',\n"
                b'\n'
                b'    # bz2_codec codec\n'
                b"    'bz2'                : 'bz2_codec',\n"
                b'\n'
                b'    # cp037 codec\n'
                b"    '037'                : 'cp037',\n"
                b"    'csibm037'           : 'cp037',\n"
                b"    'ebcdic_cp_ca'       : 'cp037',\n"
                b"    'ebcdic_cp_nl'       : 'cp037',\n"
                b"    'ebcdic_cp_us'       : 'cp037',\n"
                b"    'ebcdic_cp_wt'       : 'cp037',\n"
                b"    'ibm037'             : 'cp037',\n"
                b"    'ibm039'             : 'cp037',\n"
                b'\n'
                b'    # cp1026 codec\n'
                b"    '1026'               : 'cp1026',\n"
                b"    'csibm1026'          : 'cp1026',\n"
                b"    'ibm1026'            : 'cp1026',\n"
                b'\n'
                b'    # cp1125 codec\n'
                b"    '1125'                : 'cp1125',\n"
                b"    'ibm1125'             : 'cp1125',\n"
                b"    'cp866u'              : 'cp1125',\n"
                b"    'ruscii'              : 'cp1125',\n"
                b'\n'
                b'    # cp1140 codec\n'
                b"    '1140'               : 'cp1140',\n"
                b"    'ibm1140'            : 'cp1140',\n"
                b'\n'
                b'    # cp1250 codec\n'
                b"    '1250'               : 'cp1250',\n"
                b"    'windows_1250'       : 'cp1250',\n"
                b'\n'
                b'    # cp1251 codec\n'
                b"    '1251'               : 'cp1251',\n"
                b"    'windows_1251'       : 'cp1251',\n"
                b'\n'
                b'    # cp1252 codec\n'
                b"    '1252'               : 'cp1252',\n"
                b"    'windows_1252'       : 'cp1252',\n"
                b'\n'
                b'    # cp1253 codec\n'
                b"    '1253'               : 'cp1253',\n"
                b"    'windows_1253'       : 'cp1253',\n"
                b'\n'
                b'    # cp1254 codec\n'
                b"    '1254'               : 'cp1254',\n"
                b"    'windows_1254'       : 'cp1254',\n"
                b'\n'
                b'    # cp1255 codec\n'
                b"    '1255'               : 'cp1255',\n"
                b"    'windows_1255'       : 'cp1255',\n"
                b'\n'
                b'    # cp1256 codec\n'
                b"    '1256'               : 'cp1256',\n"
                b"    'windows_1256'       : 'cp1256',\n"
                b'\n'
                b'    # cp1257 codec\n'
                b"    '1257'               : 'cp1257',\n"
                b"    'windows_1257'       : 'cp1257',\n"
                b'\n'
                b'    # cp1258 codec\n'
                b"    '1258'               : 'cp1258',\n"
                b"    'windows_1258'       : 'cp1258',\n"
                b'\n'
                b'    # cp273 codec\n'
                b"    '273'                : 'cp273',\n"
                b"    'ibm273'             : 'cp273',\n"
                b"    'csibm273'           : 'cp273',\n"
                b'\n'
                b'    # cp424 codec\n'
                b"    '424'                : 'cp424',\n"
                b"    'csibm424'           : 'cp424',\n"
                b"    'ebcdic_cp_he'       : 'cp424',\n"
                b"    'ibm424'             : 'cp424',\n"
                b'\n'
                b'    # cp437 codec\n'
                b"    '437'                : 'cp437',\n"
                b"    'cspc8codepage437'   : 'cp437',\n"
                b"    'ibm437'             : 'cp437',\n"
                b'\n'
                b'    # cp500 codec\n'
                b"    '500'                : 'cp500',\n"
                b"    'csibm500'           : 'cp500',\n"
                b"    'ebcdic_cp_be'       : 'cp500',\n"
                b"    'ebcdic_cp_ch'       : 'cp500',\n"
                b"    'ibm500'             : 'cp500',\n"
                b'\n'
                b'    # cp775 codec\n'
                b"    '775'                : 'cp775',\n"
                b"    'cspc775baltic'      : 'cp775',\n"
                b"    'ibm775'             : 'cp775',\n"
                b'\n'
                b'    # cp850 codec\n'
                b"    '850'                : 'cp850',\n"
                b"    'cspc850multilingual' : 'cp850',\n"
                b"    'ibm850'             : 'cp850',\n"
                b'\n'
                b'    # cp852 codec\n'
                b"    '852'                : 'cp852',\n"
                b"    'cspcp852'           : 'cp852',\n"
                b"    'ibm852'             : 'cp852',\n"
                b'\n'
                b'    # cp855 codec\n'
                b"    '855'                : 'cp855',\n"
                b"    'csibm855'           : 'cp855',\n"
                b"    'ibm855'             : 'cp855',\n"
                b'\n'
                b'    # cp857 codec\n'
                b"    '857'                : 'cp857',\n"
                b"    'csibm857'           : 'cp857',\n"
                b"    'ibm857'             : 'cp857',\n"
                b'\n'
                b'    # cp858 codec\n'
                b"    '858'                : 'cp858',\n"
                b"    'csibm858'           : 'cp858',\n"
                b"    'ibm858'             : 'cp858',\n"
                b'\n'
                b'    # cp860 codec\n'
                b"    '860'                : 'cp860',\n"
                b"    'csibm860'           : 'cp860',\n"
                b"    'ibm860'             : 'cp860',\n"
                b'\n'
                b'    # cp861 codec\n'
                b"    '861'                : 'cp861',\n"
                b"    'cp_is'              : 'cp861',\n"
                b"    'csibm861'           : 'cp861',\n"
                b"    'ibm861'             : 'cp861',\n"
                b'\n'
                b'    # cp862 codec\n'
                b"    '862'                : 'cp862',\n"
                b"    'cspc862latinhebrew' : 'cp862',\n"
                b"    'ibm862'             : 'cp862',\n"
                b'\n'
                b'    # cp863 codec\n'
                b"    '863'                : 'cp863',\n"
                b"    'csibm863'           : 'cp863',\n"
                b"    'ibm863'             : 'cp863',\n"
                b'\n'
                b'    # cp864 codec\n'
                b"    '864'                : 'cp864',\n"
                b"    'csibm864'           : 'cp864',\n"
                b"    'ibm864'             : 'cp864',\n"
                b'\n'
                b'    # cp865 codec\n'
                b"    '865'                : 'cp865',\n"
                b"    'csibm865'           : 'cp865',\n"
                b"    'ibm865'             : 'cp865',\n"
                b'\n'
                b'    # cp866 codec\n'
                b"    '866'                : 'cp866',\n"
                b"    'csibm866'           : 'cp866',\n"
                b"    'ibm866'             : 'cp866',\n"
                b'\n'
                b'    # cp869 codec\n'
                b"    '869'                : 'cp869',\n"
                b"    'cp_gr'              : 'cp869',\n"
                b"    'csibm869'           : 'cp869',\n"
                b"    'ibm869'             : 'cp869',\n"
                b'\n'
                b'    # cp932 codec\n'
                b"    '932'                : 'cp932',\n"
                b"    'ms932'              : 'cp932',\n"
                b"    'mskanji'            : 'cp932',\n"
                b"    'ms_kanji'           : 'cp932',\n"
                b"    'windows_31j'        : 'cp932',\n"
                b'\n'
                b'    # cp949 codec\n'
                b"    '949'                : 'cp949',\n"
                b"    'ms949'              : 'cp949',\n"
                b"    'uhc'                : 'cp949',\n"
                b'\n'
                b'    # cp950 codec\n'
                b"    '950'                : 'cp950',\n"
                b"    'ms950'              : 'cp950',\n"
                b'\n'
                b'    # euc_jis_2004 codec\n'
                b"    'jisx0213'           : 'euc_jis_2004',\n"
                b"    'eucjis2004'         : 'euc_jis_2004',\n"
                b"    'euc_jis2004'        : 'euc_jis_2004',\n"
                b'\n'
                b'    # euc_jisx0213 codec\n'
                b"    'eucjisx0213'        : 'euc_jisx0213',\n"
                b'\n'
                b'    # euc_jp codec\n'
                b"    'eucjp'              : 'euc_jp',\n"
                b"    'ujis'               : 'euc_jp',\n"
                b"    'u_jis'              : 'euc_jp',\n"
                b'\n'
                b'    # euc_kr codec\n'
                b"    'euckr'              : 'euc_kr',\n"
                b"    'korean'             : 'euc_kr',\n"
                b"    'ksc5601'            : 'euc_kr',\n"
                b"    'ks_c_5601'          : 'euc_kr',\n"
                b"    'ks_c_5601_1987'     : 'euc_kr',\n"
                b"    'ksx1001'            : 'euc_kr',\n"
                b"    'ks_x_1001'          : 'euc_kr',\n"
                b'\n'
                b'    # gb18030 codec\n'
                b"    'gb18030_2000'       : 'gb18030',\n"
                b'\n'
                b'    # gb2312 codec\n'
                b"    'chinese'            : 'gb2312',\n"
                b"    'csiso58gb231280'    : 'gb2312',\n"
                b"    'euc_cn'             : 'gb2312',\n"
                b"    'euccn'              : 'gb2312',\n"
                b"    'eucgb2312_cn'       : 'gb2312',\n"
                b"    'gb2312_1980'        : 'gb2312',\n"
                b"    'gb2312_80'          : 'gb2312',\n"
                b"    'iso_ir_58'          : 'gb2312',\n"
                b'\n'
                b'    # gbk codec\n'
                b"    '936'                : 'gbk',\n"
                b"    'cp936'              : 'gbk',\n"
                b"    'ms936'              : 'gbk',\n"
                b'\n'
                b'    # hex_codec codec\n'
                b"    'hex'                : 'hex_codec',\n"
                b'\n'
                b'    # hp_roman8 codec\n'
                b"    'roman8'             : 'hp_roman8',\n"
                b"    'r8'                 : 'hp_roman8',\n"
                b"    'csHPRoman8'         : 'hp_roman8',\n"
                b"    'cp1051'             : 'hp_roman8',\n"
                b"    'ibm1051'            : 'hp_roman8',\n"
                b'\n'
                b'    # hz codec\n'
                b"    'hzgb'               : 'hz',\n"
                b"    'hz_gb'              : 'hz',\n"
                b"    'hz_gb_2312'         : 'hz',\n"
                b'\n'
                b'    # iso2022_jp codec\n'
                b"    'csiso2022jp'        : 'iso2022_jp',\n"
                b"    'iso2022jp'          : 'iso2022_jp',\n"
                b"    'iso_2022_jp'        : 'iso2022_jp',\n"
                b'\n'
                b'    # iso2022_jp_1 codec\n'
                b"    'iso2022jp_1'        : 'iso2022_jp_1',\n"
                b"    'iso_2022_jp_1'      : 'iso2022_jp_1',\n"
                b'\n'
                b'    # iso2022_jp_2 codec\n'
                b"    'iso2022jp_2'        : 'iso2022_jp_2',\n"
                b"    'iso_2022_jp_2'      : 'iso2022_jp_2',\n"
                b'\n'
                b'    # iso2022_jp_2004 codec\n'
                b"    'iso_2022_jp_2004'   : 'iso2022_jp_2004',\n"
                b"    'iso2022jp_2004'     : 'iso2022_jp_2004',\n"
                b'\n'
                b'    # iso2022_jp_3 codec\n'
                b"    'iso2022jp_3'        : 'iso2022_jp_3',\n"
                b"    'iso_2022_jp_3'      : 'iso2022_jp_3',\n"
                b'\n'
                b'    # iso2022_jp_ext codec\n'
                b"    'iso2022jp_ext'      : 'iso2022_jp_ext',\n"
                b"    'iso_2022_jp_ext'    : 'iso2022_jp_ext',\n"
                b'\n'
                b'    # iso2022_kr codec\n'
                b"    'csiso2022kr'        : 'iso2022_kr',\n"
                b"    'iso2022kr'          : 'iso2022_kr',\n"
                b"    'iso_2022_kr'        : 'iso2022_kr',\n"
                b'\n'
                b'    # iso8859_10 codec\n'
                b"    'csisolatin6'        : 'iso8859_10',\n"
                b"    'iso_8859_10'        : 'iso8859_10',\n"
                b"    'iso_8859_10_1992'   : 'iso8859_10',\n"
                b"    'iso_ir_157'         : 'iso8859_10',\n"
                b"    'l6'                 : 'iso8859_10',\n"
                b"    'latin6'             : 'iso8859_10',\n"
                b'\n'
                b'    # iso8859_11 codec\n'
                b"    'thai'               : 'iso8859_11',\n"
                b"    'iso_8859_11'        : 'iso8859_11',\n"
                b"    'iso_8859_11_2001'   : 'iso8859_11',\n"
                b'\n'
                b'    # iso8859_13 codec\n'
                b"    'iso_8859_13'        : 'iso8859_13',\n"
                b"    'l7'                 : 'iso8859_13',\n"
                b"    'latin7'             : 'iso8859_13',\n"
                b'\n'
                b'    # iso8859_14 codec\n'
                b"    'iso_8859_14'        : 'iso8859_14',\n"
                b"    'iso_8859_14_1998'   : 'iso8859_14',\n"
                b"    'iso_celtic'         : 'iso8859_14',\n"
                b"    'iso_ir_199'         : 'iso8859_14',\n"
                b"    'l8'                 : 'iso8859_14',\n"
                b"    'latin8'             : 'iso8859_14',\n"
                b'\n'
                b'    # iso8859_15 codec\n'
                b"    'iso_8859_15'        : 'iso8859_15',\n"
                b"    'l9'                 : 'iso8859_15',\n"
                b"    'latin9'             : 'iso8859_15',\n"
                b'\n'
                b'    # iso8859_16 codec\n'
                b"    'iso_8859_16'        : 'iso8859_16',\n"
                b"    'iso_8859_16_2001'   : 'iso8859_16',\n"
                b"    'iso_ir_226'         : 'iso8859_16',\n"
                b"    'l10'                : 'iso8859_16',\n"
                b"    'latin10'            : 'iso8859_16',\n"
                b'\n'
                b'    # iso8859_2 codec\n'
                b"    'csisolatin2'        : 'iso8859_2',\n"
                b"    'iso_8859_2'         : 'iso8859_2',\n"
                b"    'iso_8859_2_1987'    : 'iso8859_2',\n"
                b"    'iso_ir_101'         : 'iso8859_2',\n"
                b"    'l2'                 : 'iso8859_2',\n"
                b"    'latin2'             : 'iso8859_2',\n"
                b'\n'
                b'    # iso8859_3 codec\n'
                b"    'csisolatin3'        : 'iso8859_3',\n"
                b"    'iso_8859_3'         : 'iso8859_3',\n"
                b"    'iso_8859_3_1988'    : 'iso8859_3',\n"
                b"    'iso_ir_109'         : 'iso8859_3',\n"
                b"    'l3'                 : 'iso8859_3',\n"
                b"    'latin3'             : 'iso8859_3',\n"
                b'\n'
                b'    # iso8859_4 codec\n'
                b"    'csisolatin4'        : 'iso8859_4',\n"
                b"    'iso_8859_4'         : 'iso8859_4',\n"
                b"    'iso_8859_4_1988'    : 'iso8859_4',\n"
                b"    'iso_ir_110'         : 'iso8859_4',\n"
                b"    'l4'                 : 'iso8859_4',\n"
                b"    'latin4'             : 'iso8859_4',\n"
                b'\n'
                b'    # iso8859_5 codec\n'
                b"    'csisolatincyrillic' : 'iso8859_5',\n"
                b"    'cyrillic'           : 'iso8859_5',\n"
                b"    'iso_8859_5'         : 'iso8859_5',\n"
                b"    'iso_8859_5_1988'    : 'iso8859_5',\n"
                b"    'iso_ir_144'         : 'iso8859_5',\n"
                b'\n'
                b'    # iso8859_6 codec\n'
                b"    'arabic'             : 'iso8859_6',\n"
                b"    'asmo_708'           : 'iso8859_6',\n"
                b"    'csisolatinarabic'   : 'iso8859_6',\n"
                b"    'ecma_114'           : 'iso8859_6',\n"
                b"    'iso_8859_6'         : 'iso8859_6',\n"
                b"    'iso_8859_6_1987'    : 'iso8859_6',\n"
                b"    'iso_ir_127'         : 'iso8859_6',\n"
                b'\n'
                b'    # iso8859_7 codec\n'
                b"    'csisolatingreek'    : 'iso8859_7',\n"
                b"    'ecma_118'           : 'iso8859_7',\n"
                b"    'elot_928'           : 'iso8859_7',\n"
                b"    'greek'              : 'iso8859_7',\n"
                b"    'greek8'             : 'iso8859_7',\n"
                b"    'iso_8859_7'         : 'iso8859_7',\n"
                b"    'iso_8859_7_1987'    : 'iso8859_7',\n"
                b"    'iso_ir_126'         : 'iso8859_7',\n"
                b'\n'
                b'    # iso8859_8 codec\n'
                b"    'csisolatinhebrew'   : 'iso8859_8',\n"
                b"    'hebrew'             : 'iso8859_8',\n"
                b"    'iso_8859_8'         : 'iso8859_8',\n"
                b"    'iso_8859_8_1988'    : 'iso8859_8',\n"
                b"    'iso_ir_138'         : 'iso8859_8',\n"
                b'\n'
                b'    # iso8859_9 codec\n'
                b"    'csisolatin5'        : 'iso8859_9',\n"
                b"    'iso_8859_9'         : 'iso8859_9',\n"
                b"    'iso_8859_9_1989'    : 'iso8859_9',\n"
                b"    'iso_ir_148'         : 'iso8859_9',\n"
                b"    'l5'                 : 'iso8859_9',\n"
                b"    'latin5'             : 'iso8859_9',\n"
                b'\n'
                b'    # johab codec\n'
                b"    'cp1361'             : 'johab',\n"
                b"    'ms1361'             : 'johab',\n"
                b'\n'
                b'    # koi8_r codec\n'
                b"    'cskoi8r'            : 'koi8_r',\n"
                b'\n'
                b'    # kz1048 codec\n'
                b"    'kz_1048'           : 'kz1048',\n"
                b"    'rk1048'            : 'kz1048',\n"
                b"    'strk1048_2002'     : 'kz1048',\n"
                b'\n'
                b'    # latin_1 codec\n'
                b'    #\n'
                b'    # Note that the latin_1 codec is implemented internally in C and a\n'
                b'    # lot faster than the charmap codec iso8859_1 which uses the same\n'
                b'    # encoding. This is why we discourage the use of the iso8859_1\n'
                b'    # codec and alias it to latin_1 instead.\n'
                b'    #\n'
                b"    '8859'               : 'latin_1',\n"
                b"    'cp819'              : 'latin_1',\n"
                b"    'csisolatin1'        : 'latin_1',\n"
                b"    'ibm819'             : 'latin_1',\n"
                b"    'iso8859'            : 'latin_1',\n"
                b"    'iso8859_1'          : 'latin_1',\n"
                b"    'iso_8859_1'         : 'latin_1',\n"
                b"    'iso_8859_1_1987'    : 'latin_1',\n"
                b"    'iso_ir_100'         : 'latin_1',\n"
                b"    'l1'                 : 'latin_1',\n"
                b"    'latin'              : 'latin_1',\n"
                b"    'latin1'             : 'latin_1',\n"
                b'\n'
                b'    # mac_cyrillic codec\n'
                b"    'maccyrillic'        : 'mac_cyrillic',\n"
                b'\n'
                b'    # mac_greek codec\n'
                b"    'macgreek'           : 'mac_greek',\n"
                b'\n'
                b'    # mac_iceland codec\n'
                b"    'maciceland'         : 'mac_iceland',\n"
                b'\n'
                b'    # mac_latin2 codec\n'
                b"    'maccentraleurope'   : 'mac_latin2',\n"
                b"    'mac_centeuro'       : 'mac_latin2',\n"
                b"    'maclatin2'          : 'mac_latin2',\n"
                b'\n'
                b'    # mac_roman codec\n'
                b"    'macintosh'          : 'mac_roman',\n"
                b"    'macroman'           : 'mac_roman',\n"
                b'\n'
                b'    # mac_turkish codec\n'
                b"    'macturkish'         : 'mac_turkish',\n"
                b'\n'
                b'    # mbcs codec\n'
                b"    'ansi'               : 'mbcs',\n"
                b"    'dbcs'               : 'mbcs',\n"
                b'\n'
                b'    # ptcp154 codec\n'
                b"    'csptcp154'          : 'ptcp154',\n"
                b"    'pt154'              : 'ptcp154',\n"
                b"    'cp154'              : 'ptcp154',\n"
                b"    'cyrillic_asian'     : 'ptcp154',\n"
                b'\n'
                b'    # quopri_codec codec\n'
                b"    'quopri'             : 'quopri_codec',\n"
                b"    'quoted_printable'   : 'quopri_codec',\n"
                b"    'quotedprintable'    : 'quopri_codec',\n"
                b'\n'
                b'    # rot_13 codec\n'
                b"    'rot13'              : 'rot_13',\n"
                b'\n'
                b'    # shift_jis codec\n'
                b"    'csshiftjis'         : 'shift_jis',\n"
                b"    'shiftjis'           : 'shift_jis',\n"
                b"    'sjis'               : 'shift_jis',\n"
                b"    's_jis'              : 'shift_jis',\n"
                b'\n'
                b'    # shift_jis_2004 codec\n'
                b"    'shiftjis2004'       : 'shift_jis_2004',\n"
                b"    'sjis_2004'          : 'shift_jis_2004',\n"
                b"    's_jis_2004'         : 'shift_jis_2004',\n"
                b'\n'
                b'    # shift_jisx0213 codec\n'
                b"    'shiftjisx0213'      : 'shift_jisx0213',\n"
                b"    'sjisx0213'          : 'shift_jisx0213',\n"
                b"    's_jisx0213'         : 'shift_jisx0213',\n"
                b'\n'
                b'    # tis_620 codec\n'
                b"    'tis620'             : 'tis_620',\n"
                b"    'tis_620_0'          : 'tis_620',\n"
                b"    'tis_620_2529_0'     : 'tis_620',\n"
                b"    'tis_620_2529_1'     : 'tis_620',\n"
                b"    'iso_ir_166'         : 'tis_620',\n"
                b'\n'
                b'    # utf_16 codec\n'
                b"    'u16'                : 'utf_16',\n"
                b"    'utf16'              : 'utf_16',\n"
                b'\n'
                b'    # utf_16_be codec\n'
                b"    'unicodebigunmarked' : 'utf_16_be',\n"
                b"    'utf_16be'           : 'utf_16_be',\n"
                b'\n'
                b'    # utf_16_le codec\n'
                b"    'unicodelittleunmarked' : 'utf_16_le',\n"
                b"    'utf_16le'           : 'utf_16_le',\n"
                b'\n'
                b'    # utf_32 codec\n'
                b"    'u32'                : 'utf_32',\n"
                b"    'utf32'              : 'utf_32',\n"
                b'\n'
                b'    # utf_32_be codec\n'
                b"    'utf_32be'           : 'utf_32_be',\n"
                b'\n'
                b'    # utf_32_le codec\n'
                b"    'utf_32le'           : 'utf_32_le',\n"
                b'\n'
                b'    # utf_7 codec\n'
                b"    'u7'                 : 'utf_7',\n"
                b"    'utf7'               : 'utf_7',\n"
                b"    'unicode_1_1_utf_7'  : 'utf_7',\n"
                b'\n'
                b'    # utf_8 codec\n'
                b"    'u8'                 : 'utf_8',\n"
                b"    'utf'                : 'utf_8',\n"
                b"    'utf8'               : 'utf_8',\n"
                b"    'utf8_ucs2'          : 'utf_8',\n"
                b"    'utf8_ucs4'          : 'utf_8',\n"
                b"    'cp65001'            : 'utf_8',\n"
                b'\n'
                b'    # uu_codec codec\n'
                b"    'uu'                 : 'uu_codec',\n"
                b'\n'
                b'    # zlib_codec codec\n'
                b"    'zip'                : 'zlib_codec',\n"
                b"    'zlib'               : 'zlib_codec',\n"
                b'\n'
                b'    # temporary mac CJK aliases, will be replaced by proper codecs in 3.1\n'
                b"    'x_mac_japanese'      : 'shift_jis',\n"
                b"    'x_mac_korean'        : 'euc_kr',\n"
                b"    'x_mac_simp_chinese'  : 'gb2312',\n"
                b"    'x_mac_trad_chinese'  : 'big5',\n"
                b'}\n'
            ),
                new=(
                b'# Fixed fixture initialization aliases; not a general codec restriction.\n'
                b'aliases = {\n'
                b"    'cp65001': 'utf_8',\n"
                b"    'u8': 'utf_8',\n"
                b"    'utf': 'utf_8',\n"
                b"    'utf8': 'utf_8',\n"
                b"    'utf8_ucs2': 'utf_8',\n"
                b"    'utf8_ucs4': 'utf_8',\n"
                b'}\n'
            ),
            ),
        ),
    ),
)
SOURCE_PATHS = tuple(profile.path for profile in _PROFILES)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def source_patch_manifest() -> dict[str, object]:
    """Return detached preparation policy facts, without filesystem or build work."""
    files = []
    for profile in sorted(_PROFILES, key=lambda item: item.path):
        operations = [{
            "label": snippet.label,
            "before_sha256": hashlib.sha256(snippet.old).hexdigest(),
            "before_size": len(snippet.old),
            "after_sha256": hashlib.sha256(snippet.new).hexdigest(),
            "after_size": len(snippet.new),
            "required_occurrences": 1,
        } for snippet in profile.snippets]
        files.append({
            "path": profile.path, "before_sha256": profile.before_sha256,
            "before_size": profile.before_size, "after_sha256": profile.after_sha256,
            "after_size": profile.after_size, "operations": operations,
        })
    return {
        "schema": "lunar-static-python-source-preparation-v1",
        "source_version": SOURCE_VERSION, "source_commit": SOURCE_COMMIT,
        "provenance": "reviewed-git-source-files",
        "source_archive_verification": "not-performed",
        "source_signature_verification": "not-performed",
        "policy": "finite-exact-preimage-and-snippet-replacement",
        "zipimport_policy": "omit-external-init-call-retain-stock-helper",
        "patch_set_sha256": hashlib.sha256(_canonical(files)).hexdigest(),
        "files": files,
        "source_execution_performed": False, "build_performed": False,
        "frozen_headers_generated": False, "execution_performed": False,
        "runtime_load_protection": False, "production_admission": False,
        "general_code_origin_protection": False,
    }


def prepare_static_python_sources(
    inputs: dict[str, bytes],
) -> tuple[dict[str, bytes], dict[str, object]]:
    """Transform all three fixed source files only after every preflight gate.

    Caller inputs cannot choose a path, patch, callback or executable operation.
    Results are detached byte projections; no installation tree is mutated.
    """
    if type(inputs) is not dict or len(inputs) != len(_PROFILES):
        _fail("shape_invalid")
    if any(type(path) is not str for path in inputs) or set(inputs) != set(SOURCE_PATHS):
        _fail("paths_invalid")
    total = 0
    for path in SOURCE_PATHS:
        value = inputs[path]
        if type(value) is not bytes:
            _fail("bytes_invalid")
        if not 0 < len(value) <= MAX_SOURCE_BYTES:
            _fail("source_size_invalid")
        total += len(value)
    if total > MAX_TOTAL_SOURCE_BYTES:
        _fail("source_budget_exceeded")
    for profile in _PROFILES:
        value = inputs[profile.path]
        if (len(value) != profile.before_size
                or hashlib.sha256(value).hexdigest() != profile.before_sha256):
            _fail("preimage_drift")
    # All occurrence gates precede any replacement or output construction.
    for profile in _PROFILES:
        original = inputs[profile.path]
        for snippet in profile.snippets:
            if not snippet.old or original.count(snippet.old) != 1:
                _fail("snippet_drift")
    outputs = {}
    for profile in _PROFILES:
        value = inputs[profile.path]
        for snippet in profile.snippets:
            value = value.replace(snippet.old, snippet.new, 1)
        if (len(value) != profile.after_size
                or hashlib.sha256(value).hexdigest() != profile.after_sha256):
            _fail("postimage_drift")
        outputs[profile.path] = value
    return outputs, source_patch_manifest()


__all__ = [
    "MAX_SOURCE_BYTES",
    "MAX_TOTAL_SOURCE_BYTES",
    "REFUSAL_MESSAGE",
    "SOURCE_COMMIT",
    "SOURCE_PATHS",
    "SOURCE_VERSION",
    "StaticPythonSourceError",
    "prepare_static_python_sources",
    "source_patch_manifest",
]
