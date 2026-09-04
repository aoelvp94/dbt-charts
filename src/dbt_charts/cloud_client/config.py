"""The user-level config the ``dct cloud`` verbs read.

Auth is user-global and context is per-invocation (the initiative's spec), so
one file outside any project holds the credential, the host, and the default
org/project ``dct cloud use`` writes. It sits where the platform puts user
config — ``$XDG_CONFIG_HOME/dbt-charts/`` (``~/.config/dbt-charts/`` when that
is unset), ``%APPDATA%\\dbt-charts\\`` on Windows — and is written 0600, because
the token is in it.

The token comes from ``dct cloud login`` (the OAuth device grant), from
``DCT_CLOUD_TOKEN``, or from a hand-written ``token:`` line in this file;
every verb that needs one says so when it is missing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dbt_charts.cloud_client.errors import CloudConfigError

CONFIG_DIR_NAME = "dbt-charts"
CONFIG_FILE_NAME = "config.yml"
TOKEN_ENV_VAR = "DCT_CLOUD_TOKEN"
DEFAULT_HOST = "https://dbtcharts.com"


class CloudConfig(BaseModel):
    """Everything the config file may hold."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(default=DEFAULT_HOST, description="Cloud deployment to talk to.")
    token: str = Field(default="", description="Bearer token; empty when signed out.")
    org: str = Field(default="", description="Default organization slug.")
    project: str = Field(default="", description="Default project slug.")

    @field_validator("token")
    @classmethod
    def _strip_trailing_newline(cls, value: str) -> str:
        """A YAML block scalar (``token: |``) and `export TOKEN=$(cat file)`
        both routinely carry a trailing newline nobody meant as part of the
        credential -- strip it here, once, regardless of whether the token
        came from the file (``read_config``'s ``model_validate``) or
        ``DCT_CLOUD_TOKEN`` (``load_config``'s direct construction runs this
        validator too). A control character anywhere else in the token is a
        different problem this can't guess how to fix -- CloudClient rejects
        that outright instead of stripping it.
        """
        return value.rstrip("\r\n")


def config_dir() -> Path:
    """The directory this deployment's user config lives in."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / CONFIG_DIR_NAME
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / CONFIG_DIR_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def read_config() -> CloudConfig:
    """The stored config, exactly as the file has it.

    An absent file is an empty config — nothing has been configured yet. A file
    that is there but unreadable is an error: silently treating a typo'd config
    as "no config" would send the next verb at the default host with no token.
    """
    path = config_path()
    if not path.exists():
        return CloudConfig()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CloudConfigError(f"{path} could not be read: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CloudConfigError(f"{path} is not valid YAML{_where(exc)}.") from exc
    if raw is None:
        return CloudConfig()
    if not isinstance(raw, dict):
        raise CloudConfigError(
            f"{path} must be a mapping of settings, found {type(raw).__name__}."
        )
    try:
        return CloudConfig.model_validate(raw)
    except ValidationError as exc:
        raise CloudConfigError(
            f"{path} has settings this version cannot use: {rejected_fields(exc)}."
            f" Valid settings: {', '.join(CloudConfig.model_fields)}."
        ) from exc


# Nothing derived from an exception's own text may reach these messages: every
# line of this file is a credential or sits next to one, and both parsers quote
# what they choked on — pydantic prints `input_value=`, and a YAML scanner error
# prints the offending source line. A mistyped or misspelled key is exactly as
# likely to hold a live token as the right one, and this message goes to stderr
# and into the `--json` error body. So: positions and key names only.


def _where(exc: yaml.YAMLError) -> str:
    """A YAML failure's position, never its quoted line."""
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return ""
    return f" (line {mark.line + 1}, column {mark.column + 1})"


def rejected_fields(exc: ValidationError) -> str:
    """The fields pydantic rejected, by name only -- never its own text, which
    quotes the offending value (see the note above)."""
    keys = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
    return ", ".join(keys) if keys else "the file's top level"


def load_config() -> CloudConfig:
    """The stored config with the token environment override applied."""
    stored = read_config()
    env_token = os.environ.get(TOKEN_ENV_VAR, "")
    if not env_token:
        return stored
    # Merge-and-revalidate, not model_copy: naming each carried field here
    # drops any setting added to CloudConfig later, but model_copy would skip
    # the validators -- and _strip_trailing_newline has to run on the env
    # token, which is the one most likely to carry a stray newline.
    return CloudConfig.model_validate({**stored.model_dump(), "token": env_token})


def credential_source() -> Literal["env", "config"]:
    """Which surface supplies the token ``load_config()`` returns.

    Mirrors ``load_config()``'s own precedence exactly (an unset or empty
    ``DCT_CLOUD_TOKEN`` falls through to the config file), so `whoami` and
    `logout` never disagree with the token every other verb actually used.
    """
    return "env" if os.environ.get(TOKEN_ENV_VAR, "") else "config"


def save_config(config: CloudConfig) -> Path:
    """Write the config back, owner-readable only."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create private, then narrow a pre-existing file: touch() sets the mode
    # only on creation, and the token must never land in a world-readable file.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(
        yaml.safe_dump(config.model_dump(), sort_keys=True), encoding="utf-8"
    )
    return path
