"""The user-level config file the ``dct cloud`` verbs read their token from."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from dbt_charts.cloud_client import config as config_module
from dbt_charts.cloud_client.config import (
    CloudConfig,
    PendingConnect,
    PendingLogin,
    clear_pending_connect,
    clear_pending_login,
    config_path,
    credential_source,
    load_config,
    pending_connect_path,
    pending_login_path,
    read_config,
    read_pending_connect,
    read_pending_login,
    save_config,
    save_pending_connect,
    save_pending_login,
)


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("DCT_CLOUD_TOKEN", raising=False)
    return tmp_path / "dbt-charts"


def test_config_path_follows_xdg(config_home: Path) -> None:
    assert config_path() == config_home / "config.yml"


def test_config_path_defaults_to_dot_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config_path() == tmp_path / ".config" / "dbt-charts" / "config.yml"


def test_absent_file_reads_as_empty_config(config_home: Path) -> None:
    assert read_config() == CloudConfig()


def test_round_trips_through_the_file(config_home: Path) -> None:
    save_config(CloudConfig(token="t0ken", org="acme-data", project="analytics"))
    assert read_config() == CloudConfig(
        token="t0ken", org="acme-data", project="analytics"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_saved_file_is_readable_only_by_its_owner(config_home: Path) -> None:
    path = save_config(CloudConfig(token="t0ken"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_save_config_narrows_a_pre_existing_permissive_file(
    config_home: Path,
) -> None:
    """HIGH-5: `touch(mode=..., exist_ok=True)` only sets the mode on
    CREATION -- a config file that already exists at a looser mode (a stray
    `chmod`, an old dbt charts version, a copied dotfile) must still end up
    owner-only after a save, not keep whatever permissive mode it had."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("token: stale\n", encoding="utf-8")
    path.chmod(0o644)

    save_config(CloudConfig(token="t0ken"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_env_token_overrides_the_file(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interim login story: an agent exports the token, no file needed."""
    save_config(CloudConfig(token="from-file", org="acme-data"))
    monkeypatch.setenv(config_module.TOKEN_ENV_VAR, "from-env")
    assert load_config().token == "from-env"
    assert load_config().org == "acme-data"
    assert read_config().token == "from-file"


def test_env_token_with_a_trailing_newline_is_stripped(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HIGH-1: `export TOKEN=$(cat file)` and a YAML block scalar
    (``token: |``) both routinely carry a trailing newline nobody meant as
    part of the credential. Left in, it becomes an illegal HTTP header byte
    that httpx's own error text echoes back — see CloudClient.__init__'s
    control-character reject for the half this strip alone doesn't cover."""
    monkeypatch.setenv(config_module.TOKEN_ENV_VAR, "from-env\n")
    assert load_config().token == "from-env"


def test_a_trailing_newline_in_the_config_file_token_is_stripped(
    config_home: Path,
) -> None:
    """Same normalization, the file's own YAML-parse path -- a block scalar
    (``token: |``) parses with its trailing newline intact unless stripped."""
    _write(config_home, "token: |\n  from-file\n")
    assert read_config().token == "from-file"


def test_a_malformed_config_file_is_a_loud_error(config_home: Path) -> None:
    config_home.mkdir(parents=True)
    (config_home / "config.yml").write_text("- not: a mapping\n", encoding="utf-8")
    with pytest.raises(config_module.CloudConfigError) as caught:
        read_config()
    assert str(config_path()) in str(caught.value)


SECRET = "sk-live-do-not-print-me"


def _write(config_home: Path, body: str) -> None:
    config_home.mkdir(parents=True, exist_ok=True)
    (config_home / "config.yml").write_text(body, encoding="utf-8")


def test_a_rejected_setting_is_named_without_quoting_its_value(
    config_home: Path,
) -> None:
    """The whole file is credentials. A typo'd key holds a live token just as
    often as the right one does, and this message reaches stderr and the
    --json error body — so it names keys and never values."""
    _write(config_home, f"tokenn: {SECRET}\n")
    with pytest.raises(config_module.CloudConfigError) as caught:
        read_config()
    message = str(caught.value)
    assert SECRET not in message
    assert "tokenn" in message


def test_a_mistyped_setting_is_named_without_quoting_its_value(
    config_home: Path,
) -> None:
    _write(config_home, "token:\n  - 12345\n")
    with pytest.raises(config_module.CloudConfigError) as caught:
        read_config()
    message = str(caught.value)
    assert "12345" not in message
    assert "token" in message


def test_credential_source_is_config_with_no_env_var(config_home: Path) -> None:
    assert credential_source() == "config"


def test_credential_source_is_env_when_the_env_var_is_set(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config_module.TOKEN_ENV_VAR, "from-env")
    assert credential_source() == "env"


def test_a_yaml_syntax_error_reports_its_position_not_the_line(
    config_home: Path,
) -> None:
    """A YAML parser error quotes the offending source line back at you — and
    the offending line is the one holding the token."""
    _write(config_home, f'token: "{SECRET}\n')
    with pytest.raises(config_module.CloudConfigError) as caught:
        read_config()
    message = str(caught.value)
    assert SECRET not in message
    # A position, so the user can find it — the parser's own mark, not its
    # rendering of the line it read.
    assert "line" in message and "column" in message


# --- pending login (`dct cloud login --start`/`--wait`) --------------------


def _pending() -> PendingLogin:
    return PendingLogin(
        device_code="devc-secret-123",
        token_endpoint="https://cloud.example/o/token/",
        interval=5.0,
        expires_in=600.0,
        host="https://cloud.example",
    )


def test_pending_login_path_sits_beside_the_config_file(config_home: Path) -> None:
    assert pending_login_path() == config_home / "pending-login.yml"


def test_absent_pending_login_reads_as_none(config_home: Path) -> None:
    assert read_pending_login() is None


def test_pending_login_round_trips_through_the_file(config_home: Path) -> None:
    save_pending_login(_pending())
    assert read_pending_login() == _pending()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_saved_pending_login_is_readable_only_by_its_owner(config_home: Path) -> None:
    path = save_pending_login(_pending())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_clear_pending_login_removes_the_file(config_home: Path) -> None:
    save_pending_login(_pending())
    clear_pending_login()
    assert read_pending_login() is None
    assert not pending_login_path().exists()


def test_clear_pending_login_is_a_noop_with_no_pending_login(
    config_home: Path,
) -> None:
    clear_pending_login()  # must not raise


def test_a_malformed_pending_login_file_is_a_loud_error(config_home: Path) -> None:
    config_home.mkdir(parents=True)
    (config_home / "pending-login.yml").write_text(
        "- not: a mapping\n", encoding="utf-8"
    )
    with pytest.raises(config_module.CloudConfigError) as caught:
        read_pending_login()
    assert str(pending_login_path()) in str(caught.value)


# --- pending connect (`dct cloud project connect --start`/`--wait`) --------


def _pending_connect() -> PendingConnect:
    return PendingConnect(org="acme-data", host="https://cloud.example")


def test_pending_connect_path_sits_beside_the_config_file(config_home: Path) -> None:
    assert pending_connect_path() == config_home / "pending-connect.yml"


def test_absent_pending_connect_reads_as_none(config_home: Path) -> None:
    assert read_pending_connect() is None


def test_pending_connect_round_trips_through_the_file(config_home: Path) -> None:
    save_pending_connect(_pending_connect())
    assert read_pending_connect() == _pending_connect()


def test_pending_connect_round_trips_its_optional_project_fields(
    config_home: Path,
) -> None:
    pending = PendingConnect(
        org="acme-data",
        host="https://cloud.example",
        name="Analytics",
        slug="an",
        trunk="trunk",
        root="warehouse",
    )
    save_pending_connect(pending)
    assert read_pending_connect() == pending


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_saved_pending_connect_is_readable_only_by_its_owner(
    config_home: Path,
) -> None:
    path = save_pending_connect(_pending_connect())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_clear_pending_connect_removes_the_file(config_home: Path) -> None:
    save_pending_connect(_pending_connect())
    clear_pending_connect()
    assert read_pending_connect() is None
    assert not pending_connect_path().exists()


def test_clear_pending_connect_is_a_noop_with_no_pending_connect(
    config_home: Path,
) -> None:
    clear_pending_connect()  # must not raise


def test_a_malformed_pending_connect_file_is_a_loud_error(config_home: Path) -> None:
    config_home.mkdir(parents=True)
    (config_home / "pending-connect.yml").write_text(
        "- not: a mapping\n", encoding="utf-8"
    )
    with pytest.raises(config_module.CloudConfigError) as caught:
        read_pending_connect()
    assert str(pending_connect_path()) in str(caught.value)
