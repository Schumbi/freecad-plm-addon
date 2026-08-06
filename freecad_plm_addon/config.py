DEFAULT_SERVER_URL = "https://plm.lan.schumbi.de"
DEFAULT_WORKSPACE_ROOT = "~/FreeCAD-PLM"
DEFAULT_CACHE_MAX_FCSTD_FILES = 20
DEFAULT_CACHE_MAX_PROJECTS = 5
DEFAULT_CACHE_MAX_REVISIONS_PER_PROJECT = 5
DEFAULT_SLICER_KIND = "auto"
DEFAULT_SLICER_EXTRA_ARGS = "[]"
PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/FreeCADPLM"


def _params():
    import FreeCAD

    return FreeCAD.ParamGet(PARAM_PATH)


def get_server_url():
    return _params().GetString("server_url", DEFAULT_SERVER_URL)


def set_server_url(value):
    _params().SetString("server_url", value)


def get_api_token():
    return _params().GetString("api_token", "")


def set_api_token(value):
    _params().SetString("api_token", value)


def get_workspace_root():
    return _params().GetString("workspace_root", DEFAULT_WORKSPACE_ROOT)


def set_workspace_root(value):
    _params().SetString("workspace_root", value)


def get_slicer_kind():
    return _params().GetString("slicer_kind", DEFAULT_SLICER_KIND)


def set_slicer_kind(value):
    _params().SetString("slicer_kind", str(value or DEFAULT_SLICER_KIND))


def get_slicer_executable():
    return _params().GetString("slicer_executable", "")


def set_slicer_executable(value):
    _params().SetString("slicer_executable", str(value or ""))


def get_slicer_extra_args():
    return _params().GetString("slicer_extra_args", DEFAULT_SLICER_EXTRA_ARGS)


def set_slicer_extra_args(value):
    _params().SetString("slicer_extra_args", str(value or DEFAULT_SLICER_EXTRA_ARGS))


def _get_int(name, default, minimum):
    value = _params().GetInt(name, default)
    return max(value, minimum)


def _set_int(name, value, minimum):
    _params().SetInt(name, max(int(value), minimum))


def get_cache_max_fcstd_files():
    return _get_int(
        "cache_max_fcstd_files",
        DEFAULT_CACHE_MAX_FCSTD_FILES,
        DEFAULT_CACHE_MAX_FCSTD_FILES,
    )


def set_cache_max_fcstd_files(value):
    _set_int("cache_max_fcstd_files", value, DEFAULT_CACHE_MAX_FCSTD_FILES)


def get_cache_max_projects():
    return _get_int("cache_max_projects", DEFAULT_CACHE_MAX_PROJECTS, DEFAULT_CACHE_MAX_PROJECTS)


def set_cache_max_projects(value):
    _set_int("cache_max_projects", value, DEFAULT_CACHE_MAX_PROJECTS)


def get_cache_max_revisions_per_project():
    return _get_int(
        "cache_max_revisions_per_project",
        DEFAULT_CACHE_MAX_REVISIONS_PER_PROJECT,
        DEFAULT_CACHE_MAX_REVISIONS_PER_PROJECT,
    )


def set_cache_max_revisions_per_project(value):
    _set_int(
        "cache_max_revisions_per_project",
        value,
        DEFAULT_CACHE_MAX_REVISIONS_PER_PROJECT,
    )
