"""Resolve the Xero token-cache path off the install tree.

The historical default lived beside xero_client.py. After pip install that
is site-packages. The default is now the per-user state directory; a
module-adjacent token.json is used only when that file already exists.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Historical cache: next to this module. Used only when that file already
# exists so existing installs keep working after the default moved to the
# per-user state directory.
LEGACY_MODULE_TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "token.json"
)


def _home_dir() -> Path:
    return Path.home().resolve()


def _under_home(path: Path) -> bool:
    try:
        path.resolve().relative_to(_home_dir())
    except ValueError:
        return False
    return True


def _state_home_token_file() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        base_path = Path(base).expanduser()
        if not _under_home(base_path):
            base_path = Path.home() / "AppData" / "Local"
        return str(base_path.resolve() / "xero-trial-balance-export" / "token.json")
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        xdg_path = Path(xdg).expanduser()
        if _under_home(xdg_path):
            return str(xdg_path.resolve() / "xero-trial-balance-export" / "token.json")
    return str(_home_dir() / ".local" / "state" / "xero-trial-balance-export" / "token.json")


def safe_token_path(path: str) -> str:
    """Return a realpath that is allowed to hold the Xero token cache.

    The cache must be named token.json and must stay under the home
    directory, the process working directory, the system temp directory,
    or the install directory.
    """
    candidate = Path(path).expanduser().resolve()
    if candidate.name != "token.json":
        raise SystemExit("error: token cache path must be named token.json")
    roots = (
        _home_dir(),
        Path.cwd().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        Path(__file__).resolve().parent,
    )
    for root in roots:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return str(candidate)
    raise SystemExit(
        "error: token cache path must stay under the home directory, "
        "the process working directory, the system temp directory, "
        "or the install directory."
    )


DEFAULT_TOKEN_FILE = safe_token_path(_state_home_token_file())


def resolve_token_file(cli_value: str | None = None) -> str:
    """Resolve the token cache path.

    Order: an explicit command-line value (export_tb.py's --token-file),
    then the XERO_TOKEN_FILE environment variable, then an existing
    module-adjacent token.json, then the per-user state directory.
    """
    if cli_value is not None and cli_value.strip():
        return safe_token_path(str(Path(cli_value).expanduser()))
    env_value = os.environ.get("XERO_TOKEN_FILE")
    if env_value is not None and env_value.strip():
        return safe_token_path(str(Path(env_value).expanduser()))
    if os.path.isfile(LEGACY_MODULE_TOKEN_FILE):
        return safe_token_path(LEGACY_MODULE_TOKEN_FILE)
    return DEFAULT_TOKEN_FILE


# Module-level for the existing callers and tests that patch it. Entry points
# that parse a command line or load .env re-resolve after doing so.
TOKEN_FILE = resolve_token_file()
