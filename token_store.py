"""Resolve the Xero token-cache path off the install tree.

The historical default lived beside xero_client.py. After pip install that
is site-packages. The default is now the per-user state directory; a
module-adjacent token.json is used only when that file already exists.
"""
from __future__ import annotations

import os

# Historical cache: next to this module. Used only when that file already
# exists so existing installs keep working after the default moved to the
# per-user state directory.
LEGACY_MODULE_TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "token.json"
)


def _state_home_token_file() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, "xero-trial-balance-export", "token.json")
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return os.path.join(os.path.abspath(xdg), "xero-trial-balance-export", "token.json")
    return os.path.join(
        os.path.expanduser("~"), ".local", "state", "xero-trial-balance-export", "token.json"
    )


DEFAULT_TOKEN_FILE = _state_home_token_file()


def resolve_token_file(cli_value: str | None = None) -> str:
    """Resolve the token cache path.

    Order: an explicit command-line value (export_tb.py's --token-file),
    then the XERO_TOKEN_FILE environment variable, then an existing
    module-adjacent token.json, then the per-user state directory.
    """
    if cli_value is not None and cli_value.strip():
        return os.path.abspath(cli_value)
    env_value = os.environ.get("XERO_TOKEN_FILE")
    if env_value is not None and env_value.strip():
        return os.path.abspath(env_value)
    if os.path.isfile(LEGACY_MODULE_TOKEN_FILE):
        return os.path.abspath(LEGACY_MODULE_TOKEN_FILE)
    return DEFAULT_TOKEN_FILE


# Module-level for the existing callers and tests that patch it. Entry points
# that parse a command line or load .env re-resolve after doing so.
TOKEN_FILE = resolve_token_file()

