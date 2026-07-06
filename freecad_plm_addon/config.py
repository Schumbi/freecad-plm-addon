DEFAULT_SERVER_URL = "https://plm.lan.schumbi.de"
DEFAULT_WORKSPACE_ROOT = "~/FreeCAD-PLM"
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
